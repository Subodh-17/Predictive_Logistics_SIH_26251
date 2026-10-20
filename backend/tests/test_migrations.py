"""Fresh initialisation, repeatability, checksum protection, atomicity, adoption of a V5 database, guarded seeding and referential integrity.
Runs in a throw-away database created (and dropped) by the test itself; the application's own test database is never touched."""
import re
import shutil
import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from app import config, migrate

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "migrations"
SEED = ROOT / "db" / "seed.sql"


def _admin_dsn():
    u = config.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", "/postgres", u)


@pytest.fixture()
def scratch(db_available):
    if not db_available:
        pytest.skip("no test database server")
    name = "logistics_scratch_" + uuid.uuid4().hex[:8]
    try:
        with psycopg.connect(_admin_dsn(), autocommit=True) as c:
            c.execute(f'CREATE DATABASE "{name}"')
    except psycopg.Error as e:
        pytest.skip(f"cannot create a scratch database: {type(e).__name__}")
    url = re.sub(r"/[^/?]+(\?.*)?$", f"/{name}", config.DATABASE_URL)
    try:
        yield url
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def q(url, sql, *a):
    with psycopg.connect(migrate.dsn_of(url), autocommit=True) as c:
        cur = c.execute(sql, a or None)
        return cur.fetchall() if cur.description else None


def test_fresh_database_initialises_and_is_repeatable(scratch):
    done = migrate.migrate(scratch)
    assert done == ["0001", "0002", "0003", "0004"] and migrate.current_version(scratch) == "0004"
    assert migrate.migrate(scratch) == []                                    # second run: nothing to do
    assert migrate.seed_scenario(scratch) is True and migrate.seed_scenario(scratch) is False     # seeding is also repeatable
    assert q(scratch, "select count(*) from consumption")[0][0] == 5500
    assert q(scratch, "select count(*) from schema_migrations")[0][0] == 4


def test_modified_migration_is_refused(scratch, tmp_path):
    d = tmp_path / "m"
    shutil.copytree(MIGRATIONS, d)
    migrate.migrate(scratch, d)
    (d / "0002_auth_audit.sql").write_text((d / "0002_auth_audit.sql").read_text() + "\n-- edited later\n")
    with pytest.raises(migrate.MigrationError, match="modified after it was applied"):
        migrate.migrate(scratch, d)


def test_failed_migration_rolls_back_completely(scratch, tmp_path):
    d = tmp_path / "m"
    shutil.copytree(MIGRATIONS, d)
    migrate.migrate(scratch, d)
    (d / "0005_broken.sql").write_text("CREATE TABLE half_done (id int);\nINSERT INTO half_done VALUES (1);\nSELECT 1/0;\n")
    with pytest.raises(psycopg.Error):
        migrate.migrate(scratch, d)
    assert q(scratch, "select to_regclass('public.half_done')")[0][0] is None            # nothing from the failed file survives
    assert q(scratch, "select count(*) from schema_migrations where version='0005'")[0][0] == 0
    (d / "0005_broken.sql").write_text("CREATE TABLE fixed_ok (id int);\n")
    assert migrate.migrate(scratch, d) == ["0005"]                                         # and it can be retried once fixed


def test_unexpected_or_duplicate_files_are_rejected(tmp_path):
    (tmp_path / "notes.sql").write_text("select 1")
    with pytest.raises(migrate.MigrationError, match="unexpected file"):
        migrate.discover(tmp_path)
    with pytest.raises(migrate.MigrationError):
        migrate.discover(tmp_path / "missing")


def test_v5_database_is_adopted_not_recreated(scratch):
    q(scratch, (MIGRATIONS / "0001_baseline.sql").read_text())            # what V5 had: tables, no history table
    q(scratch, "INSERT INTO supplies (id, base_daily_demand, weather_sensitivity, criticality_weight) VALUES ('Keep', 1, 0.1, 0.5)")
    done = migrate.migrate(scratch)
    assert done == ["0002", "0003", "0004"]                                        # baseline recorded as adopted, newer ones applied
    assert q(scratch, "select adopted from schema_migrations where version='0001'")[0][0] is True
    assert q(scratch, "select count(*) from supplies where id='Keep'")[0][0] == 1       # existing data untouched


def test_partially_populated_scenario_is_never_overwritten(scratch):
    migrate.migrate(scratch)
    q(scratch, "INSERT INTO supplies (id, base_daily_demand, weather_sensitivity, criticality_weight) VALUES ('Only', 1, 0.1, 0.5)")
    with pytest.raises(migrate.MigrationError, match="partially populated"):
        migrate.seed_scenario(scratch)
    assert q(scratch, "select count(*) from supplies")[0][0] == 1


def test_seed_failure_leaves_no_partial_data(scratch, tmp_path):
    migrate.migrate(scratch)
    bad = tmp_path / "seed.sql"
    bad.write_text("BEGIN;\nINSERT INTO supplies (id, base_daily_demand, weather_sensitivity, criticality_weight) VALUES ('A', 1, 0.1, 0.5);\n"
                   "INSERT INTO locations (id, name, kind, geom) VALUES ('L', 'L', 'NOT_A_KIND', ST_SetSRID(ST_MakePoint(1,1),4326));\nCOMMIT;\n")
    with pytest.raises(psycopg.Error):
        migrate.seed_scenario(scratch, bad)
    assert q(scratch, "select count(*) from supplies")[0][0] == 0


def test_destructive_reset_is_guarded(scratch, monkeypatch):
    migrate.migrate(scratch)
    with pytest.raises(migrate.MigrationError, match="name must contain"):
        migrate.reset_database("postgresql+psycopg://u:p@localhost:5432/logistics_live", confirm_database_name="logistics_live")
    name = config.database_name(scratch)
    with pytest.raises(migrate.MigrationError, match="confirmation does not match"):
        migrate.reset_database(scratch, confirm_database_name="something_else")
    monkeypatch.setattr(config, "settings", replace(config.settings, app_env="production"))
    with pytest.raises(migrate.MigrationError, match="production"):
        migrate.reset_database(scratch, confirm_database_name=name)
    monkeypatch.undo()
    assert q(scratch, "select count(*) from schema_migrations")[0][0] == 4
    migrate.reset_database(scratch, confirm_database_name=name)
    assert q(scratch, "select to_regclass('public.locations')")[0][0] is None


@pytest.fixture()
def seeded(scratch):
    migrate.migrate(scratch)
    migrate.seed_scenario(scratch)
    return scratch


@pytest.mark.parametrize("sql", [
    "INSERT INTO consumption (location_id, supply_id, day_index, consumption_date, quantity) VALUES ('NOPE', 'Food', 0, '2026-01-01', 1)",       # FK
    "INSERT INTO inventory (location_id, supply_id, stock, initial_stock) VALUES ('Base_01', 'Food', -1, 0)",                                  # CHECK / PK
    "INSERT INTO iot_events (device_id, tag_id, event_type, location_id, supply_id, quantity, stock_before, stock_after, simulated) VALUES ('d','t','COUNT','Base_01','Food',1,1,1,false)",
    "INSERT INTO iot_events (device_id, tag_id, event_type, location_id, supply_id, quantity, stock_before, stock_after) VALUES ('d','t','STEAL','Base_01','Food',1,1,1)",
    "INSERT INTO routes (id, depot_id, destination_id, distance_km, road_condition, nominal_speed_kmh, geom) VALUES ('RX','Depot_A','Depot_A',5,0.5,40,ST_GeomFromText('LINESTRING(1 1,2 2)',4326))",
    "INSERT INTO forecasts (location_id, supply_id, day_index, forecast_date, kind, value, lo, hi) VALUES ('Base_01','Food',999,'2026-01-01','FORECAST',5,9,1)",
    "INSERT INTO users (username, password_hash, role) VALUES ('Bad Name', 'x', 'viewer')",
    "INSERT INTO users (username, password_hash, role) VALUES ('good_name', 'x', 'root')",
    "DELETE FROM locations WHERE id = 'Base_01'",                                                                                              # still referenced
])
def test_database_rejects_invalid_or_orphaning_changes(seeded, sql):
    with pytest.raises(psycopg.errors.IntegrityError):
        q(seeded, sql)


def test_duplicate_series_rows_are_rejected(seeded):
    q(seeded, "INSERT INTO forecasts (location_id, supply_id, day_index, forecast_date, kind, value) VALUES ('Base_01','Food',999,'2026-01-01','FORECAST',5)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        q(seeded, "INSERT INTO forecasts (location_id, supply_id, day_index, forecast_date, kind, value) VALUES ('Base_01','Food',999,'2026-01-01','FORECAST',6)")


def test_users_table_stores_no_plain_text_and_usernames_are_unique(seeded):
    q(seeded, "INSERT INTO users (username, password_hash, role) VALUES ('dup_user','h','viewer')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        q(seeded, "INSERT INTO users (username, password_hash, role) VALUES ('dup_user','h2','admin')")


def test_scenario_has_no_in_transit_or_backlog_tables(seeded):
    """The shortage-onset model needs on-hand history, in-transit and backlog ledgers. If someone adds them, this fails and the
    integration decision (docs/SHORTAGE_MODEL_DECISION.md) must be revisited deliberately."""
    names = {r[0] for r in q(seeded, "select table_name from information_schema.tables where table_schema='public'")}
    assert not {n for n in names if re.search(r"in_transit|backlog|inventory_history|stock_history", n)}


# --------------------------------------------------------------------------------------------------- least-privilege application role
@pytest.fixture()
def app_role(seeded):
    name = "plsd_app_" + uuid.uuid4().hex[:8]
    pw = "Pw-" + uuid.uuid4().hex
    with psycopg.connect(_admin_dsn(), autocommit=True) as c:
        c.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{pw}' NOSUPERUSER NOCREATEDB NOCREATEROLE")
    migrate.grant_app_privileges(name, seeded)
    url = re.sub(r"//[^@]+@", f"//{name}:{pw}@", seeded)
    try:
        yield name, url
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{config.database_name(seeded)}" WITH (FORCE)')       # the scratch fixture drops it again harmlessly
            c.execute(f"DROP ROLE IF EXISTS {name}")


def test_application_role_can_do_everything_the_application_does(app_role):
    name, url = app_role
    q(url, "UPDATE inventory SET stock = stock WHERE location_id = 'Base_01'")
    q(url, "INSERT INTO iot_events (device_id, tag_id, event_type, location_id, supply_id, quantity, stock_before, stock_after) VALUES ('d-1','t-1','COUNT','Base_01','Food',1,1,1)")
    q(url, "INSERT INTO audit_log (action, outcome) VALUES ('x', 'success')")
    q(url, "INSERT INTO users (username, password_hash, role) VALUES ('role_check', 'h', 'viewer')")
    q(url, "DELETE FROM iot_events")
    q(url, "DELETE FROM forecasts")
    assert migrate.verify_schema(url) == "0004"                                   # reads the migration history without write access


@pytest.mark.parametrize("sql", ["CREATE TABLE evil (id int)", "DROP TABLE inventory", "ALTER TABLE inventory ADD COLUMN x int", "TRUNCATE inventory",
                                 "DROP TABLE schema_migrations", "DELETE FROM schema_migrations", "UPDATE schema_migrations SET checksum = 'x'",
                                 "INSERT INTO schema_migrations (version, name, checksum) VALUES ('0009','x','x')", "CREATE EXTENSION IF NOT EXISTS hstore",
                                 "CREATE ROLE sneaky", "DROP SCHEMA public CASCADE"])
def test_application_role_cannot_change_the_schema_history_or_privileges(app_role, sql):
    _, url = app_role
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        q(url, sql)


def test_verify_schema_refuses_an_outdated_database_and_grants_validate_the_role_name(scratch, tmp_path):
    d = tmp_path / "m"
    shutil.copytree(MIGRATIONS, d)
    migrate.migrate(scratch, d)
    (d / "0006_next.sql").write_text("CREATE TABLE next_one (id int);\n")
    with pytest.raises(migrate.MigrationError, match="needs 0006"):
        migrate.verify_schema(scratch, d)
    with pytest.raises(migrate.MigrationError, match="role name"):
        migrate.grant_app_privileges("bad name; drop", scratch)
    with pytest.raises(migrate.MigrationError, match="does not exist"):
        migrate.grant_app_privileges("no_such_role_xyz", scratch)


def test_cli_migrate_reports_the_version_with_the_migration_connection(scratch, monkeypatch, capsys):
    """Regression: `migrate` printed the version using the (not yet granted) application connection and failed with 'permission denied'
    when DATABASE_URL was the restricted role and MIGRATION_DATABASE_URL the owner."""
    from dataclasses import replace
    from app import cli
    name = "plsd_cli_" + uuid.uuid4().hex[:8]
    with psycopg.connect(_admin_dsn(), autocommit=True) as c:
        c.execute(f"CREATE ROLE {name} LOGIN PASSWORD 'Pw-{name}' NOSUPERUSER NOCREATEDB NOCREATEROLE")
    try:
        app_url = re.sub(r"//[^@]+@", f"//{name}:Pw-{name}@", scratch)
        monkeypatch.setattr(config, "DATABASE_URL", app_url)                                               # the restricted role, NOT yet granted anything
        monkeypatch.setattr(config, "settings", replace(config.settings, database_url=app_url, migration_database_url=scratch))
        assert cli.main(["migrate"]) == 0
        assert "version: 0004" in capsys.readouterr().out
        assert cli.main(["grant-app-role", name]) == 0 and migrate.verify_schema(app_url) == "0004"
    finally:
        monkeypatch.undo()
        with psycopg.connect(_admin_dsn(), autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{config.database_name(scratch)}" WITH (FORCE)')
            c.execute(f"DROP ROLE IF EXISTS {name}")

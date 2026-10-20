"""Versioned, repeatable database migrations and guarded scenario seeding.

* Migrations are the numbered ``db/migrations/NNNN_name.sql`` files, applied in order, each inside its own transaction and recorded in
  ``schema_migrations`` together with a SHA-256 of the file. A concurrent runner is excluded with a PostgreSQL advisory lock.
* Re-running is a no-op. If an applied file was edited afterwards the run stops (``MigrationError``) instead of guessing.
* A database created by V5 (tables exist, no ``schema_migrations``) is *adopted*: the baseline is recorded as applied and only the newer
  migrations run. Nothing is dropped, ever. Destructive resets are a separate, explicitly named operation (``reset_database``) that refuses
  to run unless the database name marks it as a development or test database.
* The scenario seed (``db/seed.sql``) is loaded in a single transaction and only into a completely empty scenario; a partially populated
  database is reported, never overwritten.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
import psycopg.sql

from . import config

log = logging.getLogger("logistics.migrate")
ADVISORY_LOCK_KEY = 7_262_026_251          # arbitrary constant: "this application's schema lock"
_FILE_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
SCENARIO_TABLES = ("supplies", "locations", "depots", "vehicles", "routes", "terrain", "weather", "consumption", "inventory")
SAFE_RESET_NAME = re.compile(r"(^|[_-])(dev|test|ci|scratch)([_-]|$)", re.I)


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    checksum: str
    sql: str


def dsn_of(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def discover(directory: Path) -> list[MigrationFile]:
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")
    out = []
    for p in sorted(directory.glob("*.sql")):
        m = _FILE_RE.match(p.name)
        if not m:
            raise MigrationError(f"unexpected file name in migrations directory: {p.name} (expected NNNN_name.sql)")
        sql = p.read_text(encoding="utf-8")
        out.append(MigrationFile(m.group(1), m.group(2), p, hashlib.sha256(sql.encode("utf-8")).hexdigest(), sql))
    versions = [f.version for f in out]
    if len(set(versions)) != len(versions):
        raise MigrationError("duplicate migration version numbers")
    if not out:
        raise MigrationError(f"no migrations found in {directory}")
    return out


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    return bool(conn.execute("select to_regclass(%s) is not null", (f"public.{name}",)).fetchone()[0])


def migrate(url: str | None = None, directory: Path | None = None) -> list[str]:
    """Apply all pending migrations. Returns the versions applied by this call (empty when already up to date)."""
    url = url or migration_url()
    files = discover(directory or config.MIGRATIONS_DIR)
    applied_now: list[str] = []
    with psycopg.connect(dsn_of(url), autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                                version text PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
                                applied_at timestamptz NOT NULL DEFAULT now(), adopted boolean NOT NULL DEFAULT false)""")
            done = {v: c for v, c in conn.execute("select version, checksum from schema_migrations")}
            # a database created by V5 (tables present, nothing recorded): adopt the baseline instead of re-creating it
            if not done and _table_exists(conn, "locations"):
                base = files[0]
                conn.execute("insert into schema_migrations (version, name, checksum, adopted) values (%s, %s, %s, true)", (base.version, base.name, base.checksum))
                done[base.version] = base.checksum
                log.warning("existing database without migration history: baseline %s adopted without re-running it", base.version)
            for f in files:
                if f.version in done:
                    if done[f.version] != f.checksum:
                        raise MigrationError(f"migration {f.version}_{f.name} was modified after it was applied (checksum mismatch); "
                                             "add a new migration instead of editing an applied one")
                    continue
                with conn.transaction():          # all-or-nothing per migration
                    conn.execute(f.sql)
                    conn.execute("insert into schema_migrations (version, name, checksum) values (%s, %s, %s)", (f.version, f.name, f.checksum))
                applied_now.append(f.version)
                log.info("applied migration %s_%s", f.version, f.name)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    return applied_now


def current_version(url: str | None = None) -> str | None:
    with psycopg.connect(dsn_of(url or config.DATABASE_URL), autocommit=True) as conn:
        if not _table_exists(conn, "schema_migrations"):
            return None
        row = conn.execute("select max(version) from schema_migrations").fetchone()
        return row[0] if row else None


def scenario_state(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in SCENARIO_TABLES}


def seed_scenario(url: str | None = None, seed_file: Path | None = None) -> bool:
    """Load the illustrative scenario into an EMPTY database. Returns True if it was loaded, False if data already exists.
    A partially populated scenario raises MigrationError: it is never dropped or overwritten."""
    url = url or migration_url()
    seed_file = seed_file or (config.DB_DIR / "seed.sql")
    with psycopg.connect(dsn_of(url), autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            state = scenario_state(conn)
            filled = {t: n for t, n in state.items() if n}
            if len(filled) == len(SCENARIO_TABLES):
                return False
            if filled:
                raise MigrationError("scenario tables are partially populated (" + ", ".join(f"{t}={n}" for t, n in filled.items())
                                     + "); refusing to seed over them. Restore the data or reset a development database explicitly.")
            sql = seed_file.read_text(encoding="utf-8")
            body = re.sub(r"^\s*BEGIN;\s*", "", sql, flags=re.I)
            body = re.sub(r"\s*COMMIT;\s*$", "", body, flags=re.I)
            with conn.transaction():
                conn.execute(body)
            log.info("scenario seed loaded from %s", seed_file.name)
            return True
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))


ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{2,62}$")
WRITABLE_EXCEPT = ("schema_migrations", "spatial_ref_sys", "geometry_columns", "geography_columns")


def migration_url() -> str:
    """Connection used for DDL (migrations, seeding, grants): MIGRATION_DATABASE_URL when set, otherwise the application connection."""
    return config.settings.migration_database_url or config.DATABASE_URL


def expected_version(directory: Path | None = None) -> str:
    return discover(directory or config.MIGRATIONS_DIR)[-1].version


def verify_schema(url: str | None = None, directory: Path | None = None) -> str:
    """Read-only check used when AUTO_MIGRATE=0: the database must already be at the newest migration (needs only SELECT)."""
    have, want = current_version(url), expected_version(directory)
    if have != want:
        raise MigrationError(f"database schema is at version {have or 'none'} but this release needs {want}: run `python -m app.cli migrate` "
                             "with a DDL-capable role (MIGRATION_DATABASE_URL) before starting the application")
    return have


def grant_app_privileges(role: str, url: str | None = None) -> None:
    """Give an existing LOGIN role exactly what the running application needs: DML on its tables and use of its sequences. No DDL, no TRUNCATE,
    no write access to the migration history. Run with the migration (owner) connection; idempotent."""
    if not ROLE_RE.match(role):
        raise MigrationError("role name must match ^[a-z_][a-z0-9_]{2,62}$")
    with psycopg.connect(dsn_of(url or migration_url()), autocommit=True) as conn:
        if not conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone():
            raise MigrationError(f"role {role!r} does not exist: create it first (CREATE ROLE {role} LOGIN PASSWORD '...')")
        ident = psycopg.sql.Identifier(role)
        db = conn.execute("select current_database()").fetchone()[0]
        with conn.transaction():
            conn.execute(psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(psycopg.sql.Identifier(db), ident))
            conn.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident))
            conn.execute(psycopg.sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(ident))
            conn.execute(psycopg.sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(ident))
            conn.execute(psycopg.sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(ident))
            for t in WRITABLE_EXCEPT:       # migration history is read-only for the application
                if conn.execute("select to_regclass(%s) is not null", (f"public.{t}",)).fetchone()[0]:
                    conn.execute(psycopg.sql.SQL("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {} FROM {}").format(psycopg.sql.Identifier(t), ident))
        log.info("least-privilege grants applied to role %s", role)


def reset_database(url: str | None = None, *, confirm_database_name: str) -> None:
    """DESTRUCTIVE: drop every application table. Only for development/test databases whose *name* says so, only outside production,
    and only when the caller types the database name again."""
    url = url or migration_url()
    name = config.database_name(url)
    if config.settings.is_production:
        raise MigrationError("refusing to reset a database when APP_ENV=production")
    if not SAFE_RESET_NAME.search(name):
        raise MigrationError(f"refusing to reset database {name!r}: its name must contain dev, test, ci or scratch (e.g. logistics_dev)")
    if confirm_database_name != name:
        raise MigrationError(f"confirmation does not match the target database name ({name!r})")
    with psycopg.connect(dsn_of(url), autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            with conn.transaction():
                conn.execute("DROP VIEW IF EXISTS v_consumption_enriched")
                conn.execute("DROP TABLE IF EXISTS audit_log, users, simulation_runs, iot_events, allocations, priority_scores, alerts, forecasts, "
                             "consumption, inventory, weather, terrain, routes, vehicles, depots, locations, supplies, schema_migrations CASCADE")
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    log.warning("database %s reset", name)

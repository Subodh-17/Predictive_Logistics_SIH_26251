"""Test configuration.

Safety: the database-backed tests CREATE tables, seed data, reset inventory and create users. They therefore refuse to run unless
DATABASE_URL is set explicitly AND names a database whose name contains "test", "ci" or "scratch" - a developer's real database can
never be the target by accident. Create one with, for example:

    createdb logistics_test && psql logistics_test -c 'CREATE EXTENSION postgis'
    export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/logistics_test
"""
import os
import re
import secrets

# --- environment for the whole test session: must be set BEFORE any `app` module is imported -------------------------------------
os.environ["APP_ENV"] = "test"
os.environ.setdefault("PASSWORD_SCRYPT_LOG_N", "10")                 # fast hashing in tests only (production requires >= 15)
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["RATE_LIMIT_WRITE_PER_MINUTE"] = "5000"
os.environ["RATE_LIMIT_PER_MINUTE"] = "50000"
os.environ["AUTO_SEED_SCENARIO"] = "0"
os.environ.pop("BOOTSTRAP_ADMIN_USERNAME", None)
os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)

import pytest
from sqlalchemy import create_engine, text

from app import config, seed_data
from app.services.domain import Params

SAFE_DB_NAME = re.compile(r"(^|[_-])(test|ci|scratch)([_-]|$)", re.I)
TEST_PASSWORD = "Test-Passw0rd-" + secrets.token_hex(4)
USERS = {"t_viewer": "viewer", "t_operator": "operator", "t_admin": "admin"}


@pytest.fixture(scope="session")
def dataset():
    return seed_data.build_dataset()


@pytest.fixture()
def snap(dataset):
    return seed_data.snapshot_from_dataset(dataset)


@pytest.fixture(scope="session")
def db_available():
    if not os.environ.get("DATABASE_URL"):
        return False
    name = config.database_name(config.DATABASE_URL)
    if not SAFE_DB_NAME.search(name):
        pytest.exit(f"REFUSING to run database tests against {name!r}: the database name must contain 'test', 'ci' or 'scratch'.", returncode=2)
    try:
        with create_engine(config.DATABASE_URL).connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        return False


def _require(db_available):
    if not db_available:
        target = config.database_target(config.DATABASE_URL)       # host/db only - never credentials
        msg = f"PostgreSQL/PostGIS test database not reachable or DATABASE_URL not set (target {target})"
        if os.getenv("REQUIRE_DB") == "1":                          # release verification: a missing DB is a FAILURE, not a skip
            pytest.fail("REQUIRE_DB=1 but " + msg)
        pytest.skip(msg)


@pytest.fixture(scope="session")
def prepared_db(db_available):
    """Migrate the (verified-safe) test database, load the scenario if empty, and make sure the three test users exist."""
    _require(db_available)
    from app import auth, migrate, models as m
    from app.database import SessionLocal
    from sqlalchemy import select
    migrate.migrate()
    migrate.seed_scenario()
    with SessionLocal() as db:
        # users created by earlier test runs against a kept test database (names start with "t_"): remove them so the suite is re-runnable
        db.execute(text("DELETE FROM users WHERE username LIKE 't\\_%' ESCAPE '\\' AND username <> ALL(:keep)"), {"keep": list(USERS)})
        db.commit()
        for name, role in USERS.items():
            u = db.scalar(select(m.UserRow).where(m.UserRow.username == name))
            if u is None:
                auth.create_user(db, name, TEST_PASSWORD, role)
            else:                                   # re-runs against a kept test database: refresh the password for this session
                from app import security as sec
                u.password_hash = sec.hash_password(TEST_PASSWORD, config.settings.password_scrypt_log_n)
                u.role, u.is_active = role, True
                u.token_version += 1
                db.commit()
    return True


def _token(c, name):
    r = c.post("/api/auth/login", json={"username": name, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    c.cookies.clear()                                      # use the bearer token only; cookie/CSRF behaviour has its own tests
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def app_ctx(prepared_db):
    """One application lifespan per test module (bootstrap, forecasts, baseline tables)."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as boot:
        tokens = {n: _token(boot, n) for n in USERS}
        boot.headers["Authorization"] = "Bearer " + tokens["t_admin"]
        boot.post("/api/iot/reset")
        yield app, tokens
        boot.post("/api/iot/reset")


def _client(app, token=None):
    from fastapi.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    if token:
        c.headers["Authorization"] = "Bearer " + token
    return c


@pytest.fixture(scope="module")
def client(app_ctx):
    """Administrator (Bearer) - can call every endpoint. Most API tests use this."""
    app, t = app_ctx
    return _client(app, t["t_admin"])


@pytest.fixture(scope="module")
def operator_client(app_ctx):
    app, t = app_ctx
    return _client(app, t["t_operator"])


@pytest.fixture(scope="module")
def viewer_client(app_ctx):
    app, t = app_ctx
    return _client(app, t["t_viewer"])


@pytest.fixture(scope="module")
def anon_client(app_ctx):
    app, _ = app_ctx
    return _client(app)

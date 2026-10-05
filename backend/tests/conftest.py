import os

import pytest
from sqlalchemy import create_engine, text

from app import config, seed_data
from app.services.domain import Params


@pytest.fixture(scope="session")
def dataset():
    return seed_data.build_dataset()


@pytest.fixture()
def snap(dataset):
    return seed_data.snapshot_from_dataset(dataset)


@pytest.fixture(scope="session")
def db_available():
    try:
        with create_engine(config.DATABASE_URL).connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def client(db_available):
    if not db_available:
        target = config.DATABASE_URL.split("@")[-1]          # host/db only - never print credentials
        msg = f"PostgreSQL/PostGIS not reachable at {target} (set DATABASE_URL)"
        if os.getenv("REQUIRE_DB") == "1":                    # CI / release verification: a missing DB is a FAILURE, not a skip
            pytest.fail("REQUIRE_DB=1 but " + msg)
        pytest.skip(msg)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:        # runs lifespan: bootstrap, forecasts, baseline tables
        c.post("/api/iot/reset")
        yield c
        c.post("/api/iot/reset")

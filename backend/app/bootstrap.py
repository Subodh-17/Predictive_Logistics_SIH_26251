"""Start-up: wait for PostgreSQL, apply schema/seed if the database is empty, compute forecasts, refresh baseline tables."""
from __future__ import annotations

import logging
import threading
import time

import psycopg
from sqlalchemy import func, select, text

from . import config, models as m, repository as repo
from .database import SessionLocal, engine

log = logging.getLogger("logistics.bootstrap")
_lock = threading.Lock()          # one bootstrap at a time (start-up attempt vs. background retry)
_state = {"ready": False, "attempts": 0, "retrying": False}
RETRY_INTERVAL_SECONDS = 5.0


def is_ready() -> bool:
    return _state["ready"]


def _wait_for_db() -> None:
    deadline = time.time() + config.DB_WAIT_SECONDS
    while True:
        try:
            with engine.connect() as c:
                c.execute(text("select 1"))
            return
        except Exception as e:  # noqa: BLE001
            if time.time() > deadline:
                raise RuntimeError(f"PostgreSQL not reachable after {config.DB_WAIT_SECONDS}s: {e}") from e
            log.info("waiting for database...")
            time.sleep(2)


def _seeded() -> bool:
    with engine.connect() as c:
        ok = c.execute(text("select to_regclass('public.locations') is not null and to_regclass('public.consumption') is not null")).scalar()
        if not ok:
            return False
        return bool(c.execute(text("select count(*) from consumption")).scalar())


def _apply_sql_files() -> None:
    dsn = config.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        for name in ("schema.sql", "seed.sql"):
            path = config.DB_DIR / name
            log.info("applying %s", path)
            conn.execute(path.read_text())


def initialise() -> dict:
    with _lock:
        _state["attempts"] += 1
        _wait_for_db()
        if not _seeded():
            if not config.AUTO_INIT_DB:
                raise RuntimeError("database is not seeded and AUTO_INIT_DB=0")
            _apply_sql_files()
        with SessionLocal() as db:
            n = repo.ensure_forecasts(db)
            if n or not db.scalar(select(func.count()).select_from(m.AlertRow)):
                repo.persist_baseline(db)
        _state["ready"] = True
        return {"forecast_rows_created": n}


def retry_until_ready(interval: float = RETRY_INTERVAL_SECONDS, max_attempts: int | None = None, sleep=time.sleep) -> int:
    """Keep calling initialise() until it succeeds (returns the number of retries used). Raises RuntimeError after max_attempts."""
    tries = 0
    while True:
        tries += 1
        try:
            initialise()
            log.info("bootstrap succeeded on retry %d", tries)
            return tries
        except Exception as e:  # noqa: BLE001
            log.warning("bootstrap retry %d failed: %s", tries, e)
            if max_attempts is not None and tries >= max_attempts:
                raise RuntimeError(f"bootstrap did not succeed after {tries} retries") from e
            sleep(interval)


def start_background_retry(interval: float = RETRY_INTERVAL_SECONDS) -> None:
    """Self-heal after a failed start-up (e.g. the DB was unreachable): retry in a daemon thread so the API needs no restart."""
    if _state["retrying"] or _state["ready"]:
        return
    _state["retrying"] = True

    def run() -> None:
        try:
            retry_until_ready(interval)
        finally:
            _state["retrying"] = False

    threading.Thread(target=run, name="bootstrap-retry", daemon=True).start()

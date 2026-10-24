"""Start-up: wait for PostgreSQL, apply migrations, seed an empty database (only when allowed), ensure an administrator exists,
compute forecasts and refresh the baseline tables."""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import func, select, text

from . import auth, config, migrate, models as m, repository as repo
from .database import SessionLocal, engine
from .observability import metrics

log = logging.getLogger("logistics.bootstrap")
_lock = threading.Lock()          # one bootstrap at a time (start-up attempt vs. background retry)
_state = {"ready": False, "attempts": 0, "retrying": False, "last_success_at": None, "last_error": None}
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


def _scenario_present() -> bool:
    with engine.connect() as c:
        ok = c.execute(text("select to_regclass('public.locations') is not null and to_regclass('public.consumption') is not null")).scalar()
        return bool(ok and c.execute(text("select count(*) from consumption")).scalar())


def initialise() -> dict:
    """Wait for the database, apply pending migrations, load the scenario only if allowed and the database is empty, make sure an
    administrator exists, then compute forecasts and the baseline alert/priority/allocation tables."""
    with _lock:
        _state["attempts"] += 1
        _wait_for_db()
        if config.settings.auto_migrate:
            applied = migrate.migrate()
        else:
            migrate.verify_schema()          # least-privilege mode: the application role never alters the schema
            applied = []
        seeded = False
        if not _scenario_present():
            if not config.AUTO_SEED_SCENARIO:
                raise RuntimeError("the database holds no scenario data and AUTO_SEED_SCENARIO=0; load data first or set AUTO_SEED_SCENARIO=1 "
                                   "to load the illustrative scenario (it is fictional and is not operational data)")
            seeded = migrate.seed_scenario()
        with SessionLocal() as db:
            admin_state = auth.ensure_bootstrap_admin(db)
            n = repo.ensure_forecasts(db)
            if n or not db.scalar(select(func.count()).select_from(m.AlertRow)):
                repo.persist_baseline(db)
        _state["ready"] = True
        _state["last_success_at"] = time.time()
        _state["last_error"] = None
        metrics.stamp("bootstrap_completed")
        return {"migrations_applied": applied, "scenario_seeded": seeded, "forecast_rows_created": n, "admin": admin_state}


def retry_until_ready(interval: float = RETRY_INTERVAL_SECONDS, max_attempts: int | None = None, sleep=time.sleep, backoff: bool = False, max_interval: float = 30.0) -> int:
    """Keep calling initialise() until it succeeds (returns the number of retries used). Raises RuntimeError after max_attempts."""
    tries = 0
    current_interval = interval
    while True:
        tries += 1
        try:
            initialise()
            log.info("bootstrap succeeded on retry %d", tries)
            return tries
        except Exception as e:  # noqa: BLE001
            _state["last_error"] = type(e).__name__
            log.warning("bootstrap retry %d failed: %s", tries, e)
            if max_attempts is not None and tries >= max_attempts:
                raise RuntimeError(f"bootstrap did not succeed after {tries} retries") from e
            sleep(current_interval)
            if backoff:
                current_interval = min(max_interval, current_interval * 2)


def start_background_retry(interval: float = RETRY_INTERVAL_SECONDS, backoff: bool = True) -> None:
    """Self-heal after a failed start-up (e.g. the DB was unreachable): retry in a daemon thread so the API needs no restart."""
    if _state["retrying"] or _state["ready"]:
        return
    _state["retrying"] = True

    def run() -> None:
        try:
            retry_until_ready(interval, backoff=backoff)
        finally:
            _state["retrying"] = False

    threading.Thread(target=run, name="bootstrap-retry", daemon=True).start()

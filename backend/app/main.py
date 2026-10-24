from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError, OperationalError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, bootstrap, config, migrate, repository as repo
from .database import get_db
from .observability import configure_logging, metrics, request_id_var, scrub
from .routers import decision, forecast, gis, inventory, iot, ml, simulation
from .security import SlidingWindowLimiter
from .services import model_service as ms

configure_logging(config.settings.log_level, config.settings.log_json)
log = logging.getLogger("logistics")
_REQ_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_rate = SlidingWindowLimiter(config.settings.rate_limit_per_minute, 60)
_rate_write = SlidingWindowLimiter(config.settings.rate_limit_write_per_minute, 60)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",  # no-referrer breaks OSM tile CDN (403): browser must send origin as Referer
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = config.settings
    log.info("starting: env=%s database=%s docs=%s cookie_secure=%s", s.app_env, config.database_target(s.database_url), s.enable_api_docs, s.cookie_secure)
    if s.jwt_secret_is_ephemeral:
        log.warning("JWT_SECRET not set: using a random per-process secret (sessions end when the process restarts). Acceptable for development only.")
    try:
        log.info("bootstrap: %s", bootstrap.initialise())
    except Exception as e:  # noqa: BLE001  - keep the API up so /api/health can report the problem
        log.error("bootstrap failed: %s - retrying in the background every %ss", scrub(str(e)), bootstrap.RETRY_INTERVAL_SECONDS)
        bootstrap._state["last_error"] = type(e).__name__
        bootstrap.start_background_retry()
    yield


app = FastAPI(title="Predictive Logistics & Forward Supply Chain \u2014 SIH PS 26251", description=config.DATA_NOTICE + " All telemetry is simulated.",
              version="8.0.0", lifespan=lifespan,
              docs_url="/docs" if config.settings.enable_api_docs else None, redoc_url=None,
              openapi_url="/openapi.json" if config.settings.enable_api_docs else None)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"], max_age=600)


def _error(status: int, code: str, detail, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail}, headers=headers)


@app.middleware("http")
async def request_pipeline(request: Request, call_next):
    """Request id -> rate limit -> handler -> security headers -> one access-log line. Unhandled errors become a generic 500 with a reference."""
    rid = request.headers.get("x-request-id", "")
    rid = rid if _REQ_ID.match(rid) else uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    request.state.request_id = rid
    path, started = request.url.path, time.perf_counter()
    response = None
    if path.startswith("/api/") and not path.startswith("/api/health") and request.method != "OPTIONS":
        ip = auth.get_client_ip(request)
        ok, wait = _rate.hit(ip)
        if ok and request.method not in ("GET", "HEAD"):
            ok, wait = _rate_write.hit(ip)
        if not ok:
            metrics.inc("rate_limited")
            response = _error(429, "RATE_LIMITED", "Too many requests. Slow down and retry shortly.", {"Retry-After": str(wait)})
    if response is None:
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            metrics.inc("unhandled_errors")
            log.exception("unhandled error on %s %s", request.method, path)
            response = _error(500, "INTERNAL_ERROR", f"Unexpected server error. Quote reference {rid} when reporting it.")
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if config.settings.is_production and config.settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers["X-Request-ID"] = rid
    p = getattr(request.state, "principal", None)
    level = logging.ERROR if response.status_code >= 500 else logging.INFO
    if not (path == "/api/health/live" and response.status_code < 400):          # probes would drown the log
        log.log(level, "%s %s -> %s", request.method, path, response.status_code,
                extra={"status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 1), "user": p.username if p else None})
    return response


# ---------------------------------------------------------------------------------------------------------- error handlers
@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    d = exc.detail
    if isinstance(d, dict) and "code" in d:
        return _error(exc.status_code, d["code"], d.get("detail", ""), dict(exc.headers or {}))
    return _error(exc.status_code, f"HTTP_{exc.status_code}", d, dict(exc.headers or {}))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    # the default handler echoes the submitted value, which could be a password: return location and message only
    items = [{"loc": [str(x) for x in e.get("loc", ())], "msg": e.get("msg", "invalid value"), "type": e.get("type", "value_error")} for e in exc.errors()]
    return _error(422, "VALIDATION_ERROR", items)


@app.exception_handler(DataError)
async def bad_data(_: Request, exc: Exception):
    # a value the database cannot store (e.g. a NUL byte): the caller's input is at fault, the database is fine
    metrics.inc("invalid_input_rejected_by_database")
    return _error(422, "INVALID_INPUT", "A submitted value cannot be processed.")


@app.exception_handler(OperationalError)
@app.exception_handler(DBAPIError)
async def db_unavailable(_: Request, exc: Exception):
    metrics.inc("database_errors")
    log.error("database error: %s", scrub(str(exc).splitlines()[0] if str(exc) else type(exc).__name__))
    return _error(503, "DB_UNAVAILABLE", "Database unavailable. Check that PostgreSQL/PostGIS is running.")


@app.exception_handler(RuntimeError)
async def not_ready(_: Request, exc: RuntimeError):
    metrics.inc("not_ready_errors")
    log.error("service not ready: %s", scrub(str(exc)))
    return _error(503, "NOT_READY", "The service is not ready: initial data load or forecast generation has not completed. See the system status page.")


# ------------------------------------------------------------------------------------------------------------------ health
def _model_component() -> dict:
    r = ms.resolve_forecast()
    f, ferr = ms.forecaster()
    s, serr = ms.shortage_model()
    if r.family == "machine_learning":
        fstatus = "trained_model_active"
    elif r.is_fallback:
        fstatus = "fallback_to_statistical"          # the trained model failed to load or run: visible degradation, never silent
    else:
        fstatus = "statistical_selected"             # statistical by configuration or because the trained model was not promoted
    return {"forecast_model": {"status": fstatus, "family": r.family},
            "shortage_model": {"status": "loaded" if s is not None else "unavailable"},
            "_detail": {"active_model_id": r.model_id, "fallback_reason": r.reason, "forecast_artefact_error": ms.safe_error(ferr), "shortage_artefact_error": ms.safe_error(serr)}}


@app.get("/api/health/live", tags=["health"])
def live():
    """Liveness: the process is running and serving requests. Says nothing about the database or models."""
    return {"status": "ok"}


def _db_check(db: Session) -> tuple[bool, str | None]:
    try:
        db.execute(text("select 1"))
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


@app.get("/api/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    """Readiness: the database answers and start-up (migrations, scenario data, forecasts) has completed."""
    ok, err = _db_check(db)
    state = {"database": ok, "startup_complete": bootstrap.is_ready()}
    return JSONResponse(status_code=200 if ok and bootstrap.is_ready() else 503, content={"status": "ready" if ok and bootstrap.is_ready() else "not_ready", **state})


@app.get("/api/health", tags=["health"])
def health(db: Session = Depends(get_db), user: auth.Principal | None = Depends(auth.optional_principal)):
    """API / database / model status. Anonymous callers get statuses only; signed-in users also get versions and counts."""
    notice = {"data_notice": config.DATA_NOTICE, "simulated_iot": True}
    ok, err = _db_check(db)
    models = _model_component()
    comps = {"api": {"status": "up"}, "database": {"status": "up" if ok else "down"}, "startup": {"status": "complete" if bootstrap.is_ready() else "pending"},
             "forecast_model": models["forecast_model"], "shortage_model": models["shortage_model"]}
    if not ok:
        return JSONResponse(status_code=503, content={"status": "degraded", "api": "up", "database": {"connected": False, "error": err}, "components": comps, **notice})
    database: dict = {"connected": True}
    if user is not None:
        try:
            database.update(repo.health(db))
        except Exception as e:  # noqa: BLE001 - e.g. schema not migrated yet
            database["detail_error"] = type(e).__name__
    status_ok = bootstrap.is_ready()
    return JSONResponse(status_code=200 if status_ok else 503, content={"status": "ok" if status_ok else "degraded", "api": "up", "database": database, "components": comps, **notice})


@app.get("/api/health/detail", tags=["health"])
def health_detail(db: Session = Depends(get_db), p: auth.Principal | None = Depends(auth.optional_principal)):
    """Operational detail for signed-in users and public evaluators: active model and version, last model load, forecast generation time, data coverage, fallbacks, counters."""
    ok, err = _db_check(db)
    models = _model_component()
    out = {"environment": config.APP_ENV, "api_version": app.version, "database": {"connected": ok, "schema_version": None},
           "startup": {"complete": bootstrap.is_ready(), "attempts": bootstrap._state["attempts"], "last_error": bootstrap._state["last_error"],
                       "last_success_at": None if not bootstrap._state["last_success_at"] else ms._iso(bootstrap._state["last_success_at"])},
           "models": ms.registry_status(), "model_state": models["_detail"], "operational": metrics.snapshot()}
    if p is not None and p.can("admin"):
        out["database"]["target"] = config.database_target(config.DATABASE_URL)       # host and database name: administrators only
    if ok:
        try:
            out["database"]["schema_version"] = migrate.current_version()
            out["data_freshness"] = repo.data_freshness(db)
            out["forecast_meta"] = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in repo.forecast_meta(db).items()}
        except Exception as e:  # noqa: BLE001
            out["data_freshness"] = {"error": type(e).__name__}
    return out


for r in (gis.router, inventory.router, forecast.router, decision.router, iot.router, simulation.router, ml.router):
    app.include_router(r)
app.include_router(auth.users_router, dependencies=[Depends(auth.admin)])
app.include_router(auth.router)

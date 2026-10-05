from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from . import bootstrap, config, repository as repo
from .database import get_db
from .routers import decision, forecast, gis, inventory, iot, simulation
from .schemas import Health

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("logistics")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        log.info("bootstrap: %s", bootstrap.initialise())
    except Exception as e:  # noqa: BLE001  - keep the API up so /api/health can report the problem
        log.error("bootstrap failed: %s - retrying in the background every %ss", e, bootstrap.RETRY_INTERVAL_SECONDS)
        bootstrap.start_background_retry()
    yield


app = FastAPI(title="Predictive Logistics & Forward Supply Chain \u2014 SIH PS 26251",
              description=config.DATA_NOTICE + " All telemetry is simulated.", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(OperationalError)
@app.exception_handler(DBAPIError)
async def db_unavailable(_: Request, exc: Exception):
    return JSONResponse(status_code=503, content={"code": "DB_UNAVAILABLE", "detail": "Database unavailable. Check that PostgreSQL/PostGIS is running."})


@app.exception_handler(RuntimeError)
async def not_ready(_: Request, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"code": "NOT_READY", "detail": str(exc)})


@app.get("/api/health", response_model=Health, tags=["health"])
def health(db: Session = Depends(get_db)):
    try:
        h = repo.health(db)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "degraded", "api": "up", "database": {"connected": False, "error": type(e).__name__},
                                                     "data_notice": config.DATA_NOTICE, "simulated_iot": True})
    return {"status": "ok", "api": "up", "database": {"connected": True, **h}, "data_notice": config.DATA_NOTICE}


for r in (gis.router, inventory.router, forecast.router, decision.router, iot.router, simulation.router):
    app.include_router(r)

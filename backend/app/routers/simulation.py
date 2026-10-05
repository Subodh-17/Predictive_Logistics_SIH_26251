from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import repository as repo
from ..database import get_db
from ..schemas import ScenarioIn
from ..services import simulation as sim
from ..services.domain import Params

router = APIRouter(prefix="/api/simulation", tags=["what-if-simulation"])


@router.post("/run")
def run(body: ScenarioIn, db: Session = Depends(get_db)):
    """Recalculate shortage locations, inventory risk, ETA, route risk, transport capacity, allocation and recommendations
    for a scenario; returns before/after metrics and explanations. The run is stored in simulation_runs."""
    snap = repo.load_snapshot(db)
    p = Params(body.demand_increase, body.weather_severity, body.road_degradation, body.vehicle_availability)
    out = sim.run(snap, p)
    out["run_id"] = repo.save_simulation(db, out)
    return out


@router.get("/runs")
def runs(limit: int = 20, db: Session = Depends(get_db)):
    return repo.list_simulations(db, max(1, min(limit, 100)))

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from .. import auth, repository as repo
from ..database import get_db
from ..schemas import ScenarioIn
from ..services import simulation as sim
from ..services.domain import Params

router = APIRouter(prefix="/api/simulation", tags=["what-if-simulation"])


@router.post("/run")
def run(body: ScenarioIn, request: Request, p: auth.Principal = Depends(auth.operator), db: Session = Depends(get_db)):
    """Recalculate shortage locations, inventory risk, ETA, route risk, transport capacity, allocation and recommendations
    for a scenario; returns before/after metrics and explanations. The run is stored in simulation_runs."""
    snap = repo.load_snapshot(db)
    prm = Params(body.demand_increase, body.weather_severity, body.road_degradation, body.vehicle_availability)
    out = sim.run(snap, prm)
    out["run_id"] = repo.save_simulation(db, out)
    auth.audit(p.username, "simulation_run", "success", target=str(out["run_id"]), ip=auth.get_client_ip(request), detail=prm.as_dict())
    return out


@router.get("/runs")
def runs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return repo.list_simulations(db, limit)


HIGHER_IS_BETTER = {"mean_days_cover", "allocated_units", "transport_capacity"}
LABELS = {"critical_items": "Critical items", "warning_items": "Warning items", "shortage_locations": "Locations at shortage risk", "overall_risk_index": "Overall risk index",
          "mean_days_cover": "Mean days of supply", "expected_shortage_units": "Expected shortage (units, 14 d)", "transport_need": "Transport need (units)",
          "transport_capacity": "Transport capacity (units)", "capacity_deficit": "Capacity deficit (units)", "allocated_units": "Units allocated",
          "unmet_after_allocation": "Unmet after allocation (units)", "mean_route_risk": "Mean route risk", "mean_eta_delay_h": "Mean ETA delay (h)", "weather_index": "Weather index"}


@router.get("/compare")
def compare(a: int = Query(..., ge=1), b: int = Query(..., ge=1), db: Session = Depends(get_db)):
    """Side-by-side comparison of two saved scenario runs, computed from the stored 'after' metrics (nothing is re-simulated).
    `same_baseline` is false when the inventory/forecast state differed between the two runs (e.g. events were recorded in between), in which case
    differences mix scenario effects and baseline changes and the response says so."""
    rows = {r["id"]: r for r in repo.list_simulations(db, 100000)}
    if a not in rows or b not in rows:
        raise HTTPException(404, "unknown simulation run")
    ra, rb = rows[a], rows[b]
    metrics = []
    for k in LABELS:
        if k in ra["after"] and k in rb["after"]:
            va, vb = ra["after"][k], rb["after"][k]
            d = round(vb - va, 3)
            better = "same" if d == 0 else (("b" if d > 0 else "a") if k in HIGHER_IS_BETTER else ("a" if d > 0 else "b"))
            metrics.append({"metric": k, "label": LABELS[k], "a": va, "b": vb, "delta": d, "delta_pct": None if va == 0 else round(100 * d / abs(va), 1),
                            "better": better if k != "weather_index" else "same"})
    same = ra["before"] == rb["before"]
    return {"a": {"id": a, "created_at": ra["created_at"], "params": ra["params"]}, "b": {"id": b, "created_at": rb["created_at"], "params": rb["params"]},
            "same_baseline": same, "metrics": metrics,
            "note": "Both runs start from the same baseline state; differences are caused by the scenario settings." if same else
                    "WARNING: the baseline state differed between the two runs (stock or events changed in between), so differences mix scenario effects and baseline changes."}

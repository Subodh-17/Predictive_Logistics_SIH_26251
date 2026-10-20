from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repository as repo
from ..schemas import AlertOut, InventoryOut
from ..serializers import alert_dict, item_dict
from ..services import inventory as inv_svc, model_service as ms
from .common import Ctx, IdQuery, OptIdQuery

router = APIRouter(prefix="/api", tags=["inventory"])


@router.get("/inventory", response_model=list[InventoryOut])
def inventory(location: OptIdQuery = None, supply: OptIdQuery = None,
              risk: str | None = Query(None, pattern="^(CRITICAL|WARNING|NORMAL)$"), c: Ctx = Depends()):
    """Inventory position, days of supply, predicted shortage and risk class for each location x supply."""
    if location and not repo.location_exists(c.db, location):
        raise HTTPException(404, f"unknown location {location}")
    if supply and not repo.supply_exists(c.db, supply):
        raise HTTPException(404, f"unknown supply {supply}")
    rows = [i for i in c.res.items if (not location or i.location_id == location) and (not supply or i.supply_id == supply)
            and (not risk or i.status == risk)]
    return [item_dict(i) for i in sorted(rows, key=lambda i: i.days)]


@router.get("/inventory/projection")
def projection(location: IdQuery, supply: IdQuery, c: Ctx = Depends()):
    """14-day stock projection against safety stock (scenario-aware)."""
    i = next((x for x in c.res.items if x.location_id == location and x.supply_id == supply), None)
    if i is None:
        raise HTTPException(404, "unknown location/supply pair")
    pts = [max(0.0, i.stock - i.scale * sum(i.fut[:j])) for j in range(15)]
    return {"location": location, "supply": supply, "days": list(range(15)), "projected_stock": [round(p, 1) for p in pts],
            "safety_stock": round(i.safety, 1), "days_left": round(i.days, 2), "status": i.status}


@router.get("/alerts")
def alerts(c: Ctx = Depends()):
    """Baseline alerts are read from the `alerts` table (refreshed on startup, IoT updates and recompute);
    scenario alerts are derived live from the scenario-aware engine."""
    if c.p.is_baseline:
        rows, source = repo.stored_alerts(c.db), "database"
    else:
        rows, source = [alert_dict(i) for i in sorted((i for i in c.res.items if i.status != "NORMAL"), key=lambda i: i.days)], "scenario"
    return {"source": source, "critical": sum(1 for r in rows if r["severity"] == "CRITICAL"),
            "warning": sum(1 for r in rows if r["severity"] == "WARNING"), "alerts": rows}


@router.get("/inventory/risk-basis")
def risk_basis():
    """How every inventory risk estimate is produced: source, horizon, rules, limitations, and the status of the shortage-onset model."""
    res = ms.resolve_forecast()
    return {**inv_svc.risk_basis(),
            "forecast_model": {"model_id": res.model_id, "family": res.family, "fallback_reason": res.reason},
            "shortage_onset_model": ms.shortage_integration()}

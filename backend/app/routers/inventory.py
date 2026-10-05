from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repository as repo
from ..schemas import AlertOut, InventoryOut
from ..serializers import alert_dict, item_dict
from .common import Ctx

router = APIRouter(prefix="/api", tags=["inventory"])


@router.get("/inventory", response_model=list[InventoryOut])
def inventory(location: str | None = None, supply: str | None = None,
              risk: str | None = Query(None, pattern="^(CRITICAL|WARNING|NORMAL)$"), c: Ctx = Depends()):
    """Inventory position, days of supply, predicted shortage and risk class for each location x supply."""
    rows = [i for i in c.res.items if (not location or i.location_id == location) and (not supply or i.supply_id == supply)
            and (not risk or i.status == risk)]
    return [item_dict(i) for i in sorted(rows, key=lambda i: i.days)]


@router.get("/inventory/projection")
def projection(location: str, supply: str, c: Ctx = Depends()):
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

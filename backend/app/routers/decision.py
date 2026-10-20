from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import repository as repo
from ..schemas import PriorityOut
from ..serializers import insight_dict, iso_date
from ..services import engine, forecasting as F
from ..services import status as st
from ..services.allocation import allocate
from ..services.domain import ND, NF, Params, day_date
from ..services.explain import why_at_risk
from ..services.inventory import risk_band
from ..services.priority import WEIGHTS, prioritise
from ..services.recommendation import recommend
from .common import Ctx

router = APIRouter(prefix="/api", tags=["decision-support"])


@router.get("/priority", response_model=list[PriorityOut])
def priority(limit: int = Query(0, ge=0, le=100), c: Ctx = Depends()):
    """Supply priority queue: decision-support priority score from shortage, deficit, criticality, lead time, route feasibility, capacity."""
    rows = prioritise(c.res)
    rows = rows[:limit] if limit else rows
    return [{"rank": k, "location": p.item.location_id, "supply": p.item.supply_id, "status": p.item.status, "score": p.score,
             "components": {k2: round(v, 3) for k2, v in p.components.items()}, "days_cover": round(p.item.days, 2),
             "stockout_date": iso_date(p.item.stockout_date), "replenish_qty": p.item.qty, "best_route": p.best_route,
             "route_feasible": p.route_feasible} for k, p in enumerate(rows, 1)]


@router.get("/priority/weights")
def priority_weights():
    return {"weights": WEIGHTS, "note": "Fixed, documented assumptions; not calibrated against real operations."}


@router.get("/allocation")
def allocation(c: Ctx = Depends()):
    """Decision-support allocation respecting actual depot stock and effective vehicle capacity."""
    a = allocate(c.res, c.snap)
    reasons: dict = {}
    for r in a.rows:
        if r.unmet:
            reasons[r.unmet_reason] = reasons.get(r.unmet_reason, 0) + r.unmet
    depot = [{"depot": d, "supply": s, "start": c.snap.depot_stock[(d, s)], "remaining": a.depot_stock_after[(d, s)],
              "used": c.snap.depot_stock[(d, s)] - a.depot_stock_after[(d, s)]}
             for (d, s) in c.snap.depot_stock if c.snap.depot_stock[(d, s)] != a.depot_stock_after[(d, s)]]
    return {
        "label": "Decision-Support Allocation \u2014 Illustrative Scenario",
        "total_need": c.res.need, "fleet_capacity": c.res.capacity, "allocated": a.used, "unmet": a.unmet, "capacity_left": a.capacity_left,
        "pooled_fleet_deficit": c.res.deficit, "unmet_by_reason": reasons,
        "rows": [{"rank": k, "location": r.prio.item.location_id, "supply": r.prio.item.supply_id, "score": r.prio.score,
                  "safety_deficit": r.safety_deficit, "lead_days": round(r.prio.item.lead, 2), "need": r.need, "allocated": r.allocated,
                  "unmet": r.unmet, "status": r.status, "unmet_reason": r.unmet_reason,
                  "legs": [{"vehicle": g.vehicle, "route": g.route, "depot": g.depot, "quantity": g.quantity} for g in r.legs]}
                 for k, r in enumerate(a.rows, 1)],
        "depot_stock_used": sorted(depot, key=lambda d: -d["used"]),
        "notes": ["Allocation never exceeds effective vehicle capacity or the serving depot's stock of that supply.",
                  "Unmet can exceed the pooled fleet deficit because each vehicle can only serve routes from its own depot.",
                  "The AI Logistics Insight is a stand-alone recommendation per item that assumes full vehicle availability; the plan resolves vehicle contention across all items, so the assigned vehicle can differ."],
    }


@router.get("/insights")
def insights(c: Ctx = Depends()):
    """AI Logistics Insight (deterministic rule-based engine), prioritised dispatch list and 'Why at risk' explanations."""
    at_risk = sorted([i for i in c.res.items if i.status != "NORMAL"], key=lambda i: i.days)
    crit = [i for i in at_risk if i.status == "CRITICAL"]
    top = (crit or at_risk or [None])[0]
    return {
        "engine": "deterministic rule-based recommendation engine; no external AI model is used",
        "top": insight_dict(top, c.res) if top else None,
        "dispatch": [insight_dict(i, c.res) for i in at_risk[:5]],
        "why_at_risk": [w for w in (why_at_risk(c.res, l.id) for l in c.res.locs if l.status != "NORMAL") if w],
        "at_risk_count": len(at_risk),
    }


@router.get("/dashboard")
def dashboard(c: Ctx = Depends()):
    """KPIs, aggregate forecast chart, system status, data coverage and data-pipeline summary."""
    res, snap, db = c.res, c.snap, c.db
    crit = [i for i in res.items if i.status == "CRITICAL"]
    band, level = risk_band(res.risk_index)
    s = repo.forecast_series(db, None, None)
    sc = 1 + res.params.demand if res.params.demand else 1
    chart = [{"date": day_date(d).date().isoformat(), "actual": s["actual"][d], "forecast": None} for d in range(ND - 30, ND)]
    chart[-1]["forecast"] = s["actual"][-1]
    chart += [{"date": day_date(ND + k).date().isoformat(), "actual": None, "forecast": s["fut"][k] * sc} for k in range(14)]
    h = repo.health(db)
    bt = F.backtest(s["actual"], s["fit"])
    n_rec = h["counts"]["consumption"]
    base_res = res if res.params.is_baseline else engine.compute(snap, Params())
    at_risk = [i for i in res.items if i.status != "NORMAL"]
    return {
        "kpis": {"locations": len(snap.locations), "depots": len(snap.depots), "forward": len(snap.forward), "critical_shortages": len(crit),
                 "warning_locations": sum(1 for l in res.locs if l.status == "WARNING"), "critical_locations": sum(1 for l in res.locs if l.status == "CRITICAL"),
                 "vehicles_available": sum(1 for _, (d, cp) in res.vehicles_eff.items() if cp), "vehicles_total": len(snap.vehicles),
                 "transport_capacity": res.capacity, "supplies_at_risk_units": res.short_total, "risk_index": res.risk_index, "risk_band": band, "risk_level": level,
                 "transport_need": res.need, "capacity_deficit": res.deficit},
        "forecast_chart": chart, "scenario": res.params.as_dict(), "scenario_active": not res.params.is_baseline,
        "system_status": st.engine_status(snap, res, base_res, n_rec, bt.mape, len(snap.positions)),
        "data_coverage": {"historical_days": ND, "forward_locations": len(snap.forward), "supply_types": len(snap.supplies), "historical_records": n_rec,
                          "depots": len(snap.depots), "routes": len(snap.routes), "vehicles": len(snap.vehicles)},
        "pipeline": [{"stage": "Consumption", "detail": f"{n_rec:,} records"}, {"stage": "Inventory", "detail": f"{len(res.items)} positions"},
                     {"stage": "Weather", "detail": f"{ND + NF}-day index"}, {"stage": "Transport", "detail": f"{len(snap.vehicles)} vehicles"},
                     {"stage": "Routes", "detail": f"{len(snap.routes)} routes \u00b7 terrain"},
                     {"stage": "Prediction Engine", "detail": f"{len(snap.positions)} forecasts \u00b7 {NF}-day outlook"},
                     {"stage": "Risk Engine", "detail": f"{res.n_critical} critical \u00b7 {res.n_warning} warning items"},
                     {"stage": "Recommendation Engine", "detail": f"{len(at_risk)} prioritised actions \u00b7 route selection"}],
    }

"""Explainable risk ('Why at risk') and what-if explanations."""
from __future__ import annotations

from . import routing as rt
from . import terrain as T
from .recommendation import fx


def weather_label(v: float) -> str:
    return "Normal" if v == 0 else "Elevated" if v < .5 else "Heavy" if v < 1 else "Severe"


def road_scenario_label(v: float) -> str:
    return "Good" if v == 0 else "Fair" if v < .5 else "Poor"


def best_route(result, loc_id):
    rs = result.routes_to(loc_id)
    return min(rs, key=lambda r: r.risk) if rs else None


def demand_change_pct(item) -> float:
    return (item.dem / item.hist7 - 1) * 100 if item.hist7 else 0.0


def why_at_risk(result, loc_id) -> dict | None:
    loc = next(l for l in result.locs if l.id == loc_id)
    items = sorted([i for i in result.items if i.location_id == loc_id and i.status != "NORMAL"], key=lambda i: i.days)[:3]
    if not items:
        return None
    br = best_route(result, loc_id)
    t = items[0]
    ch = demand_change_pct(t)
    return {
        "location": loc_id, "status": loc.status, "weather_index": round(result.weather, 2),
        "best_route": br.id, "best_route_risk_level": T.risk_level(br.risk), "best_route_risk": round(br.risk * 100),
        "items": [{"supply": i.supply_id, "demand_change_pct": round(demand_change_pct(i), 1), "stock": round(i.stock),
                   "days_cover": round(i.days, 1), "safety": round(i.safety), "below_safety": i.stock < i.safety,
                   "lead_days": round(i.lead, 1)} for i in items],
        "summary": (f"{t.supply_id}: forecast demand is {'+' if ch >= 0 else ''}{ch:.0f}% vs the last 7 days; {fx(t.stock)} units "
                    f"on hand is {'below' if t.stock < t.safety else 'above'} the {fx(t.safety)} safety stock, giving {t.days:.1f} days "
                    f"of cover against a {t.lead:.1f} day replenishment lead time, with route risk {T.risk_level(br.risk)} "
                    f"at weather index {result.weather:.2f}."),
    }

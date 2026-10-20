"""Deterministic, rule-based recommendation engine (no external AI model)."""
from __future__ import annotations

from .domain import js_round
from . import routing as rt
from . import terrain as T


def fx(v, d=0):
    return f"{v:,.{d}f}"


def recommend(result, item) -> dict:
    """Best available depot / vehicle / route for one at-risk item (stand-alone, assumes full fleet availability)."""
    rows = [r for r in rt.rank_routes(result.routes, result.vehicles_eff, item.location_id, item.qty) if r["feasible"]]
    if not rows:
        return {"source": None, "vehicle": None, "route": None,
                "reason": "No available vehicle can serve this location; escalate transport allocation."}
    best = rows[0]["ev"]
    vs = [(vid, c) for vid, (d, c) in result.vehicles_eff.items() if d == best.depot_id and c > 0]
    suff = sorted([v for v in vs if v[1] >= item.qty], key=lambda v: v[1])
    veh = suff[0] if suff else max(vs, key=lambda v: v[1])
    elev = best.route.elevation_label.split(" ")[0].lower()
    reason = (f"Predicted consumption ({fx(item.dem * 14)} units / 14 d) exceeds available inventory ({fx(item.stock)}); "
              f"cover is {item.days:.1f} d against a {item.lead:.1f} d replenishment lead time. "
              f"{best.depot_id} has {veh[0]} ({fx(veh[1])} units) available on {best.id} "
              f"(route risk {T.risk_level(best.risk)}, ETA {best.eta:.1f} h, {best.route.terrain_type} terrain at {elev} elevation)")
    reason += "; quantity exceeds one sortie, so split the dispatch." if veh[1] < item.qty else "."
    return {"source": best.depot_id, "vehicle": veh[0], "route": best.id, "reason": reason}

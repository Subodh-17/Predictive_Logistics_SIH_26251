"""Decision-Support Priority Score (0-100) for at-risk items.

score = 100 x ( 0.30 shortage urgency   (1 - days of cover / 10)
              + 0.15 shortage volume    (unmet share of 14-day demand)
              + 0.15 stock deficit      (share of safety stock missing)
              + 0.15 supply criticality (fixed prototype weight per supply type)
              + 0.10 lead-time pressure (replenishment lead time vs remaining cover)
              + 0.10 route feasibility  (risk of best feasible route; 1.0 if none)
              + 0.05 transport capacity (quantity to move vs serving depot capacity) )
Weights are fixed, documented assumptions of this prototype.
"""
from __future__ import annotations

from dataclasses import dataclass

from .domain import clamp, js_round
from . import routing as rt

WEIGHTS = {"urgency": 0.30, "shortage": 0.15, "deficit": 0.15, "criticality": 0.15,
           "lead_time": 0.10, "route": 0.10, "capacity": 0.05}


@dataclass
class Prioritised:
    item: object
    score: int
    components: dict
    best_route: str | None
    route_feasible: bool


def components(item, result) -> tuple:
    rows = rt.rank_routes(result.routes, result.vehicles_eff, item.location_id, item.qty)
    feas = [r for r in rows if r["feasible"]]
    best = feas[0] if feas else (rows[0] if rows else None)
    route_term = feas[0]["ev"].risk if feas else 1.0
    cap_term = clamp(item.qty / feas[0]["capacity"], 0, 1) if feas and item.qty > 0 else (0.0 if feas else 1.0)
    comp = {
        "urgency": clamp(1 - item.days / 10, 0, 1),
        "shortage": clamp(item.short / (item.dem * 14), 0, 1) if item.dem > 0 else 0.0,
        "deficit": clamp((item.safety - item.stock) / item.safety, 0, 1) if item.safety > 0 else 0.0,
        "criticality": item.criticality,
        "lead_time": clamp(0.5 * item.lead / max(item.days, 0.25), 0, 1),
        "route": route_term,
        "capacity": cap_term,
    }
    return comp, (best["ev"].id if best else None), bool(feas)


def prioritise(result) -> list:
    out = []
    for i in result.items:
        if i.status == "NORMAL":
            continue
        comp, best, ok = components(i, result)
        score = js_round(100 * sum(WEIGHTS[k] * comp[k] for k in WEIGHTS))
        out.append(Prioritised(i, score, comp, best, ok))
    out.sort(key=lambda p: (-p.score, p.item.days))
    return out

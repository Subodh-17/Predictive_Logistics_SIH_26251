"""Decision-support allocation: ranked needs -> feasible routes -> vehicle loads, within real depot stock and vehicle capacity.

Order = priority score. For each item the routes to its destination are tried in combined-score order. On each route
the depot can ship at most its remaining stock of that supply; vehicles at the depot are loaded within remaining
effective capacity (smallest sufficient vehicle first). Unmet quantity is reported with its binding constraint.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import routing as rt
from .priority import prioritise


@dataclass
class Leg:
    route: str
    vehicle: str
    depot: str
    quantity: int


@dataclass
class AllocRow:
    prio: object
    need: int
    allocated: int
    unmet: int
    legs: list
    safety_deficit: int
    unmet_reason: str      # '' | 'VEHICLE CAPACITY' | 'DEPOT STOCK' | 'NO FEASIBLE ROUTE'

    @property
    def status(self):
        return "FULL" if self.unmet == 0 else "PARTIAL" if self.allocated else "NOT SERVED"


@dataclass
class Allocation:
    rows: list
    used: int
    unmet: int
    capacity_left: int
    depot_stock_after: dict


def allocate(result, snap) -> Allocation:
    cap = {vid: c for vid, (_, c) in result.vehicles_eff.items()}
    depot_of = {vid: d for vid, (d, _) in result.vehicles_eff.items()}
    dstock = {k: v for k, v in snap.depot_stock.items()}
    rows = []
    for pr in prioritise(result):
        item = pr.item
        if item.qty <= 0:
            continue
        need, legs, reasons = item.qty, [], set()
        ranked = rt.rank_routes(result.routes, result.vehicles_eff, item.location_id, item.qty)
        if not any(r["feasible"] for r in ranked):
            reasons.add("NO FEASIBLE ROUTE")
        for r in ranked:
            if need <= 0:
                break
            if not r["feasible"]:
                continue
            dep = r["ev"].depot_id
            key = (dep, item.supply_id)
            while need > 0:
                avail = dstock.get(key, 0)
                vs = [v for v, d in depot_of.items() if d == dep and cap[v] > 0]
                if avail <= 0:
                    reasons.add("DEPOT STOCK")
                    break
                if not vs:
                    reasons.add("VEHICLE CAPACITY")
                    break
                target = min(need, avail)
                suff = sorted([v for v in vs if cap[v] >= target], key=lambda v: cap[v])
                f = suff[0] if suff else max(vs, key=lambda v: cap[v])
                q = int(min(target, cap[f]))
                cap[f] -= q
                dstock[key] = avail - q
                need -= q
                legs.append(Leg(r["ev"].id, f, dep, q))
        reason = ""
        if need > 0:
            reason = "DEPOT STOCK" if "DEPOT STOCK" in reasons else sorted(reasons)[0] if reasons else "VEHICLE CAPACITY"
        rows.append(AllocRow(pr, item.qty, item.qty - need, need, legs, max(0, int(item.safety - item.stock)), reason))
    return Allocation(rows, sum(r.allocated for r in rows), sum(r.unmet for r in rows), int(sum(cap.values())), dstock)

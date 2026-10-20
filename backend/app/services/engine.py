"""Core logistics engine: scenario-aware inventory + route + risk calculation over a Snapshot (port of v3 calc())."""
from __future__ import annotations

from dataclasses import dataclass, field

from .domain import Params, Snapshot, js_round, day_date
from . import inventory as inv
from . import routing as rt


@dataclass
class Item:
    location_id: str
    supply_id: str
    sensitivity: float
    criticality: float
    stock: float
    safety: float
    f7: float
    fut: tuple
    hist7: float
    dem: float
    days: float
    lead: float
    status: str
    qty: int
    short: int
    stockout_date: object
    scale: float


@dataclass
class LocStatus:
    id: str
    status: str
    n_critical: int
    n_warning: int
    n_normal: int
    min_days: float
    min_supply: str
    short: int
    dem: float


@dataclass
class Result:
    params: Params
    weather: float
    weather_now: float
    items: list
    locs: list
    routes: list            # list[RouteEval]
    vehicles_eff: dict      # {vehicle_id: (depot_id, effective_capacity)}
    capacity: int
    need: int
    deficit: int
    n_critical: int
    n_warning: int
    avg_route_risk: float
    risk_index: int
    short_total: int
    mean_delay: float
    avg_days: float
    shortage_locations: int

    def route(self, rid):
        return next(r for r in self.routes if r.id == rid)

    def routes_to(self, dest):
        return [r for r in self.routes if r.dest_id == dest]


def weather_now(snapshot: Snapshot) -> float:
    w, nd = snapshot.weather, snapshot.nd
    return (w[nd] + w[nd + 1] + w[nd + 2]) / 3


def compute(snap: Snapshot, p: Params) -> Result:
    wn = weather_now(snap)
    w = wn + p.weather * (0.9 - wn)
    dm = lambda s: (1 + p.demand) * (1 + s * 0.6 * (w - wn))

    routes = [rt.evaluate_route(r, w, p) for r in snap.routes]
    veff = {v.id: (v.depot_id, js_round(v.capacity * p.vehicles) if v.available else 0) for v in snap.vehicles}
    cap = sum(c for _, c in veff.values())

    lead = {}
    for loc in snap.forward:
        etas = [r.eta for r in routes if r.dest_id == loc.id]
        lead[loc.id] = 1 + (min(etas) if etas else 0) / 24

    items = []
    for ps in snap.positions:
        s = snap.supply(ps.supply_id)
        dem = ps.f7 * dm(s.sensitivity)
        days = inv.days_of_supply(ps.stock, dem)
        ld = lead[ps.location_id]
        st = inv.classify(days, ld, ps.stock, ps.safety_stock)
        items.append(Item(ps.location_id, ps.supply_id, s.sensitivity, s.criticality, ps.stock, ps.safety_stock,
                          ps.f7, ps.fut, ps.hist7, dem, days, ld, st,
                          inv.replenishment_qty(st, ps.safety_stock, dem, ld, ps.stock),
                          inv.predicted_shortage(dem, ps.stock, 14), day_date(snap.nd + days), dem / ps.f7))

    locs = []
    for loc in snap.forward:
        it = [i for i in items if i.location_id == loc.id]
        c = sum(1 for i in it if i.status == "CRITICAL")
        n = sum(1 for i in it if i.status == "WARNING")
        mn = min(it, key=lambda i: i.days)
        locs.append(LocStatus(loc.id, inv.location_status(c, n), c, n, len(it) - c - n, mn.days, mn.supply_id,
                              sum(i.short for i in it), sum(i.dem for i in it)))

    need = sum(i.qty for i in items)
    deficit = max(0, need - cap)
    N = len(items)
    crit = sum(1 for i in items if i.status == "CRITICAL")
    warn = sum(1 for i in items if i.status == "WARNING")
    ar = sum(r.risk for r in routes) / len(routes)
    risk = inv.overall_risk_index(crit, warn, N, ar, deficit, need)
    return Result(p, w, wn, items, locs, routes, veff, cap, need, deficit, crit, warn, ar, risk,
                  sum(i.short for i in items), sum(r.delay for r in routes) / len(routes),
                  sum(i.days for i in items) / N, sum(1 for l in locs if l.status != "NORMAL"))

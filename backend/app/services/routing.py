"""Route evaluation, scoring and selection.

Combined route score (lower is better) = route risk (0..1) + ETA / 24 h + capacity penalty.
Route risk already contains distance, road condition, weather and terrain; ETA uses terrain/road/weather
adjusted effective speed; the capacity penalty (0..0.2) grows when the serving depot's available vehicle
capacity cannot carry the quantity that needs to move. A route is feasible only if (1) its depot has at
least one available vehicle and (2) the corridor is not closed (weather risk below CLOSURE_WEATHER_RISK).
NOT modelled: convoy escort or fuel limits, bridge load limits, time windows, driver hours, enemy action,
per-vehicle cargo compatibility. A feasible route is therefore "feasible under these constraints", not a guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass

from .domain import Params, Route, Vehicle, clamp
from . import terrain as T

CAPACITY_PENALTY_WEIGHT = 0.2
# Documented assumption (V7): a corridor is treated as CLOSED, hence not feasible, when its weather risk reaches this level. The scenario's
# speed model otherwise never stops a convoy (effective speed has an 8 km/h floor), which would let a storm-closed road count as usable.
CLOSURE_WEATHER_RISK = 0.85


@dataclass
class RouteEval:
    route: Route
    road: float
    terrain_risk: float
    weather_risk: float
    speed: float
    eta: float
    delay: float
    risk: float

    @property
    def id(self): return self.route.id
    @property
    def depot_id(self): return self.route.depot_id
    @property
    def dest_id(self): return self.route.dest_id


def evaluate_route(route: Route, weather: float, params: Params) -> RouteEval:
    tr = T.terrain_risk(route.terrain_difficulty, route.elevation_band)
    road = min(1.0, route.road_condition + 0.5 * params.road)
    wr = T.route_weather_risk(weather, tr)
    v = T.effective_speed(route.nominal_speed, road, tr, wr)
    eta = route.distance_km / v
    return RouteEval(route, road, tr, wr, v, eta, eta - route.distance_km / route.nominal_speed,
                     T.route_risk(road, wr, tr, route.distance_km))


def depot_capacity(vehicles_eff: dict, depot_id: str) -> int:
    return sum(c for (d, c) in vehicles_eff.values() if d == depot_id)


def score_route(ev: RouteEval, capacity: float, required: float = 0.0) -> float:
    """Combined score; `required` (units to move) adds a capacity penalty when capacity falls short."""
    pen = 0.0
    if required > 0:
        pen = CAPACITY_PENALTY_WEIGHT * clamp(1 - capacity / required, 0, 1)
    return ev.risk + ev.eta / 24 + pen


def rank_routes(evals: list, vehicles_eff: dict, dest_id: str, required: float = 0.0) -> list:
    """All routes to a destination with capacity, score and feasibility, best first (feasible before infeasible)."""
    rows = []
    for ev in evals:
        if ev.dest_id != dest_id:
            continue
        cap = depot_capacity(vehicles_eff, ev.depot_id)
        closed = ev.weather_risk >= CLOSURE_WEATHER_RISK
        reason = "ROUTE CLOSED" if closed else "NO AVAILABLE VEHICLE" if cap <= 0 else ""
        rows.append({"ev": ev, "capacity": cap, "score": score_route(ev, cap, required), "feasible": not reason, "blocked_reason": reason})
    rows.sort(key=lambda r: (not r["feasible"], r["score"]))
    return rows


def explain_selection(rows: list, dest_id: str) -> str:
    feas = [r for r in rows if r["feasible"]]
    if not feas:
        why = sorted({r["blocked_reason"] for r in rows if r.get("blocked_reason")})
        return "No feasible route: " + (" and ".join(w.lower() for w in why) if why else "no corridor serves this location") + "."
    ch = feas[0]["ev"]
    if len(feas) == 1:
        tail = " (the other routes have no available vehicle)." if len(rows) > 1 else " (single-corridor location)."
        return f"{ch.id} is the only feasible corridor to {dest_id}{tail}"
    o = feas[1]["ev"]
    risk_txt = "lower route risk" if ch.risk <= o.risk else "higher route risk but shorter ETA"
    eta_txt = " and shorter ETA." if ch.eta <= o.eta else " despite a longer ETA."
    return (f"{ch.id} has the lowest combined score ({feas[0]['score']:.2f} vs {feas[1]['score']:.2f} for {o.id}): "
            f"{risk_txt}{eta_txt} Terrain risk {round(ch.terrain_risk * 100)} ({ch.route.terrain_type}) "
            f"vs {round(o.terrain_risk * 100)} ({o.route.terrain_type}).")

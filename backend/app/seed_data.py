"""Deterministic FICTIONAL synthetic dataset (port of the v3 prototype generator).

Used by scripts/generate_seed.py to render db/seed.sql, and by unit tests to build a Snapshot without a database.
No real military bases, routes, units, deployments or sensitive information are represented. Coordinates are arbitrary
points placed on a base map purely so the Leaflet GIS view has something to draw.
"""
from __future__ import annotations

import math
from datetime import date

from .services import forecasting as F
from .services.domain import (ND, NF, Location, Position, Route, Snapshot, Supply, Vehicle, clamp, day_date, js_round)
from .services.terrain import ELEVATION_LABELS

M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & M32


def mulberry32(seed: int):
    """Same PRNG as the v3 JavaScript prototype (bit-exact)."""
    s = seed & M32

    def rnd() -> float:
        nonlocal s
        s = (s + 0x6D2B79F5) & M32
        t = _imul(s ^ (s >> 15), 1 | s)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & M32) ^ t
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return rnd


# id, base daily demand, weather sensitivity
SUPPLY_ROWS = [("Food", 420, .2), ("Fuel", 650, .5), ("Water", 900, .6), ("Medical", 130, .15), ("Maintenance", 160, .1),
               ("Engineering", 210, .05), ("Clothing", 110, .3), ("Comms", 60, .05), ("Spares", 140, .1), ("Shelter", 90, .35)]
CRITICALITY = {"Medical": 1, "Water": .95, "Food": .9, "Fuel": .85, "Comms": .7, "Maintenance": .6, "Engineering": .55,
               "Spares": .5, "Shelter": .5, "Clothing": .4}
# fictional grid coordinates (v3 schematic grid); mapped to lon/lat below
DEPOTS = [("Depot_A", 12, 52), ("Depot_B", 40, 63), ("Depot_C", 84, 58)]
# id, x, y, demand factor, stock penalty (generator only)
BASES = [("Base_01", 30, 36, .7, 0), ("Base_02", 56, 42, .9, 2), ("Base_03", 18, 16, 1, 3), ("Base_04", 48, 12, 1.3, 5), ("Base_05", 82, 24, 1.1, 2.8)]
# id, depot, destination, km, road condition (0 good..1 poor), nominal km/h
ROUTES = [("R01", "Depot_A", "Base_01", 62, .2, 50), ("R02", "Depot_A", "Base_03", 118, .5, 35), ("R03", "Depot_A", "Base_04", 134, .45, 38),
          ("R04", "Depot_B", "Base_01", 74, .25, 48), ("R05", "Depot_B", "Base_02", 58, .15, 55), ("R06", "Depot_C", "Base_02", 88, .3, 46),
          ("R07", "Depot_C", "Base_05", 96, .55, 32), ("R08", "Depot_B", "Base_04", 150, .6, 34)]
# route id, terrain type, difficulty 0..1, elevation band 0..3 (fictional bands)
TERRAIN = [("R01", "Foothill road", .3, 1), ("R02", "Forested hills", .65, 2), ("R03", "Mountain pass", .6, 2), ("R04", "Rolling plains", .25, 0),
           ("R05", "Valley floor", .15, 0), ("R06", "Rocky plateau", .35, 1), ("R07", "High-altitude ridge", .85, 3), ("R08", "Mountain pass", .7, 2)]
# id, depot, capacity (units), available, type
VEHICLES = [("V001", "Depot_A", 4000, True, "Heavy truck"), ("V002", "Depot_A", 6000, True, "Tractor-trailer"), ("V003", "Depot_A", 3500, True, "Heavy truck"),
            ("V004", "Depot_B", 5500, True, "Tractor-trailer"), ("V005", "Depot_B", 4500, True, "Heavy truck"), ("V006", "Depot_C", 6500, True, "Tractor-trailer"),
            ("V007", "Depot_C", 4000, True, "Heavy truck"), ("V008", "Depot_B", 3500, False, "Heavy truck")]
# share of network stock held by each depot, and days of network demand held (finite, so depot stock can bind under stress)
DEPOT_SHARE = {"Depot_A": .40, "Depot_B": .35, "Depot_C": .25}
DEPOT_DAYS_COVER = 8

LON0, LON_STEP, LAT0, LAT_STEP = 78.60, 0.0205, 22.90, 0.0185


def xy_to_lonlat(x: float, y: float) -> tuple:
    return round(LON0 + x * LON_STEP, 5), round(LAT0 - y * LAT_STEP, 5)


def route_polyline(a: tuple, b: tuple, idx: int) -> list:
    """Fictional road polyline: start, one bent waypoint, end (lon, lat)."""
    (x1, y1), (x2, y2) = a, b
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    sign = 1 if idx % 2 == 0 else -1
    wx, wy = mx - dy * 0.07 * sign, my + dx * 0.07 * sign
    return [xy_to_lonlat(x1, y1), xy_to_lonlat(wx, wy), xy_to_lonlat(x2, y2)]


def build_weather(rnd) -> list:
    W = []
    for d in range(ND + NF):
        W.append(clamp(.32 + .22 * math.sin(d / 8.5) + .12 * math.sin(d / 2.7 + 1) + (.35 if 112 <= d <= 117 else 0) + (rnd() - .5) * .1, 0, 1))
    return W


def build_dataset() -> dict:
    rnd = mulberry32(2026)
    W = build_weather(rnd)
    hist, stocks = {}, {}
    for b, _, _, f, pen in BASES:
        for t, base, s in SUPPLY_ROWS:
            ad = lambda d: 1 + s * .6 * W[d]
            x = [js_round(base * f * (1 + .0015 * d) * ad(d) * F.weekly_season(d) * (1 + (rnd() - .5) * .14)) for d in range(ND)]
            hist[(b, t)] = x
            d0 = 2.8 if (b == "Base_04" and t == "Medical") else max(1.5, 3 + 10 * rnd() - pen)
            _, fut = F.fit_and_forecast(x, s, W)
            f7 = F.mean_first(fut)
            stocks[(b, t)] = (js_round(d0 * f7), js_round(4 * f7))
    # depot stock: share of (DEPOT_DAYS_COVER x network daily demand per supply), rounded to 50
    net = {}
    for (b, t), (stock, safety) in stocks.items():
        _, fut = F.fit_and_forecast(hist[(b, t)], next(s for (n, _, s) in SUPPLY_ROWS if n == t), W)
        net[t] = net.get(t, 0) + F.mean_first(fut)
    depot_stock = {(d, t): int(js_round(DEPOT_SHARE[d] * DEPOT_DAYS_COVER * net[t] / 50) * 50) for d, _, _ in DEPOTS for t, _, _ in SUPPLY_ROWS}
    return {"weather": W, "history": hist, "stocks": stocks, "depot_stock": depot_stock}


def locations() -> list:
    out = [Location(d, d.replace("_", " ") + " (fictional)", "DEPOT", *reversed(xy_to_lonlat(x, y)), 1.0) for d, x, y in DEPOTS]
    out += [Location(b, b.replace("_", " ") + " (fictional)", "FORWARD", *reversed(xy_to_lonlat(x, y)), f) for b, x, y, f, _ in BASES]
    return out


def routes() -> list:
    pos = {d: (x, y) for d, x, y in DEPOTS}
    pos.update({b: (x, y) for b, x, y, _, _ in BASES})
    ter = {r: (t, td, el) for r, t, td, el in TERRAIN}
    out = []
    for i, (rid, a, b, km, rd, sp) in enumerate(ROUTES):
        t, td, el = ter[rid]
        coords = tuple((lat, lon) for lon, lat in route_polyline(pos[a], pos[b], i))
        out.append(Route(rid, a, b, km, rd, sp, t, td, el, ELEVATION_LABELS[el], coords))
    return out


def supplies() -> list:
    return [Supply(n, b, s, CRITICALITY[n]) for n, b, s in SUPPLY_ROWS]


def vehicles() -> list:
    return [Vehicle(*v[:4], v[4]) for v in VEHICLES]


def snapshot_from_dataset(ds: dict | None = None, stock_override: dict | None = None) -> Snapshot:
    """Build an in-memory Snapshot (no database). Used by unit tests and the seed generator."""
    ds = ds or build_dataset()
    W = ds["weather"]
    sup = supplies()
    positions = []
    for (b, t), x in ds["history"].items():
        s = next(q for q in sup if q.id == t)
        _, fut = F.fit_and_forecast(x, s.sensitivity, W)
        stock, safety = ds["stocks"][(b, t)]
        if stock_override and (b, t) in stock_override:
            stock = stock_override[(b, t)]
        positions.append(Position(b, t, stock, safety, F.mean_first(fut), tuple(fut), sum(x[-7:]) / 7))
    return Snapshot(locations(), sup, routes(), vehicles(), positions, dict(ds["depot_stock"]), W)

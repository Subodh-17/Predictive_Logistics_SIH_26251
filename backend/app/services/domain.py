"""Plain data structures shared by the pure calculation engines.

All engines in app/services are pure functions over these dataclasses so they can be
unit-tested without a database. app/repository.py builds a Snapshot from PostgreSQL.
All scenario data is fictional and simulated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

ND = 110          # days of history
NF = 30           # days of forecast outlook
# Simulation clock origin (history day index ND == this instant). Same value as the v3 version.
T0 = datetime(2026, 6, 19, 6, 0, tzinfo=timezone.utc)


def js_round(x: float) -> int:
    """JavaScript Math.round semantics (half rounds up) so v3 numbers are reproduced."""
    return int(math.floor(x + 0.5))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def day_date(day_index: float) -> datetime:
    return T0 + timedelta(days=day_index - ND)


@dataclass(frozen=True)
class Supply:
    id: str
    base_demand: float
    sensitivity: float      # weather sensitivity 0..1
    criticality: float      # criticality weight 0..1


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    kind: str               # DEPOT | FORWARD
    lat: float
    lon: float
    demand_factor: float = 1.0


@dataclass(frozen=True)
class Route:
    id: str
    depot_id: str
    dest_id: str
    distance_km: float
    road_condition: float   # 0 good .. 1 poor
    nominal_speed: float    # km/h
    terrain_type: str
    terrain_difficulty: float   # 0..1
    elevation_band: int         # 0..3
    elevation_label: str
    coords: tuple = ()          # ((lat, lon), ...) fictional polyline


@dataclass(frozen=True)
class Vehicle:
    id: str
    depot_id: str
    capacity: int
    available: bool
    vehicle_type: str = ""


@dataclass(frozen=True)
class Position:
    """Inventory position of one supply type at one forward location."""
    location_id: str
    supply_id: str
    stock: float
    safety_stock: float
    f7: float                    # mean of first 7 days of the baseline forecast (units/day)
    fut: tuple                   # 30-day baseline forecast
    hist7: float                 # mean actual consumption over the last 7 history days


@dataclass
class Snapshot:
    locations: list
    supplies: list
    routes: list
    vehicles: list
    positions: list
    depot_stock: dict            # {(depot_id, supply_id): units}
    weather: list                # severity index per day, length ND + NF
    nd: int = ND
    nf: int = NF

    def supply(self, sid: str) -> Supply:
        return next(s for s in self.supplies if s.id == sid)

    @property
    def forward(self):
        return [l for l in self.locations if l.kind == "FORWARD"]

    @property
    def depots(self):
        return [l for l in self.locations if l.kind == "DEPOT"]


@dataclass(frozen=True)
class Params:
    """What-if scenario. demand: +0..0.5, weather: 0..1, road: 0..1, vehicles: availability 0.5..1."""
    demand: float = 0.0
    weather: float = 0.0
    road: float = 0.0
    vehicles: float = 1.0

    @property
    def is_baseline(self) -> bool:
        return self.demand == 0 and self.weather == 0 and self.road == 0 and self.vehicles == 1

    def as_dict(self) -> dict:
        return {"demand": self.demand, "weather": self.weather, "road": self.road, "vehicles": self.vehicles}


# status codes
OK, WARNING, CRITICAL = "NORMAL", "WARNING", "CRITICAL"

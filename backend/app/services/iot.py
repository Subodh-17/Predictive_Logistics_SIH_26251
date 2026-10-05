"""Simulated ESP32 / RFID inventory events. All telemetry is simulated; no hardware is connected."""
from __future__ import annotations

from dataclasses import dataclass

EVENT_TYPES = ("RECEIVE", "ISSUE", "COUNT")


class IotError(ValueError):
    pass


@dataclass
class Applied:
    before: float
    after: float
    delta: float
    clipped: bool


def apply_event(stock: float, event_type: str, quantity: float) -> Applied:
    """RECEIVE adds, ISSUE subtracts (never below zero), COUNT sets stock to the scanned count."""
    if event_type not in EVENT_TYPES:
        raise IotError(f"unknown event_type {event_type!r}; expected one of {EVENT_TYPES}")
    if quantity < 0 or (event_type != "COUNT" and quantity == 0):
        raise IotError("quantity must be positive (COUNT may be zero)")
    clipped = False
    if event_type == "RECEIVE":
        after = stock + quantity
    elif event_type == "ISSUE":
        after = stock - quantity
        if after < 0:
            after, clipped = 0.0, True
    else:
        after = float(quantity)
    return Applied(stock, after, after - stock, clipped)


def feed_from_allocation(alloc, t0_epoch_minutes: int = 0) -> list:
    """Simulated in-transit container feed derived from the allocation plan (same rule as the v3 prototype)."""
    states = ["IN TRANSIT", "LOADING", "STAGED"]
    legs = [(r.prio.item, g) for r in alloc.rows for g in r.legs]
    out = []
    for k, (item, g) in enumerate(legs[:8]):
        out.append({"container_id": f"CTN-{4000 + k * 37 + int(item.location_id[-1]) * 11}", "source": g.depot,
                    "destination": item.location_id, "supply": item.supply_id, "quantity": g.quantity,
                    "status": states[k % 3], "minutes_before_sim_clock": k * 7 + 3, "route": g.route, "vehicle": g.vehicle,
                    "simulated": True})
    return out


def generate_events(result, alloc, n: int, seed: int) -> list:
    """Deterministic simulated ESP32/RFID scans: container arrivals (RECEIVE) for planned dispatches and consumption scans (ISSUE)."""
    from .domain import js_round
    import random
    rng = random.Random(seed)
    legs = [(r.prio.item, g) for r in alloc.rows for g in r.legs]
    fwd = [i for i in result.items]
    out = []
    for k in range(n):
        dev = f"ESP32-SIM-{rng.randint(1, 3):02d}"
        tag = f"RFID-SIM-{rng.randint(1000, 9999)}"
        if legs and rng.random() < 0.45:
            item, g = rng.choice(legs)
            out.append({"device_id": dev, "tag_id": tag, "event_type": "RECEIVE", "location_id": item.location_id,
                        "supply_id": item.supply_id, "quantity": max(50, js_round(g.quantity * rng.uniform(0.2, 0.5) / 10) * 10),
                        "note": f"simulated container arrival via {g.route}/{g.vehicle}"})
        else:
            item = rng.choice(fwd)
            out.append({"device_id": dev, "tag_id": tag, "event_type": "ISSUE", "location_id": item.location_id,
                        "supply_id": item.supply_id, "quantity": max(10, js_round(item.dem * rng.uniform(0.3, 1.0) / 10) * 10),
                        "note": "simulated issue scan"})
    return out

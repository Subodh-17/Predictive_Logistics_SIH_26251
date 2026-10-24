"""Convert engine results to JSON-ready dicts."""
from __future__ import annotations

from .services import routing as rt, terrain as T
from .services.domain import T0
from .services.explain import best_route
from .services.recommendation import recommend


def iso_date(dt) -> str:
    return dt.date().isoformat()


def item_dict(i) -> dict:
    return {"location": i.location_id, "supply": i.supply_id, "stock": round(i.stock, 1), "safety_stock": round(i.safety, 1),
            "daily_use": round(i.dem, 2), "days_left": round(i.days, 2), "shortage_14d": i.short, "status": i.status,
            "lead_days": round(i.lead, 2), "stockout_date": iso_date(i.stockout_date), "replenish_qty": i.qty,
            "below_safety": i.stock < i.safety}


def alert_dict(i) -> dict:
    return {"location": i.location_id, "supply": i.supply_id, "severity": i.status, "days_cover": round(i.days, 1),
            "stockout_date": iso_date(i.stockout_date), "lead_days": round(i.lead, 1),
            "message": f"{i.location_id} \u00b7 {i.supply_id}: {i.days:.1f} d cover \u00b7 stock-out {i.stockout_date:%d %b} \u00b7 lead {i.lead:.1f} d"}


def route_dict(ev, res, geo_len=None) -> dict:
    cap = sum(c for d, c in res.vehicles_eff.values() if d == ev.depot_id)
    r = ev.route
    return {"id": r.id, "depot": r.depot_id, "destination": r.dest_id, "distance_km": r.distance_km, "geo_length_km": geo_len,
            "road_condition": round(ev.road, 3), "road_label": T.road_label(ev.road),
            "terrain": {"type": r.terrain_type, "difficulty": r.terrain_difficulty, "elevation_band": r.elevation_band,
                        "elevation_label": r.elevation_label, "risk": round(ev.terrain_risk, 4)},
            "nominal_speed_kmh": r.nominal_speed, "effective_speed_kmh": round(ev.speed, 2), "eta_h": round(ev.eta, 2),
            "delay_h": round(ev.delay, 2), "weather_risk": round(ev.weather_risk, 3), "weather_level": T.risk_level(ev.weather_risk),
            "risk": round(ev.risk, 4), "risk_level": T.risk_level(ev.risk), "vehicle_capacity": cap, "feasible": cap > 0 and ev.weather_risk < rt.CLOSURE_WEATHER_RISK,
            "blocked_reason": "ROUTE CLOSED" if ev.weather_risk >= rt.CLOSURE_WEATHER_RISK else "NO AVAILABLE VEHICLE" if cap <= 0 else "",
            "coordinates": [[a, b] for a, b in r.coords]}


def insight_dict(i, res) -> dict:
    rec = recommend(res, i)
    return {"location": i.location_id, "supply": i.supply_id, "days_cover": round(i.days, 1), "status": i.status,
            "headline": f"{i.location_id} is projected to run out of {i.supply_id} in {i.days:.1f} days.",
            "predicted_demand_14d": round(i.dem * 14), "stock": round(i.stock), "safety_stock": round(i.safety),
            "stockout_date": iso_date(i.stockout_date), "lead_days": round(i.lead, 1), "replenish_qty": i.qty,
            "source": rec["source"], "vehicle": rec["vehicle"], "route": rec["route"], "reason": rec["reason"]}


def location_dict(loc, res, snap) -> dict:
    base = {"id": loc.id, "name": loc.name, "kind": loc.kind, "lat": loc.lat, "lon": loc.lon, "status": None}
    if loc.kind == "DEPOT":
        base["available_capacity"] = sum(c for d, c in res.vehicles_eff.values() if d == loc.id)
        return base
    ls = next(l for l in res.locs if l.id == loc.id)
    br = best_route(res, loc.id)
    base.update({"status": ls.status, "n_critical": ls.n_critical, "n_warning": ls.n_warning, "n_normal": ls.n_normal,
                 "min_days": round(ls.min_days, 2), "min_supply": ls.min_supply, "short_units": ls.short,
                 "demand_per_day": round(ls.dem, 1), "best_route": br.id if br else None,
                 "best_route_risk": round(br.risk, 3) if br else None})
    return base


def sim_iso(minutes_before: int) -> str:
    from datetime import timedelta
    return (T0 - timedelta(minutes=minutes_before)).isoformat()

"""What-If simulation: baseline vs scenario with before/after metrics and explanations."""
from __future__ import annotations

from . import engine
from .allocation import allocate
from .domain import Params
from .explain import road_scenario_label, weather_label
from .recommendation import fx
from . import terrain as T


def metrics(res, alloc) -> dict:
    return {
        "critical_items": res.n_critical, "warning_items": res.n_warning, "shortage_locations": res.shortage_locations,
        "expected_shortage_units": res.short_total, "transport_capacity": res.capacity, "capacity_deficit": res.deficit,
        "transport_need": res.need, "mean_route_risk": round(res.avg_route_risk * 100, 2),
        "mean_eta_delay_h": round(res.mean_delay, 3), "overall_risk_index": res.risk_index,
        "unmet_after_allocation": alloc.unmet, "allocated_units": alloc.used, "mean_days_cover": round(res.avg_days, 2),
        "weather_index": round(res.weather, 3),
    }


def run(snap, p: Params, base_params: Params = Params()) -> dict:
    B = engine.compute(snap, base_params)
    A = engine.compute(snap, p)
    ab, aa = allocate(B, snap), allocate(A, snap)
    why = []
    if p.demand:
        why.append(f"Demand +{round(p.demand * 100)}% scales every item's burn rate, cutting mean cover from {B.avg_days:.1f} d to {A.avg_days:.1f} d.")
    if p.weather:
        why.append(f"{weather_label(p.weather)} weather lifts consumption of weather-sensitive supplies (Water, Fuel, Shelter) and slows convoys; "
                   f"mean route risk {B.avg_route_risk * 100:.0f} \u2192 {A.avg_route_risk * 100:.0f}.")
    if p.road:
        why.append(f"{road_scenario_label(p.road)} road condition cuts convoy speed, adding {A.mean_delay - B.mean_delay:.1f} h mean ETA and lengthening replenishment lead time.")
    if p.vehicles < 1:
        why.append(f"Fleet availability {round(p.vehicles * 100)}% reduces capacity to {fx(A.capacity)} units against a need of {fx(A.need)}, leaving a {fx(A.deficit)} unit deficit.")
    if p.weather or p.road:
        k = max(((a, a.eta - b.eta) for a, b in zip(A.routes, B.routes)), key=lambda x: x[1])
        why.append(f"Terrain amplifies these effects: {k[0].id} ({k[0].route.terrain_type}, terrain risk {round(k[0].terrain_risk * 100)}/100) slows most, +{k[1]:.1f} h ETA.")
    if aa.unmet > ab.unmet:
        reasons = sorted({r.unmet_reason for r in aa.rows if r.unmet})
        why.append(f"Unmet quantity after allocation rises from {fx(ab.unmet)} to {fx(aa.unmet)} units (binding constraint: {', '.join(reasons).lower() or 'n/a'}).")
    changed = [l.id for l, b in zip(A.locs, B.locs) if l.status != b.status]
    why.append(f"Status escalated at: {', '.join(changed)}." if changed else "No location changed status; margins narrowed only.")
    return {
        "params": p.as_dict(), "before": metrics(B, ab), "after": metrics(A, aa),
        "locations": [{"id": b.id, "before": b.status, "after": a.status, "days_before": round(b.min_days, 2), "days_after": round(a.min_days, 2)} for b, a in zip(B.locs, A.locs)],
        "routes": [{"id": b.id, "eta_before": round(b.eta, 2), "eta_after": round(a.eta, 2), "risk_before": round(b.risk * 100), "risk_after": round(a.risk * 100)} for b, a in zip(B.routes, A.routes)],
        "explanation": why,
    }

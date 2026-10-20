from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repository as repo
from ..schemas import LocationOut, VehicleOut
from ..serializers import insight_dict, item_dict, location_dict, route_dict
from ..services import routing as rt
from ..services.explain import why_at_risk
from .common import Ctx, IdPath, IdQuery

router = APIRouter(prefix="/api", tags=["gis"])


@router.get("/locations", response_model=list[LocationOut])
def locations(c: Ctx = Depends()):
    """Depots and forward locations (fictional), with PostGIS-derived coordinates and scenario-aware risk status."""
    return [location_dict(l, c.res, c.snap) for l in c.snap.locations]


@router.get("/locations/{location_id}")
def location_detail(location_id: IdPath, c: Ctx = Depends()):
    loc = next((l for l in c.snap.locations if l.id == location_id), None)
    if loc is None:
        raise HTTPException(404, f"unknown location {location_id}")
    out = {"location": location_dict(loc, c.res, c.snap)}
    if loc.kind == "FORWARD":
        items = sorted([i for i in c.res.items if i.location_id == location_id], key=lambda i: i.days)
        out["items"] = [item_dict(i) for i in items]
        out["why_at_risk"] = why_at_risk(c.res, location_id)
        out["insight"] = insight_dict(items[0], c.res) if items[0].status != "NORMAL" else None
        out["routes_to"] = [route_dict(e, c.res) for e in c.res.routes_to(location_id)]
    return out


@router.get("/routes")
def routes(c: Ctx = Depends()):
    """Routes with terrain-, road- and weather-adjusted speed, ETA and risk; geometry comes from PostGIS."""
    lens = repo.route_geo_lengths(c.db)
    return [route_dict(e, c.res, lens.get(e.id)) for e in c.res.routes]


@router.get("/routes/compare")
def compare(destination: IdQuery, c: Ctx = Depends()):
    """Feasible routes to a destination ranked by combined score, with the reason the best one was selected."""
    if destination not in {l.id for l in c.snap.forward}:
        raise HTTPException(404, f"unknown forward location {destination}")
    required = sum(i.qty for i in c.res.items if i.location_id == destination)
    rows = rt.rank_routes(c.res.routes, c.res.vehicles_eff, destination, required)
    lens = repo.route_geo_lengths(c.db)
    selected = next((r["ev"].id for r in rows if r["feasible"]), None)
    out = []
    for r in rows:
        d = route_dict(r["ev"], c.res, lens.get(r["ev"].id))
        d.update({"combined_score": round(r["score"], 3), "decision": r["blocked_reason"].replace("NO AVAILABLE VEHICLE", "NO VEHICLE") if not r["feasible"] else "SELECTED" if r["ev"].id == selected else "ALTERNATIVE"})
        out.append(d)
    return {"destination": destination, "required_units": required, "routes": out, "selected": selected,
            "reason": rt.explain_selection(rows, destination),
            "formula": "route risk = 0.25 road + 0.25 weather + 0.30 terrain + 0.20 distance; combined score = route risk + ETA/24 h + capacity penalty (<=0.2)"}


@router.get("/vehicles", response_model=list[VehicleOut])
def vehicles(c: Ctx = Depends()):
    return [{"id": v.id, "depot_id": v.depot_id, "vehicle_type": v.vehicle_type, "capacity": v.capacity,
             "effective_capacity": c.res.vehicles_eff[v.id][1], "available": v.available} for v in c.snap.vehicles]

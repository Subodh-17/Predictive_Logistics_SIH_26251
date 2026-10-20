"""Database access: loads a Snapshot for the pure engines from PostgreSQL/PostGIS and persists derived data."""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.orm import Session

from . import config, models as m
from .ml.features import eligibility
from .services import allocation as alloc_svc
from .services import engine, forecasting as F, iot as iot_svc, model_service as ms
from .services.domain import (ND, NF, Location, Params, Position, Route, Snapshot, Supply, Vehicle, day_date)


log = logging.getLogger("logistics.repository")


class NotFound(LookupError):
    pass


class MLTimeout(RuntimeError):
    pass


# ---------------------------------------------------------------- snapshot
def load_snapshot(db: Session) -> Snapshot:
    locs = [Location(i, n, k, float(lat), float(lon), float(f)) for i, n, k, lat, lon, f in db.execute(
        select(m.LocationRow.id, m.LocationRow.name, m.LocationRow.kind, func.ST_Y(m.LocationRow.geom), func.ST_X(m.LocationRow.geom),
               m.LocationRow.demand_factor).order_by(m.LocationRow.kind.desc(), m.LocationRow.sort_order))]
    sups = [Supply(i, float(b), float(s), float(c)) for i, b, s, c in db.execute(
        select(m.SupplyRow.id, m.SupplyRow.base_daily_demand, m.SupplyRow.weather_sensitivity, m.SupplyRow.criticality_weight)
        .order_by(m.SupplyRow.sort_order))]
    routes = []
    for r in db.execute(select(m.RouteRow, m.TerrainRow, func.ST_AsGeoJSON(m.RouteRow.geom)).join(m.TerrainRow, m.TerrainRow.route_id == m.RouteRow.id)
                        .order_by(m.RouteRow.id)):
        row, ter, gj = r
        coords = tuple((lat, lon) for lon, lat in json.loads(gj)["coordinates"])
        routes.append(Route(row.id, row.depot_id, row.destination_id, float(row.distance_km), float(row.road_condition),
                            float(row.nominal_speed_kmh), ter.terrain_type, float(ter.difficulty), int(ter.elevation_band),
                            ter.elevation_label, coords))
    vehicles = [Vehicle(v.id, v.depot_id, v.capacity_units, v.available, v.vehicle_type) for v in
                db.scalars(select(m.VehicleRow).order_by(m.VehicleRow.id))]
    weather = list(db.scalars(select(m.WeatherRow.severity_index).order_by(m.WeatherRow.day_index)))

    fut = defaultdict(list)
    for loc, sup, val in db.execute(select(m.ForecastRow.location_id, m.ForecastRow.supply_id, m.ForecastRow.value)
                                    .where(m.ForecastRow.kind == "FORECAST").order_by(m.ForecastRow.location_id, m.ForecastRow.supply_id, m.ForecastRow.day_index)):
        fut[(loc, sup)].append(val)
    hist7 = {(l, s): float(a) for l, s, a in db.execute(
        select(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, func.avg(m.ConsumptionRow.quantity))
        .where(m.ConsumptionRow.day_index >= ND - 7).group_by(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id))}
    kinds = {l.id: l.kind for l in locs}
    inv = {(r.location_id, r.supply_id): r for r in db.scalars(select(m.InventoryRow))}
    positions, depot_stock = [], {}
    for l in locs:
        for s in sups:
            row = inv.get((l.id, s.id))
            if row is None:
                continue
            if l.kind == "DEPOT":
                depot_stock[(l.id, s.id)] = float(row.stock)
            else:
                f = fut.get((l.id, s.id))
                if not f or len(f) < NF:
                    raise RuntimeError("forecasts missing - call ensure_forecasts() first")
                positions.append(Position(l.id, s.id, float(row.stock), float(row.safety_stock), F.mean_first(f), tuple(f), hist7.get((l.id, s.id), 0.0)))
    if not positions or len(weather) < ND + NF:
        raise RuntimeError("database is not seeded")
    return Snapshot(locs, sups, routes, vehicles, positions, depot_stock, weather)


# ---------------------------------------------------------------- forecasts
def _statistical_rows(loc, sup, hist, sens, weather, now):
    fit, fut = F.fit_and_forecast(hist, sens, weather)
    rows = [{"location_id": loc, "supply_id": sup, "day_index": d, "forecast_date": day_date(d).date(), "kind": "FIT", "value": v,
             "model": ms.STATISTICAL_ID, "generated_at": now} for d, v in enumerate(fit) if v is not None]
    rows += [{"location_id": loc, "supply_id": sup, "day_index": len(hist) + k, "forecast_date": day_date(len(hist) + k).date(), "kind": "FORECAST",
              "value": v, "model": ms.STATISTICAL_ID, "generated_at": now} for k, v in enumerate(fut)]
    return rows


def _ml_rows(res, loc, sup, hist, sens, weather, now):
    """Trained-model rows for one series (FIT = out-of-sample one-step forecasts; FORECAST = direct multi-horizon with 80% interval)."""
    n = len(hist)
    use_w = res.adapter == "weather"
    pf = [F.weather_adj(sens, weather[d]) for d in range(n)] if use_w else None
    ff = [F.weather_adj(sens, weather[n + k]) for k in range(NF)] if use_w else None
    fits = res.forecaster.one_step_fits(hist, past_factors=pf)
    out = res.forecaster.predict(hist, NF, past_factors=pf, future_factors=ff)
    rows = [{"location_id": loc, "supply_id": sup, "day_index": d, "forecast_date": day_date(d).date(), "kind": "FIT", "value": float(v),
             "model": res.model_id, "generated_at": now} for d, v in enumerate(fits) if v == v]
    rows += [{"location_id": loc, "supply_id": sup, "day_index": n + k, "forecast_date": day_date(n + k).date(), "kind": "FORECAST", "value": float(out.values[k]),
              "lo": float(out.lo[k]), "hi": float(out.hi[k]), "model": res.model_id, "generated_at": now} for k in range(NF)]
    return rows


def ensure_forecasts(db: Session, force: bool = False) -> int:
    """Compute forecasts from consumption history + weather and store them in `forecasts`.

    The producing model is stored per row. Rows are regenerated when forced, or when the model that should be active (see
    services.model_service) differs from the one that produced the stored rows. If the trained model fails at run time
    (exception or time budget) every series is recomputed with the statistical model and the fallback reason is exposed.
    """
    from datetime import datetime, timezone
    res = ms.resolve_forecast()
    if not force:
        have = set(db.scalars(select(m.ForecastRow.model).distinct()))
        if have and ((res.family == "statistical" and have == {res.model_id})
                     or (res.family == "machine_learning" and res.model_id in have and have <= {res.model_id, ms.STATISTICAL_ID})):
            return 0
    weather = list(db.scalars(select(m.WeatherRow.severity_index).order_by(m.WeatherRow.day_index)))
    sens = {s.id: float(s.weather_sensitivity) for s in db.scalars(select(m.SupplyRow))}
    series = defaultdict(list)
    for loc, sup, q in db.execute(select(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, m.ConsumptionRow.quantity)
                                  .order_by(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, m.ConsumptionRow.day_index)):
        series[(loc, sup)].append(q)
    now = datetime.now(timezone.utc)

    def build(res):
        rows, t0 = [], time.monotonic()
        for (loc, sup), hist in series.items():
            if res.forecaster is not None:
                ok, why = eligibility(hist)
                if ok:
                    rows += _ml_rows(res, loc, sup, hist, sens[sup], weather, now)
                else:
                    log.warning("series %s/%s not eligible for the trained model (%s); statistical model used for it", loc, sup, why)
                    rows += _statistical_rows(loc, sup, hist, sens[sup], weather, now)
                if time.monotonic() - t0 > config.ML_RECOMPUTE_TIMEOUT_S:
                    raise MLTimeout(f"trained-model inference exceeded {config.ML_RECOMPUTE_TIMEOUT_S:.0f}s")
            else:
                rows += _statistical_rows(loc, sup, hist, sens[sup], weather, now)
        return rows

    try:
        rows = build(res)
    except Exception as e:  # noqa: BLE001 - any inference failure must degrade visibly, never silently
        if res.forecaster is None:
            raise
        ms.force_statistical(f"{type(e).__name__}: {e}")
        res = ms.resolve_forecast()
        rows = build(res)
    db.execute(delete(m.ForecastRow))
    for i in range(0, len(rows), 2000):
        db.execute(insert(m.ForecastRow), rows[i:i + 2000])
    db.commit()
    log.info("forecasts regenerated with %s: %d rows, %d series", res.model_id, len(rows), len(series))
    return len(rows)


def forecast_series(db: Session, location: str | None, supply: str | None) -> dict:
    """Aggregate actual, model fit and forecast (+ interval when the trained model produced it) for the selection (all when None)."""
    def agg(table_col, kind=None):
        cols = (table_col.day_index, func.sum(table_col.quantity if table_col is m.ConsumptionRow else table_col.value))
        q = select(*cols).group_by(table_col.day_index).order_by(table_col.day_index)
        if location:
            q = q.where(table_col.location_id == location)
        if supply:
            q = q.where(table_col.supply_id == supply)
        if kind:
            q = q.where(table_col.kind == kind)
        return {d: float(v) for d, v in db.execute(q)}
    actual, fit, fut = agg(m.ConsumptionRow), agg(m.ForecastRow, "FIT"), agg(m.ForecastRow, "FORECAST")
    out = {"actual": [actual.get(d, 0.0) for d in range(ND)], "fit": [fit.get(d, 0.0) for d in range(ND)],
           "fut": [fut.get(ND + k, 0.0) for k in range(NF)], "fut_lo": None, "fut_hi": None}
    # interval of a sum of series: sum of values -/+ root-sum-of-squares of the per-series half-widths (independent errors assumed)
    q = (select(m.ForecastRow.day_index, func.count(), func.count(m.ForecastRow.lo), func.sqrt(func.sum(func.power(m.ForecastRow.value - m.ForecastRow.lo, 2))),
                func.sqrt(func.sum(func.power(m.ForecastRow.hi - m.ForecastRow.value, 2))))
         .where(m.ForecastRow.kind == "FORECAST").group_by(m.ForecastRow.day_index).order_by(m.ForecastRow.day_index))
    if location:
        q = q.where(m.ForecastRow.location_id == location)
    if supply:
        q = q.where(m.ForecastRow.supply_id == supply)
    rows = {d: (n, nl, a, b) for d, n, nl, a, b in db.execute(q)}
    if rows and all(rows.get(ND + k, (0, 1, 0, 0))[0] == rows.get(ND + k, (0, 1, 0, 0))[1] and rows.get(ND + k, (0, 0, 0, 0))[0] > 0 for k in range(NF)):
        out["fut_lo"] = [max(0.0, out["fut"][k] - float(rows[ND + k][2])) for k in range(NF)]
        out["fut_hi"] = [out["fut"][k] + float(rows[ND + k][3]) for k in range(NF)]
    return out


def ml_preview(db: Session, location: str | None, supply: str | None, horizon: int) -> dict | None:
    try:
        return _ml_preview(db, location, supply, horizon)
    except Exception as e:  # noqa: BLE001 - the preview is optional and must never break the main forecast response
        log.warning("trained-model preview unavailable: %s", e)
        return None


def _ml_preview(db: Session, location: str | None, supply: str | None, horizon: int) -> dict | None:
    """On-the-fly forecast of the trained model for the selection, for side-by-side comparison when it is NOT the active model.
    Inference only (no training, nothing stored). Returns None when the model is unavailable."""
    f, _ = ms.forecaster()
    if f is None:
        return None
    res = ms.resolve_forecast()
    adapter = (f.meta.get("promotion") or {}).get("adapter", "plain")
    weather = list(db.scalars(select(m.WeatherRow.severity_index).order_by(m.WeatherRow.day_index)))
    sens = {x.id: float(x.weather_sensitivity) for x in db.scalars(select(m.SupplyRow))}
    q = select(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, m.ConsumptionRow.quantity).order_by(
        m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, m.ConsumptionRow.day_index)
    if location:
        q = q.where(m.ConsumptionRow.location_id == location)
    if supply:
        q = q.where(m.ConsumptionRow.supply_id == supply)
    series = defaultdict(list)
    for l, sp, v in db.execute(q):
        series[(l, sp)].append(v)
    tot = [0.0] * horizon
    for (l, sp), h in series.items():
        ok, _ = eligibility(h)
        if not ok:
            return None
        n = len(h)
        pf = [F.weather_adj(sens[sp], weather[d]) for d in range(n)] if adapter == "weather" else None
        ff = [F.weather_adj(sens[sp], weather[n + k]) for k in range(horizon)] if adapter == "weather" else None
        out = f.predict(h, horizon, past_factors=pf, future_factors=ff)
        tot = [a + float(b) for a, b in zip(tot, out.values)]
    return {"model_id": f.model_id, "values": tot, "active": res.model_id == f.model_id}


def forecast_meta(db: Session, location: str | None = None, supply: str | None = None) -> dict:
    """Which model(s) produced the stored forecasts for the selection, and when."""
    q = select(m.ForecastRow.model, func.count(func.distinct(m.ForecastRow.location_id + "|" + m.ForecastRow.supply_id)), func.max(m.ForecastRow.generated_at))
    if location:
        q = q.where(m.ForecastRow.location_id == location)
    if supply:
        q = q.where(m.ForecastRow.supply_id == supply)
    rows = db.execute(q.group_by(m.ForecastRow.model)).all()
    return {"models": {r[0]: int(r[1]) for r in rows}, "generated_at": max((r[2] for r in rows), default=None)}


# ---------------------------------------------------------------- derived tables
def scenario_key(p: Params) -> str:
    return "baseline" if p.is_baseline else f"d{p.demand}-w{p.weather}-r{p.road}-v{p.vehicles}"


def persist_baseline(db: Session, snap: Snapshot | None = None, commit: bool = True) -> None:
    """Refresh the baseline snapshot rows in alerts, priority_scores and allocations from the current inventory."""
    from .services.priority import prioritise
    snap = snap or load_snapshot(db)
    res = engine.compute(snap, Params())
    for t in (m.AlertRow, m.PriorityScoreRow, m.AllocationRow):
        db.execute(delete(t).where(t.scenario_key == "baseline"))
    for i in sorted((i for i in res.items if i.status != "NORMAL"), key=lambda i: i.days):
        db.add(m.AlertRow(location_id=i.location_id, supply_id=i.supply_id, severity=i.status, days_cover=i.days,
                          stockout_date=i.stockout_date.date(), lead_days=i.lead,
                          message=f"{i.location_id} \u00b7 {i.supply_id}: {i.days:.1f} d cover \u00b7 stock-out {i.stockout_date:%d %b} \u00b7 lead {i.lead:.1f} d"))
    for k, p in enumerate(prioritise(res), 1):
        db.add(m.PriorityScoreRow(rank=k, location_id=p.item.location_id, supply_id=p.item.supply_id, score=p.score, components=p.components))
    for r in alloc_svc.allocate(res, snap).rows:
        legs = r.legs or [None]
        for g in legs:
            db.add(m.AllocationRow(location_id=r.prio.item.location_id, supply_id=r.prio.item.supply_id, route_id=g.route if g else None,
                                   vehicle_id=g.vehicle if g else None, need=r.need, quantity=g.quantity if g else 0, unmet=r.unmet,
                                   status=r.status, unmet_reason=r.unmet_reason or None))
    if commit:
        db.commit()
    else:
        db.flush()


def stored_alerts(db: Session) -> list:
    return [{"location": a.location_id, "supply": a.supply_id, "severity": a.severity, "days_cover": round(a.days_cover, 1),
             "stockout_date": a.stockout_date.isoformat() if a.stockout_date else None, "lead_days": round(a.lead_days, 1),
             "message": a.message, "created_at": a.created_at.isoformat()}
            for a in db.scalars(select(m.AlertRow).where(m.AlertRow.scenario_key == "baseline").order_by(m.AlertRow.days_cover))]


# ---------------------------------------------------------------- IoT
class Duplicate(Exception):
    """An event with the same idempotency key was already applied."""


def apply_iot_event(db: Session, ev: dict, commit: bool = True) -> dict:
    row = db.execute(select(m.InventoryRow).where(m.InventoryRow.location_id == ev["location_id"], m.InventoryRow.supply_id == ev["supply_id"])
                     .with_for_update()).scalar_one_or_none()
    if row is None:
        raise NotFound(f"no inventory record for {ev['location_id']} / {ev['supply_id']}")
    key = ev.get("event_id")
    if key:                                   # checked while holding the inventory row lock, so concurrent duplicates are serialised
        if db.scalar(select(func.count()).select_from(m.IotEventRow).where(m.IotEventRow.event_id == key)):
            raise Duplicate(key)
    applied = iot_svc.apply_event(float(row.stock), ev["event_type"], float(ev["quantity"]))
    row.stock = applied.after
    row.updated_at = datetime.now(timezone.utc)
    rec = m.IotEventRow(device_id=ev["device_id"], tag_id=ev["tag_id"], event_type=ev["event_type"], location_id=ev["location_id"],
                        supply_id=ev["supply_id"], quantity=ev["quantity"], stock_before=applied.before, stock_after=applied.after,
                        simulated=True, event_id=key or None, payload={"clipped_at_zero": applied.clipped, "note": ev.get("note")})
    db.add(rec)
    if commit:
        db.commit()
        db.refresh(rec)
    else:
        db.flush()
    return {"id": rec.id, "applied": applied, "event_time": rec.event_time.isoformat()}


def list_iot_events(db: Session, limit: int = 50) -> list:
    return [{"id": e.id, "event_time": e.event_time.isoformat(), "device_id": e.device_id, "tag_id": e.tag_id, "event_type": e.event_type,
             "location_id": e.location_id, "supply_id": e.supply_id, "quantity": float(e.quantity), "stock_before": float(e.stock_before),
             "stock_after": float(e.stock_after), "simulated": e.simulated, "clipped_at_zero": bool((e.payload or {}).get("clipped_at_zero"))}
            for e in db.scalars(select(m.IotEventRow).order_by(m.IotEventRow.id.desc()).limit(limit))]


def reset_inventory(db: Session, commit: bool = True) -> int:
    n = db.execute(update(m.InventoryRow).values(stock=m.InventoryRow.initial_stock, updated_at=func.now())).rowcount
    db.execute(delete(m.IotEventRow))
    if commit:
        db.commit()
    return n


# ---------------------------------------------------------------- simulation history
def save_simulation(db: Session, result: dict) -> int:
    row = m.SimulationRunRow(params=result["params"], before=result["before"], after=result["after"], explanation=result["explanation"])
    db.add(row)
    db.commit()
    return row.id


def list_simulations(db: Session, limit: int = 20) -> list:
    return [{"id": r.id, "created_at": r.created_at.isoformat(), "params": r.params, "before": r.before, "after": r.after, "explanation": r.explanation}
            for r in db.scalars(select(m.SimulationRunRow).order_by(m.SimulationRunRow.id.desc()).limit(limit))]


# ---------------------------------------------------------------- health / coverage
def location_exists(db: Session, location_id: str) -> bool:
    return db.scalar(select(func.count()).select_from(m.LocationRow).where(m.LocationRow.id == location_id)) > 0


def supply_exists(db: Session, supply_id: str) -> bool:
    return db.scalar(select(func.count()).select_from(m.SupplyRow).where(m.SupplyRow.id == supply_id)) > 0


def data_freshness(db: Session) -> dict:
    """What the stored data actually covers (the scenario is a fixed history, so this is 'coverage', not 'age')."""
    last_hist = db.scalar(select(func.max(m.ConsumptionRow.consumption_date)))
    last_iot = db.scalar(select(func.max(m.IotEventRow.event_time)))
    gen = db.scalar(select(func.max(m.ForecastRow.generated_at)))
    return {"history_through": last_hist.isoformat() if last_hist else None, "last_inventory_event_at": last_iot.isoformat() if last_iot else None,
            "forecasts_generated_at": gen.isoformat() if gen else None}


def health(db: Session) -> dict:
    ver = db.execute(text("select postgis_version()")).scalar()
    cnt = lambda t: db.scalar(select(func.count()).select_from(t))
    return {"postgis": ver, "counts": {"locations": cnt(m.LocationRow), "depots": cnt(m.DepotRow), "supplies": cnt(m.SupplyRow),
            "routes": cnt(m.RouteRow), "vehicles": cnt(m.VehicleRow), "consumption": cnt(m.ConsumptionRow), "inventory": cnt(m.InventoryRow),
            "forecasts": cnt(m.ForecastRow), "weather": cnt(m.WeatherRow), "iot_events": cnt(m.IotEventRow), "simulation_runs": cnt(m.SimulationRunRow)}}


def route_geo_lengths(db: Session) -> dict:
    """Straight-line length of each fictional route polyline, measured by PostGIS on the WGS84 spheroid (km)."""
    return {rid: round(float(v) / 1000, 1) for rid, v in db.execute(select(m.RouteRow.id, func.ST_Length(func.Geography(m.RouteRow.geom))))}

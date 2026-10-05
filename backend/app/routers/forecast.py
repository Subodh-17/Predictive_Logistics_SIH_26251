from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import repository as repo
from ..database import get_db
from ..services import challenger as ch
from ..services import forecasting as F
from ..services.domain import ND, NF, day_date

router = APIRouter(prefix="/api/forecast", tags=["forecast"])
_challenger_cache: dict = {}


@router.get("")
def forecast(location: str | None = None, supply: str | None = None, horizon: int = Query(14, description="7, 14 or 30"),
             db: Session = Depends(get_db)):
    """Actual vs predicted consumption with an 80% interval band, backtest MAPE and forecast confidence."""
    if horizon not in (7, 14, 30):
        horizon = 14
    s = repo.forecast_series(db, location, supply)
    a, f, u = s["actual"], s["fit"], s["fut"]
    bt = F.backtest(a, f)
    band = F.interval_band(u[:horizon], bt.rmse)
    conf = F.confidence(bt.mape, horizon)
    sups = list(db.scalars(select(m.SupplyRow).where(m.SupplyRow.id == supply))) if supply else list(db.scalars(select(m.SupplyRow)))
    weather = list(db.scalars(select(m.WeatherRow.severity_index).order_by(m.WeatherRow.day_index)))
    outlook = weather[ND:ND + NF]
    peak = max(outlook)
    sens = [float(x.weather_sensitivity) for x in sups]
    n_records = db.scalar(select(func.count()).select_from(m.ConsumptionRow))
    return {
        "location": location, "supply": supply, "horizon": horizon,
        "history": [{"date": day_date(d).date().isoformat(), "actual": a[d], "fit": f[d] if d else None} for d in range(ND - 60, ND)],
        "forecast": [{"date": day_date(ND + k).date().isoformat(), "value": u[k], "lo": band[k][0], "hi": band[k][1]} for k in range(horizon)],
        "totals": {"d7": sum(u[:7]), "d14": sum(u[:14]), "d30": sum(u[:30])},
        "hist_mean_per_day": sum(a[-30:]) / 30,
        "backtest": {"mape": bt.mape, "rmse": bt.rmse, "coefficient_of_variation": bt.cv, "interval_coverage": bt.coverage, "window_days": 60},
        "confidence": conf,
        "methodology": {
            "method": "Statistical time-series model, not a trained ML model: weather-adjusted EWMA (alpha 0.2) + damped linear trend (0.5 x recent 7-day slope) + weekly seasonality. Deterministic.",
            "history_days": ND, "outlook_days": NF, "weather_sensitivity_range": [min(sens), max(sens)],
            "weather_index_now": sum(weather[ND:ND + 3]) / 3, "weather_outlook_peak": peak, "weather_outlook_peak_day": outlook.index(peak) + 1,
            "seasonality": "Weekly cycle (period 7 d, +/-8% amplitude) removed from history and re-applied to the forecast.",
            "confidence_formula": "100 - MAPE x (1 + horizon/30); the horizon factor is a stated heuristic (multi-day-ahead error is not separately backtested).",
            "accuracy_caveat": "The synthetic history is generated from the same weather and weekly-seasonality structure the model assumes, so low error is expected and is not evidence of real-world accuracy.",
            "records": n_records,
        },
    }


@router.get("/challenger")
def challenger(db: Session = Depends(get_db)):
    """Random Forest challenger vs the statistical model on the same hold-out samples (cross-check only)."""
    if "r" not in _challenger_cache:
        hist, fit = defaultdict(list), defaultdict(lambda: [0.0] * ND)
        for l, s, q in db.execute(select(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, m.ConsumptionRow.quantity)
                                  .order_by(m.ConsumptionRow.location_id, m.ConsumptionRow.supply_id, m.ConsumptionRow.day_index)):
            hist[(l, s)].append(q)
        for l, s, d, v in db.execute(select(m.ForecastRow.location_id, m.ForecastRow.supply_id, m.ForecastRow.day_index, m.ForecastRow.value)
                                     .where(m.ForecastRow.kind == "FIT")):
            fit[(l, s)][d] = v
        weather = list(db.scalars(select(m.WeatherRow.severity_index).order_by(m.WeatherRow.day_index)))
        sens = {x.id: float(x.weather_sensitivity) for x in db.scalars(select(m.SupplyRow))}
        _challenger_cache["r"] = ch.train_and_validate(hist, weather, sens, fit)
    return {**_challenger_cache["r"], "role": "cross-check only; dashboard forecasts use the statistical model", "library": "scikit-learn RandomForestRegressor"}


@router.post("/recompute")
def recompute(db: Session = Depends(get_db)):
    """Recompute stored forecasts from consumption history and refresh the baseline alert/priority/allocation tables."""
    n = repo.ensure_forecasts(db, force=True)
    _challenger_cache.clear()
    repo.persist_baseline(db)
    return {"forecast_rows": n}

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, models as m
from .. import repository as repo
from .. import config
from ..database import get_db
from ..services import challenger as ch
from ..services import forecasting as F
from ..services import model_service as ms
from ..services.domain import ND, NF, day_date
from .common import OptIdQuery

router = APIRouter(prefix="/api/forecast", tags=["forecast"])
_challenger_cache: dict = {}


@router.get("")
def forecast(location: OptIdQuery = None, supply: OptIdQuery = None,
             horizon: int = Query(14, description="7, 14 or 30"), db: Session = Depends(get_db)):
    """Actual vs predicted consumption with an 80% interval, backtest error, confidence index and model attribution."""
    if horizon not in (7, 14, 30):
        raise HTTPException(422, "horizon must be 7, 14 or 30")
    if location and not repo.location_exists(db, location):
        raise HTTPException(404, f"unknown location {location}")
    if supply and not repo.supply_exists(db, supply):
        raise HTTPException(404, f"unknown supply {supply}")
    s = repo.forecast_series(db, location, supply)
    a, f, u = s["actual"], s["fit"], s["fut"]
    bt = F.backtest(a, f)
    meta = repo.forecast_meta(db, location, supply)
    if not meta["models"]:
        raise RuntimeError("forecasts have not been generated yet")
    if s["fut_lo"] is not None:
        band = [[s["fut_lo"][k], s["fut_hi"][k]] for k in range(NF)][:horizon]
        interval = {"level": 0.8, "source": "trained model: per-horizon quantiles of benchmark-validation residuals, scaled to the series; aggregates combine series half-widths as independent errors"}
    else:
        band = F.interval_band(u[:horizon], bt.rmse)
        interval = {"level": 0.8, "source": "statistical model: +/-1.28 x backtest RMSE, widening with horizon"}
    conf = F.confidence(bt.mape, horizon)
    sups = list(db.scalars(select(m.SupplyRow).where(m.SupplyRow.id == supply))) if supply else list(db.scalars(select(m.SupplyRow)))
    weather = list(db.scalars(select(m.WeatherRow.severity_index).order_by(m.WeatherRow.day_index)))
    outlook = weather[ND:ND + NF]
    peak = max(outlook)
    sens = [float(x.weather_sensitivity) for x in sups]
    n_records = db.scalar(select(func.count()).select_from(m.ConsumptionRow))
    res = ms.resolve_forecast()
    ml_ids = [k for k in meta["models"] if k != ms.STATISTICAL_ID]
    primary = ml_ids[0] if ml_ids else ms.STATISTICAL_ID
    fam = "machine_learning" if ml_ids else "statistical"
    n_stat_fallback = meta["models"].get(ms.STATISTICAL_ID, 0) if ml_ids else 0
    if fam == "machine_learning":
        fmeta, _ = ms.forecaster()
        bm = fmeta.meta["benchmark_test_metrics"]
        method = (f"Trained gradient-boosted model ({fmeta.meta['model_name']}), direct multi-horizon: predicts each of the next days from lagged demand, "
                  "same-weekday lags and rolling statistics, scale-free. " + ("Known weather effects of the application are divided out of the history and re-applied to the forecast. " if res.adapter == "weather" else "")
                  + f"Trained on the ISOMORPH research benchmark ({fmeta.meta['training_data']['licence']}); benchmark test WAPE {bm['overall']['lightgbm']['wape'] * 100:.1f}%.")
        caveat = ("Benchmark accuracy does not transfer automatically: the model was trained on a simulator-generated benchmark and is scored here only on this "
                  "illustrative scenario's own history. Neither is evidence of accuracy on real operations.")
        seasonality = "Weekly pattern captured through same-weekday lag features (no fixed calendar phase)."
    else:
        method = ("Statistical time-series model (not a trained ML model): weather-adjusted EWMA (alpha 0.2) + damped linear trend (0.5 x recent 7-day slope) + weekly seasonality. Deterministic.")
        caveat = ("The scenario history is generated from the same weather and weekly-seasonality structure this model assumes, so low error is expected and is not "
                  "evidence of real-world accuracy.")
        seasonality = "Weekly cycle (period 7 d, +/-8% amplitude) removed from history and re-applied to the forecast."
    preview = repo.ml_preview(db, location, supply, horizon) if fam == "statistical" else None
    return {
        "location": location, "supply": supply, "horizon": horizon,
        "trained_model_preview": None if preview is None else {
            "model_id": preview["model_id"], "dates": [day_date(ND + k).date().isoformat() for k in range(horizon)], "values": preview["values"],
            "note": "Inference-only preview for comparison. This model is not driving the application (see model.fallback_reason)."},
        "model": {"id": primary, "family": fam, "label": "Trained ML model" if fam == "machine_learning" else "Statistical baseline",
                  "series_by_model": meta["models"], "series_on_statistical_fallback": n_stat_fallback,
                  "fallback_reason": res.reason if fam == "statistical" else None, "configured_mode": config.FORECAST_MODEL_MODE,
                  "generated_at": meta["generated_at"].isoformat() if meta["generated_at"] else None,
                  "history_through": day_date(ND - 1).date().isoformat(), "interval": interval},
        "history": [{"date": day_date(d).date().isoformat(), "actual": a[d], "fit": f[d] if d else None} for d in range(ND - 60, ND)],
        "forecast": [{"date": day_date(ND + k).date().isoformat(), "value": u[k], "lo": band[k][0], "hi": band[k][1]} for k in range(horizon)],
        "totals": {"d7": sum(u[:7]), "d14": sum(u[:14]), "d30": sum(u[:30])},
        "hist_mean_per_day": sum(a[-30:]) / 30,
        "backtest": {"mape": bt.mape, "rmse": bt.rmse, "coefficient_of_variation": bt.cv, "interval_coverage": bt.coverage, "window_days": 60,
                     "kind": "one-step-ahead, out-of-sample" if fam == "machine_learning" else "one-step-ahead rolling fit"},
        "confidence": conf,
        "methodology": {
            "method": method,
            "history_days": ND, "outlook_days": NF, "weather_sensitivity_range": [min(sens), max(sens)],
            "weather_index_now": sum(weather[ND:ND + 3]) / 3, "weather_outlook_peak": peak, "weather_outlook_peak_day": outlook.index(peak) + 1,
            "seasonality": seasonality,
            "confidence_formula": "100 - MAPE x (1 + horizon/30); the horizon factor is a stated heuristic (multi-day-ahead error is not separately backtested).",
            "accuracy_caveat": caveat,
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
    return {**_challenger_cache["r"], "role": "secondary cross-check trained on this scenario's own short history; it never feeds decisions", "library": "scikit-learn RandomForestRegressor"}


@router.post("/recompute")
def recompute(request: Request, p: auth.Principal = Depends(auth.admin), db: Session = Depends(get_db)):
    """Recompute stored forecasts from consumption history and refresh the baseline alert/priority/allocation tables (administrator only)."""
    ms.reset_cache()          # also lets a repaired model artefact be picked up without restarting the service
    n = repo.ensure_forecasts(db, force=True)
    _challenger_cache.clear()
    repo.persist_baseline(db)
    auth.audit(p.username, "forecast_recompute", "success", ip=auth.get_client_ip(request), detail={"rows": n})
    return {"forecast_rows": n}

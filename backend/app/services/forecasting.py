"""Statistical demand forecasting (deterministic, not a trained ML model).

Weather-adjusted EWMA level (alpha 0.2) + damped linear trend (0.5 x recent 7-day slope) + weekly seasonality.
History is de-weathered / de-seasonalised, smoothed, then re-weathered with the weather outlook.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .domain import ND, NF, clamp, js_round

ALPHA = 0.2
INTERVAL_Z = 1.28   # 80% interval


def weather_adj(sensitivity: float, w: float) -> float:
    return 1 + sensitivity * 0.6 * w


def weekly_season(day: int) -> float:
    return 1 + 0.08 * math.sin(2 * math.pi * day / 7)


def fit_and_forecast(history: list, sensitivity: float, weather: list, nf: int = NF):
    """Return (fit, fut). fit[d] is the one-step-ahead model fit for history day d (None for d=0)."""
    n = len(history)
    base = [v / (weather_adj(sensitivity, weather[d]) * weekly_season(d)) for d, v in enumerate(history)]
    level = [base[0]]
    fit = [None]
    for d in range(1, n):
        fit.append(level[d - 1] * weather_adj(sensitivity, weather[d]) * weekly_season(d))
        level.append(ALPHA * base[d] + (1 - ALPHA) * level[d - 1])
    m = lambda a: sum(a) / len(a)
    slope = (m(base[-7:]) - m(base[-14:-7])) / 7 * 0.5
    fut = [(level[n - 1] + slope * k) * weather_adj(sensitivity, weather[n + k - 1]) * weekly_season(n + k - 1)
           for k in range(1, nf + 1)]
    return fit, fut


def mean_first(fut: list, k: int = 7) -> float:
    return sum(fut[:k]) / k


@dataclass
class Backtest:
    mape: float
    rmse: float
    cv: float
    coverage: float


def backtest(actual: list, fit: list, window: int = 60) -> Backtest:
    """Rolling one-step-ahead backtest over the last `window` days."""
    a = actual[-window:]
    f = [x or 0.0 for x in fit[-window:]]
    n = len(a)
    err = [x - y for x, y in zip(a, f)]
    mape = sum(abs(e) / x for e, x in zip(err, a)) / n * 100
    rmse = math.sqrt(sum(e * e for e in err) / n)
    mu = sum(a) / n
    cv = math.sqrt(sum((x - mu) ** 2 for x in a) / n) / mu * 100
    cov = sum(1 for e in err if abs(e) <= INTERVAL_Z * rmse) / n * 100
    return Backtest(mape, rmse, cv, cov)


def confidence(mape: float, horizon: int) -> dict:
    """Forecast confidence = 100 - MAPE x (1 + horizon/30), clamped 0..100 (documented heuristic)."""
    c = int(clamp(js_round(100 - mape * (1 + horizon / 30)), 0, 100))
    label, level = ("HIGH", "ok") if c >= 90 else ("MODERATE", "wr") if c >= 75 else ("LOW", "cr")
    return {"value": c, "label": label, "level": level}


def interval_band(fut: list, rmse: float) -> list:
    return [[v - INTERVAL_Z * rmse * (1 + k / 30), v + INTERVAL_Z * rmse * (1 + k / 30)] for k, v in enumerate(fut)]

"""Leakage-safe, scale-free feature construction for direct multi-horizon demand forecasting.

For an origin day ``t`` (the last observed day) and a horizon ``h`` (1..MAX_HORIZON) every feature uses only
observations at days <= t. The target is ``y[t+h] / scale`` where ``scale`` is the mean of the 28 days ending at ``t``.
Features are expressed relative to that scale, so one model serves series with very different demand levels.

No absolute calendar phase is used: weekly seasonality is captured through "seasonal lags" - the observations that
fall on the same weekday as the target day (``y[t+h-7k]``) - which are available whatever weekday a series starts on.
"""
from __future__ import annotations

import math

import numpy as np

SCHEMA_VERSION = 1
MAX_HORIZON = 30
MIN_HISTORY = 28          # days of history needed to build any feature
SCALE_WINDOW = 28
SCALE_FLOOR = 1.0         # a series averaging < 1 unit/day over the last 28 d is treated as intermittent (see eligibility)
N_LAGS = 14
N_SEASONAL = 4

FEATURE_NAMES = ([f"lag_{k}" for k in range(N_LAGS)] + [f"seas_{j}" for j in range(1, N_SEASONAL + 1)]
                 + ["mean7", "mean14", "cv7", "cv28", "trend_7v7", "trend_14v14", "horizon"])


class InputError(ValueError):
    """Raised when inference/training inputs are missing, malformed or insufficient."""


def validate_history(history, *, min_len: int = MIN_HISTORY) -> np.ndarray:
    a = np.asarray(history, dtype=float)
    if a.ndim != 1:
        raise InputError("history must be a one-dimensional sequence of daily values")
    if a.size < min_len:
        raise InputError(f"history has {a.size} days; at least {min_len} are required")
    if not np.all(np.isfinite(a)):
        raise InputError("history contains missing or non-finite values")
    if np.any(a < 0):
        raise InputError("history contains negative demand values")
    return a


def eligibility(history, *, max_zero_share: float = 0.3) -> tuple[bool, str]:
    """(ok, reason). The scale-free model is not designed for intermittent / near-zero demand."""
    a = validate_history(history)
    w = a[-SCALE_WINDOW:]
    if w.mean() < SCALE_FLOOR:
        return False, "mean demand over the last 28 days is below 1 unit/day"
    if float(np.mean(w == 0)) > max_zero_share:
        return False, f"more than {max_zero_share:.0%} zero-demand days in the last 28 days (intermittent demand)"
    return True, ""


def seasonal_lag_index(origin: np.ndarray, horizon: np.ndarray, j: int) -> np.ndarray:
    k1 = -(-horizon // 7)                      # ceil(h / 7): first same-weekday day that is <= origin
    return origin + horizon - 7 * (k1 + j - 1)


def build(Y: np.ndarray, items: np.ndarray, origins: np.ndarray, horizons: np.ndarray, *, with_target: bool = False):
    """Vectorised feature matrix for (item, origin, horizon) triples.

    Y: array (T, C) of observed daily demand. Returns (X, scale[, y_ratio]).
    Only Y[:origin+1] is read to form features; Y[origin+h] is read solely when ``with_target`` is true.
    """
    Y = np.asarray(Y, dtype=np.float64)
    if Y.ndim != 2:
        raise InputError("Y must be a (days, series) array")
    items, origins, horizons = (np.asarray(v, dtype=np.int64) for v in (items, origins, horizons))
    T = Y.shape[0]
    if len(items) == 0:
        raise InputError("no (series, origin, horizon) triples supplied")
    if origins.min() < MIN_HISTORY - 1 or origins.max() > T - 1:
        raise InputError("origin outside the range with sufficient history")
    if horizons.min() < 1 or horizons.max() > MAX_HORIZON:
        raise InputError(f"horizon must be within 1..{MAX_HORIZON}")
    if with_target and (origins + horizons).max() > T - 1:
        raise InputError("target day beyond the end of the data")
    if items.min() < 0 or items.max() >= Y.shape[1]:
        raise InputError("series index out of range")

    z = np.zeros((1, Y.shape[1]))
    cs, cs2 = np.vstack([z, np.cumsum(Y, 0)]), np.vstack([z, np.cumsum(Y * Y, 0)])
    o, i = origins, items

    def wsum(c, w):
        return c[o + 1, i] - c[o + 1 - w, i]

    m28 = wsum(cs, 28) / 28
    scale = np.maximum(m28, SCALE_FLOOR)
    cols = [Y[o - k, i] / scale for k in range(N_LAGS)]
    cols += [Y[np.clip(seasonal_lag_index(o, horizons, j), 0, None), i] / scale for j in range(1, N_SEASONAL + 1)]
    m7, m14 = wsum(cs, 7) / 7, wsum(cs, 14) / 14
    v7 = np.maximum(wsum(cs2, 7) / 7 - m7 ** 2, 0.0)
    v28 = np.maximum(wsum(cs2, 28) / 28 - m28 ** 2, 0.0)
    prev7 = (cs[o + 1 - 7, i] - cs[o + 1 - 14, i]) / 7
    prev14 = (cs[o + 1 - 14, i] - cs[o + 1 - 28, i]) / 14
    eps = 1e-9
    cols += [m7 / scale, m14 / scale, np.sqrt(v7) / np.maximum(m7, eps), np.sqrt(v28) / np.maximum(m28, eps),
             m7 / np.maximum(prev7, eps), m14 / np.maximum(prev14, eps), horizons.astype(np.float64)]
    X = np.column_stack(cols)
    if with_target:
        return X, scale, Y[o + horizons, i] / scale
    return X, scale


def build_single(history, horizon: int = MAX_HORIZON):
    """Features for one series at its last observed day, for horizons 1..horizon."""
    a = validate_history(history)
    if not (1 <= horizon <= MAX_HORIZON) or int(horizon) != horizon:
        raise InputError(f"horizon must be an integer within 1..{MAX_HORIZON}")
    hs = np.arange(1, horizon + 1)
    X, scale = build(a[:, None], np.zeros(horizon, int), np.full(horizon, a.size - 1), hs)
    return X, float(scale[0])

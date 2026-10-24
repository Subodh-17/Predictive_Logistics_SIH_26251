"""Forecast-accuracy metrics with explicit zero-denominator handling.

MAE   = mean(|y - f|)
RMSE  = sqrt(mean((y - f)^2))
WAPE  = sum(|y - f|) / sum(|y|)            -> NaN when sum(|y|) == 0 (undefined, never reported as 0)
MAPE  = mean(|y - f| / y) over y > 0 only  -> NaN when there is no y > 0; the number of excluded points is reported
Bias  = sum(f - y) / sum(|y|)              -> NaN when sum(|y|) == 0
"""
from __future__ import annotations

import numpy as np


def _arr(y, f):
    y, f = np.asarray(y, float), np.asarray(f, float)
    if y.shape != f.shape:
        raise ValueError("actual and forecast must have the same shape")
    if y.size == 0:
        raise ValueError("empty input")
    return y, f


def mae(y, f) -> float:
    y, f = _arr(y, f)
    return float(np.mean(np.abs(y - f)))


def rmse(y, f) -> float:
    y, f = _arr(y, f)
    return float(np.sqrt(np.mean((y - f) ** 2)))


def wape(y, f) -> float:
    y, f = _arr(y, f)
    den = float(np.sum(np.abs(y)))
    return float("nan") if den == 0 else float(np.sum(np.abs(y - f)) / den)


def bias(y, f) -> float:
    y, f = _arr(y, f)
    den = float(np.sum(np.abs(y)))
    return float("nan") if den == 0 else float(np.sum(f - y) / den)


def mape(y, f) -> tuple[float, int]:
    """(MAPE as a fraction, number of zero-actual points excluded)."""
    y, f = _arr(y, f)
    m = y > 0
    if not m.any():
        return float("nan"), int(y.size)
    return float(np.mean(np.abs(y[m] - f[m]) / y[m])), int((~m).sum())


def interval_coverage(y, lo, hi) -> float:
    y, lo = _arr(y, lo)
    hi = np.asarray(hi, float)
    return float(np.mean((y >= lo) & (y <= hi)))


def summary(y, f) -> dict:
    mp, excl = mape(y, f)
    return {"n": int(np.size(y)), "mae": mae(y, f), "rmse": rmse(y, f), "wape": wape(y, f), "bias": bias(y, f),
            "mape": mp, "mape_zero_actuals_excluded": excl}


# --- classification / calibration -------------------------------------------------------------------------------
def brier(y, p) -> float:
    y, p = _arr(y, p)
    return float(np.mean((p - y) ** 2))


def expected_calibration_error(y, p, bins: int = 10) -> float:
    y, p = _arr(y, p)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)

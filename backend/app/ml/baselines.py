"""Simple reference forecasters evaluated against the ML model. All use history up to the origin only.

``history`` is a 1-D array; each function returns forecasts for horizons 1..H.
"""
from __future__ import annotations

import numpy as np

from .features import MAX_HORIZON, validate_history


def naive_last(history, horizon: int = MAX_HORIZON) -> np.ndarray:
    a = validate_history(history, min_len=1)
    return np.full(horizon, a[-1])


def seasonal_naive(history, horizon: int = MAX_HORIZON, period: int = 7) -> np.ndarray:
    """y_hat[t+h] = y[t+h-k*period] with the smallest k that points at an observed day."""
    a = validate_history(history, min_len=period)
    t = a.size - 1
    h = np.arange(1, horizon + 1)
    return a[t + h - period * (-(-h // period))]


def trailing_mean(history, horizon: int = MAX_HORIZON, window: int = 28) -> np.ndarray:
    a = validate_history(history, min_len=1)
    return np.full(horizon, a[-window:].mean())

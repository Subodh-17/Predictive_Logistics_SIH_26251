"""Inference wrapper for the trained direct multi-horizon LightGBM demand model."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import features as F
from .artifacts import ArtifactError, current_version_dir, read_verified


@dataclass
class ForecastResult:
    values: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    model_id: str
    scale: float


class MLForecaster:
    KIND = "demand_forecast"

    def __init__(self, booster, meta: dict):
        self.booster, self.meta = booster, meta
        self.model_id = f"{meta['model_name']}@{meta['version']}"
        q = meta["interval"]
        q_lo, q_hi = np.asarray(q["ratio_lo"], float), np.asarray(q["ratio_hi"], float)
        if q_lo.shape != (F.MAX_HORIZON,) or q_hi.shape != (F.MAX_HORIZON,):
            raise ValueError(
                f"interval ratio_lo and ratio_hi must have exactly {F.MAX_HORIZON} elements, got {q_lo.shape} and {q_hi.shape}"
            )
        if not np.all(np.isfinite(q_lo)) or not np.all(np.isfinite(q_hi)):
            raise ValueError("interval ratio_lo and ratio_hi must contain finite numeric values")
        self._q_lo, self._q_hi = q_lo, q_hi
        self.interval_level = q["level"]

    @classmethod
    def load(cls, artifact_root: Path | str, pin: str | None = None) -> "MLForecaster":
        try:
            import lightgbm as lgb
        except ImportError as e:
            raise ArtifactError("lightgbm is not installed") from e
        d = current_version_dir(Path(artifact_root), "forecast")
        meta, model_p = read_verified(d, expected_kind=cls.KIND, pin=pin)
        try:
            booster = lgb.Booster(model_file=str(model_p))
        except Exception as e:  # noqa: BLE001
            raise ArtifactError(f"model file could not be parsed: {e}") from e
        if booster.num_feature() != len(F.FEATURE_NAMES):
            raise ArtifactError("model feature count does not match this code version")
        try:
            return cls(booster, meta)
        except (KeyError, TypeError, ValueError) as e:
            raise ArtifactError(f"model metadata is incomplete or malformed: {type(e).__name__}: {e}") from e

    # ------------------------------------------------------------------ prediction
    def _predict_ratio(self, X: np.ndarray) -> np.ndarray:
        return np.maximum(self.booster.predict(X, num_threads=1), 0.0)

    def predict(self, history, horizon: int = F.MAX_HORIZON, *, past_factors=None, future_factors=None) -> ForecastResult:
        """Forecast days t+1..t+horizon.

        past_factors / future_factors: optional multiplicative effects that are *known to the application* (for example
        a weather adjustment). History is divided by ``past_factors`` before modelling and the forecast multiplied by
        ``future_factors`` afterwards. Omit both for a plain forecast.
        """
        a = F.validate_history(history)
        if past_factors is not None:
            pf = np.asarray(past_factors, float)
            if pf.shape != a.shape or not np.all(pf > 0):
                raise F.InputError("past_factors must be positive and match the history length")
            a = a / pf
        ff = np.ones(horizon)
        if future_factors is not None:
            ff = np.asarray(future_factors, float)[:horizon]
            if ff.shape != (horizon,) or not np.all(ff > 0):
                raise F.InputError("future_factors must be positive with one value per forecast day")
        X, scale = F.build_single(a, horizon)
        r = self._predict_ratio(X)
        h = np.arange(horizon)
        vals = r * scale * ff
        lo = np.maximum((r + self._q_lo[h]) * scale * ff, 0.0)
        hi = np.maximum((r + self._q_hi[h]) * scale * ff, vals)
        return ForecastResult(vals, np.minimum(lo, vals), hi, self.model_id, scale)

    def one_step_fits(self, history, *, past_factors=None) -> np.ndarray:
        """Out-of-sample one-step-ahead forecasts: element d is the h=1 forecast made at day d-1 (NaN where < 28 days of history)."""
        a = F.validate_history(history)
        pf = np.ones_like(a) if past_factors is None else np.asarray(past_factors, float)
        base = a / pf
        n = a.size
        out = np.full(n, np.nan)
        origins = np.arange(F.MIN_HISTORY - 1, n - 1)
        if origins.size:
            X, scale = F.build(base[:, None], np.zeros(origins.size, int), origins, np.ones(origins.size, int))
            out[origins + 1] = self._predict_ratio(X) * scale * pf[origins + 1]
        return out

    def timed_predict(self, history, horizon: int = F.MAX_HORIZON):
        t0 = time.perf_counter()
        r = self.predict(history, horizon)
        return r, (time.perf_counter() - t0) * 1000

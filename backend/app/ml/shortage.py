"""Shortage-onset risk: features + inference.

Target (defined on the ISOMORPH benchmark, destination node): "does the destination record any new backlog on at least one of
the next 7 days (t+1..t+7)?", evaluated for item-days with NO backlog at day t (shortage *onset*). All features use
observations at days <= t only. Inputs required at inference: >= 28 days of demand / on-hand / in-transit / new-backlog
history for the item at the node. These inputs exist in the benchmark; they do NOT exist in the illustrative application
scenario (no backlog or in-transit ledger), so the application's own status classification is not driven by this model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .artifacts import ArtifactError, current_version_dir, read_verified
from .features import InputError

SHORTAGE_SCHEMA = 1
HORIZON = 7
WINDOW = 28
FEATURE_NAMES = ["cover_days_28", "cover_days_7", "backlog_ratio", "in_transit_ratio", "cover_plus_pipeline_days", "demand_ratio_7v28",
                 "demand_cv_28", "on_hand_change_7d", "in_transit_change_7d", "shortage_days_last_28", "days_since_shortage"]
STOCK_ONLY = ["cover_days_28", "cover_days_7", "demand_ratio_7v28", "demand_cv_28", "on_hand_change_7d"]
NO_SHORTAGE_SENTINEL = 60.0


def build(dem, oh, bl, it, nb, items, origins) -> np.ndarray:
    """Feature matrix for (item, origin) pairs from (T, C) arrays; reads only rows <= origin."""
    dem, oh, bl, it, nb = (np.asarray(a, float) for a in (dem, oh, bl, it, nb))
    items, origins = np.asarray(items, int), np.asarray(origins, int)
    T = dem.shape[0]
    if origins.min() < WINDOW - 1 or origins.max() >= T:
        raise InputError("origin outside the range with sufficient history")
    z = np.zeros((1, dem.shape[1]))
    cs, cs2 = np.vstack([z, np.cumsum(dem, 0)]), np.vstack([z, np.cumsum(dem * dem, 0)])
    sh = (nb > 0).astype(float)
    css = np.vstack([z, np.cumsum(sh, 0)])
    idx = np.where(nb > 0, np.arange(T)[:, None], -10_000)
    last = np.maximum.accumulate(idx, axis=0)
    o, i = origins, items
    m28 = (cs[o + 1, i] - cs[o + 1 - 28, i]) / 28
    m7 = (cs[o + 1, i] - cs[o + 1 - 7, i]) / 7
    s28 = np.maximum(m28, 1.0)
    v28 = np.maximum((cs2[o + 1, i] - cs2[o + 1 - 28, i]) / 28 - m28 ** 2, 0)
    since = np.minimum(o - last[o, i], NO_SHORTAGE_SENTINEL)
    return np.column_stack([
        oh[o, i] / s28, oh[o, i] / np.maximum(m7, 1.0), bl[o, i] / s28, it[o, i] / s28, (oh[o, i] + it[o, i]) / s28, m7 / s28,
        np.sqrt(v28) / np.maximum(m28, 1e-9), (oh[o, i] - oh[o - 7, i]) / s28, (it[o, i] - it[o - 7, i]) / s28,
        css[o + 1, i] - css[o + 1 - 28, i], since])


def build_record(demand, on_hand, in_transit, backlog, new_backlog) -> np.ndarray:
    """One record from five equally long daily histories (oldest first, last element = today)."""
    arrs = []
    for name, a in (("demand", demand), ("on_hand", on_hand), ("in_transit", in_transit), ("backlog", backlog), ("new_backlog", new_backlog)):
        a = np.asarray(a, float)
        if a.ndim != 1 or a.size < WINDOW:
            raise InputError(f"{name} needs a one-dimensional history of at least {WINDOW} days")
        if not np.all(np.isfinite(a)) or np.any(a < 0):
            raise InputError(f"{name} contains missing, non-finite or negative values")
        arrs.append(a)
    if len({a.size for a in arrs}) != 1:
        raise InputError("all histories must have the same length")
    d, o, t, b, n = (a[:, None] for a in arrs)
    return build(d, o, b, t, n, [0], [d.shape[0] - 1])


class ShortageModel:
    KIND = "shortage_risk"

    def __init__(self, booster, meta):
        self.booster, self.meta = booster, meta
        cal = meta["calibration"]
        self._x, self._y = np.asarray(cal["x"], float), np.asarray(cal["y"], float)
        self.model_id = f"{meta['model_name']}@{meta['version']}"
        self.feature_names = meta["feature_names"]

    @classmethod
    def load(cls, artifact_root: Path | str, pin: str | None = None) -> "ShortageModel":
        try:
            import lightgbm as lgb
        except ImportError as e:
            raise ArtifactError("lightgbm is not installed") from e
        d = current_version_dir(Path(artifact_root), "shortage")
        meta, model_p = read_verified(d, expected_kind=cls.KIND, pin=pin)
        if meta.get("feature_names") != FEATURE_NAMES or meta.get("shortage_schema") != SHORTAGE_SCHEMA:
            raise ArtifactError("shortage model feature schema is incompatible with this code version")
        try:
            return cls(lgb.Booster(model_file=str(model_p)), meta)
        except Exception as e:  # noqa: BLE001
            raise ArtifactError(f"model file could not be parsed: {e}") from e

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.booster.predict(np.asarray(X, float), num_threads=1)
        return np.clip(np.interp(raw, self._x, self._y), 0.0, 1.0)

    def score_record(self, demand, on_hand, in_transit, backlog, new_backlog) -> dict:
        if float(np.asarray(backlog, float)[-1]) > 0:
            return {"applicable": False, "reason": "backlog already present at the origin day; the model is defined for shortage onset only",
                    "model": self.model_id}
        p = float(self.predict_proba(build_record(demand, on_hand, in_transit, backlog, new_backlog))[0])
        return {"applicable": True, "probability": p, "horizon_days": HORIZON, "model": self.model_id,
                "threshold": self.meta["operating_point"]["threshold"], "flag": p >= self.meta["operating_point"]["threshold"]}

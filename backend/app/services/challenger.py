"""Random Forest challenger (cross-check only; does not drive dashboard numbers).

Same design as the v3 prototype: 20 trees, depth 6, seeded, trained on days 1-90 of the synthetic history and validated on
the last 20 days, with the statistical model scored on the same hold-out samples.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestRegressor

TRAIN_END = 90
FIRST_DAY = 8
N_TREES, DEPTH, SEED = 20, 6, 7
FEATURES = ["previous-day demand (normalised)", "7-day mean demand (normalised)", "weather index (today)",
            "weather index (previous day)", "day of week", "supply weather sensitivity"]


def train_and_validate(history: dict, weather: list, sensitivity: dict, fit: dict) -> dict:
    """history/fit: {(location, supply): [daily values]}; sensitivity: {supply: float}."""
    X, y, Xh, yh, mus, sfit = [], [], [], [], [], []
    for key, h in history.items():
        mu = sum(h[:TRAIN_END]) / TRAIN_END
        for d in range(FIRST_DAY, len(h)):
            x = [h[d - 1] / mu, sum(h[d - 7:d]) / 7 / mu, weather[d], weather[d - 1], d % 7, sensitivity[key[1]]]
            if d < TRAIN_END:
                X.append(x); y.append(h[d] / mu)
            else:
                Xh.append(x); yh.append(h[d]); mus.append(mu); sfit.append(fit[key][d])
    rf = RandomForestRegressor(n_estimators=N_TREES, max_depth=DEPTH, max_features=0.5, bootstrap=True, random_state=SEED, n_jobs=1)
    rf.fit(np.array(X), np.array(y))
    pred = rf.predict(np.array(Xh)) * np.array(mus)
    yh_a = np.array(yh)
    return {"trees": N_TREES, "depth": DEPTH, "train_samples": len(X), "holdout_samples": len(Xh),
            "holdout_series": len(history), "rf_mape": float(np.mean(np.abs(pred - yh_a) / yh_a) * 100),
            "statistical_mape": float(np.mean(np.abs(np.array(sfit) - yh_a) / yh_a) * 100), "features": FEATURES,
            "train_days": f"1-{TRAIN_END}", "holdout_days": f"{TRAIN_END + 1}-{len(next(iter(history.values())))}"}

"""Rolling-origin holdout of the trained model on the application's own illustrative scenario (50 location x supply series, 110 days),
and the pre-registered promotion decision.

The trained model never saw this data. Origins t = 40, 43, ..., 79; for each origin every series is forecast for days t+1..t+30 using only days
<= t, and scored against the actual values that follow (all within the 110-day history). The weather outlook is treated as known, exactly as the
application does for the statistical model.

PROMOTION RULE (fixed before looking at the result; see ml/README.md). The trained model drives the application (FORECAST_MODEL_MODE=auto) only if ALL hold:
  1. Scenario holdout, horizons 1-14: WAPE of the best trained variant is at least 2% lower (relative) than the statistical model's AND the
     95% bootstrap CI of that improvement excludes 0.
  2. Benchmark test (ml/reports/forecast_benchmark_eval.json): the trained model beats the best simple baseline with the 95% CI excluding 0.
  3. Series-level 80% interval coverage on the scenario holdout lies within [70%, 90%].
Otherwise the decision is "not_promoted" with the failed criteria listed; the model stays available as an explicit opt-in.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import common as C
from app import seed_data as SD
from app.ml import baselines as B, features as F, metrics as M
from app.ml.artifacts import sha256_file
from app.ml.forecaster import MLForecaster
from app.services.forecasting import fit_and_forecast, weather_adj

ORIGINS = list(range(40, 80, 3))
H = 30
BUCKETS = {"h01_14": (1, 14), "h01_07": (1, 7), "h08_14": (8, 14), "h15_30": (15, 30)}


def boot(y, a, b, groups, n=500, seed=0):
    rng = np.random.default_rng(seed)
    _, inv = np.unique(groups, return_inverse=True)
    G = inv.max() + 1
    ea, eb = (np.bincount(inv, weights=np.abs(y - p), minlength=G) for p in (a, b))
    v = []
    for _ in range(n):
        s = rng.integers(0, G, G)
        v.append((eb[s].sum() - ea[s].sum()) / eb[s].sum())
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=C.ML_DIR / "artifacts", type=Path)
    ap.add_argument("--reports", default=C.ML_DIR / "reports", type=Path)
    ap.add_argument("--no-promote", action="store_true", help="write the report but do not touch artefact metadata")
    a = ap.parse_args()
    fc = MLForecaster.load(a.artifacts)
    ds = SD.build_dataset()
    W = ds["weather"]
    sens = {n: s for n, _, s in SD.SUPPLY_ROWS}
    keys = sorted(ds["history"])
    locs, sups = sorted({k[0] for k in keys}), sorted({k[1] for k in keys})
    rec = {k: [] for k in ("series", "origin", "h", "y")}
    P = {n: [] for n in ("statistical_ewma (existing)", "ml_plain", "ml_weather_adapter", "naive_last", "seasonal_naive_7", "trailing_mean_28")}
    LO = {"ml_plain": [], "ml_weather_adapter": []}
    HI = {"ml_plain": [], "ml_weather_adapter": []}
    for si, key in enumerate(keys):
        y_full, s = np.array(ds["history"][key], float), sens[key[1]]
        for t in ORIGINS:
            hist = y_full[: t + 1]
            pf = [weather_adj(s, W[d]) for d in range(t + 1)]
            ff = [weather_adj(s, W[t + 1 + k]) for k in range(H)]
            stat = np.array(fit_and_forecast(hist.tolist(), s, W[: t + 1 + H], H)[1])
            mp = fc.predict(hist, H)
            mw = fc.predict(hist, H, past_factors=pf, future_factors=ff)
            base = {"naive_last": B.naive_last(hist, H), "seasonal_naive_7": B.seasonal_naive(hist, H), "trailing_mean_28": B.trailing_mean(hist, H)}
            rec["series"] += [si] * H; rec["origin"] += [t] * H; rec["h"] += list(range(1, H + 1)); rec["y"] += y_full[t + 1: t + 1 + H].tolist()
            P["statistical_ewma (existing)"] += stat.tolist(); P["ml_plain"] += mp.values.tolist(); P["ml_weather_adapter"] += mw.values.tolist()
            for n, v in base.items():
                P[n] += v.tolist()
            LO["ml_plain"] += mp.lo.tolist(); HI["ml_plain"] += mp.hi.tolist(); LO["ml_weather_adapter"] += mw.lo.tolist(); HI["ml_weather_adapter"] += mw.hi.tolist()
    R = {k: np.array(v) for k, v in rec.items()}
    P = {k: np.array(v) for k, v in P.items()}
    LO, HI = {k: np.array(v) for k, v in LO.items()}, {k: np.array(v) for k, v in HI.items()}
    y, h = R["y"], R["h"]
    overall = {k: M.summary(y, v) for k, v in P.items()}
    buckets = {b: {k: M.summary(y[(h >= lo) & (h <= hi)], v[(h >= lo) & (h <= hi)]) for k, v in P.items()} for b, (lo, hi) in BUCKETS.items()}
    per_series = {f"{keys[i][0]}/{keys[i][1]}": {k: M.wape(y[R["series"] == i], P[k][R["series"] == i]) for k in ("statistical_ewma (existing)", "ml_plain", "ml_weather_adapter")}
                  for i in range(len(keys))}
    groups = R["series"] * 1000 + R["origin"]
    m14 = (h <= 14)
    best_variant = min(("ml_plain", "ml_weather_adapter"), key=lambda k: M.wape(y[m14], P[k][m14]))
    ci = {k: boot(y[m14], P[best_variant][m14], P[k][m14], groups[m14]) for k in P if k != best_variant}

    def coverage(variant):
        out = {"nominal": 0.8, "series_level": M.interval_coverage(y, LO[variant], HI[variant])}
        for name, idx_fn in (("by_location_aggregate", lambda i: locs.index(keys[i][0])), ("by_supply_aggregate", lambda i: sups.index(keys[i][1])), ("all_series_aggregate", lambda i: 0)):
            grp = np.array([idx_fn(i) for i in R["series"]])
            cov = []
            for g in np.unique(grp):
                for t in ORIGINS:
                    for hh in range(1, H + 1):
                        m_ = (grp == g) & (R["origin"] == t) & (h == hh)
                        v, ya = P[variant][m_].sum(), y[m_].sum()
                        lo = max(0.0, v - np.sqrt(((P[variant][m_] - LO[variant][m_]) ** 2).sum())); hi = v + np.sqrt(((HI[variant][m_] - P[variant][m_]) ** 2).sum())
                        cov.append(lo <= ya <= hi)
            out[name] = float(np.mean(cov))
        return out
    cov = {v: coverage(v) for v in ("ml_plain", "ml_weather_adapter")}

    # ---- promotion decision
    bench = json.loads((a.reports / "forecast_benchmark_eval.json").read_text())["test"]
    stat_w = M.wape(y[m14], P["statistical_ewma (existing)"][m14])
    ml_w = M.wape(y[m14], P[best_variant][m14])
    rel = (stat_w - ml_w) / stat_w
    ci_stat = ci["statistical_ewma (existing)"]
    bb = bench["best_baseline"]
    c1 = rel >= 0.02 and ci_stat[0] > 0
    c2 = bench["rel_wape_improvement_vs_baseline_95ci"][bb][0] > 0
    c3 = 0.70 <= cov[best_variant]["series_level"] <= 0.90
    failed = []
    if not c1:
        failed.append(f"scenario holdout h1-14: {best_variant} WAPE {ml_w * 100:.2f}% vs statistical {stat_w * 100:.2f}% (relative improvement {rel * 100:+.1f}%, 95% CI {ci_stat[0] * 100:+.1f}..{ci_stat[1] * 100:+.1f}%); need >= +2% with CI above 0")
    if not c2:
        failed.append(f"benchmark test: CI of improvement over best baseline ({bb}) includes 0 ({bench['rel_wape_improvement_vs_baseline_95ci'][bb]})")
    if not c3:
        failed.append(f"series-level interval coverage {cov[best_variant]['series_level'] * 100:.1f}% outside 70-90%")
    decision = {"status": "promoted" if not failed else "not_promoted", "adapter": "weather" if best_variant == "ml_weather_adapter" else "plain",
                "best_variant": best_variant, "reason": None if not failed else "; ".join(failed),
                "criteria": {"scenario_holdout_improvement_ge_2pct_ci_gt0": bool(c1), "benchmark_beats_best_baseline_ci_gt0": bool(c2), "interval_coverage_70_90": bool(c3)},
                "decided_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    report = {"generated_utc": decision["decided_utc"], "protocol": {"origins": ORIGINS, "horizons": "1..30", "series": len(keys), "rows": int(len(y)),
              "weather": "outlook treated as known (as in the application)", "note": "scenario history is generated from the statistical model's own structure (weather x weekly x trend); it favours that model"},
              "overall": overall, "by_horizon_bucket": buckets, "per_series_wape": per_series, "best_trained_variant": best_variant,
              "rel_wape_improvement_h1_14_95ci_vs": ci, "interval_coverage": cov, "promotion": decision}
    a.reports.mkdir(exist_ok=True)
    (a.reports / "forecast_scenario_eval.json").write_text(json.dumps(report, indent=2))
    if not a.no_promote:
        mp = a.artifacts / "forecast" / (a.artifacts / "forecast" / "CURRENT").read_text().strip() / "metadata.json"
        meta = json.loads(mp.read_text())
        meta["promotion"] = decision
        mp.write_text(json.dumps(meta, indent=2))
    print(json.dumps({"wape_h1_14": {k: round(M.wape(y[m14], v[m14]), 4) for k, v in P.items()}, "overall_wape": {k: round(v["wape"], 4) for k, v in overall.items()},
                      "coverage": cov, "ci": ci, "decision": decision}, indent=2))


if __name__ == "__main__":
    main()

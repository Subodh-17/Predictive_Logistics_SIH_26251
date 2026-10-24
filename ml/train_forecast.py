"""Train and evaluate the demand-forecasting model on the ISOMORPH research benchmark.

    python ml/train_forecast.py --data-dir <path containing output_item50/> [--version v1]

Protocol (all chronological, fixed seed, configuration in ml/configs/forecast.json):
  1. Split days into train / validation / test (70/15/15). Rows are never shuffled across time.
  2. Fit candidates on the training segment; select hyper-parameters on validation only.
  3. Evaluate the selected model and every baseline ONCE on the held-out test segment.
  4. Calibrate the 80% interval from validation residuals (per horizon) and measure its coverage on test.
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestRegressor

import common as C
from app.ml import baselines as B, features as F, metrics as M
from app.ml.artifacts import sha256_file
from app.services.forecasting import fit_and_forecast

BUCKETS = {"h01_07": (1, 7), "h08_14": (8, 14), "h15_30": (15, 30)}


def stat_predictions(Y, items, origins, horizons, window: int):
    """Existing project model (weather-adjusted EWMA + damped trend + weekly term) with the weather term disabled
    (sensitivity 0, zero weather): the benchmark has no weather series."""
    out = np.empty(len(items))
    cache = {}
    zeros = [0.0] * (window + F.MAX_HORIZON)
    for r, (i, o) in enumerate(zip(items, origins)):
        key = (i, o)
        if key not in cache:
            hist = Y[max(0, o - window + 1): o + 1, i].tolist()
            cache[key] = np.array(fit_and_forecast(hist, 0.0, zeros[:len(hist) + F.MAX_HORIZON], F.MAX_HORIZON)[1])
        out[r] = cache[key][horizons[r] - 1]
    return out


def baseline_predictions(Y, items, origins, horizons):
    cache = {}
    res = {"naive_last": np.empty(len(items)), "seasonal_naive_7": np.empty(len(items)), "trailing_mean_28": np.empty(len(items))}
    for r, (i, o) in enumerate(zip(items, origins)):
        if (i, o) not in cache:
            h = Y[max(0, o - 55): o + 1, i]
            cache[(i, o)] = (B.naive_last(h), B.seasonal_naive(h), B.trailing_mean(h))
        a, b, c = cache[(i, o)]
        k = horizons[r] - 1
        res["naive_last"][r], res["seasonal_naive_7"][r], res["trailing_mean_28"][r] = a[k], b[k], c[k]
    return res


def lgb_fit(cfg, params, Xtr, ytr, Xva, yva):
    p = {**cfg["lightgbm"]["fixed"], **params, "random_state": cfg["seed"]}
    m = lgb.LGBMRegressor(**p)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], eval_metric="l1",
          callbacks=[lgb.early_stopping(cfg["lightgbm"]["early_stopping_rounds"], verbose=False)])
    return m


def bucket_metrics(y, preds: dict, h):
    out = {}
    for name, (lo, hi) in BUCKETS.items():
        m = (h >= lo) & (h <= hi)
        out[name] = {k: M.summary(y[m], v[m]) for k, v in preds.items()}
    return out


def bootstrap_rel_improvement(y, a, b, groups, n_boot=500, seed=0):
    """95% CI of (WAPE_b - WAPE_a)/WAPE_b by resampling (series, origin) groups. Positive = model a better than b."""
    rng = np.random.default_rng(seed)
    _, inv = np.unique(groups, return_inverse=True)
    G = inv.max() + 1
    ea, eb, ya = (np.bincount(inv, weights=w, minlength=G) for w in (np.abs(y - a), np.abs(y - b), np.abs(y)))
    vals = []
    for _ in range(n_boot):
        s = rng.integers(0, G, G)
        vals.append((eb[s].sum() - ea[s].sum()) / eb[s].sum())
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--config", default=C.ML_DIR / "configs" / "forecast.json", type=Path)
    ap.add_argument("--out-root", default=C.ML_DIR / "artifacts", type=Path)
    ap.add_argument("--reports", default=C.ML_DIR / "reports", type=Path)
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text())
    rng = np.random.default_rng(cfg["seed"])
    t_all = time.time()

    Y, items, prov = C.load_isomorph_demand(a.data_dir)
    T, nI = Y.shape
    sp = C.chronological_split(T, cfg["split"]["train"], cfg["split"]["val"])
    print(f"data {Y.shape}; split {sp}")

    # ---- training / validation samples (labels strictly inside their own segment)
    tr = C.sample_triples(rng, nI, *sp["train"][:1], sp["train"][1], cfg["sampling"]["train_rows"])
    va = C.sample_triples(rng, nI, sp["val"][0], sp["val"][1], cfg["sampling"]["val_rows"])
    Xtr, _, ytr = F.build(Y, *tr, with_target=True)
    Xva, sva, yva = F.build(Y, *va, with_target=True)
    assert (tr[1] + tr[2]).max() < sp["val"][0] and (va[1] + va[2]).min() >= sp["val"][0]   # no label leakage across split

    # ---- LightGBM grid, selected on validation WAPE (units)
    grid, results = [], []
    for nl in cfg["lightgbm"]["grid"]["num_leaves"]:
        for obj in cfg["lightgbm"]["grid"]["objective"]:
            t0 = time.time()
            m = lgb_fit(cfg, {"num_leaves": nl, "objective": obj}, Xtr, ytr, Xva, yva)
            pv = np.maximum(m.predict(Xva), 0) * sva
            w = M.wape(yva * sva, pv)
            results.append({"num_leaves": nl, "objective": obj, "best_iteration": int(m.best_iteration_ or m.n_estimators),
                            "val_wape": w, "val_mae": M.mae(yva * sva, pv), "fit_seconds": round(time.time() - t0, 1)})
            grid.append((w, m, results[-1]))
            print(results[-1])
    best_w, best_m, best_cfg = min(grid, key=lambda g: g[0])
    train_seconds = best_cfg["fit_seconds"]

    # ---- random-forest challenger (same features; same split; fixed config)
    sub = rng.choice(len(ytr), min(cfg["sampling"]["rf_train_rows"], len(ytr)), replace=False)
    t0 = time.time()
    rf = RandomForestRegressor(**cfg["random_forest"], random_state=cfg["seed"]).fit(Xtr[sub], ytr[sub])
    rf_seconds = time.time() - t0
    rf_val_wape = M.wape(yva * sva, np.maximum(rf.predict(Xva), 0) * sva)

    # ---- interval calibration on validation residuals (ratio space, per horizon)
    pr_val = np.maximum(best_m.predict(Xva), 0)
    lvl = cfg["interval"]["level"]
    q_lo, q_hi = [], []
    for h in range(1, F.MAX_HORIZON + 1):
        r = (yva - pr_val)[va[2] == h]
        q_lo.append(float(np.quantile(r, (1 - lvl) / 2)))
        q_hi.append(float(np.quantile(r, 1 - (1 - lvl) / 2)))

    # ---- held-out TEST evaluation (once)
    items_t, o_t, h_t = C.test_grid(T, sp["test"][0], nI, cfg["sampling"]["test_origin_stride"])
    Xte, ste, yte_r = F.build(Y, items_t, o_t, h_t, with_target=True)
    y = yte_r * ste
    preds = {"lightgbm": np.maximum(best_m.predict(Xte), 0) * ste, "random_forest": np.maximum(rf.predict(Xte), 0) * ste}
    t0 = time.time()
    preds["statistical_ewma (existing)"] = stat_predictions(Y, items_t, o_t, h_t, cfg["statistical_window_days"])
    stat_seconds = time.time() - t0
    preds.update(baseline_predictions(Y, items_t, o_t, h_t))
    overall = {k: M.summary(y, v) for k, v in preds.items()}
    buckets = bucket_metrics(y, preds, h_t)
    per_h = {int(h): {k: M.wape(y[h_t == h], v[h_t == h]) for k, v in preds.items()} for h in (1, 3, 7, 14, 21, 30)}
    best_base = min((k for k in preds if k not in ("lightgbm", "random_forest")), key=lambda k: overall[k]["wape"])
    groups = items_t * 10_000_000 + o_t
    ci = {name: bootstrap_rel_improvement(y, preds["lightgbm"], preds[name], groups) for name in preds if name != "lightgbm"}
    per_item = {items[i]: {"lightgbm": M.summary(y[items_t == i], preds["lightgbm"][items_t == i]),
                           best_base: M.summary(y[items_t == i], preds[best_base][items_t == i])} for i in range(nI)}
    wins = sum(per_item[i]["lightgbm"]["wape"] < per_item[i][best_base]["wape"] for i in per_item)

    # interval coverage on test (ratio-space quantiles, same for every series)
    lo = np.maximum(preds["lightgbm"] + np.array(q_lo)[h_t - 1] * ste, 0)
    hi = preds["lightgbm"] + np.array(q_hi)[h_t - 1] * ste
    coverage = {"nominal": lvl, "test_overall": M.interval_coverage(y, lo, hi),
                **{b: M.interval_coverage(y[(h_t >= l) & (h_t <= u)], lo[(h_t >= l) & (h_t <= u)], hi[(h_t >= l) & (h_t <= u)])
                   for b, (l, u) in BUCKETS.items()}}

    # ---- resource measurements
    hist = Y[:, 0][: sp["test"][0] + 200]
    Xs, _ = F.build_single(hist, F.MAX_HORIZON)
    lat = []
    for _ in range(200):
        t0 = time.perf_counter(); best_m.booster_.predict(Xs, num_threads=1); lat.append((time.perf_counter() - t0) * 1000)
    resources = {"train_seconds_best_config": train_seconds, "grid_total_seconds": round(sum(r["fit_seconds"] for r in results), 1),
                 "rf_train_seconds": round(rf_seconds, 1), "statistical_eval_seconds_for_test_grid": round(stat_seconds, 1),
                 "lightgbm_latency_ms_30_horizons_median": round(float(np.median(lat)), 3),
                 "lightgbm_latency_ms_p95": round(float(np.percentile(lat, 95)), 3), "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
                 "train_rows": int(len(ytr)), "cpu": f"{platform.processor() or platform.machine()} (1 thread used)"}

    # ---- artefact
    out = a.out_root / "forecast" / a.version
    out.mkdir(parents=True, exist_ok=True)
    best_m.booster_.save_model(str(out / "model.txt"))
    resources["model_file_kb"] = round((out / "model.txt").stat().st_size / 1024, 1)
    meta = {
        "kind": "demand_forecast", "model_name": "lightgbm-direct-multihorizon", "version": a.version, "schema_version": F.SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "feature_names": F.FEATURE_NAMES,
        "max_horizon": F.MAX_HORIZON, "min_history_days": F.MIN_HISTORY,
        "model_sha256": sha256_file(out / "model.txt"), "hyperparameters": best_cfg,
        "libraries": {"lightgbm": lgb.__version__, "numpy": np.__version__, "scikit-learn": sklearn.__version__, "python": platform.python_version()},
        "training_data": {**prov, "target": "daily_records.demand (observed Poisson counts), NOT demand_signals.npy (latent intensity)",
                          "split_days": {k: list(v) for k, v in sp.items()}, "seed": cfg["seed"], "config": cfg},
        "interval": {"level": lvl, "method": "empirical per-horizon quantiles of validation residuals in scale-free ratio space",
                     "ratio_lo": q_lo, "ratio_hi": q_hi, "test_coverage": coverage},
        "benchmark_test_metrics": {"overall": overall, "best_baseline": best_base},
        "applicability": ("Scale-free model trained on a simulator-generated benchmark. Valid inputs: >=28 days of non-negative daily demand "
                          "with a mean >= 1 unit/day and few zero days. Its accuracy on any other system is NOT established by this benchmark."),
        "promotion": {"status": "pending", "note": "set by ml/evaluate_app_series.py"},
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    (a.out_root / "forecast" / "CURRENT").write_text(a.version + "\n")

    report = {"generated_utc": meta["created_utc"], "data": {"shape": [T, nI], "split": sp, "provenance": prov},
              "validation_grid": results, "selected": best_cfg, "random_forest_val_wape": rf_val_wape,
              "test": {"origins_stride": cfg["sampling"]["test_origin_stride"], "n_rows": int(len(y)), "overall": overall, "by_horizon_bucket": buckets,
                       "wape_by_horizon": per_h, "best_baseline": best_base,
                       "rel_wape_improvement_vs_baseline_95ci": ci, "per_item": per_item,
                       "items_where_lightgbm_beats_best_baseline": f"{wins}/{nI}", "interval_coverage": coverage},
              "resources": resources}
    a.reports.mkdir(exist_ok=True)
    (a.reports / "forecast_benchmark_eval.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"overall_wape": {k: round(v["wape"], 4) for k, v in overall.items()}, "coverage": coverage,
                      "ci_vs_baselines": ci, "wins": report["test"]["items_where_lightgbm_beats_best_baseline"], "resources": resources}, indent=2))
    print(f"total {time.time() - t_all:.0f}s")


if __name__ == "__main__":
    main()

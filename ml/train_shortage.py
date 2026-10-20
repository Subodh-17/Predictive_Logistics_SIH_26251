"""Train and evaluate the 7-day shortage-onset risk model on the ISOMORPH benchmark (destination node).

Target: y(t) = 1 if new_backlog_today > 0 on any of days t+1..t+7. Population: item-days with backlog == 0 at t (onset); an
all-days view is also reported because persistence (existing backlog) trivially predicts continued shortage.

Chronological split with purging (labels reach 7 days ahead, so origins within 7 days of a boundary are dropped). Validation is split
in two chronological halves: the first half selects hyper-parameters / early-stops, the second half fits the isotonic calibrator and the
operating threshold. Test is evaluated once.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.preprocessing import StandardScaler

import common as C
from app.ml import metrics as M, shortage as S
from app.ml.artifacts import sha256_file


def make_labels(nb: np.ndarray, H: int) -> np.ndarray:
    """y[t, i] = any(nb[t+1..t+H, i] > 0); rows without a full look-ahead window are NaN."""
    T = nb.shape[0]
    ev = np.zeros(nb.shape, bool)
    for h in range(1, H + 1):
        ev[:T - h] |= nb[h:] > 0
    y = ev.astype(float)
    y[T - H:] = np.nan
    return y


def cls_metrics(y, p, thr=None) -> dict:
    out = {"n": int(len(y)), "positives": int(y.sum()), "base_rate": float(y.mean()),
           "roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
           "brier": M.brier(y, p), "ece": M.expected_calibration_error(y, p)}
    if thr is not None:
        pred = p >= thr
        tp = float((pred & (y == 1)).sum())
        out.update({"threshold": float(thr), "precision": tp / max(pred.sum(), 1), "recall": tp / max(y.sum(), 1),
                    "flag_rate": float(pred.mean())})
        out["f1"] = 2 * out["precision"] * out["recall"] / max(out["precision"] + out["recall"], 1e-12)
    return out


def best_f1_threshold(y, p) -> float:
    pr, rc, th = precision_recall_curve(y, p)
    f1 = 2 * pr[:-1] * rc[:-1] / np.maximum(pr[:-1] + rc[:-1], 1e-12)
    return float(th[int(np.nanargmax(f1))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--config", default=C.ML_DIR / "configs" / "shortage.json", type=Path)
    ap.add_argument("--out-root", default=C.ML_DIR / "artifacts", type=Path)
    ap.add_argument("--reports", default=C.ML_DIR / "reports", type=Path)
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text())
    rng = np.random.default_rng(cfg["seed"])
    H = cfg["horizon_days"]

    st, items, prov = C.load_destination_state(a.data_dir)
    T, nI = st["demand"].shape
    y_all = make_labels(st["new_backlog"], H)
    sp = C.chronological_split(T, cfg["split"]["train"], cfg["split"]["val"])
    a0, b0 = sp["val"][0], sp["val"][1]
    mid = a0 + int((b0 - a0) * cfg["split"]["val_calibration_fraction"])
    segs = {"train": (S.WINDOW - 1, a0 - H), "val_select": (a0, mid - H), "val_calib": (mid, b0 - H), "test": (b0, T - H)}   # purged origin ranges

    def collect(lo, hi, onset_only=True):
        t = np.arange(lo, hi)
        ii, tt = np.meshgrid(np.arange(nI), t, indexing="ij")
        ii, tt = ii.ravel(), tt.ravel()
        if onset_only:
            keep = st["backlog"][tt, ii] == 0
            ii, tt = ii[keep], tt[keep]
        return ii, tt

    def mats(name, onset_only=True, limit=None):
        ii, tt = collect(*segs[name], onset_only)
        if limit and len(ii) > limit:
            s = rng.choice(len(ii), limit, replace=False)
            ii, tt = ii[s], tt[s]
        X = S.build(st["demand"], st["on_hand"], st["backlog"], st["in_transit"], st["new_backlog"], ii, tt)
        return X, y_all[tt, ii], ii, tt

    Xtr, ytr, _, ttr = mats("train", limit=cfg["sampling"]["train_rows"])
    Xvs, yvs, _, _ = mats("val_select")
    Xvc, yvc, _, _ = mats("val_calib")
    Xte, yte, ite, tte = mats("test")
    assert ttr.max() + H < a0                              # no training label reaches the validation segment
    print({"train": Xtr.shape, "val_select": Xvs.shape, "val_calib": Xvc.shape, "test": Xte.shape,
           "pos_rate": {"train": ytr.mean(), "val_select": yvs.mean(), "val_calib": yvc.mean(), "test": yte.mean()}})

    # ---- candidates
    results, fits = [], []
    for nl in cfg["lightgbm"]["grid"]["num_leaves"]:
        t0 = time.time()
        m = lgb.LGBMClassifier(**cfg["lightgbm"]["fixed"], num_leaves=nl, random_state=cfg["seed"])
        m.fit(Xtr, ytr, eval_set=[(Xvs, yvs)], eval_metric="average_precision",
              callbacks=[lgb.early_stopping(cfg["lightgbm"]["early_stopping_rounds"], verbose=False)])
        pr = average_precision_score(yvs, m.predict_proba(Xvs)[:, 1])
        results.append({"num_leaves": nl, "best_iteration": int(m.best_iteration_ or m.n_estimators), "val_pr_auc": float(pr), "fit_seconds": round(time.time() - t0, 1)})
        fits.append((pr, m))
        print(results[-1])
    _, best = max(fits, key=lambda f: f[0])
    best_cfg = max(results, key=lambda r: r["val_pr_auc"])

    # stock-only variant (what an operator with only on-hand + demand would have)
    cols_so = [S.FEATURE_NAMES.index(c) for c in S.STOCK_ONLY]
    so = lgb.LGBMClassifier(**cfg["lightgbm"]["fixed"], num_leaves=best_cfg["num_leaves"], random_state=cfg["seed"])
    so.fit(Xtr[:, cols_so], ytr, eval_set=[(Xvs[:, cols_so], yvs)], eval_metric="average_precision",
           callbacks=[lgb.early_stopping(cfg["lightgbm"]["early_stopping_rounds"], verbose=False)])

    # logistic regression (all features) and cover-days-only baseline
    sc = StandardScaler().fit(Xtr)
    lr = LogisticRegression(max_iter=1000, C=1.0).fit(sc.transform(Xtr), ytr)
    c0 = S.FEATURE_NAMES.index("cover_days_28")
    lr_cover = LogisticRegression(max_iter=500).fit(Xtr[:, [c0]], ytr)
    base_rate = float(ytr.mean())

    # ---- calibration + operating point on val_calib only
    raw_vc = best.predict_proba(Xvc)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(raw_vc, yvc)
    cal = lambda raw: np.clip(np.interp(raw, iso.X_thresholds_, iso.y_thresholds_), 0, 1)
    thr = best_f1_threshold(yvc, cal(raw_vc))

    def pred_all(X):
        return {"lightgbm_calibrated": cal(best.predict_proba(X)[:, 1]), "lightgbm_uncalibrated": best.predict_proba(X)[:, 1],
                "lightgbm_stock_only": so.predict_proba(X[:, cols_so])[:, 1], "logistic_regression": lr.predict_proba(sc.transform(X))[:, 1],
                "cover_days_rule_logistic": lr_cover.predict_proba(X[:, [c0]])[:, 1],
                "constant_base_rate": np.full(len(X), base_rate)}

    P_te = pred_all(Xte)
    test = {}
    for k, p in P_te.items():
        if k == "constant_base_rate":
            test[k] = {"n": int(len(yte)), "positives": int(yte.sum()), "base_rate": float(yte.mean()), "roc_auc": 0.5, "pr_auc": float(yte.mean()),
                       "brier": M.brier(yte, p), "ece": M.expected_calibration_error(yte, p)}
        else:
            test[k] = cls_metrics(yte, p, thr if k == "lightgbm_calibrated" else None)

    # all-days view incl. persistence baseline
    ii_a, tt_a = collect(*segs["test"], onset_only=False)
    Xa = S.build(st["demand"], st["on_hand"], st["backlog"], st["in_transit"], st["new_backlog"], ii_a, tt_a)
    ya = y_all[tt_a, ii_a]
    pa = np.where(st["backlog"][tt_a, ii_a] > 0, 0.978, cal(best.predict_proba(Xa)[:, 1]))  # model applied to onset rows only
    persistence = (st["backlog"][tt_a, ii_a] > 0).astype(float)
    all_days = {"persistence_backlog_gt_0": {k: v for k, v in cls_metrics(ya, persistence, 0.5).items()},
                "n": int(len(ya)), "base_rate": float(ya.mean()),
                "share_of_positive_days_that_are_onset": float(ya[st["backlog"][tt_a, ii_a] == 0].sum() / ya.sum())}

    # reliability table (test, calibrated)
    p = P_te["lightgbm_calibrated"]
    edges = np.quantile(p, np.linspace(0, 1, 11))
    bins = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, 9)
    reliability = [{"bin": b, "mean_predicted": float(p[bins == b].mean()), "observed_rate": float(yte[bins == b].mean()), "n": int((bins == b).sum())}
                   for b in range(10) if (bins == b).any()]
    imp = dict(sorted(zip(S.FEATURE_NAMES, map(int, best.booster_.feature_importance("gain"))), key=lambda kv: -kv[1]))

    out = a.out_root / "shortage" / a.version
    out.mkdir(parents=True, exist_ok=True)
    best.booster_.save_model(str(out / "model.txt"))
    meta = {"kind": "shortage_risk", "model_name": "lightgbm-shortage-onset-7d", "version": a.version, "shortage_schema": S.SHORTAGE_SCHEMA, "schema_version": S.SHORTAGE_SCHEMA,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "feature_names": S.FEATURE_NAMES, "horizon_days": H,
            "target": "any new_backlog_today > 0 on days t+1..t+7 at the destination node; population = item-days with backlog == 0 at t",
            "model_sha256": sha256_file(out / "model.txt"), "hyperparameters": best_cfg,
            "calibration": {"method": "isotonic regression fitted on the second half of validation", "x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]},
            "operating_point": {"threshold": thr, "rule": "maximises F1 on the calibration half of validation"},
            "libraries": {"lightgbm": lgb.__version__, "python": platform.python_version()},
            "training_data": {**prov, "split_origin_ranges": {k: list(v) for k, v in segs.items()}, "seed": cfg["seed"], "config": cfg},
            "benchmark_test_metrics": test,
            "applicability": ("Benchmark-only. Requires >=28 days of demand, on-hand, in-transit and new-backlog history per item at the node, "
                              "and is defined for shortage onset (no backlog today). Probabilities are calibrated to the ISOMORPH replenishment policy and "
                              "must not be read as probabilities for any other supply system.")}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    (a.out_root / "shortage" / "CURRENT").write_text(a.version + "\n")
    report = {"generated_utc": meta["created_utc"], "horizon_days": H, "split_origin_ranges": {k: list(v) for k, v in segs.items()},
              "label_definition": meta["target"], "validation_grid": results, "selected": best_cfg, "operating_point": meta["operating_point"],
              "test_onset_population": test, "test_all_days_context": all_days, "reliability_test": reliability, "feature_gain_importance": imp,
              "stock_only_note": "lightgbm_stock_only uses only on-hand cover and demand statistics (no backlog / pipeline / shortage history)"}
    (a.reports / "shortage_benchmark_eval.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"test": {k: {m: round(v[m], 4) for m in ("roc_auc", "pr_auc", "brier", "ece")} for k, v in test.items()}, "base_rate": float(yte.mean()),
                      "all_days": all_days, "thr": thr, "imp": imp}, indent=2))


if __name__ == "__main__":
    main()

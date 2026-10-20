"""Render ml/reports/EVALUATION_REPORT.md from the measured JSON reports (no number is typed by hand).

    python ml/make_report_md.py
"""
import json
from pathlib import Path

R = Path(__file__).resolve().parent / "reports"
J = lambda n: json.loads((R / n).read_text())
pc = lambda v, d=2: f"{v * 100:.{d}f}%"
NAME = {"lightgbm": "Trained LightGBM", "random_forest": "Random Forest (same features)", "statistical_ewma (existing)": "Statistical EWMA (existing model)", "naive_last": "Last value",
        "seasonal_naive_7": "Seasonal naive (7 d)", "trailing_mean_28": "Trailing 28-day mean", "ml_plain": "Trained model (plain)", "ml_weather_adapter": "Trained model + weather adapter",
        "lightgbm_calibrated": "LightGBM (calibrated)", "lightgbm_uncalibrated": "LightGBM (uncalibrated)", "lightgbm_stock_only": "LightGBM, stock-only inputs",
        "logistic_regression": "Logistic regression", "cover_days_rule_logistic": "Days-of-cover rule (calibrated)", "constant_base_rate": "Constant base rate"}


def main():
    b, s, h, c = J("forecast_benchmark_eval.json"), J("forecast_scenario_eval.json"), J("shortage_benchmark_eval.json"), J("supply_csv_profile.json")
    t, o = b["test"], b["test"]["overall"]
    L = ["# Evaluation report (generated from ml/reports/*.json)", "",
         "> ISOMORPH is a simulator-generated research benchmark (CC-BY-4.0). These numbers describe performance on that benchmark and on this application's illustrative scenario; they are not evidence of accuracy on real operations.", "",
         "## 1. Demand forecast - ISOMORPH benchmark, chronological test split (evaluated once)", "",
         f"Data: {b['data']['shape'][0]:,} days x {b['data']['shape'][1]} items; train days {b['data']['split']['train']}, validation {b['data']['split']['val']}, test {b['data']['split']['test']}. "
         f"Test rows: {t['n_rows']:,} (every item, origins {t['origins_stride']} days apart, horizons 1-30).", "",
         "| Model | WAPE | MAE | RMSE | Bias | WAPE d1-7 | d8-14 | d15-30 |", "|---|---|---|---|---|---|---|---|"]
    for k, v in o.items():
        L.append(f"| {NAME.get(k, k)} | {pc(v['wape'])} | {v['mae']:.2f} | {v['rmse']:.2f} | {pc(v['bias'])} | " + " | ".join(pc(t["by_horizon_bucket"][x][k]["wape"]) for x in ("h01_07", "h08_14", "h15_30")) + " |")
    bb = t["best_baseline"]; ci = t["rel_wape_improvement_vs_baseline_95ci"]
    L += ["", f"Best simple baseline: **{NAME.get(bb, bb)}**. Relative WAPE improvement of the trained model vs each reference (95% bootstrap CI over series-origin groups):", ""]
    L += [f"- vs {NAME.get(k, k)}: {pc(v[0], 1)} to {pc(v[1], 1)}" for k, v in ci.items()]
    cov = t["interval_coverage"]
    L += ["", f"Items where the trained model beats the best baseline: {t['items_where_lightgbm_beats_best_baseline']}. 80% interval coverage on test: {pc(cov['test_overall'], 1)} (d1-7 {pc(cov['h01_07'], 1)}, d8-14 {pc(cov['h08_14'], 1)}, d15-30 {pc(cov['h15_30'], 1)}).",
          f"Selected hyper-parameters: {b['selected']}.", "", "Resources (1 CPU thread): " + ", ".join(f"{k}={v}" for k, v in b["resources"].items()), "",
          "Metric definitions: WAPE = sum|y-f| / sum|y| (NaN if sum|y| = 0); MAPE excludes zero actuals and reports how many; bias = sum(f-y)/sum|y|. The existing statistical model was run on the benchmark with its weather term disabled (no weather series exists).", "",
          "## 2. Same models on the application's illustrative scenario (rolling-origin holdout)", "", f"{s['protocol']['series']} series, {s['protocol']['rows']:,} forecast rows, origins {s['protocol']['origins'][0]}..{s['protocol']['origins'][-1]}. {s['protocol']['note']}.", "",
          "| Model | WAPE d1-30 | WAPE d1-14 | MAE | RMSE |", "|---|---|---|---|---|"]
    for k, v in s["overall"].items():
        L.append(f"| {NAME.get(k, k)} | {pc(v['wape'])} | {pc(s['by_horizon_bucket']['h01_14'][k]['wape'])} | {v['mae']:.2f} | {v['rmse']:.2f} |")
    p = s["promotion"]
    L += ["", f"**Promotion decision: {p['status']}.** {p['reason'] or 'All criteria met.'}", "", "Interval coverage (nominal 80%): " + "; ".join(f"{k}: " + ", ".join(f"{a}={pc(x, 1)}" for a, x in v.items() if a != 'nominal') for k, v in s["interval_coverage"].items()), "",
          "## 3. Shortage-onset risk - ISOMORPH benchmark (7 days ahead, destination node, item-days with no backlog)", "", f"Target: {h['label_definition']}.", "",
          "| Model | Base rate | ROC-AUC | PR-AUC | Brier | ECE |", "|---|---|---|---|---|---|"]
    for k, v in h["test_onset_population"].items():
        L.append(f"| {NAME.get(k, k)} | {pc(v['base_rate'])} | {v['roc_auc']:.3f} | {v['pr_auc']:.3f} | {v['brier']:.4f} | {v['ece']:.4f} |")
    cal = h["test_onset_population"]["lightgbm_calibrated"]
    L += ["", f"Operating point (maximises F1 on the calibration half of validation): threshold {h['operating_point']['threshold']:.3f} -> precision {pc(cal['precision'], 1)}, recall {pc(cal['recall'], 1)} on test.",
          f"Only {pc(h['test_all_days_context']['share_of_positive_days_that_are_onset'], 0)} of shortage-risk days are onsets; continuing backlogs are predicted by persistence alone.",
          "Gain importance (top): " + ", ".join(f"{k}={v}" for k, v in list(h["feature_gain_importance"].items())[:4]) + ".",
          "Interpretation: the strong score is driven by the in-transit pipeline, i.e. by the simulator's deterministic replenishment policy. With stock-only inputs the model is no better than a calibrated days-of-cover rule. This does not transfer to any system whose replenishment policy differs.", "",
          "## 4. Supply optimisation CSV", "", f"{c['rows']:,} rows. {c['conclusion']}", ""]
    (R / "EVALUATION_REPORT.md").write_text("\n".join(L))
    print("wrote", R / "EVALUATION_REPORT.md")


if __name__ == "__main__":
    main()

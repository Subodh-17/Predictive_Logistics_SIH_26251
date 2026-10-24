# Evaluation report (generated from ml/reports/*.json)

> ISOMORPH is a simulator-generated research benchmark (CC-BY-4.0). These numbers describe performance on that benchmark and on this application's illustrative scenario; they are not evidence of accuracy on real operations.

## 1. Demand forecast - ISOMORPH benchmark, chronological test split (evaluated once)

Data: 52,560 days x 50 items; train days [0, 36792], validation [36792, 44676], test [44676, 52560]. Test rows: 907,500 (every item, origins 13 days apart, horizons 1-30).

| Model | WAPE | MAE | RMSE | Bias | WAPE d1-7 | d8-14 | d15-30 |
|---|---|---|---|---|---|---|---|
| Trained LightGBM | 9.32% | 15.27 | 20.80 | -0.34% | 7.47% | 8.52% | 10.48% |
| Random Forest (same features) | 9.43% | 15.45 | 21.03 | 0.27% | 7.60% | 8.59% | 10.59% |
| Statistical EWMA (existing model) | 11.83% | 19.39 | 25.99 | -1.10% | 9.55% | 10.67% | 13.34% |
| Last value | 11.87% | 19.45 | 25.68 | -0.06% | 10.37% | 11.15% | 12.83% |
| Seasonal naive (7 d) | 11.12% | 18.23 | 24.46 | -0.07% | 9.22% | 10.25% | 12.34% |
| Trailing 28-day mean | 11.76% | 19.28 | 26.12 | -0.12% | 9.49% | 10.81% | 13.18% |

Best simple baseline: **Seasonal naive (7 d)**. Relative WAPE improvement of the trained model vs each reference (95% bootstrap CI over series-origin groups):

- vs Random Forest (same features): 1.1% to 1.2%
- vs Statistical EWMA (existing model): 21.0% to 21.5%
- vs Last value: 21.1% to 21.8%
- vs Seasonal naive (7 d): 16.0% to 16.4%
- vs Trailing 28-day mean: 20.4% to 21.1%

Items where the trained model beats the best baseline: 50/50. 80% interval coverage on test: 80.9% (d1-7 81.2%, d8-14 81.1%, d15-30 80.7%).
Selected hyper-parameters: {'num_leaves': 31, 'objective': 'regression_l1', 'best_iteration': 1078, 'val_wape': 0.0948949688672366, 'val_mae': 14.995282419824138, 'fit_seconds': 51.8}.

Resources (1 CPU thread): train_seconds_best_config=51.8, grid_total_seconds=207.2, rf_train_seconds=155.3, statistical_eval_seconds_for_test_grid=3.5, lightgbm_latency_ms_30_horizons_median=1.473, lightgbm_latency_ms_p95=1.745, peak_rss_mb=1013, train_rows=400000, cpu=x86_64 (1 thread used), model_file_kb=3188.0

Metric definitions: WAPE = sum|y-f| / sum|y| (NaN if sum|y| = 0); MAPE excludes zero actuals and reports how many; bias = sum(f-y)/sum|y|. The existing statistical model was run on the benchmark with its weather term disabled (no weather series exists).

## 2. Same models on the application's illustrative scenario (rolling-origin holdout)

50 series, 21,000 forecast rows, origins 40..79. scenario history is generated from the statistical model's own structure (weather x weekly x trend); it favours that model.

| Model | WAPE d1-30 | WAPE d1-14 | MAE | RMSE |
|---|---|---|---|---|
| Statistical EWMA (existing model) | 4.62% | 4.00% | 15.90 | 28.25 |
| Trained model (plain) | 7.87% | 6.33% | 27.07 | 55.05 |
| Trained model + weather adapter | 4.91% | 4.34% | 16.89 | 30.46 |
| Last value | 9.65% | 8.91% | 33.21 | 60.93 |
| Seasonal naive (7 d) | 7.43% | 6.61% | 25.56 | 50.37 |
| Trailing 28-day mean | 8.13% | 7.83% | 27.97 | 52.37 |

**Promotion decision: not_promoted.** scenario holdout h1-14: ml_weather_adapter WAPE 4.34% vs statistical 4.00% (relative improvement -8.5%, 95% CI -11.0..-6.2%); need >= +2% with CI above 0; series-level interval coverage 99.9% outside 70-90%

Interval coverage (nominal 80%): ml_plain: series_level=95.6%, by_location_aggregate=59.1%, by_supply_aggregate=76.7%, all_series_aggregate=28.3%; ml_weather_adapter: series_level=99.9%, by_location_aggregate=90.9%, by_supply_aggregate=94.6%, all_series_aggregate=57.6%

## 3. Shortage-onset risk - ISOMORPH benchmark (7 days ahead, destination node, item-days with no backlog)

Target: any new_backlog_today > 0 on days t+1..t+7 at the destination node; population = item-days with backlog == 0 at t.

| Model | Base rate | ROC-AUC | PR-AUC | Brier | ECE |
|---|---|---|---|---|---|
| LightGBM (calibrated) | 1.33% | 0.988 | 0.883 | 0.0027 | 0.0008 |
| LightGBM (uncalibrated) | 1.33% | 0.988 | 0.891 | 0.0041 | 0.0090 |
| LightGBM, stock-only inputs | 1.33% | 0.842 | 0.494 | 0.0096 | 0.0053 |
| Logistic regression | 1.33% | 0.989 | 0.858 | 0.0038 | 0.0017 |
| Days-of-cover rule (calibrated) | 1.33% | 0.858 | 0.457 | 0.0090 | 0.0031 |
| Constant base rate | 1.33% | 0.500 | 0.013 | 0.0131 | 0.0032 |

Operating point (maximises F1 on the calibration half of validation): threshold 0.625 -> precision 90.8%, recall 86.1% on test.
Only 29% of shortage-risk days are onsets; continuing backlogs are predicted by persistence alone.
Gain importance (top): in_transit_ratio=318597, cover_plus_pipeline_days=62740, days_since_shortage=17079, cover_days_28=9071.
Interpretation: the strong score is driven by the in-transit pipeline, i.e. by the simulator's deterministic replenishment policy. With stock-only inputs the model is no better than a calibrated days-of-cover rule. This does not transfer to any system whose replenishment policy differs.

## 4. Supply optimisation CSV

36,000 rows. Not suitable for training a demand-forecast, shortage or route-disruption model. There is no calendar year/date, no SKU/item identifier and no location identifier, so no time series can be formed. Every numeric column is consistent with an independent uniform draw over a fixed range (Quantity Sold is integer-valued, 450-599), the largest absolute pairwise correlation is about 0.01, no month effect survives a multiple-comparison correction (temperature has no seasonal cycle), and route distance is not stable within a route ID. These properties are typical of randomly generated tabular data and give no evidence of real-world provenance; the file documents no source or licence. It is therefore used only for schema validation/profiling, never for training or for any displayed metric.

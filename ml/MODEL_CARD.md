# Model card

## Demand forecast: `lightgbm-direct-multihorizon@v1`
* **Task**: forecast daily demand for days t+1..t+30 from >= 28 days of history.
* **Model**: LightGBM regressor (`regression_l1`, 31 leaves, 1,078 trees), direct multi-horizon (horizon is a feature), scale-free features. 3.2 MB text model; ~1.5 ms per series for 30 horizons on one CPU thread.
* **Training data**: ISOMORPH Sample (CC-BY-4.0), simulator-generated; first 70% of days, 400,000 sampled (item, origin, horizon) rows; seed 42.
* **Known application effects**: an optional adapter divides known multiplicative effects (weather) out of the history and re-applies them to the forecast; it is used only when the promotion metadata names it.
* **Measured**: see `reports/EVALUATION_REPORT.md`. Benchmark test WAPE 9.32% vs 11.12% best baseline; on the application scenario it is **not better** than the statistical model.
* **Intended use**: research benchmark comparison and opt-in forecasting for series that resemble the training distribution (counts, mean >= 1/day, few zeros).
* **Not valid for**: intermittent demand, series shorter than 28 days, any claim of accuracy on real operations, or anything outside the benchmark's dynamics. The trained interval is calibrated to the benchmark's Poisson noise; on the scenario it is over-wide per series (99.9% coverage at 80% nominal) and under-covers when aggregated, which is why the decision rule rejected it.

## Shortage-onset risk: `lightgbm-shortage-onset-7d@v1`
* **Task**: P(new backlog on any of the next 7 days | no backlog today) for one item at the destination node.
* **Inputs**: >= 28 days of demand, on-hand, in-transit and new-backlog history. Isotonic calibration; operating threshold maximises validation F1.
* **Limits**: benchmark-only. Scores are driven by in-transit visibility of the simulator's deterministic replenishment policy; probabilities are meaningless for other policies. Not used by the application's status classification.

## Not modelled
Route disruption / delay: no outcome labels exist in any supplied dataset, so no model was trained and none is claimed.

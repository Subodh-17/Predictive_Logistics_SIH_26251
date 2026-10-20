# Decision: the shortage-onset model is not connected to inventory status

## What the model predicts
A LightGBM classifier (artefact `ml/artifacts/shortage/v1`) trained on the ISOMORPH simulator benchmark. **Target:** a backlog *begins* within the next 7 days for one item at one node (no backlog today, backlog > 0 at some point in days +1..+7). **Inputs (only information available at prediction time):** the last 28 days of daily demand, on-hand stock, in-transit quantity, backlog and new backlog. **Output:** an isotonic-calibrated probability and a flag at an operating threshold chosen on validation data. The training report compares it with a days-of-cover rule and a constant base-rate predictor and reports PR-AUC, ROC-AUC, Brier score, calibration and a bootstrap interval (`ml/reports/shortage_benchmark_eval.json`; **not re-run in V6**, the benchmark data is not bundled).

## Why it is not wired into the application's status
The application's data model (`db/migrations`) holds a 110-day consumption history but **only the current stock level**: no daily on-hand history, no in-transit ledger and no backlog ledger. Three of the five required inputs do not exist and a fourth (on-hand history) could only be *reconstructed*. Feeding reconstructed or zero-filled series into the model would produce numbers that look like calibrated probabilities but have no relationship to its training distribution. V5's own documentation said the same; V6 re-inspected the code and data model and agrees.

## What V6 does instead
* Inventory status and predicted shortage stay **deterministic rules** over the validated demand forecast, and the UI explains them (`GET /api/inventory/risk-basis`, "How is this risk estimated?" on the Inventory page): source, 14-day horizon, thresholds, limitations, and that the trained model is not used.
* The model remains available for what it can honestly score: `POST /api/ml/shortage-risk` and the "Shortage-onset check" card on the Model Evaluation page score **one record the user supplies in benchmark format**. It reads no application data and changes no status.
* A test (`test_scenario_has_no_in_transit_or_backlog_tables`) fails if someone adds such tables to the schema, forcing this decision to be revisited deliberately; another asserts that status is unchanged when the model is unavailable.

## What would make integration valid
Record daily on-hand, in-transit and backlog per item and node for at least 28 days from a real or properly simulated ledger; re-define the target on that ledger; retrain and recalibrate; evaluate chronologically against the days-of-cover rule; only then connect it, with its horizon and limits shown next to every probability.

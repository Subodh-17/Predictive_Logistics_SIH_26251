# ML pipeline - demand forecasting and shortage-onset risk

Reproducible training, evaluation and artefact pipeline for the SIH PS 26251 application. Everything here is **measured, not asserted**:
results live in `reports/` (JSON + the generated `reports/EVALUATION_REPORT.md`).

> ISOMORPH is a **simulator-generated research benchmark**, not observed logistics operations. Benchmark scores are not evidence of accuracy on real operations.

## Layout

| Path | Purpose |
|---|---|
| `../backend/app/ml/` | Shared code used by training **and** the API: `features.py` (leakage-safe features), `metrics.py`, `baselines.py`, `artifacts.py` (safe loading), `forecaster.py`, `shortage.py` |
| `common.py` | Dataset loading + validation, chronological split, purged samplers, provenance |
| `train_forecast.py` | Candidate comparison on ISOMORPH, one-shot test evaluation, artefact export |
| `evaluate_app_series.py` | Rolling-origin holdout on the application's illustrative scenario + the pre-registered promotion decision |
| `train_shortage.py` | 7-day shortage-onset model on the ISOMORPH destination node |
| `profile_supply_csv.py` | Independent profile of `Dataset_AI_Supply_Optimization.csv` (never used for training) |
| `make_report_md.py` | Renders `reports/EVALUATION_REPORT.md` from the JSON reports |
| `configs/*.json` | Seeds, split fractions, sampling sizes, hyper-parameter grids |
| `artifacts/{forecast,shortage}/<version>/` | `model.txt` (LightGBM text format) + `metadata.json`; `CURRENT` names the active version |
| `DATA_CARD.md`, `MODEL_CARD.md` | Provenance, licences, limitations |
| `requirements-ml.txt` | Exact training environment (Python 3.12) |

## Retraining procedure

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r ml/requirements-ml.txt

# ISOMORPH_SAMPLE.zip extracted so that <DATA>/output_item50/daily_records.parquet exists
DATA=/path/to/isomorph

python ml/train_forecast.py   --data-dir "$DATA"              # ~7 min on 1 CPU thread, <1.5 GB RAM
python ml/evaluate_app_series.py                              # scenario holdout + promotion decision (writes it into metadata.json)
python ml/train_shortage.py   --data-dir "$DATA"              # ~2 min
python ml/profile_supply_csv.py --csv /path/to/Dataset_AI_Supply_Optimization.csv
python ml/make_report_md.py
pytest ml/tests backend/tests -p no:warnings                  # REQUIRE_DB=1 for the database-backed API tests
```

Order matters: `evaluate_app_series.py` reads the benchmark report written by `train_forecast.py`. Use `--version v2` to add a new artefact version
(then point `artifacts/forecast/CURRENT` at it); the old version stays loadable. Memory note: loading the ISOMORPH `inventory_history` / `backlog_history`
tables whole needs far more than 4 GB - the pipeline never does (destination state comes from `daily_records` and is verified identical to the NewYork rows).

## Protocol (no leakage, no test-set tuning)

1. **Target**: observed daily demand (`daily_records.demand`). `demand_signals.npy` is the simulator's *latent Poisson intensity* (non-integer; `mean((D-lambda)^2/lambda) = 1.00`), not observable demand, and is not used.
2. **Split**: chronological 70 / 15 / 15 of the 52,560 days. Training labels end before validation starts (purged by construction, asserted in code and tests); validation labels end before test starts.
3. **Features** (`app/ml/features.py`): 14 daily lags, 4 same-weekday lags, 7/14/28-day means, variability, trend ratios and the horizon - all relative to the 28-day mean, all from days <= origin. Unit tests change every future value and assert features are bit-identical.
4. **Selection**: LightGBM grid (leaves x objective) chosen on validation WAPE only. The test split is evaluated once. Random Forest is a fixed-config comparison.
5. **Intervals**: per-horizon 10/90% quantiles of validation residuals (scale-free); coverage measured on test.
6. **Promotion rule** (fixed before the scenario result was seen; in `evaluate_app_series.py`): the trained model drives the application (`FORECAST_MODEL_MODE=auto`) only if it (1) beats the statistical model on the scenario holdout by >= 2% relative WAPE (days 1-14) with the 95% CI above 0, (2) beats the best simple baseline on the benchmark test with the CI above 0, and (3) has series-level 80% interval coverage within 70-90%.
7. **Shortage target**: any `new_backlog_today > 0` on days t+1..t+7 for item-days with no backlog at t (onset). Calibration + threshold use a separate chronological half of validation.

Known weakness of the CIs: (item, origin) groups are resampled as if independent; overlapping 30-day windows and shared macro shocks make them somewhat optimistic.

## Reproducing the scenario evaluation without the benchmark data (V6)

`evaluate_app_series.py` needs only the application's own scenario and the shipped benchmark report, so it can be re-run anywhere:

```bash
cp -r ml/artifacts /tmp/arts && cp -r ml/reports /tmp/reps
PYTHONPATH=backend python ml/evaluate_app_series.py --artifacts /tmp/arts --reports /tmp/reps --no-promote
diff <(jq 'del(..|.generated_utc?, .decided_utc?)' ml/reports/forecast_scenario_eval.json) <(jq 'del(..|.generated_utc?, .decided_utc?)' /tmp/reps/forecast_scenario_eval.json)
```
In the V6 verification run the re-computed numbers were identical to the shipped report (scenario holdout, horizons 1-14: trained model with weather adapter 4.34% WAPE vs 4.00% for the statistical model; decision: not promoted). **The ISOMORPH benchmark evaluation itself (`train_forecast.py`, `train_shortage.py`) was not re-run in V6** because the dataset is not bundled and was not reachable; the benchmark figures in `reports/` are as produced for V5. Benchmark results come from a simulator and are not observations of any real operation.

## Integrity pins (V6)

The SHA-256 in `metadata.json` detects corruption only. To also detect a model file replaced together with its metadata, publish the digests out of band and set `ML_FORECAST_SHA256` / `ML_SHORTAGE_SHA256` (see `docs/CONFIGURATION.md`); the shipped digests are the `model_sha256` values in `artifacts/*/v1/metadata.json`. Symbolic links inside the artefact directory are refused.

## Run-time behaviour (API)

* The API only **loads** artefacts (SHA-256, schema version and feature list verified; text format, never pickle) - nothing is trained per request.
* `FORECAST_MODEL_MODE`: `auto` (default; follows the recorded promotion decision), `ml` (trained model whenever it loads), `statistical`.
* Missing/corrupt/incompatible artefact, missing `lightgbm`, an inference exception or exceeding `ML_RECOMPUTE_TIMEOUT_S` -> the whole forecast set is recomputed with the statistical model, the reason is stored and shown (`/api/ml/models`, Forecast page). A baseline result is never labelled as ML.
* Each stored forecast row records the model that produced it; changing the mode regenerates the rows on the next start / `POST /api/forecast/recompute`, and inventory, projections, alerts, priorities, allocation, simulation and dashboard all read the same rows.
* Series with < 1 unit/day mean or > 30% zero days in the last 28 days are ineligible for the trained model and use the statistical model (labelled per row).

## Result of the shipped run (see `reports/EVALUATION_REPORT.md` for all numbers)

* Benchmark test: trained LightGBM 9.32% WAPE vs 11.12% for the best simple baseline (seasonal naive) and 11.83% for the existing statistical model run without weather.
* Application scenario holdout: the existing statistical model wins (4.00% vs 4.34% for the trained model with the weather adapter, days 1-14). The scenario is generated from the statistical model's own structure, which favours it. **Promotion: not promoted**, so the default application forecast remains the statistical model; the trained model is available as an explicit opt-in and as a labelled preview on the Forecast page.
* Shortage onset (benchmark): ROC-AUC 0.988 / PR-AUC 0.883 (calibrated, base rate 1.3%), driven by in-transit visibility; stock-only inputs reach only the level of a calibrated days-of-cover rule. Not wired into the application's status because the scenario has no backlog / in-transit ledger.
* Not trained: route-disruption prediction - no historical outcome labels exist in any supplied dataset.

# Limitations and assumptions

## What the data is
Everything the application displays is a **fictional illustrative scenario with simulated telemetry**. It is not Indian Army data and nothing here has been validated against real operations. Public terrain, road or weather data are not used. The ISOMORPH benchmark (used only to train/evaluate the model artefacts) is simulator output about a US supply chain.

## Model assumptions
* Default forecaster: weather-adjusted EWMA + damped trend + weekly seasonality (deterministic). The trained LightGBM model is **not promoted** (scenario holdout h1-14: 4.34% vs 4.00% WAPE) and is shown only as a preview/challenger. The scenario history is generated from the statistical model's own structure, which favours it.
* Benchmark accuracy figures were not re-run in V7 and describe simulator data, not the application's data.
* Inventory risk is rule-based (days of supply thresholds, 14-day horizon). It is **not a probability** and the thresholds are not calibrated against real operations.
* The shortage-onset model cannot be fed by this application's data (no on-hand history, no in-transit or backlog ledger) and is not used for status.
* Priority-score weights are fixed documented assumptions (`GET /api/priority/weights`).

## Logistics assumptions
* **Feasible route** means: at least one vehicle is available at the serving depot **and** the corridor is not closed (weather risk below 0.85, reached only at maximum scenario severity on the most exposed corridor). Not modelled: escort and fuel limits, bridge/axle limits, time windows, driver hours, hostile action, cargo compatibility, road blockages other than the weather rule. Feasible means "feasible under these constraints", never "guaranteed".
* ETA = distance / effective speed; effective speed = nominal x (1 - 0.45 road) x (1 - 0.35 terrain risk) x (1 - 0.3 weather risk), floor 8 km/h. Fictional coefficients.
* Allocation is a greedy, priority-ordered heuristic, not an optimal solver. Vehicles serve only their own depot's corridors; one depot shipment per item is bounded by depot stock and the vehicles' remaining capacity; there is no multi-leg routing, no trip scheduling and no return loads.
* Backlog and in-transit inventory are not accounted for in the application (see above); replenishment quantities do not subtract stock already on its way.
* Scenario comparisons are only as fair as their starting state: the compare endpoint reports `same_baseline` and warns when stock changed between runs.
* The corridor-closure rule is a V7 addition and deliberately deviates from the original V3 calculations only at extreme weather severity (the V3 parity fixtures still pass).

## Deployment status (V7.1)
Docker image builds, `docker compose up` and persistence across container restarts were **not executed** (no Docker; image registries unreachable from the verification environment); the Compose design was validated by the compose-spec schema, hadolint, tests and an equivalent non-container stack. Render was not deployed. On Render the API runs as the database owner unless a second role is created by hand, and the correct proxy range for per-client rate limits is unknown. See `DEPLOYMENT.md`.

## Security and operations
Single-tenant (no organisation isolation). No MFA, password recovery, encryption at rest, independent security review or penetration test. Rate limits and lock-outs are per process. Map tiles come from a third-party host unless removed. Docker images, Render deployment and hosted TLS were not executed in the verification environment. No backups or restore procedure is provided. Only headless Chromium was used for browser tests; no screen-reader sessions.

## Interface
The bundle is a single ~0.84 MB chunk. Tile imagery could not be loaded in the test sandbox, so map imagery was never visually verified (markers, routes and layout were). The What-If, forecast and map pages are English-only.

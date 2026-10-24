# Changes from V6 to V7

Built on the delivered V6 archive. Baseline before editing: the extracted V6 ZIP passed 389/389 backend tests and 14/14 ML tests; Docker was unavailable.

## Correctness and logistics
| Change | Why | Evidence |
|---|---|---|
| Route feasibility now also requires an **open corridor** (weather risk < 0.85); responses carry `blocked_reason` (`ROUTE CLOSED` / `NO AVAILABLE VEHICLE`); UI and explanations show it | V6 treated any corridor with an available vehicle as usable even in a storm (the speed model has an 8 km/h floor) | `test_logistics_integrity.py`; V3 parity tests unchanged |
| Optional **idempotency key** (`event_id`) for inventory events, migration `0004`, HTTP 409 on duplicates | Duplicate/retried requests were applied twice | duplicate and concurrent-duplicate tests |
| Concurrency and ledger tests: no lost updates under 6 concurrent writers, ledger chain consistency (`stock_before` = previous `stock_after`), clipping reported | requirement: concurrent updates, inventory conservation | `test_logistics_integrity.py` |
| Allocation invariants over six scenarios: legs sum to allocation, within vehicle capacity and depot stock, only on open feasible routes; insufficient-stock and no-vehicle cases | requirement: conservation, capacity, infeasible routes | same |
| **Scenario comparison**: `GET /api/simulation/compare` and a "Compare saved scenarios" card; flags runs whose baseline differed | scenario comparison existed only as before/after of one run | `test_saved_scenarios_can_be_compared_fairly` |

## Security
Least-privilege database role support (`MIGRATION_DATABASE_URL`, `AUTO_MIGRATE`, `grant-app-role`, `verify-schema`) with tests against a real restricted role; database host shown to administrators only; details in `SECURITY_REVIEW.md`.

## Packaging and documentation
* `legacy/v3/index.html` **removed**: it displayed prohibited wording (14 matches) and was not served. The V3 calculations remain pinned by `backend/tests/golden_v3.json`.
* New or rewritten documents: `ARCHITECTURE`, `DEPLOYMENT`, `SECURITY_REVIEW` (replaces `SECURITY`), `ML_EVALUATION_REPORT` (generated from the stored reports), `DATA_DICTIONARY` (generated from the migrated schema), `LIMITATIONS_AND_ASSUMPTIONS`, `VERIFICATION_REPORT`.
* `scripts/guided_walkthrough.py`: deterministic evaluator walkthrough through the real API (sign-in, inventory, forecast, shortage, recommendation, shipment plan, scenario comparison, calculation trace), with assertions.
* Tests: backend 389 -> 427; browser 263 -> 268 checks (new `e2e_v7_workflows.py`); document-existence and absolute-path checks added. Exact results: `VERIFICATION_REPORT.md`.

## Not changed (deliberately)
Models, evaluation code and the promotion decision (statistical forecaster remains the default); the benchmark data (not available) and therefore the benchmark figures; terrain data (none added: no dataset would materially improve the fictional route engine, and downloading global datasets was out of scope).

## Compatibility
`event_id` is optional; route objects gain `blocked_reason`; simulation gains `/compare`; at maximum weather severity one corridor can now be closed (differs from V6/V3 only there).

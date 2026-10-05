# V4 polish pass — what changed and what was verified

Prototype uses fictional synthetic logistics data and is intended for decision-support demonstration only.

## Scope
Presentation-layer polish on top of V3. **Not touched:** everything under `backend/` (services, routers, schemas, models, tests, scripts), `db/`, `legacy/`, `iot-simulator/`, `docker-compose.yml`, `frontend/nginx.conf`, `tests/e2e/e2e_playwright.py`, `package.json` / lockfile.
(The brief names `backend/app/engines.py`; this tree has no such file — the engine lives in `backend/app/services/*`, which is also untouched.)

## Files changed
| File | Change |
|---|---|
| `frontend/src/components/ui.tsx` | `InfoTip`, `ConfidenceIndex`, `CONFIDENCE_NOTE` |
| `frontend/src/components/ModelRoles.tsx`, `pages/Forecast.tsx` | Confidence shown as `Confidence Index: V/100 — LABEL` + tooltip + visible note; KPI shows `V/100` (no `%`) |
| `frontend/src/App.tsx` | Header: `SIMULATION TIME · 19 JUN 2026`, `DATA · SYNTHETIC` (same clock, date-level display) |
| `frontend/src/components/DecisionFlow.tsx` (new), `pages/Dashboard.tsx` | 7-step decision-flow strip |
| `frontend/src/components/WhyRecommendation.tsx`, `recommend.ts` | Advisory recommendation banner (source depot → destination via route) |
| `frontend/src/components/RouteSelection.tsx` | `WHY THIS ROUTE?`, total-risk and alternatives tiles |
| `frontend/src/components/IotFlow.tsx` | Compact value flow ESP32/RFID → API → PostgreSQL → inventory/risk → decision support |
| `frontend/src/components/RecommendedResponse.tsx` | Route-risk line, fleet-availability line, rerun note (all from the simulation result) |
| `tests/e2e/e2e_ui_enhancements.py` | Two assertions updated for the deliberate wording changes (header clock; confidence index — now split into value check + tooltip check). Nothing removed. |
| `tests/e2e/e2e_v4_polish.py` (new) | Checks for the items above, both themes, 390 px, console |
| `README.md`, `docs/` | Notes |

## Verification status of THIS tree
The V4 edits were made in a sandbox with **no network and no PostgreSQL / FastAPI / Node dependencies installed**. Only the following was executed against the V4 files:

* TypeScript **syntax and unused-symbol diagnostics** compared with the V3 tree (global `tsc`; React/Leaflet/Recharts type packages were unavailable, so a full `tsc -b` type-check was **not** possible). No new syntax / unused-symbol / undefined-name diagnostics vs V3.
* Server-side render smoke test (esbuild via `tsx`, `react-dom/server`) of the new/changed components with fixture data; output text inspected.
* `python -m py_compile` on both E2E files.
* `python backend/scripts/verify_v3_parity.py` on an extracted copy of this tree: exit 0, `V3 PARITY: PASS` (needs only Python, numpy and node).

**Not executed:** backend pytest, DB tests, API sweep, `npm ci`, `tsc -b`, `vite build`, any Playwright E2E, theme/contrast tests, 390 px layout. Run them before relying on V4 — the V3 results in `TEST_RESULTS.md` do not cover this tree.

Suggested order: `cd frontend && npm ci && npx tsc -b --noEmit && npm run build`; `cd backend && REQUIRE_DB=1 python -m pytest -rA`; `python backend/scripts/verify_v3_parity.py`; `python backend/scripts/api_sweep.py`; with the stack up: `APP_URL=http://localhost:80 python tests/e2e/e2e_playwright.py`, `e2e_ui_enhancements.py`, `e2e_v4_polish.py`.

# Test results — exact commands and outputs (UI/UX pass)

> **These results were produced on the V3 tree.** They are NOT evidence for the V4 polish pass; see `docs/V4_POLISH_NOTES.md` for what changed in V4 and what has / has not been executed against it.

Prototype uses fictional synthetic logistics data and is intended for decision-support demonstration only.

Everything below was produced by running an orchestration script (not shipped) against a **completely fresh extraction of a candidate ZIP of this exact tree**
(clean Python venv from `backend/requirements.txt`, `npm ci` from the lockfile). Raw logs: `docs/evidence/`. This file and `docs/evidence/` are the only files written after that run.
Environment: Ubuntu 24.04 sandbox · PostgreSQL 16 + PostGIS 3.4 · Python 3.12 · Node 22 · headless Chromium 141 (Playwright) · nginx 1.24 (Ubuntu package).

## Scope of this pass
UI/UX only. **No change** to backend engines, API contracts, database schema, forecasting/routing/allocation logic, parity behaviour, `docker-compose.yml`, `nginx.conf`, or the existing tests.
Verified by `diff -r` against the previously verified tree: the only differences are inside `frontend/` (13 files edited; 6 new components + `recommend.ts` + `theme.tsx` added), the new E2E file `tests/e2e/e2e_ui_enhancements.py`, `README.md` and `docs/`. `backend/`, `db/`, `legacy/`, `iot-simulator/`, `tests/e2e/e2e_playwright.py`, `docker-compose.yml` and `frontend/nginx.conf` are byte-identical.

## A. Tests actually executed (fresh extraction)

| # | What | Command | Result |
|---|---|---|---|
| A5 | Backend, full suite, DB up | `cd backend && REQUIRE_DB=1 python -m pytest -rA` | **70 passed, 0 skipped, 0 failed** |
| A6 | The 10 DB integration tests | `pytest -m db` | **10 passed** |
| A7 | Non-DB tests | `pytest -m "not db"` | **60 passed** |
| A8 | DB stopped, default | `pytest` | 60 passed, **10 skipped** (reason printed), 0 failed |
| A9 | DB stopped, release mode | `REQUIRE_DB=1 pytest` | 60 passed, **10 errors** (fail instead of silently skipping) |
| A11 | v3 parity | `python backend/scripts/verify_v3_parity.py` | **PASS** |
| A12 | Every API operation | `python backend/scripts/api_sweep.py` | **PASS** — 24/24 operations 200, 8/8 expected-error cases correct |
| A3 | TypeScript | `npx tsc -b --noEmit` | **PASS** |
| A4 | Frontend build | `npm run build` | **PASS** |
| A2 | Lockfile install | `npm ci` | **PASS** |
| A1 | Backend deps in a clean venv | `pip install -r backend/requirements.txt` | **PASS** |
| A13–A18 | nginx, shipped config | see `docs/evidence/SUMMARY.txt` | **PASS** |
| A19 | **Original E2E (unmodified file)** | `APP_URL=http://localhost:80 python -u tests/e2e/e2e_playwright.py` | **73 collected · 73 passed · 0 failed · 0 skipped** · exit 0 |
| A20 | **UI/UX-pass E2E (new file)** | `APP_URL=http://localhost:80 python -u tests/e2e/e2e_ui_enhancements.py` | **91 collected · 91 passed · 0 failed · 0 skipped** · exit 0 |

### Original E2E (73) — unchanged behaviour
Screens: Dashboard (16) · Forecast (6) · GIS (6) · Inventory (5) · Simulation (7), plus Leaflet, Allocation, IoT, Controls, Placeholders, Mobile 390 px, Console.
Leaflet rendered YES · What-If YES · IoT update YES · Allocation YES · 390 px layout YES.
```
--- dead-control audit (every visible button on every screen is clicked) ---
   Dashboard  [SHOW Base_04 ON MAP ›] -> alive
   Dashboard  [SHOW Base_03 ON MAP ›] -> alive
   Dashboard  [VIEW ROUTE COMPARISON →] -> alive
   Forecast   [7-DAY] -> alive
   Forecast   [14-DAY] -> alive
   Forecast   [30-DAY] -> alive
   Inventory  [SEND SCAN] -> alive
   Inventory  [RUN SIMULATOR ×5] -> alive
   Inventory  [RESET INVENTORY] -> alive
   Simulation [RUN SIMULATION] -> alive
   Simulation [APPLY TO ALL SCREENS] -> alive
   Simulation [RESET] -> alive
   Banner     [Clear] -> alive
PASS [Controls] no dead buttons (13 buttons clicked across 5 screens) · 13 alive, 0 allowed no-op
```

### UI/UX-pass E2E (91) — what it proves
Every number the new UI shows is compared with the backend API response, not with a hard-coded constant.
```
PASS [Theme] Dark is the default (fresh browser profile, empty storage) 
PASS [Theme] toggle is an accessible switch (role=switch, aria-checked, label) 
PASS [Theme] toggle works from the keyboard -> Light 
PASS [Theme] choice persisted in localStorage 
PASS [Theme] Light survives a reload (applied before first paint) 
PASS [Theme] back to Dark and persisted after reload 
PASS [Theme] toggled to Light for the Light contrast run 
PASS [Header] clock is labelled SYNTHETIC SIMULATION TIME (not an ambiguous timestamp) 
PASS [Header] tooltip explains it is a fictional clock, not real time 
```
Measured contrast (WCAG 2.x ratio; threshold 4.5:1) and status hues, per theme:
```
PASS [Contrast (dark)] all sampled text/background pairs >= 4.5:1 (WCAG AA) · [('page title', 7.8), ('card title', 5.4), ('table text', 13.1), ('muted text', 5.4), ('critical (red) text', 5.0), ('warning (yellow) text', 8.9), ('ok (green) text', 7.2), ('nav item', 13.8), ('active nav item', 16.0), ('header strip', 5.7), ('footer banner', 7.7), ('theme toggle', 12.3), ('select', 12.3)]
PASS [Semantics (dark)] GREEN / YELLOW(amber) / RED text keep their hue · hues(deg) {'text-ok': 150, 'text-wr': 46, 'text-cr': 3}
PASS [Contrast (light)] all sampled text/background pairs >= 4.5:1 (WCAG AA) · [('page title', 5.3), ('card title', 7.5), ('table text', 16.8), ('muted text', 7.5), ('critical (red) text', 5.3), ('warning (yellow) text', 4.9), ('ok (green) text', 5.1), ('nav item', 13.6), ('active nav item', 15.9), ('header strip', 6.1), ('footer banner', 6.1), ('theme toggle', 15.4), ('select', 15.4)]
PASS [Semantics (light)] GREEN / YELLOW(amber) / RED text keep their hue · hues(deg) {'text-ok': 152, 'text-wr': 40, 'text-cr': 3}
PASS [Contrast (light)] primary button (RUN SIMULATION) text on accent >= 4.5:1 · 6.1
PASS [Contrast (dark)] primary button text on accent >= 4.5:1 · 8.0
```
Briefing / Why-this-recommendation / GIS / Forecast / Response / IoT-flow checks:
```
PASS [Briefing] overall risk shown and equals the API (risk index) · UI '62 / 100' vs API 62
PASS [Briefing] critical locations listed and equal the API · ['Base_03', 'Base_04']
PASS [Briefing] predicted shortages equal the API (units, 14 d) · 1,44,595
PASS [Briefing] transport capacity vs need equals the API · 34000 / 41800
PASS [Briefing] active alerts equal the API (critical / warning) · 8/6
PASS [Briefing] exactly 3 recommended actions · 3
PASS [Briefing] action #1 matches the API top priority (location, supply, score) · Base_04 Water 76
PASS [Briefing] dispatch text groups vehicles under their own depot + route (no cross-depot merge) · {('Depot_A', 'R03'): ['V002', 'V001', 'V003'], ('Depot_B', 'R08'): ['V005']}
PASS [Briefing] baseline action #1 really spans 2 depots (so the grouping fix is exercised) · ['Depot_A', 'Depot_B']
PASS [Briefing] labelled RULE-BASED, not machine learning / LLM 
PASS [Briefing] SHOW ... ON MAP opens GIS for that location 
PASS [Why] selector lists the top priorities (<=10), #1 selected by default · 10
PASS [Why] priority #1: shows stock-out horizon, shortage, lead time, criticality, route risk, vehicle 
PASS [Why] priority #1: values equal the API · cover 1.7 d, shortage 19898, lead 1.3, crit 95
PASS [Why] priority #1: score breakdown sums to the API priority score · 76 vs 76
PASS [Why] priority #3: shows stock-out horizon, shortage, lead time, criticality, route risk, vehicle 
PASS [Why] priority #3: values equal the API · cover 1.5 d, shortage 890, lead 1.3, crit 70
PASS [Why] priority #3: score breakdown sums to the API priority score · 69 vs 69
PASS [Why] changing the selection updates the facts · Base_04 Water -> Base_03 Comms
PASS [Why] states it is rule-based with transparent weights 
PASS [Why] insight card title says RULE-BASED (NOT ML / LLM) 
PASS [Why] no page text claims the engine is AI-powered/generated 
PASS [GIS] banner shows source -> destination, selected route and alternatives · SELECTED ROUTE R03 · Depot_A → Base_04 · 134 km · ETA 6.3 h · risk HIGH (55) · alternatives (dotted): R08
PASS [GIS] map labels the selected route and the alternative(s) · ['R03 · SELECTED · 6.3 h', 'R08 · alt · 8.9 h']
PASS [GIS] map tags SOURCE depot and DESTINATION base 
PASS [GIS] direction arrows drawn on the selected + alternative routes only · 2
PASS [GIS] selected-route arrow points source -> destination (within 90 deg of the chord) · chord -47 deg, arrows [-55, -73]
PASS [GIS] explanation panel: SELECTED route, source -> destination, ETA, distance · Depot_A → Base_04 SELECTED R03 HIGH 134 km · ETA 6.3 h · 26,650 units to move
PASS [GIS] explanation text equals the backend reason · R03 has the lowest combined score (0.92 vs 1.13 for R08): lower route 
PASS [GIS] alternatives get a "why not" with score / risk / ETA deltas · ['R08']
PASS [GIS] criteria shown: distance/time, capacity, road, weather, terrain 
PASS [GIS] single-corridor case (Base_05) explained, no fake alternative 
PASS [Forecast] three distinct model cards: statistical baseline / Random Forest challenger / validation 
PASS [Forecast] roles are explicit: drives dashboard vs cross-check only / not used in decisions 
PASS [Forecast] hold-out MAPE shown for both models and equals the API · stat 3.7% RF 4.8%
PASS [Forecast] confidence value equals the API and its formula/caveat is shown · {'value': 99, 'label': 'HIGH', 'level': 'ok'}
PASS [Forecast] states what is and is not AI (rule-based engine is NOT ML / LLM) 
PASS [Forecast] only the Random Forest is described as the trained ML model 
PASS [Response] concise Recommended Response (3-7 points) with severity tags · 5
PASS [Response] verdict line equals the backend before/after risk · Overall risk 62 → 93 (+31); critical items 8 → 12; unserved after allocation 7,800 → 52,20
PASS [Response] transport shortfall numbers equal the backend result · need 72600 cap 20400 deficit 52200
PASS [Response] names the locations the backend says escalated · ['Base_02', 'Base_05']
PASS [Response] dispatch-first list equals the scenario priority queue from the API · [('Base_04', 'Water', 83), ('Base_04', 'Food', 82), ('Base_04', 'Maintenance', 75)]
PASS [Response] every top-3 item that has vehicles lists them under their own depot + route · 1 items verified; items with no feasible vehicle (stated as such in the UI): ['Base_04 Food', 'Base_04 Maintenance']
PASS [Response] items with no feasible vehicle are said so, never given an invented one 
PASS [Response] labelled RULE-BASED, not ML/LLM; derived from simulation + priority/allocation 
PASS [IoT flow] idle state explains Telemetry -> Database -> Inventory/Risk impact 
PASS [IoT flow] stage 1 Telemetry: SIMULATED RECEIVE Base_04/Medical x2,000 with device + tag · RFID-SIM-3401
PASS [IoT flow] stage 2 Database: event id equals iot_events row; stock 563 -> 2,563 · event #397
PASS [IoT flow] stage 3 Impact: cover, CRITICAL -> NORMAL, critical items 8 -> 7, risk 62 -> 57 · 3 · INVENTORY / RISK IMPACT recalculated by the backend Base_04 Medical: cover 12.7 d (was 2.8 d) · CRITICAL → NORMAL location status: CRITI
PASS [IoT flow] flow numbers agree with the database via the API 
PASS [IoT flow] simulator batch shows "latest of 5 scans" 
PASS [IoT flow] reset returns the flow to idle and the baseline to 8 critical 
```
Both themes — render check (no NaN/undefined/null) on all 5 screens, 390 px no-overflow on all 5 screens, console/network:
```
PASS [Both themes] dark/Dashboard: renders, no NaN/undefined/null · 14028 chars
PASS [Both themes] dark/Forecast: renders, no NaN/undefined/null · 5016 chars
PASS [Both themes] dark/GIS: renders, no NaN/undefined/null · 4080 chars
PASS [Both themes] dark/Inventory: renders, no NaN/undefined/null · 4225 chars
PASS [Both themes] dark/Simulation: renders, no NaN/undefined/null · 2927 chars
PASS [Mobile 390px] dark/Dashboard: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] dark/Forecast: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] dark/GIS: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] dark/Inventory: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] dark/Simulation: no horizontal page scroll · scrollWidth=390
PASS [Both themes] light/Dashboard: renders, no NaN/undefined/null · 14028 chars
PASS [Both themes] light/Forecast: renders, no NaN/undefined/null · 5016 chars
PASS [Both themes] light/GIS: renders, no NaN/undefined/null · 4080 chars
PASS [Both themes] light/Inventory: renders, no NaN/undefined/null · 4225 chars
PASS [Both themes] light/Simulation: renders, no NaN/undefined/null · 2927 chars
PASS [Mobile 390px] light/Dashboard: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] light/Forecast: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] light/GIS: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] light/Inventory: no horizontal page scroll · scrollWidth=390
PASS [Mobile 390px] light/Simulation: no horizontal page scroll · scrollWidth=390
PASS [Console] no uncaught page errors 
PASS [Console] no failed /api calls 
PASS [Console] no console errors other than blocked OSM tile loads · unexpected=[] | OSM tile errors=166
```

## B. Configuration-only validation (not runtime)
| Check | Result |
|---|---|
| `docker compose config -q` | PASS |
| All paths referenced by the Dockerfiles / compose exist | PASS |
| Dockerfile install/build steps replayed outside Docker (`pip install -r`, `npm ci`, `npm run build`) | PASS |

## C. Blocked by the environment — NOT RUN
* **Docker runtime: NOT RUN.** `docker pull postgis/postgis:16-3.4` → `403 Forbidden` (Docker Hub is blocked in the sandbox; `docs/evidence/docker_pull.log`). Image builds, Compose networking/DNS, `depends_on` and healthchecks at runtime, `restart` behaviour and first-run init are untested. The nginx resolver behaviour was tested with the shipped `nginx.conf` against a DNS stand-in on 127.0.0.11 and Ubuntu's nginx 1.24, not Docker's DNS or `nginx:alpine`.
* Real OpenStreetMap imagery (tiles blocked) — only the graceful-failure path was exercised.

## Defects found by this pass's own verification, and fixed
1. **Misleading dispatch text** — the first draft of the top-action headline merged legs from two depots into one route ("from Depot_A via R03 using V002 + V001 + V003 + V005", but V005 is a Depot_B vehicle on R08). Fixed with `legsText()` (groups by depot + route); the new E2E asserts it against the API's allocation legs, on a baseline action that genuinely spans two depots.
2. **Clipped table** — the Random Forest column of the validation card was cut off in the narrow card; replaced with a two-row list.
3. **Amber gauge segment** looked brown in Light; a separate fill token keeps it amber while text stays AA-compliant.
4. **Test-quality issues in my own new E2E** (not app defects): one check ended in `or True` and could never fail (replaced by a real before/after comparison), and one assumed a scenario's priority #2 would have vehicles (it legitimately may not; the check now verifies every item that has legs and separately asserts that items without legs are stated as such).

## Known limitations of the evidence
* Chromium only; 390 px is a viewport emulation, not a real device. Contrast was measured on sampled elements (listed above), not with a full accessibility audit tool; no screen-reader testing.
* The legacy card name “AI Logistics Insight” is retained as a substring because the original E2E asserts it; it is always shown with a RULE-BASED / NOT ML / LLM qualifier.
* The forecast error figures are on self-generated synthetic data and say nothing about real-world accuracy.

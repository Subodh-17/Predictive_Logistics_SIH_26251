# Architecture

```
Browser (React 18 + Vite + TypeScript + Tailwind, Leaflet map)
   |  HTTPS, same origin; HttpOnly session cookie + CSRF header
nginx (unprivileged; CSP + security headers; limit_req; proxies /api)             frontend/nginx.conf.template
   |  X-Forwarded-For overwritten with the client address (TRUSTED_PROXY_HOPS=1)
FastAPI backend (uvicorn)                                                          backend/app
   |  request pipeline: request id -> rate limit -> auth/RBAC/CSRF -> handler -> headers -> access log
   |  SQLAlchemy 2 + psycopg 3; per-operation transactions
PostgreSQL 16 + PostGIS 3.4                                                        db/migrations, db/seed.sql
Model artefacts (read-only files): ml/artifacts/{forecast,shortage}/v1            LightGBM text models + metadata
```

## Backend modules
| Module | Responsibility |
|---|---|
| `config.py` | Environment profiles (development/test/production) and fail-fast validation of secrets, CORS, cookies, database URLs. |
| `security.py`, `auth.py` | Password hashing, JWT, CSRF, rate-limit primitives; sign-in/out, roles, user administration, audit trail. |
| `migrate.py`, `cli.py` | Versioned non-destructive migrations (checksums, advisory lock, V5 adoption), guarded seeding, least-privilege grants, operational commands. |
| `bootstrap.py` | Start-up: wait for the database, migrate (or verify), seed an empty database only when allowed, ensure an administrator, generate forecasts and baseline tables; background retry. |
| `repository.py` | All SQL access; composable operations that can share one transaction. |
| `services/` | Pure calculation engine (no database): `domain` (types, parameters), `forecasting` (statistical model), `model_service` (which forecaster is active, fallbacks, shortage-model status), `inventory` (days of supply, status rules, risk basis), `terrain`/`routing` (speed, ETA, risk, feasibility, closure), `priority`, `allocation`, `recommendation`/`explain`, `simulation`, `iot`. |
| `ml/` | Feature builder, LightGBM forecaster and shortage scorer, artefact integrity checks. Inference only; training is in the top-level `ml/` directory. |
| `routers/` | HTTP layer; role dependencies; strict request models in `schemas.py`. |
| `observability.py` | JSON logs with redaction, request ids, in-process counters. |

## Calculation pipeline (one request)
`load_snapshot` (database) -> `engine.compute(snapshot, scenario params)`:
1. demand forecast per (location, supply): the selected forecaster (statistical by default) -> daily demand = mean of the first 7 forecast days;
2. inventory: days of supply = stock / daily demand; lead time from the best feasible route's ETA; status and 14-day predicted shortage by the documented rules;
3. routes: effective speed (road, terrain, weather) -> ETA, delay, risk; feasibility = vehicle available **and** corridor not closed (weather risk < 0.85);
4. priority score (documented weights) -> allocation (greedy by priority, within depot stock and vehicle capacity, with the binding constraint reported per row);
5. recommendations/explanations from the same numbers. Scenario parameters (demand, weather, road, fleet) re-run steps 1-5 on the same snapshot; baseline and scenario therefore share one starting state.

`persist_baseline` stores alerts/priorities/allocations for the unmodified scenario; state-changing endpoints refresh them in the **same transaction** as the change.

## Workflows and where they live
| Workflow | UI | API | Tables |
|---|---|---|---|
| Sign-in, session, roles | `Login`, sidebar | `/api/auth/*` | `users`, `audit_log` |
| Dashboard, alerts | `Dashboard` | `/api/dashboard`, `/api/alerts`, `/api/insights` | derived |
| Demand forecast | `Forecast` | `/api/forecast`, `/api/forecast/challenger` | `consumption`, `forecasts`, `weather` |
| Inventory, risk basis | `Inventory` | `/api/inventory`, `/projection`, `/risk-basis` | `inventory` |
| Replenishment, allocation, priority | Dashboard/GIS panels | `/api/priority`, `/api/allocation` | `priority_scores`, `allocations` |
| Shipment planning, route alternatives, ETA | `Gis` | `/api/routes`, `/api/routes/compare`, `/api/vehicles` | `routes`, `vehicles`, `terrain` |
| Inventory events (simulated scanner) | `Inventory` | `/api/iot/*` | `iot_events`, `inventory` |
| Scenario run and comparison | `Simulation` | `/api/simulation/run`, `/runs`, `/compare` | `simulation_runs` |
| Models, evaluation, shortage check | `Models` | `/api/ml/*` | artefacts, `ml/reports` |
| Status, accounts, user admin, audit | `System`, `Users` | `/api/health/*`, `/api/users`, `/api/audit-log` | `users`, `audit_log` |

## Extension points (not implemented)
Real geospatial inputs: `routes.geom` and `locations.geom` are PostGIS columns, so road/terrain datasets can be loaded by a migration and used by `routing`/`terrain` in place of the fictional classes. A shortage-onset model needs daily on-hand/in-transit/backlog tables first (`docs/SHORTAGE_MODEL_DECISION.md`).

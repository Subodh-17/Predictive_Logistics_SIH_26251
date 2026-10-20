# Changes from V5 to V6

Incremental upgrade: the V5 engines, API contracts (extended, not broken), visual design and ML artefacts are unchanged. Defects found by the V6 audit are listed first.

## Defects found in V5 and fixed
| # | Defect | Fix |
|---|---|---|
| 1 | No authentication: inventory reset, forecast recompute, IoT updates and simulation runs were open to anyone | Sessions, roles, CSRF, lock-out, audit trail (see `docs/SECURITY_REVIEW.md`) |
| 2 | `GET /api/forecast?location=UNKNOWN` crashed with an unhandled `ZeroDivisionError` (HTTP 500); invalid `horizon` was silently replaced by 14 | 404 for unknown ids, 422 for invalid parameters |
| 3 | `db/schema.sql` started with `DROP TABLE ... CASCADE` and bootstrap could run it on a partially filled database | Versioned non-destructive migrations; partially populated scenarios are refused, never overwritten; destructive reset only for dev/test-named databases |
| 4 | Test fixtures called `iot/reset` on whatever `DATABASE_URL` defaulted to (a developer's real database) | Tests refuse any database not named test/ci/scratch |
| 5 | Default database credentials (`logistics`/`logistics`) published on the host; no production/development separation | Profiles; secrets mandatory and validated; DB/API not published |
| 6 | Multi-step writes (event + derived tables, batch simulation, reset) committed step by step | One transaction each; rollback tested |
| 7 | Internal exception text and artefact paths could reach API callers; validation errors echoed submitted values | Generic errors with reference id; values and paths masked |
| 8 | A NUL byte in a filter produced "database unavailable" | Identifier patterns at the edge; database data errors map to 422 |
| 9 | No security headers, rate limits, request ids; permissive CORS methods/headers | Added; CORS restricted |
| 10 | Health endpoint could not distinguish API, database, start-up and model state; fallback to the statistical model was invisible in the UI | Layered health, `/api/health/detail`, banner and status chip for fallbacks |
| 11 | Inline theme script incompatible with a strict CSP | Moved to `public/theme-init.js` |
| 12 | Accessibility: unnamed depot markers, red text below 4.5:1 contrast, unstyled password/textarea controls, unfocusable scroll regions | Fixed; axe-core WCAG 2 A/AA scan is part of the browser suite |
| 13 | Terminology audit mis-handled the JavaScript `prototype` keyword and scanned only part of what users can see | Rewritten; scope now includes API text, seed values, reports, simulator output |
| 14 | Stale V4 evidence/result documents shipped inside the V5 archive | Removed; V6 reports are regenerated |

## Features and changes
* Backend: `config.py` (profiles), `security.py`, `auth.py`, `migrate.py`, `observability.py`, `cli.py`; `/api/auth/*`, `/api/users`, `/api/audit-log`, `/api/inventory/risk-basis`, `/api/health/{live,ready,detail}`.
* ML integration: unchanged models; artefact pins, symlink refusal, load timestamps, failure/fallback counters, sanitised errors; shortage model integration decision documented (`docs/SHORTAGE_MODEL_DECISION.md`).
* Frontend: sign-in, role-aware controls, System & Account (status, model, data coverage, change password), User Administration (accounts, roles, audit trail), inventory risk explanation, benchmark-format shortage check, honest unavailable/starting-up/fallback states.
* Deployment: hardened images, nginx template with CSP and rate limits, Compose requiring secrets, Render blueprint (unverified), `scripts/generate_env.py`, `scripts/local_stack.sh`.
* Tests: 136 -> 389 backend tests; 203 -> 263 browser checks; deployment-file and secret-scan tests.

## Compatibility notes
* All `/api/*` routes now require sign-in (except health probes, the session probe and login). Existing API clients must authenticate; `iot-simulator/simulator.py` reads `PLSD_USER`/`PLSD_PASSWORD`.
* Error bodies have the shape `{"code": ..., "detail": ...}` (V5 had `detail` only); validation errors list `loc`/`msg`/`type` without the submitted value.
* `AUTO_INIT_DB` is accepted as an alias of `AUTO_SEED_SCENARIO`; the production default is now **off**.
* `backend/scripts/api_sweep.py` was removed; the OpenAPI-driven coverage test in `tests/test_terminology.py` and the role matrix in `tests/test_auth_api.py` replace it.
* An existing V5 database is adopted (baseline recorded, newer migrations applied); no data is dropped.

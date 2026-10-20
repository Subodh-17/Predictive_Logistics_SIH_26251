# V7.1 verification report

Executed on 2026-10-13 in one sandbox (Ubuntu 24.04, Python 3.12.3, Node 22.22.2, PostgreSQL 16 + PostGIS 3.4.2 installed locally, nginx 1.24.0 with the realip module, headless Chromium 141 via Playwright 1.56). Raw outputs: `docs/evidence/v7_1/`. All data is the fictional illustrative scenario; nothing here validates real operations. The five categories below are kept strictly apart.

## How these results relate to the shipped archive
The candidate archive was extracted into a fresh directory; Python dependencies came from the pinned lockfile into a **new** virtual environment, `npm ci` from `package-lock.json`; every check marked "fresh" ran against that extracted tree, from a fresh database. The shipped archive differs from the verified tree **only** in `README.md`, `docs/CHANGES_V7_1.md`, `docs/VERIFICATION_REPORT.md` and `docs/evidence/` (documents that could not be finished before the results existed); the comparison is shown at the end. One defect (map error on fast navigation) was found during the first full run: the fix was made and **every check below was re-run on the fixed source**.

## 1. Freshly executed on the final source
| Check | Command (from the extracted tree) | Passed | Failed | Skipped |
|---|---|---|---|---|
| Backend tests, PostgreSQL/PostGIS (`REQUIRE_DB=1`) | `cd backend && pytest` | **434** | 0 | 0 |
| ML pipeline tests | `cd ml && pytest` | **14** | 0 | 0 |
| Terminology audit (sources / built bundle) | `scripts/audit_terminology.py [--dist]` | 0 matches in 89 / 93 files | - | - |
| Frontend `npm ci`, typecheck, production build | `npm ci && tsc -b --noEmit && npm run build` | succeeded | 0 | - |
| Browser: GIS/resilience (new) | `tests/e2e/e2e_v71_gis_resilience.py` | 14 | 0 | 0 |
| Browser: security/roles + axe WCAG 2 A/AA on 8 pages | `e2e_v6_security_workflows.py` | 59 | 0 | 1 (last-admin protection: covered by API tests) |
| Browser: scenario comparison | `e2e_v7_workflows.py` | 5 | 0 | 0 |
| Browser: main workflows | `e2e_playwright.py` | 73 | 0 | 0 |
| Browser: UI/UX | `e2e_ui_enhancements.py` | 92 | 0 | 0 |
| Browser: polish | `e2e_v4_polish.py` | 38 | 0 | 0 |
| Evaluator walkthrough (10 assertions) | `scripts/guided_walkthrough.py` | passed | 0 | - |
| Scenario evaluation re-run from scratch | `ml/evaluate_app_series.py --no-promote` | 0 differing values vs the shipped report | - | - |
| Python dependency audit | `pip-audit -r backend/requirements.txt --no-deps` | no known vulnerabilities | - | - |
| npm audit: production / all | `npm audit --omit=dev` / `npm audit` | 0 vulnerabilities / **5 high, all from one advisory (`braces`, build-time, no patched release)** | - | - |
Browser total: 282 collected, 281 passed, 0 failed, 1 skipped. Backend tests by module (434): allocation/simulation/IoT 24, API 10, API hardening 39, authentication/RBAC 53, bootstrap 3, configuration 26, seed 4, deployment files/documents/role-init script 22, forecasting 7, inventory 12, logistics integrity 22, migrations/least privilege 34, ML API 7, ML artefacts 19, ML core 22, ML regression 34, security primitives 14, terminology 72, terrain/routing 10.

### Operational checks executed (production profile, no containers)
`scripts/local_stack.sh` with `STACK_LEAST_PRIVILEGE=1`, which mirrors the Compose role design: the real `db/init/10-roles.sh` creates two non-superuser roles and PostGIS; `plsd_owner` migrates, grants and seeds a **fresh database**; the API runs as the data-only role `plsd_app` (`APP_ENV=production`, `AUTO_MIGRATE=0`, Secure cookies, docs off) behind the real nginx template.
* Both `plsd_owner` and `plsd_app` have `rolsuper = false`; as `plsd_app`, `CREATE TABLE` -> "permission denied for schema public" and `DROP TABLE inventory` -> "must be owner of table inventory".
* **Clean restart** on the same database: the init script re-ran idempotently ("extension postgis already exists, skipping"), no migration or seed was re-applied, the 18 saved scenario runs and 5,500 consumption rows were intact, users could sign in.
* **Database outage:** `/api/health/live` 200, `/api/health/ready` 503, data endpoint a generic 503 `DB_UNAVAILABLE`; after PostgreSQL returned both `ready` and the data endpoint were 200 again **without restarting the API**.
* **Client address behind a trusted proxy** (executed in the preceding development run, same nginx template): with the peer listed in `TRUSTED_PROXY_CIDR` a request carrying `X-Forwarded-For: 203.0.113.7` was recorded in the audit log as `203.0.113.7`; with another range listed the same header was ignored and the peer address `127.0.0.1` was recorded.
* Browser suites ran against this stack: unauthorised direct API calls refused (403/401), CSRF enforced, repeated `event_id` rejected, blocked corridor R07 -> Base_05 explained as "No feasible route: route closed", tiles failing -> notice shown and corridors still drawn, empty/500/truncated route responses survived, 12 rapid open/leave cycles of the map without an uncaught error, comparison at 390 px without horizontal overflow, visible keyboard focus, saved scenarios persisted across reload.

## 2. Historical results (not re-presented as V7.1 results)
The delivered V7 archive: 427 backend tests, 14 ML, 267 browser checks passed + 1 skipped, 10 walkthrough assertions (`docs/evidence/v7_historical/`). Its backend suite was re-run on the extracted V7 archive at the start of this release as the baseline (427/427; `evidence/v7_1/v7_archive_baseline_backend_junit.xml`). ISOMORPH **benchmark** metrics (LightGBM 9.32%, Random Forest 9.43%, seasonal-naive 11.12%, EWMA 11.83% WAPE) are historical, from V5/V6 reports; **they were not reproduced in V7 or V7.1** (dataset not available) and are not new validated results. Application-scenario WAPE (EWMA 4.00%, LightGBM 4.34%, h1-14) **was** re-computed from scratch in V7.1 and matched exactly; LightGBM stays unpromoted.

## 3. Static inspection (executed tools, nothing started)
| Check | Result |
|---|---|
| `docker-compose.yml` against the compose-spec JSON schema (`check-jsonschema`) | ok |
| Dockerfiles with hadolint 2.12.0 | frontend clean; backend DL3008 (unpinned `libgomp1`), accepted |
| nginx template (`nginx -t`, security headers, CSP, real-IP wiring) | passed in `test_deployment_config.py` |
| Secret scan of the whole tree, `.env.example` empty secrets, pinned dependencies, absolute-path scan | passed in `test_deployment_config.py` |
| `render.yaml` parsed and audited against the application's real configuration | see `docs/DEPLOYMENT.md` section 5 |

## 4. Blocked by unavailable tooling
| Check | Blocker (exact) | Next step |
|---|---|---|
| Docker image builds; `docker compose up`; container health checks; persistence across `docker compose down/up`; non-root/read-only behaviour inside containers | `docker`/`podman`: not found; `registry-1.docker.io`, `auth.docker.io`, `ghcr.io`: HTTP 000 from the sandbox (`evidence/v7_1/docker_blocker.txt`), so base images cannot be pulled even if a client were installed | run the commands in `docs/DEPLOYMENT.md` section 1 on a Docker host |
| Real map tile imagery | OpenStreetMap tile requests are blocked in the sandbox; tile failure handling was verified instead | open the GIS page on a networked machine |
| ISOMORPH benchmark reproduction | dataset not available | obtain the dataset and run `ml/train_forecast.py` / `train_shortage.py` per `ml/README.md` |

## 5. Not performed
A Render deployment (no account or network access) and everything that depends on it (platform proxy range, PostGIS permission on Render, private-service health checks); independent security review or penetration test; load, soak and multi-replica tests; browsers other than headless Chromium; screen-reader sessions; backup/restore drills; hash-verified dependency installs.

## Reproduce
```bash
pip install -r backend/requirements-dev.txt && createdb logistics_test && psql logistics_test -c 'CREATE EXTENSION postgis'
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/logistics_test       # name must contain test/ci/scratch; a superuser lets the role-init test run
(cd backend && REQUIRE_DB=1 python -m pytest) && (cd ml && PYTHONPATH=../backend python -m pytest)
(cd frontend && npm ci && npm run typecheck && npm run build) && python scripts/audit_terminology.py --dist
check-jsonschema --builtin-schema vendor.compose-spec docker-compose.yml        # pip install check-jsonschema
DATABASE_ADMIN_URL=postgresql://USER:PASSWORD@localhost:5432/postgres STACK_LEAST_PRIVILEGE=1 scripts/local_stack.sh start
# then tests/e2e/*.py (README section 4) and scripts/guided_walkthrough.py
```

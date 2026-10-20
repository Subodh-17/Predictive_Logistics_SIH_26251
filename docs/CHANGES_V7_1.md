# Changes from V7 to V7.1 (deployment verification and hardening)

Scope: verification and hardening only; no feature was added for its own sake and the forecasting algorithms, models and promotion decision are unchanged.

## Defects found and fixed
| # | Defect | Fix | Evidence |
|---|---|---|---|
| 1 | **Compose ran the API as the database administrator** (superuser) and applied migrations with it; the V7 least-privilege design existed only in the code | Compose now has four services: `db` (admin role only for volume initialisation: roles + PostGIS via `db/init/10-roles.sh`), one-shot `migrate` (non-superuser owner `plsd_owner`: migrate -> grant -> seed), `backend` (data-only `plsd_app`, `AUTO_MIGRATE=0`, no owner credentials), `frontend`. `generate_env.py`/`.env.example` provide the three database secrets | init script run against real PostgreSQL in `test_deployment_config.py`; the same role design executed by `scripts/local_stack.sh` (fresh DB, restart) |
| 2 | `python -m app.cli migrate` crashed with "permission denied for table schema_migrations" whenever `DATABASE_URL` was the restricted role (it printed the version through the not-yet-granted application connection) - this would have broken the Compose `migrate` step | version read through the migration connection | regression test `test_cli_migrate_reports_the_version_with_the_migration_connection` |
| 3 | Behind a platform load balancer all users shared one client address: per-address rate limits and the sign-in lock-out (20 failures per address) would apply to everyone at once - a lock-out denial of service | nginx `set_real_ip_from ${TRUSTED_PROXY_CIDR}` + `real_ip_header X-Forwarded-For`; default trusts nobody | executed through nginx: trusted peer -> `X-Forwarded-For` honoured; untrusted -> ignored (audit log shows the recorded address); template tests |
| 4 | `postgres://` database URLs (some hosting platforms) failed with `NoSuchModuleError`; `postgresql://` depended on SQLAlchemy's default driver | normalised to `postgresql+psycopg://` for `DATABASE_URL` and `MIGRATION_DATABASE_URL`; password rules still apply | `test_config.py` |
| 5 | Render blueprint: no web health check, no proxy-trust setting, undocumented single-role limitation | updated; audit table in `DEPLOYMENT.md` | `test_render_blueprint...` |
| 6 | Build-tool advisories reported by V7: 9 (3 moderate, 6 high: `braces`, `esbuild`, `postcss-selector-parser`, then `vite`) | Vite 5 -> 7.3.7 (+ `@vitejs/plugin-react` 4.7), `overrides` for `braces` (^3.0.3) and `postcss-selector-parser` (^7.1.6); typecheck, build and every browser suite re-run; generated CSS has an identical selector set (356). **Result: 5 reported, all stemming from `braces` (no patched release exists); production dependencies: 0** | `SECURITY_REVIEW.md` |

| 7 | **Map crash on fast navigation:** leaving the GIS page within 50 ms of opening it made a deferred Leaflet resize run on an already-removed map (`Cannot read properties of undefined (reading '_leaflet_pos')`, an uncaught page error). Seen as 4 failing checks in one browser run | the deferred resize is cancelled on unmount and guarded (`isConnected`); map fitting no longer animates | `e2e_v71_gis_resilience.py`: 12 rapid open/leave cycles raise no error. The dedicated loop was written after the fix; its sensitivity to the old code was not separately demonstrated |

## Added verification (no new product features)
`tests/e2e/e2e_v71_gis_resilience.py` (14 checks): blocked-corridor explanation in the real GIS page, map with all tile requests failing, empty / failed (500) / truncated (malformed) route responses, map resizing, scenario comparison at 390 px without horizontal overflow, visible keyboard focus, persistence across reload. Backend: 427 -> 434 tests (role-init script run against real PostgreSQL, Compose role separation, proxy trust, URL normalisation, CLI regression).

## Unchanged and re-checked
Scenario evaluation re-run from scratch: identical to the shipped report (0 differing values); LightGBM remains unpromoted (4.34% vs 4.00% WAPE, horizons 1-14). The ISOMORPH benchmark was **not** re-run (dataset unavailable). `pip-audit`: no known vulnerabilities.

## Not done (blocked)
Docker image builds and `docker compose up` (no Docker; registries unreachable); a Render deployment. See `DEPLOYMENT.md` for commands to run elsewhere.

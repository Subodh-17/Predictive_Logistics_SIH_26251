# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker compose up` stops with "POSTGRES_PASSWORD is required" | Run `python scripts/generate_env.py` (creates `.env`), or set the variables yourself. There are no defaults by design. |
| Backend exits with "Invalid configuration:" and a list | Production profile validation. Fix every listed item (`python -m app.cli check-config` shows the list without starting the server). |
| Sign-in impossible, no users | Set `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` for the first start, or run `python -m app.cli create-user NAME --role admin` inside the backend environment. |
| Sign-in works but every request returns 401 over plain HTTP on another machine | The production profile sets a Secure cookie; browsers send it only over HTTPS or on `localhost`. Use HTTPS, or `APP_ENV=development` for local-network testing. |
| 403 "Missing or invalid CSRF token" | Only for cookie sessions making state-changing calls without the `X-CSRF-Token` header (the UI does this automatically; reload the page). API clients should use a bearer token. |
| 429 responses | Rate limit or sign-in lock-out; wait for `Retry-After`. Limits are configurable (`docs/CONFIGURATION.md`). |
| UI shows "STARTING UP" / `/api/health/ready` returns 503 | Migrations, seeding or forecast generation are still running or failed; see the API log and *System & Account → Start-up*. With `AUTO_SEED_SCENARIO=0` an empty database is reported, not silently filled. |
| "scenario tables are partially populated" | A previous load was interrupted outside a transaction (or data was deleted by hand). The application refuses to overwrite it. Restore the data, or on a *development* database `python -m app.cli reset-database --confirm <dbname>` then `migrate`. |
| "migration … was modified after it was applied" | An applied file in `db/migrations` was edited. Restore it; add a new numbered migration instead. |
| Tests: "REFUSING to run database tests against …" | The test database name must contain `test`, `ci` or `scratch`. |
| Tests: "REQUIRE_DB=1 but PostgreSQL … not reachable" | Start PostgreSQL/PostGIS and set `DATABASE_URL` to the test database. |
| Banner "FALLBACK ACTIVE" | The trained forecasting model failed to load or run and the statistical model is in use. *System & Account* shows the reason; fix the artefact and use an administrator's forecast recompute (it clears the fallback), or restart. |
| Map shows no background | Tiles come from tile.openstreetmap.org; the CSP allows only that host. Offline use shows markers and routes without imagery. |
| `pip-compile` / dependency resolution is slow | See `docs/DEPENDENCIES.md`. |

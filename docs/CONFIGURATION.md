# Configuration reference

All backend settings come from environment variables and are validated at start-up by `backend/app/config.py`.
`python -m app.cli check-config` validates the current environment without starting the server and lists **every** problem at once.

## Profiles (`APP_ENV`)

| Value | Intended use | Behaviour |
|---|---|---|
| `production` (Docker default) | any shared or networked deployment | All secrets required and checked for strength; Secure session cookie; interactive API docs off; the scenario is loaded only if `AUTO_SEED_SCENARIO=1`; cheap password hashing refused. The process **refuses to start** if anything is missing or weak. |
| `development` (non-Docker default) | a local machine | A random per-process `JWT_SECRET` is used when none is set (sessions end on restart); API docs on; the scenario is loaded into an empty database. Not safe to expose to a network. |
| `test` | automated tests | Like development, never auto-seeds; the test suite additionally refuses any database whose name does not contain `test`, `ci` or `scratch`. |

An unknown value is treated as production for validation purposes.

## Variables

| Variable | Default | Production | Meaning |
|---|---|---|---|
| `APP_ENV` | `development` | `production` | Profile (above). |
| `DATABASE_URL` | local development URL without password | **required** | `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB`. Password must be >= 12 characters and not a known default. |
| `JWT_SECRET` | random per process (dev/test only) | **required** | >= 32 characters, not a placeholder. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `MIGRATION_DATABASE_URL` | unset (migrations use `DATABASE_URL`) | recommended | DDL-capable (owner) connection used only by `python -m app.cli migrate / seed-scenario / grant-app-role` and, when `AUTO_MIGRATE=1`, at start-up. Lets `DATABASE_URL` be a data-only role (`docs/DEPLOYMENT.md` §3). Same password rules as `DATABASE_URL`. |
| `AUTO_MIGRATE` | `1` | `0` with a data-only `DATABASE_URL` | `1`: apply pending migrations at start-up. `0`: only verify that the schema is at the newest version (read-only) and refuse to start otherwise. |
| `ACCESS_TOKEN_MINUTES` | `60` | optional | Session lifetime (5-1440). |
| `COOKIE_SECURE` | on in production, off otherwise | must stay on | Secure flag of the session cookie (browsers accept it on `http://localhost`). |
| `CORS_ORIGINS` | local development origins | **required** | Exact origins allowed to call the API cross-origin; no wildcards; `https` in production. Not needed when the UI is served through the bundled nginx (same origin). |
| `ENABLE_API_DOCS` | off in production, on otherwise | optional | Serves `/docs` and `/openapi.json`. |
| `TRUSTED_PROXY_HOPS` | `0` | `1` behind the bundled nginx | Number of reverse proxies whose `X-Forwarded-For` entry is trusted, counted from the right. `0` ignores the header (it is client-controlled). |
| `RATE_LIMIT_PER_MINUTE` | `600` | optional | Requests per client address per minute for `/api/*` (health probes excluded). |
| `RATE_LIMIT_WRITE_PER_MINUTE` | `60` | optional | State-changing requests per client address per minute. |
| `LOGIN_MAX_FAILURES` | `5` | optional | Failed sign-ins per user name + address before a lock-out (per address: 4x). |
| `LOGIN_WINDOW_SECONDS` | `900` | optional | Window of the lock-out. |
| `PASSWORD_SCRYPT_LOG_N` | `15` | >= 15 | scrypt cost (N = 2^value, r = 8, p = 3). |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` | unset | set together | First administrator, created only while the users table is empty. Remove the password afterwards. Alternative: `python -m app.cli create-user NAME --role admin`. |
| `AUTO_SEED_SCENARIO` | on in development, off in production/test (`AUTO_INIT_DB` is accepted as an alias) | explicit | Load the fictional illustrative scenario (`db/seed.sql`) into an **empty** database. A partially populated database is never seeded or overwritten. |
| `DB_WAIT_SECONDS` | `60` | optional | How long start-up waits for PostgreSQL before the background retry takes over. |
| `DB_DIR` | `<repo>/db` | optional | Directory with `seed.sql` and `migrations/`. |
| `MIGRATIONS_DIR` | `<DB_DIR>/migrations` | optional | Migration files. |
| `ML_DIR` | `<repo>/ml` | optional | Parent of `artifacts/` and `reports/`. |
| `ML_ARTIFACT_DIR` | `<ML_DIR>/artifacts` | optional | Trained-model artefacts (mount read-only). |
| `ML_REPORTS_DIR` | `<ML_DIR>/reports` | optional | Evaluation reports served by `/api/ml/evaluation`. |
| `FORECAST_MODEL_MODE` | `auto` | optional | `auto`: the trained model drives forecasts only if its metadata records a *promoted* decision (currently it does not: see `ml/reports`). `ml`: use it whenever it loads (visible fallback otherwise). `statistical`: never use it. |
| `ML_FORECAST_SHA256` / `ML_SHORTAGE_SHA256` | unset | recommended | Out-of-band SHA-256 pins of the model files. A model whose file differs is refused even if its metadata was rewritten to match. |
| `ML_RECOMPUTE_TIMEOUT_S` | `30` | optional | Time budget for regenerating forecasts with the trained model before the statistical model takes over. |
| `LOG_LEVEL` | `INFO` | optional | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_JSON` | `1` | optional | One JSON object per line (set `0` for readable text). |

### Docker Compose only

| Variable | Meaning |
|---|---|
| `POSTGRES_PASSWORD` | **Required.** Password of the administrative role `plsd_admin`; used only to initialise the database volume (never by the application). |
| `OWNER_DB_PASSWORD` | **Required.** Password of `plsd_owner` (non-superuser database owner; used only by the one-shot `migrate` service). |
| `APP_DB_PASSWORD` | **Required.** Password of `plsd_app` (the API's data-only role). The generator uses hex values, which are safe inside a database URL. |
| `TRUSTED_PROXY_CIDR` | Web container: address range of a load balancer **in front of** nginx (default `127.0.0.1/32` = trust nobody). |
| `BACKEND_HOSTPORT` | Used by the nginx container (`backend:8000` by default) to reach the API. |

`python scripts/generate_env.py` writes a `.env` with fresh random secrets and prints the first administrator's password once.

# Deployment

## Status at a glance (V7.1)
| Path | Status | Evidence / blocker |
|---|---|---|
| Local production-profile stack without containers (`scripts/local_stack.sh`): API `APP_ENV=production`, real nginx template, PostgreSQL/PostGIS, **same role design as Compose** (admin initialises roles + PostGIS with the real `db/init/10-roles.sh`; non-superuser owner migrates/seeds; API runs as a data-only role) | **executed** (fresh database, clean restart, outage recovery, browser suites, walkthrough) | `VERIFICATION_REPORT.md` |
| Docker image builds, `docker compose up`, container health checks, persistence across `docker compose down/up` | **blocked, not executed** | no `docker`/`podman` binary in the verification environment, and `registry-1.docker.io`, `auth.docker.io` and `ghcr.io` are unreachable from it (HTTP 000), so the base images (`python:3.12-slim`, `node:22-alpine`, `nginxinc/nginx-unprivileged`, `postgis/postgis`) cannot be pulled. Exact commands for a Docker host are in section 1. |
| `docker-compose.yml` against the compose-spec JSON schema | **executed (static)** | `check-jsonschema --builtin-schema vendor.compose-spec` -> ok |
| Dockerfiles linted | **executed (static)** | hadolint 2.12.0: frontend clean; backend one warning DL3008 (unpinned `libgomp1`), accepted |
| nginx template syntax | **executed (static)** | `nginx -t` in `test_deployment_config.py` |
| Render blueprint | **audited statically, not deployed** | `render.yaml` parsed and checked by tests; no Render account/network |

## 1. Docker Compose (run these on a machine with Docker; none of this has been executed here)
```bash
python scripts/generate_env.py            # .env with random POSTGRES/OWNER_DB/APP_DB passwords, JWT secret, first-admin password (printed once)
docker compose config -q                  # validates the file and that required secrets are set
docker compose up --build -d              # db -> migrate (one-shot) -> backend -> frontend ; UI on http://localhost:8080
docker compose ps                         # expect: db healthy, migrate exited 0, backend healthy, frontend healthy
curl -fsS http://localhost:8080/api/health/ready      # {"status":"ready",...}
# sign in at http://localhost:8080 with the printed admin account, then:
docker compose exec -T backend python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health/live').read())"
# persistence: users and saved scenarios must survive a restart
docker compose down && docker compose up -d && curl -fsS http://localhost:8080/api/health/ready
# restricted role check (must print: permission denied)
docker compose exec -T db psql -U plsd_app -d logistics -c "CREATE TABLE should_fail (i int)"
docker compose down -v                    # removes the data volume (destructive)
```
**Roles.** `plsd_admin` (the image's administrative user) is used only by the one-time init script `db/init/10-roles.sh`, which creates two non-superuser roles and the PostGIS extension: `plsd_owner` (owns the database; used only by the one-shot `migrate` service for `migrate`, `grant-app-role`, `seed-scenario`) and `plsd_app` (what the API connects as: data access only; the API holds no owner credentials; `AUTO_MIGRATE=0` makes it verify the schema version read-only). The init script runs only when the data volume is first created; to rotate a role password later, change `.env` and re-run `docker compose exec db sh /docker-entrypoint-initdb.d/10-roles.sh` (idempotent), then restart the services. Migrations run on every `up` (no-op when current); the scenario is loaded only into an empty database and never overwritten.

**Known unverified risks in the Compose path** (reasoned from the files, not observed): the `postgis/postgis` image's init-script environment handling, the nginx-unprivileged image's template rendering into `/etc/nginx/conf.d`, `read_only: true` with `tmpfs: /tmp`, and the `service_completed_successfully` ordering. All have a documented fallback: `docker compose logs <service>`.

## 2. Without Docker
Requirements: Python 3.12, Node 22 (>= 22.12 for Vite 7), PostgreSQL 16 + PostGIS 3.4, nginx.
```bash
pip install -r backend/requirements.txt && (cd frontend && npm ci && npm run build)
export APP_ENV=production JWT_SECRET=... CORS_ORIGINS=https://your.host        # docs/CONFIGURATION.md
export DATABASE_URL=postgresql+psycopg://plsd_app:...@host/logistics MIGRATION_DATABASE_URL=postgresql+psycopg://plsd_owner:...@host/logistics AUTO_MIGRATE=0
(cd backend && python -m app.cli check-config && python -m app.cli migrate && python -m app.cli grant-app-role plsd_app && python -m app.cli seed-scenario)   # release step
BOOTSTRAP_ADMIN_USERNAME=admin BOOTSTRAP_ADMIN_PASSWORD='<long password>' uvicorn app.main:app --host 127.0.0.1 --port 8000   # first start; run from backend/
```
Create the database, the two roles and `CREATE EXTENSION postgis` once, with an administrator (`db/init/10-roles.sh` shows exactly what to run). Serve `frontend/dist` and proxy `/api` with `frontend/nginx.conf.template` (variables `BACKEND_HOSTPORT`, `NGINX_LOCAL_RESOLVERS`, `TRUSTED_PROXY_CIDR`; `scripts/local_stack.sh` renders it). Terminate TLS in front: production cookies are `Secure`.

## 3. Reverse proxies and client addresses
nginx overwrites `X-Forwarded-For` with the client address it sees and the API trusts exactly one hop (`TRUSTED_PROXY_HOPS=1`). If another proxy or cloud load balancer sits **in front of nginx**, set `TRUSTED_PROXY_CIDR` on the web container to that proxy's address range: nginx then takes the client address from `X-Forwarded-For` (only when the TCP peer is in the range, `real_ip_recursive on`). Without it every client shares the load balancer's address, so the per-address rate limits and sign-in lock-outs apply to everyone at once. Executed locally: with the peer listed, a request carrying `X-Forwarded-For: 203.0.113.7` was recorded in the audit log as `203.0.113.7`; with a different range listed the same header was ignored and the peer address was recorded. The correct range for a hosted platform was **not** verified.

## 4. Upgrading from V6/V7
Back up the database, then run the release step (`python -m app.cli migrate`; applies `0004_event_idempotency` if missing) and `grant-app-role` again. V7 -> V7.1 adds no migration. Existing users and data are kept. A V7 Compose volume has the single `logistics` superuser role and no `plsd_*` roles: create the two roles by running `db/init/10-roles.sh` with the superuser (it is idempotent), run the release step as `plsd_owner`, and switch `DATABASE_URL` to `plsd_app`; or dump/restore into a new V7.1 stack.

## 5. Render (audit only; nothing was deployed)
`render.yaml` defines a PostgreSQL database, a private service `api` (Docker, `backend/Dockerfile`) and a public Docker web service `web` (nginx + frontend). Audited against the real configuration:
| Item | Finding |
|---|---|
| Build/start commands, versions | Docker runtime: Python 3.12 and Node 22 come from the Dockerfiles; no separate Render build command is needed. |
| Database URL | Render's `connectionString` (`postgresql://...`) is accepted: V7.1 normalises `postgres://` and `postgresql://` to the psycopg 3 driver (tested). Password strength rules apply; Render-generated passwords are expected to pass (not verified). |
| Migration strategy | `AUTO_MIGRATE` is on by default, so the API migrates at start-up using the only role Render provides (the owner). **Least-privilege separation is therefore not in effect on Render by default**; to get it, create a second role by hand, run `grant-app-role`, and set `MIGRATION_DATABASE_URL` (owner) / `DATABASE_URL` (data-only) / `AUTO_MIGRATE=0`. |
| PostGIS | Migration 0001 runs `CREATE EXTENSION IF NOT EXISTS postgis`; whether Render's database user may do so was **not verified**. |
| Health checks | `web`: `/healthz` (nginx). `api`: `/api/health/ready`; whether Render honours health checks for private services was **not verified**. |
| Frontend API URL and CORS | The browser only talks to `web` (same origin); `/api` is proxied, so no cross-origin calls and no CORS needed, but `CORS_ORIGINS` is still required in production (set it to the public `https://...onrender.com` URL). |
| Cookies, HTTPS | Production cookies are `Secure`, SameSite=Strict: they work because users reach the app over Render's HTTPS on a single origin. |
| Proxy trust | See section 3: `TRUSTED_PROXY_CIDR` on `web` must be set to Render's proxy range (left unset in the blueprint: `sync: false`). |
| Secrets | `JWT_SECRET` is generated by Render; the first-admin variables are `sync: false` (enter once, remove afterwards). Nothing secret is in the archive. |
| Persistent storage | None needed by the services (stateless; database on Render Postgres). Model artefacts are baked into the image. |
| Resources | LightGBM and scikit-learn need roughly 300-400 MB of RAM in the API process (observed ~290 MB RSS locally); choose a plan accordingly. |
| Debug settings | API docs are off and debug features absent in production. |
Deployment checklist for a person with a Render account: create the Blueprint; set `CORS_ORIGINS`, the first-admin variables and `TRUSTED_PROXY_CIDR`; wait for `api` and `web` to be live; open the `web` URL; sign in; run the evaluator walkthrough against it; then remove `BOOTSTRAP_ADMIN_PASSWORD`.

## 6. Health, restart and recovery
`/api/health/live` (process), `/api/health/ready` (database + start-up complete; use for probes), `/api/health` (components), `/api/health/detail` (models, data coverage, counters; host name for administrators only). Executed in V7.1 (local stack, API as the data-only role): clean restart keeps users, data and saved scenario runs; with PostgreSQL stopped `ready` returns 503 and data endpoints a generic 503, and everything recovers when PostgreSQL returns, without restarting the API.

## 7. Not covered
Backups and restore drills, TLS termination, log shipping, horizontal scaling (limits and lock-outs are per process), zero-downtime migrations, hosted-platform behaviour.

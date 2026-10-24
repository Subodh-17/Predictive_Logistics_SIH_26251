#!/usr/bin/env bash
# Production-like local stack WITHOUT Docker: PostgreSQL/PostGIS database + FastAPI (APP_ENV=production) + the real nginx configuration
# serving the built frontend. Used to verify the release where containers cannot be run; it exercises the same application settings,
# the same nginx template and the same migrations as the Docker images.
#
#   scripts/local_stack.sh start     # needs: a reachable PostgreSQL with PostGIS (superuser DATABASE_ADMIN_URL), nginx, `npm run build` done
#   scripts/local_stack.sh stop
#
# STACK_LEAST_PRIVILEGE=1 mirrors docker-compose.yml's role design: non-superuser owner migrates, the API runs as a data-only role.
# Without it a single superuser role does everything (development convenience only).
# Environment (all optional): STACK_DIR=/tmp/plsd-stack  WEB_PORT=18080  API_PORT=18000  DATABASE_ADMIN_URL=postgresql://USER:PASSWORD@localhost:5432/postgres
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STACK_DIR="${STACK_DIR:-/tmp/plsd-stack}"; WEB_PORT="${WEB_PORT:-18080}"; API_PORT="${API_PORT:-18000}"
mkdir -p "$STACK_DIR"
cmd="${1:-status}"

stop() {
  [ -f "$STACK_DIR/nginx.pid" ] && kill "$(cat "$STACK_DIR/nginx.pid")" 2>/dev/null || true
  [ -f "$STACK_DIR/api.pid" ] && kill "$(cat "$STACK_DIR/api.pid")" 2>/dev/null || true
  rm -f "$STACK_DIR/nginx.pid" "$STACK_DIR/api.pid"
}

start() {
  [ -d "$ROOT/frontend/dist" ] || { echo "frontend/dist missing: run 'npm ci && npm run build' in frontend/ first" >&2; exit 1; }
  : "${DATABASE_ADMIN_URL:?set DATABASE_ADMIN_URL to a superuser connection string (database 'postgres')}"
  DB_NAME="${DB_NAME:-logistics_stack_test}"
  # secrets are generated per start and kept only in $STACK_DIR (mode 600)
  umask 077
  if [ ! -f "$STACK_DIR/secrets.env" ]; then
    python3 - "$STACK_DIR/secrets.env" <<'PY'
import secrets, sys
open(sys.argv[1], "w").write(f"STACK_DB_PASSWORD={secrets.token_hex(24)}\nJWT_SECRET={secrets.token_urlsafe(48)}\nSTACK_ADMIN_PASSWORD={secrets.token_urlsafe(18)}\nSTACK_APP_DB_PASSWORD={secrets.token_hex(24)}\n")
PY
  fi
  grep -q STACK_APP_DB_PASSWORD "$STACK_DIR/secrets.env" || echo "STACK_APP_DB_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')" >> "$STACK_DIR/secrets.env"
  set -a; . "$STACK_DIR/secrets.env"; set +a
  export APP_ENV=production JWT_SECRET
  export CORS_ORIGINS="http://localhost:${WEB_PORT}" AUTO_SEED_SCENARIO=1 TRUSTED_PROXY_HOPS=1
  export BOOTSTRAP_ADMIN_USERNAME=stackadmin BOOTSTRAP_ADMIN_PASSWORD="$STACK_ADMIN_PASSWORD" LOG_LEVEL=INFO
  if [ "${STACK_LEAST_PRIVILEGE:-0}" = "1" ]; then
    # Same role design as docker-compose.yml: the administrative role only runs db/init/10-roles.sh (roles + PostGIS); `plsd_owner` (NOT a
    # superuser) migrates and seeds; the API runs as `plsd_app` (data access only) with AUTO_MIGRATE=0.
    grep -q STACK_OWNER_DB_PASSWORD "$STACK_DIR/secrets.env" || echo "STACK_OWNER_DB_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')" >> "$STACK_DIR/secrets.env"
    set -a; . "$STACK_DIR/secrets.env"; set +a
    eval "$(python3 - "$DATABASE_ADMIN_URL" "$DB_NAME" <<'PY'
import sys, shlex, psycopg
from urllib.parse import urlsplit
url, db = sys.argv[1:3]
with psycopg.connect(url, autocommit=True) as c:
    if not c.execute("select 1 from pg_database where datname=%s", (db,)).fetchone():
        c.execute(f'CREATE DATABASE "{db}"')                       # owned by the administrative role until 10-roles.sh hands it to plsd_owner
u = urlsplit(url)
for k, v in (("PGHOST", u.hostname), ("PGPORT", str(u.port or 5432)), ("PGUSER", u.username), ("PGPASSWORD", u.password or "")):
    print(f"export {k}={shlex.quote(v)}")
PY
)"
    POSTGRES_USER="$PGUSER" POSTGRES_DB="$DB_NAME" OWNER_DB_PASSWORD="$STACK_OWNER_DB_PASSWORD" APP_DB_PASSWORD="$STACK_APP_DB_PASSWORD" sh "$ROOT/db/init/10-roles.sh"
    unset PGPASSWORD PGUSER PGHOST PGPORT
    export MIGRATION_DATABASE_URL="postgresql+psycopg://plsd_owner:${STACK_OWNER_DB_PASSWORD}@localhost:5432/${DB_NAME}"
    export DATABASE_URL="postgresql+psycopg://plsd_app:${STACK_APP_DB_PASSWORD}@localhost:5432/${DB_NAME}" AUTO_MIGRATE=0
    # release step (what the compose `migrate` service runs), as the owner role
    (cd "$ROOT/backend" && python3 -m app.cli migrate && python3 -m app.cli grant-app-role plsd_app && python3 -m app.cli seed-scenario && python3 -m app.cli grant-app-role plsd_app)
    echo "API runs as the data-only role plsd_app (AUTO_MIGRATE=0); migrations ran as the non-superuser owner plsd_owner"
  else
    python3 - "$DATABASE_ADMIN_URL" "$DB_NAME" "$STACK_DB_PASSWORD" <<'PY'
import sys, psycopg
url, db, pw = sys.argv[1:4]
with psycopg.connect(url, autocommit=True) as c:
    if not c.execute("select 1 from pg_roles where rolname='svc_stack'").fetchone():
        c.execute(f"CREATE ROLE svc_stack LOGIN SUPERUSER PASSWORD '{pw}'")      # simple mode: one superuser role does everything (development convenience only)
    else:
        c.execute(f"ALTER ROLE svc_stack PASSWORD '{pw}'")
    if not c.execute("select 1 from pg_database where datname=%s", (db,)).fetchone():
        c.execute(f'CREATE DATABASE "{db}" OWNER svc_stack')
PY
    export DATABASE_URL="postgresql+psycopg://svc_stack:${STACK_DB_PASSWORD}@localhost:5432/${DB_NAME}"
  fi
  (cd "$ROOT/backend" && python3 -m app.cli check-config)
  cd "$ROOT/backend"
  nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --no-server-header > "$STACK_DIR/api.log" 2>&1 &
  echo $! > "$STACK_DIR/api.pid"          # the PID of uvicorn itself (not of a wrapper shell), so `stop` really stops it
  cd "$ROOT"
  sleep 1; kill -0 "$(cat "$STACK_DIR/api.pid")" 2>/dev/null || { echo "API process exited at start-up (port ${API_PORT} already in use?):" >&2; tail -15 "$STACK_DIR/api.log" >&2; exit 1; }
  # real nginx template, rendered the way the container entrypoint does it
  export BACKEND_HOSTPORT="127.0.0.1:${API_PORT}" NGINX_LOCAL_RESOLVERS="127.0.0.53" TRUSTED_PROXY_CIDR="${TRUSTED_PROXY_CIDR:-127.0.0.1/32}"
  envsubst '${BACKEND_HOSTPORT} ${NGINX_LOCAL_RESOLVERS} ${TRUSTED_PROXY_CIDR}' < "$ROOT/frontend/nginx.conf.template" \
    | sed "s#listen 8080#listen ${WEB_PORT}#; s#/usr/share/nginx/html#${ROOT}/frontend/dist#; s#/etc/nginx/proxy_common.conf#${ROOT}/frontend/proxy_common.conf#" > "$STACK_DIR/site.conf"
  cat > "$STACK_DIR/nginx.conf" <<CONF
pid ${STACK_DIR}/nginx.pid; error_log ${STACK_DIR}/nginx-error.log; events {}
http { include /etc/nginx/mime.types; access_log ${STACK_DIR}/nginx-access.log; client_body_temp_path ${STACK_DIR}/t1; proxy_temp_path ${STACK_DIR}/t2; fastcgi_temp_path ${STACK_DIR}/t3; uwsgi_temp_path ${STACK_DIR}/t4; scgi_temp_path ${STACK_DIR}/t5;
  include ${STACK_DIR}/site.conf; }
CONF
  nginx -c "$STACK_DIR/nginx.conf" -p "$STACK_DIR"
  for i in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:${WEB_PORT}/api/health/ready" >/dev/null 2>&1; then echo "stack ready: http://localhost:${WEB_PORT}  (admin: stackadmin / see ${STACK_DIR}/secrets.env)"; return 0; fi
    sleep 1
  done
  echo "stack did not become ready; see ${STACK_DIR}/api.log" >&2; tail -20 "$STACK_DIR/api.log" >&2; exit 1
}

case "$cmd" in
  start) stop; start ;;
  stop) stop ;;
  status) curl -fsS "http://127.0.0.1:${WEB_PORT}/api/health/ready" && echo ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac

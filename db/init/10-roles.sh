#!/bin/sh
# Runs ONCE, on first initialisation of the database volume (postgres image: /docker-entrypoint-initdb.d), as the image's administrative user.
# It only creates ROLES and the PostGIS extension; every table is created later by the versioned migrations, using the owner role.
#   plsd_owner : owns the database; runs migrations/seeding. NOT a superuser, cannot create roles or databases.
#   plsd_app   : the running API. Data access only (grants are applied by `python -m app.cli grant-app-role plsd_app` after each migration).
# Idempotent: safe to run again (re-syncs the two passwords). Passwords come from the environment and are passed as psql variables (quoted by %L).
set -eu
: "${OWNER_DB_PASSWORD:?OWNER_DB_PASSWORD is required}" "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v owner_pw="$OWNER_DB_PASSWORD" -v app_pw="$APP_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE plsd_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'owner_pw')
  WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'plsd_owner') \gexec
SELECT format('ALTER ROLE plsd_owner NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'owner_pw') \gexec
SELECT format('CREATE ROLE plsd_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_pw')
  WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'plsd_app') \gexec
SELECT format('ALTER ROLE plsd_app NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_pw') \gexec
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT format('ALTER DATABASE %I OWNER TO plsd_owner', current_database()) \gexec
SQL

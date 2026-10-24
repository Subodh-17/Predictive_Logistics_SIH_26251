# Security review (V7.1)

This document lists the controls implemented, the checks that were actually performed, and what remains open.
**The application has not been security-certified, independently reviewed or penetration-tested, and must not be described as "secure" or "audited".**

## Controls implemented

| Area | Control | Where |
|---|---|---|
| Authentication | Local accounts; passwords stored only as salted scrypt hashes (N=2^15, r=8, p=3, parameters stored per hash and upgraded on sign-in); policy: 12-128 characters, no user name inside, no trivial values. | `backend/app/security.py`, `auth.py` |
| Sessions | HS256 JWT (exp, nbf, iat, iss, aud, jti, token version all verified; `alg=none` and wrong keys rejected) carried in an HttpOnly, SameSite=Strict, Secure (production) cookie; `Authorization: Bearer` for API clients. Logout, password change, role change and deactivation bump a per-user token version, so previously issued tokens stop working immediately. The role in a token is **not** trusted; the database role is used. | `auth.py` |
| CSRF | Cookie sessions must echo an HMAC token (`X-CSRF-Token`) on every state-changing request; bearer-token requests are not cookie-borne and need none. | `auth.py` |
| Authorisation | Roles viewer < operator < admin, enforced server-side on every route (all `/api/*` except health probes, the session probe and login require sign-in). Viewer: read. Operator: also record inventory events and run simulations. Admin: also reset inventory, recompute forecasts, manage users, read the audit log. The UI hides what a role cannot do, but the server is the authority (tested by calling the endpoints directly). | `auth.py`, routers |
| Brute force / abuse | Lock-out after 5 failed sign-ins per user name + address (and 20 per address) within 15 minutes; per-address request limits (general and write); nginx adds `limit_req` for `/api/` and the login route. Limits in the application are **per process**. Unknown user names cost the same time as wrong passwords and give the same answer. | `auth.py`, `main.py`, `nginx.conf.template` |
| Input validation | Strict Pydantic models (`extra="forbid"`: no mass assignment), bounded numbers, identifier patterns for every location/supply parameter, enumerations, length limits; validation errors never echo the submitted value (a password could otherwise be reflected). All database access uses SQLAlchemy bound parameters; a test sends SQL metacharacters and a NUL byte. | `schemas.py`, `routers/common.py`, `main.py` |
| Errors | Unhandled exceptions return a generic 500 with a reference id that matches the log line; no stack traces, SQL, host names or file paths reach callers (artefact error text has the server's directory layout masked). | `main.py`, `model_service.py` |
| Headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, COOP/CORP, `Cache-Control: no-store` for `/api`, HSTS in production; nginx adds a CSP (`script-src 'self'`, no inline or remote scripts, `frame-ancestors 'none'`). | `main.py`, `nginx.conf.template` |
| CORS | Exact configured origins only, never `*`; credentials allowed only for those origins. | `config.py`, `main.py` |
| Secrets | None in the repository. `.env.example` has empty secret fields; Compose refuses to start without them; production refuses weak/placeholder/short secrets, default database passwords, wildcard CORS, insecure cookies and cheap password hashing. `scripts/generate_env.py` creates random values. The development profile uses a random per-process JWT secret, never a fixed one. | `config.py`, `docker-compose.yml` |
| Frontend | React escapes all rendered values; no `dangerouslySetInnerHTML` or `innerHTML`; the session token is never visible to scripts (HttpOnly) and nothing sensitive is kept in web storage (checked in the browser tests). | `frontend/src` |
| Logging | JSON logs with request id, user and status; credentials, tokens, cookies and database passwords are masked before writing; the audit table records sign-ins, denied actions, user changes and state-changing operations and never stores passwords or tokens. | `observability.py`, `auth.py` |
| Database | Non-destructive, checksum-protected migrations; destructive reset only for databases named dev/test/ci/scratch and never in production; statement and idle-transaction timeouts; multi-step writes are one transaction. | `migrate.py`, `database.py` |
| Containers | Non-root users, read-only root filesystem and dropped capabilities for the API, `no-new-privileges`, database and API not published on the host. (Configuration validated statically; images not built here.) | `Dockerfile`s, `docker-compose.yml` |
| Model files | LightGBM text models (no pickle/executable deserialisation); SHA-256 and schema checks; symlinks refused; version pointer restricted to a strict pattern; optional out-of-band SHA-256 pins (`ML_FORECAST_SHA256`, `ML_SHORTAGE_SHA256`) so a model replaced together with its metadata is still refused. |  `backend/app/ml/artifacts.py` |
| File uploads | The application has **no** upload endpoints or evidence storage; nothing to harden (`client_max_body_size 64k` in nginx). | - |

## Checks actually performed (V7 release)

* Automated backend tests (see `VERIFICATION_REPORT.md` for exact counts) including: configuration rules, token forgery/expiry/`alg=none`, CSRF, lock-out, role matrix over every endpoint, last-administrator protection, logout/password-change revocation, injection strings, strict body validation, rollback on failure, security headers, CORS, rate limits, log redaction, secret scan of the source tree, pinned dependencies.
* Browser tests against the production profile behind the real nginx configuration: cookie flags, no token in storage, no CSP violations on any page, server refusal of actions attempted from the page, session revocation, WCAG 2 A/AA scan (axe-core).
* Dependency audits are summarised in the table below (V7.1).


## Added in V7

| Area | Control / finding | Evidence |
|---|---|---|
| Least-privilege database role | `MIGRATION_DATABASE_URL` (DDL-capable) is separate from `DATABASE_URL` (data-only); `AUTO_MIGRATE=0` makes start-up verify the schema read-only; `python -m app.cli grant-app-role ROLE` grants DML on the application tables and nothing else (no CREATE on the schema, no TRUNCATE, read-only migration history). Whether the superuser used by the Compose default is acceptable is a deployment decision: **the Compose file still runs the application as the database owner**; use the split topology for any shared deployment. | `test_migrations.py` (a real restricted PostgreSQL role is denied CREATE/DROP/ALTER/TRUNCATE/migration-history writes/extension creation); the API ran as such a role in `scripts/local_stack.sh` with `STACK_LEAST_PRIVILEGE=1` and every state-changing endpoint worked |
| Duplicate / replayed requests | Optional `event_id` idempotency key on inventory events (unique index; checked under the row lock). Without a key a repeated request is applied twice (V6 behaviour). | `test_logistics_integrity.py` incl. concurrent duplicates |
| Lost updates | Inventory rows are locked (`FOR UPDATE`) while an event is applied; 30 concurrent events change stock by exactly their sum. | same |
| Database host disclosure | The database host/name is returned to administrators only. | `test_api_hardening.py` |
| Cross-organisation isolation | **Not applicable and not implemented:** the application is single-tenant (one deployment, one organisation, no tenant column anywhere). Running several organisations in one deployment would be unsafe. | - |
| Session expiry / logout | Token expiry is enforced on every request (expired and not-yet-valid tokens rejected); logout, password change, role change and deactivation revoke tokens server-side; a browser test shows an open session ending when an admin deactivates the user. | `test_auth_api.py`, `test_security_core.py`, browser suite |
| Rate limits in the supported topology | Behind the bundled nginx (first hop, overwrites `X-Forwarded-For`) with `TRUSTED_PROXY_HOPS=1`: a spoofed header did not change the client address used (checked through the local nginx stack). nginx `limit_req` is shared by all API workers; the application's own limiter is per process. Behind an additional platform proxy (Render, a cloud load balancer) all clients may share one address unless the proxy chain is configured. **Not verified on any hosted platform.** | `scripts/local_stack.sh` run, `test_security_core.py::client_ip` |

## Dependency advisories (V7.1, freshly executed)
| Scope | Tool | Result |
|---|---|---|
| Python runtime (pinned lock) | `pip-audit -r backend/requirements.txt --no-deps` | no known vulnerabilities |
| npm production dependencies | `npm audit --omit=dev` | 0 vulnerabilities |
| npm including build tooling | `npm audit` | **5 high-severity reports, all from one advisory** (below) |

**Resolved in V7.1** by compatible updates (Vite 5.4 -> 7.3.7 and `@vitejs/plugin-react` 4.7, plus `overrides` for `braces` ^3.0.3 and `postcss-selector-parser` ^7.1.6): `esbuild` (dev-server request exposure, GHSA-67mh-4wv8-2f99), `postcss-selector-parser`, and the `vite` advisories (GHSA-4w7w-66w2-5vf9 path traversal in optimised-deps `.map` handling, GHSA-fx2h-pf6j-xcff `server.fs.deny` bypass on Windows, launch-editor NTLM disclosure GHSA-v6wh-96g9-6wx3). The update was judged safe because typecheck and build pass, the generated stylesheet has an identical selector set (356 selectors, 0 differences) and every browser suite was re-run on the new build; Vite 7 needs Node >= 22.12 (the image uses `node:22-alpine`). The `postcss-selector-parser` override forces a newer major than Tailwind 3 declares; it is exercised by the build only (no Tailwind test suite), so treat it as the least-certain part of the change.

**Unresolved:** `braces` - "stack-exhaustion denial of service through deeply nested patterns", GHSA-vfj7-8cjw-p6xm, reported for every version (no patched release; `npm audit fix --force` offers no usable fix). Dependency paths: `tailwindcss -> chokidar -> braces` and `tailwindcss -> fast-glob -> micromatch -> braces`. Exposure: build-time only (Tailwind's glob matching of the project's own source paths); `braces` is not in the shipped bundle or any container image's runtime, and no user-controlled pattern ever reaches it. Reassess when Tailwind or its dependants publish a release that drops or patches `braces`.

## Added in V7.1
| Area | Finding / control | Evidence |
|---|---|---|
| Compose database privileges | V7's Compose ran the API as the database administrator. V7.1 separates `plsd_admin` (volume initialisation only), `plsd_owner` (non-superuser; one-shot migrate/grant/seed) and `plsd_app` (data-only API without owner credentials). Nothing was solved by granting superuser to the application role. | init script executed against PostgreSQL; role attributes verified (`rolsuper` false for both); API ran as `plsd_app`; DDL denied |
| Migration role | A non-superuser owner runs every migration (PostGIS pre-created by the admin; `CREATE EXTENSION IF NOT EXISTS` is a no-op) | `test_role_init_script_runs_against_a_real_database_and_is_idempotent` |
| Client address behind a load balancer | Without trusting the platform proxy, all users shared one address (shared rate limits; lock-out of everyone after 20 failures). `TRUSTED_PROXY_CIDR` fixes this; default trusts nobody; a spoofed header from an untrusted peer is ignored | executed through nginx (both cases) |
| Database URL schemes | `postgres://` and `postgresql://` normalised to the psycopg 3 driver | `test_config.py` |
| Error handling under hostile responses | The UI survives empty, failed and truncated API responses without uncaught exceptions and shows only the generic error reference | `e2e_v71_gis_resilience.py` |

## Reassessed, unchanged
Session expiry, CSRF, CORS, password hashing, rate limiting, input validation, log redaction and secret handling were not changed in V7.1; their V7 tests were re-run (see `VERIFICATION_REPORT.md`). No independent penetration test has been performed.

## Not covered (unchanged)

MFA, password recovery, malware scanning (there are no uploads), encryption at rest, independent penetration testing, a formal threat model, secrets management beyond environment variables, backup/restore procedures.

## Other known limitations

* No independent security review, penetration test, threat model sign-off or fuzzing.
* No multi-factor authentication, password-reset by e-mail, or single sign-on; accounts are administered by an admin.
* Rate limits and the sign-in lock-out are in-process (per worker/replica) and lost on restart; enforce limits at a shared proxy for multi-replica deployments. On platforms where another proxy sits in front of nginx, per-address limits see that proxy's address unless the forwarding configuration is adapted.
* Tokens are stateless apart from the per-user version: a stolen token is valid until expiry or until that user signs out / changes password / is deactivated. Logout therefore signs the user out everywhere.
* No encryption at rest and no TLS termination inside the containers (terminate TLS in front; `COOKIE_SECURE` requires it, except on localhost).
* The simulated IoT scanner has no device authentication; it uses an operator account.
* The CSP allows inline *styles* (needed by Leaflet and charts) and loads map tiles from `tile.openstreetmap.org`; that host sees users' IP addresses and viewed tiles. Remove the map tiles or self-host them for air-gapped or sensitive use.
* The in-container checks of `docker compose` and the Render blueprint were not executed.

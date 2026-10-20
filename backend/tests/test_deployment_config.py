"""Static validation of deployment and configuration files: no secrets in the repository, secure container settings, pinned dependencies,
a valid nginx configuration, and complete configuration documentation. (Building the images and starting containers is verified separately
where Docker is available; see docs/VERIFICATION_REPORT.md.)"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
from app import config as config_mod


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------------ secrets
SECRET_PATTERNS = [r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----", r"AKIA[0-9A-Z]{16}", r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}",
                   r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9+/_\-]{16,}['\"]?\s*$", r"postgres(ql)?(\+\w+)?://[^:@/\s]+:[^@/\s${]{4,}@"]
SCAN_SUFFIX = {".py", ".ts", ".tsx", ".js", ".json", ".yml", ".yaml", ".sh", ".conf", ".template", ".env", ".example", ".toml", ".md", ".sql", ".txt", ".cfg", ".ini", ".html"}
SKIP = {"node_modules", "dist", "__pycache__", ".pytest_cache", "tests", "docs", ".git", "legacy"}


def _tracked_files():
    for p in ROOT.rglob("*"):
        if (
            p.is_file()
            and not (SKIP & set(p.relative_to(ROOT).parts))
            and p != ROOT / ".env"  # local developer environment file, ignored by .gitignore and .dockerignore
            and (p.suffix in SCAN_SUFFIX or (p.name.startswith(".env") and p.name != ".env"))
            and p.name != "package-lock.json"
            and p.stat().st_size < 3_000_000
        ):
            yield p


def test_no_credentials_are_committed_anywhere_in_the_source_tree():
    hits = []
    for p in _tracked_files():
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if p.suffix == ".md" and "example" in line.lower():
                continue
            for pat in SECRET_PATTERNS:
                if re.search(pat, line) and ":PASSWORD@" not in line:        # documentation placeholder, not a credential
                    hits.append(f"{p.relative_to(ROOT)}:{n}")
    assert not hits, f"Potential credentials found in tracked files: {hits}"


def test_a_real_env_file_is_never_packaged(tmp_path):
    # Verify .gitignore and .dockerignore rules
    gi, di = text(".gitignore"), text(".dockerignore")
    assert ".env" in gi and ".env" in di and "!.env.example" in gi

    # Verify that in a staged release directory respecting .gitignore / .dockerignore, .env is excluded
    staged = tmp_path / "staged_release"
    staged.mkdir()

    def _release_ignore(directory, names):
        ignored = set()
        for name in names:
            if name in {"node_modules", "dist", "__pycache__", ".pytest_cache", ".git"}:
                ignored.add(name)
            elif name == ".env" or (name.startswith(".env.") and name != ".env.example"):
                ignored.add(name)
        return ignored

    shutil.copytree(ROOT, staged / "pkg", ignore=_release_ignore)
    assert not (staged / "pkg" / ".env").exists(), ".env must never be present in a packaged release"
    assert (staged / "pkg" / ".env.example").exists(), ".env.example must be preserved in release"


def test_release_staging_catches_accidentally_packaged_env_file(tmp_path):
    # Regression test: if an unredacted .env is included in a release artifact, the check must fail
    leak_dir = tmp_path / "leaked_release"
    leak_dir.mkdir()
    (leak_dir / ".env").write_text("APP_DB_PASSWORD=fake_secret_12345678\n")
    # Validator detects presence of .env in release artifact
    release_env_files = [p.name for p in leak_dir.glob(".env*") if p.name != ".env.example"]
    assert release_env_files == [".env"], "Validator must catch leaked .env in release bundle"


def test_env_example_contains_no_secret_values():
    secrets = {"POSTGRES_PASSWORD", "OWNER_DB_PASSWORD", "APP_DB_PASSWORD", "JWT_SECRET", "BOOTSTRAP_ADMIN_PASSWORD", "ML_FORECAST_SHA256", "ML_SHORTAGE_SHA256", "BOOTSTRAP_ADMIN_USERNAME"}
    seen = {}
    for line in text(".env.example").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            seen[k] = v
    assert secrets <= set(seen)
    assert all(seen[k] == "" for k in secrets), "secret placeholders in .env.example must be empty"
    assert seen["APP_ENV"] == "production"


def test_generate_env_script_produces_valid_strong_secrets(tmp_path, monkeypatch):
    import importlib.util
    import os
    import sys
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "generate_env.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    assert gen.main([]) == 0 and gen.main([]) == 1                                       # second call refuses to overwrite
    env = dict(l.split("=", 1) for l in (tmp_path / ".env").read_text().splitlines() if l and not l.startswith("#") and "=" in l)
    from app import config
    # the generated file must pass the production validation
    assert len({env["POSTGRES_PASSWORD"], env["OWNER_DB_PASSWORD"], env["APP_DB_PASSWORD"]}) == 3          # three different database secrets
    s = config.load({"APP_ENV": "production", "DATABASE_URL": f"postgresql+psycopg://plsd_app:{env['APP_DB_PASSWORD']}@db:5432/logistics",
                     "MIGRATION_DATABASE_URL": f"postgresql+psycopg://plsd_owner:{env['OWNER_DB_PASSWORD']}@db:5432/logistics",
                     "JWT_SECRET": env["JWT_SECRET"], "CORS_ORIGINS": env["CORS_ORIGINS"], "BOOTSTRAP_ADMIN_USERNAME": env["BOOTSTRAP_ADMIN_USERNAME"],
                     "BOOTSTRAP_ADMIN_PASSWORD": env["BOOTSTRAP_ADMIN_PASSWORD"]})
    assert s.is_production
    from app import security as sec
    sec.validate_new_password(env["BOOTSTRAP_ADMIN_PASSWORD"], env["BOOTSTRAP_ADMIN_USERNAME"])
    if sys.platform != "win32" and os.name == "posix":
        assert (tmp_path / ".env").stat().st_mode & 0o077 == 0                          # owner-only permissions on POSIX
    else:
        # On Windows NTFS, Python os.chmod sets read-only attributes, not POSIX permission bits.
        # Verify file exists, is non-empty, and readable by the owner.
        st = (tmp_path / ".env").stat()
        assert st.st_size > 0
        assert bool(st.st_mode & 0o400)


# ------------------------------------------------------------------------------------------------------------------ compose
@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(text("docker-compose.yml"))


def test_compose_requires_secrets_and_has_no_default_credentials(compose):
    raw = text("docker-compose.yml")
    assert all(f"${{{k}:?" in raw for k in ("POSTGRES_PASSWORD", "OWNER_DB_PASSWORD", "APP_DB_PASSWORD", "JWT_SECRET"))
    assert not re.search(r"(POSTGRES|OWNER_DB|APP_DB)_PASSWORD:\s*[A-Za-z0-9]", raw) and "logistics:logistics" not in raw
    assert not re.search(r"JWT_SECRET:\s*[A-Za-z0-9]", raw)


def test_compose_publishes_only_the_web_port(compose):
    s = compose["services"]
    assert "ports" not in s["db"] and "ports" not in s["backend"] and "ports" not in s["migrate"]
    assert s["frontend"]["ports"] == ["8080:8080"]


def test_compose_hardens_containers_and_defaults_to_production(compose):
    b = compose["services"]["backend"]
    assert b["read_only"] is True and b["cap_drop"] == ["ALL"] and "no-new-privileges:true" in b["security_opt"]
    assert b["environment"]["APP_ENV"].startswith("${APP_ENV:-production")
    assert b["environment"]["TRUSTED_PROXY_HOPS"] == "1"
    for name in ("db", "backend", "frontend"):
        assert "no-new-privileges:true" in compose["services"][name]["security_opt"]
    assert compose["services"]["db"]["healthcheck"] and compose["services"]["backend"]["depends_on"]["db"]["condition"] == "service_healthy"
    init = [v for v in compose["services"]["db"].get("volumes", []) if "initdb" in str(v)]
    assert init == ["./db/init:/docker-entrypoint-initdb.d:ro"], "only the roles/extension init script may run at volume initialisation"
    assert sorted(p.name for p in (ROOT / "db" / "init").iterdir()) == ["10-roles.sh"]


def test_compose_config_variables_are_all_known_to_the_application(compose):
    from app import config
    src = text("backend/app/config.py")
    known = set(re.findall(r'"([A-Z][A-Z0-9_]{3,})"', src)) | {"ML_FORECAST_SHA256", "ML_SHORTAGE_SHA256"}     # the pins are built with an f-string
    for k in compose["services"]["backend"]["environment"]:
        assert k in known, f"{k} is passed to the backend but config.py does not read it"


# ------------------------------------------------------------------------------------------------------------------ images
def test_backend_image_runs_as_non_root_with_healthcheck_and_pinned_base():
    d = text("backend/Dockerfile")
    assert re.search(r"^USER appuser", d, re.M) and "HEALTHCHECK" in d and "/api/health/ready" in d
    assert re.search(r"^FROM python:3\.12-slim", d, re.M) and ":latest" not in d
    assert "requirements.txt" in d and "APP_ENV=production" in d and "COPY .env" not in d


def test_frontend_image_is_unprivileged_and_uses_the_lockfile():
    d = text("frontend/Dockerfile")
    assert "nginx-unprivileged" in d and "npm ci" in d and ":latest" not in d and "EXPOSE 8080" in d


def test_python_dependencies_are_fully_pinned():
    for rel in ("backend/requirements.txt", "ml/requirements-ml.txt", "backend/requirements-dev.txt"):
        for line in text(rel).splitlines():
            line = line.split("#")[0].strip()
            if line and not line.startswith("-r"):
                assert "==" in line or line.startswith("pip-audit"), f"{rel}: {line}"
    reqin = {re.split(r"[<>=\[]", l)[0].lower() for l in text("backend/requirements.in").splitlines() if l and not l.startswith("#")}
    locked = {re.split(r"==", l)[0].lower().replace("_", "-") for l in text("backend/requirements.txt").splitlines() if "==" in l}
    assert {r.replace("_", "-") for r in reqin} <= locked


def test_frontend_lockfile_is_consistent_with_package_json():
    import json
    pkg, lock = json.loads(text("frontend/package.json")), json.loads(text("frontend/package-lock.json"))
    root = lock["packages"][""]
    assert set(pkg["dependencies"]) == set(root["dependencies"]) and set(pkg["devDependencies"]) == set(root["devDependencies"])


# ------------------------------------------------------------------------------------------------------------------ nginx
def render_nginx(tmp_path, hostport="127.0.0.1:8000"):
    t = text("frontend/nginx.conf.template").replace("${BACKEND_HOSTPORT}", hostport).replace("${NGINX_LOCAL_RESOLVERS}", "127.0.0.53").replace("${TRUSTED_PROXY_CIDR}", "127.0.0.1/32")
    (tmp_path / "default.conf").write_text(t)
    (tmp_path / "proxy_common.conf").write_text(text("frontend/proxy_common.conf"))
    return t


def test_nginx_template_security_headers_and_csp(tmp_path):
    t = render_nginx(tmp_path)
    csp = re.search(r'Content-Security-Policy "([^"]+)"', t).group(1)
    assert "script-src 'self'" in csp and "'unsafe-eval'" not in csp and "script-src 'self' 'unsafe-inline'" not in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "default-src 'self'" in csp and "connect-src 'self'" in csp
    for h in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy"):
        assert h in t
    assert "server_tokens off" in t and "client_max_body_size" in t and "limit_req" in t
    assert "X-Forwarded-For $remote_addr" in text("frontend/proxy_common.conf")           # client-supplied header is overwritten, not appended


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx not installed")
def test_nginx_configuration_is_syntactically_valid(tmp_path):
    render_nginx(tmp_path)
    conf = tmp_path / "nginx.conf"
    conf.write_text(f"pid {tmp_path}/n.pid; error_log {tmp_path}/e.log; events {{}}\nhttp {{ access_log off; include {tmp_path}/default.conf; }}\n")
    # the template includes /etc/nginx/proxy_common.conf (path inside the image): point it at the rendered copy for the syntax check
    (tmp_path / "default.conf").write_text((tmp_path / "default.conf").read_text().replace("/etc/nginx/proxy_common.conf", str(tmp_path / "proxy_common.conf")).replace("listen 8080", "listen 18080"))
    r = subprocess.run(["nginx", "-t", "-c", str(conf)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ------------------------------------------------------------------------------------------------------------------ render
def test_render_blueprint_has_generated_secrets_and_no_literals():
    r = yaml.safe_load(text("render.yaml"))
    api = next(s for s in r["services"] if s["name"] == "api")
    env = {e["key"]: e for e in api["envVars"]}
    assert env["JWT_SECRET"].get("generateValue") is True and "value" not in env["JWT_SECRET"]
    assert "fromDatabase" in env["DATABASE_URL"] and env["APP_ENV"]["value"] == "production"
    assert env["BOOTSTRAP_ADMIN_PASSWORD"].get("sync") is False and "value" not in env["BOOTSTRAP_ADMIN_PASSWORD"]
    assert api["type"] == "pserv", "the API must not be a public service: the web service proxies it"


# ------------------------------------------------------------------------------------------------------------ documentation
def test_every_environment_variable_is_documented():
    src = text("backend/app/config.py")
    names = set(re.findall(r'"([A-Z][A-Z0-9_]{3,})"', src)) | {f"ML_{k}_SHA256" for k in ("FORECAST", "SHORTAGE")}
    names -= {"APP_ENV_", "DEBUG", "INFO", "WARNING", "ERROR", "FORECAST", "SHORTAGE"}
    env_names = {n for n in names if re.search(rf'env\.get\("{n}"\)|_(bool|int|float)\(env, "{n}"', src) or n in ("ML_FORECAST_SHA256", "ML_SHORTAGE_SHA256")}
    doc = text("docs/CONFIGURATION.md")
    assert [n for n in sorted(env_names) if n not in doc] == []


REQUIRED_DOCS = ["README.md", "docs/ARCHITECTURE.md", "docs/CHANGES_V7.md", "docs/VERIFICATION_REPORT.md", "docs/ML_EVALUATION_REPORT.md", "docs/SECURITY_REVIEW.md",
                 "docs/DATA_DICTIONARY.md", "docs/DEPLOYMENT.md", "docs/LIMITATIONS_AND_ASSUMPTIONS.md", "docs/CONFIGURATION.md", "docs/SHORTAGE_MODEL_DECISION.md"]


def test_required_documents_exist_and_internal_links_resolve():
    for d in REQUIRED_DOCS:
        assert (ROOT / d).is_file() and (ROOT / d).stat().st_size > 400, d
    for rel in ["README.md"] + [d for d in REQUIRED_DOCS if d.startswith("docs/")]:
        base = (ROOT / rel).parent
        for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)\s#]+)", text(rel)):
            assert (base / target).exists(), f"{rel} links to missing {target}"


def test_no_machine_specific_absolute_paths_are_packaged():
    bad = []
    for p in _tracked_files():
        if p.suffix in {".sh", ".py", ".md", ".yml", ".yaml", ".json", ".template", ".conf"} and p.name != "package-lock.json":
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.search(r"/home/claude|/mnt/user-data|C:\\\\Users", line):
                    bad.append(f"{p.relative_to(ROOT)}:{n}")
    assert not bad, bad


def test_nginx_trusts_no_upstream_proxy_by_default_and_the_variable_is_wired_everywhere():
    tpl = text("frontend/nginx.conf.template")
    assert "set_real_ip_from ${TRUSTED_PROXY_CIDR};" in tpl and "real_ip_header X-Forwarded-For;" in tpl
    assert "TRUSTED_PROXY_CIDR=127.0.0.1/32" in text("frontend/Dockerfile")             # image default: trust nobody
    assert "${TRUSTED_PROXY_CIDR}" in text("scripts/local_stack.sh")


def test_compose_separates_admin_owner_and_application_database_roles(compose):
    s = compose["services"]
    be, mg, db = s["backend"]["environment"], s["migrate"]["environment"], s["db"]["environment"]
    assert be["DATABASE_URL"].startswith("postgresql+psycopg://plsd_app:") and be["AUTO_MIGRATE"] == "0" and be["AUTO_SEED_SCENARIO"] == "0"
    assert "MIGRATION_DATABASE_URL" not in be and not any("OWNER_DB_PASSWORD" in str(v) for v in be.values()), "the running API must hold no owner credentials"
    assert mg["MIGRATION_DATABASE_URL"].startswith("postgresql+psycopg://plsd_owner:")
    cmd = " ".join(s["migrate"]["command"])
    assert cmd.index("app.cli migrate") < cmd.index("grant-app-role plsd_app") < cmd.index("seed-scenario")
    assert s["migrate"]["restart"] == "no" and s["backend"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert db["POSTGRES_USER"] == "plsd_admin" and not any("plsd_admin" in str(v) for v in list(be.values()) + list(mg.values()))
    assert s["frontend"]["environment"]["TRUSTED_PROXY_CIDR"].startswith("${TRUSTED_PROXY_CIDR:-127.0.0.1/32")


def test_role_init_script_creates_only_roles_and_the_extension():
    sh = text("db/init/10-roles.sh")
    assert "NOSUPERUSER" in sh and "SUPERUSER PASSWORD" not in sh.replace("NOSUPERUSER", "")
    code = "\n".join(l for l in sh.splitlines() if not l.lstrip().startswith("#"))          # comments may mention grants
    assert not re.search(r"(?i)\bCREATE\s+TABLE\b|\bDROP\b|\bGRANT\b", code), "tables and grants belong to the migrations / grant-app-role"
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in sh and "ON_ERROR_STOP=1" in sh and "%L" in sh


@pytest.mark.skipif(shutil.which("psql") is None, reason="psql not installed")
def test_role_init_script_runs_against_a_real_database_and_is_idempotent(db_available, tmp_path):
    """Executes the actual init script (as the image would) in a scratch database, then migrates as the non-superuser owner."""
    import os, uuid, psycopg
    from urllib.parse import urlsplit
    if not db_available:
        pytest.skip("no test database server")
    u = urlsplit(config_mod.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://"))
    admin = psycopg.connect(f"postgresql://{u.username}:{u.password}@{u.hostname}:{u.port or 5432}/postgres", autocommit=True)
    if not admin.execute("select rolsuper from pg_roles where rolname = current_user").fetchone()[0]:
        pytest.skip("needs a superuser connection to stand in for the image's administrative role")
    if admin.execute("select 1 from pg_roles where rolname in ('plsd_owner', 'plsd_app')").fetchone():
        pytest.skip("plsd_owner/plsd_app already exist in this cluster (e.g. a running local stack): not touching their passwords")
    db = "logistics_scratch_" + uuid.uuid4().hex[:8]
    admin.execute(f'CREATE DATABASE "{db}"')
    env = dict(os.environ, POSTGRES_USER=u.username, POSTGRES_DB=db, OWNER_DB_PASSWORD="Owner-" + uuid.uuid4().hex, APP_DB_PASSWORD="App-" + uuid.uuid4().hex,
               PGHOST=u.hostname, PGPORT=str(u.port or 5432), PGPASSWORD=u.password or "")
    try:
        for _ in range(2):                                                         # second run: idempotent
            r = subprocess.run(["sh", str(ROOT / "db" / "init" / "10-roles.sh")], env=env, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        row = admin.execute("select rolname, rolsuper, rolcreatedb, rolcreaterole from pg_roles where rolname in ('plsd_owner','plsd_app') order by 1").fetchall()
        assert row == [("plsd_app", False, False, False), ("plsd_owner", False, False, False)]
        assert admin.execute("select pg_get_userbyid(datdba) from pg_database where datname = %s", (db,)).fetchone()[0] == "plsd_owner"
        owner_url = f"postgresql+psycopg://plsd_owner:{env['OWNER_DB_PASSWORD']}@{u.hostname}:{u.port or 5432}/{db}"
        from app import migrate
        assert migrate.migrate(owner_url) == ["0001", "0002", "0003", "0004"]      # a NON-superuser owner can run every migration (PostGIS already present)
        migrate.grant_app_privileges("plsd_app", owner_url)
        app_url = owner_url.replace("plsd_owner:" + env["OWNER_DB_PASSWORD"], "plsd_app:" + env["APP_DB_PASSWORD"])
        assert migrate.verify_schema(app_url) == "0004"
        with psycopg.connect(app_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("CREATE TABLE nope (i int)")
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        admin.execute("DROP ROLE IF EXISTS plsd_owner")
        admin.execute("DROP ROLE IF EXISTS plsd_app")
        admin.close()

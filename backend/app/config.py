"""Application configuration.

Three profiles, selected by ``APP_ENV``:

* ``development`` (default) - convenient defaults for a local machine. Nothing here is safe to expose to a network.
* ``production``  - every security-relevant setting must be supplied explicitly; a missing or placeholder secret makes the
  process refuse to start with a message listing *all* problems (see ``ConfigError``). No secret has a built-in default.
* ``test``        - used by the automated tests; behaves like development but never auto-seeds a database.

``load(env)`` is a pure function over a mapping so the validation rules are unit-tested without touching ``os.environ``.
"""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

ENVIRONMENTS = ("development", "test", "production")
DEFAULT_DEV_DATABASE_URL = "postgresql+psycopg://logistics_dev@localhost:5432/logistics_dev"
_PLACEHOLDER = re.compile(r"(change[-_ ]?me|replace[-_ ]?me|your[-_ ]?(secret|password)|example|placeholder|todo|password123|secret123)", re.I)
_KNOWN_WEAK_PASSWORDS = {"logistics", "postgres", "password", "admin", "root", "changeme", "123456", "letmein"}
DATA_NOTICE = ("Illustrative scenario: fictional locations and simulated telemetry, not operational records. "
               "Decision support only; final logistics decisions remain with authorised personnel.")


class ConfigError(RuntimeError):
    """One or more configuration problems; ``problems`` lists every one of them."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid configuration:\n  - " + "\n  - ".join(problems))


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(env: Mapping[str, str], key: str, default: int, problems: list[str], lo: int | None = None, hi: int | None = None) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        problems.append(f"{key} must be an integer (got {raw!r})")
        return default
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        problems.append(f"{key} must be between {lo} and {hi} (got {v})")
        return default
    return v


def _float(env: Mapping[str, str], key: str, default: float, problems: list[str]) -> float:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        problems.append(f"{key} must be a number (got {raw!r})")
        return default


def normalise_database_url(url: str) -> str:
    """Hosted platforms hand out `postgres://` or `postgresql://` URLs; the application always uses the psycopg 3 driver explicitly so the
    result never depends on SQLAlchemy's default-driver choice."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def database_target(url: str) -> str:
    """host:port/database of a SQLAlchemy URL - never includes the user name or password (safe to log)."""
    try:
        u = urlsplit(url.replace("postgresql+psycopg://", "postgresql://"))
        return f"{u.hostname or '?'}:{u.port or 5432}/{(u.path or '/').lstrip('/')}"
    except ValueError:
        return "unparseable-database-url"


def database_name(url: str) -> str:
    return database_target(url).rsplit("/", 1)[-1]


def database_password(url: str) -> str | None:
    try:
        return urlsplit(url.replace("postgresql+psycopg://", "postgresql://")).password
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    cors_origins: tuple[str, ...]
    db_dir: Path
    migrations_dir: Path
    migration_database_url: str | None
    auto_migrate: bool
    auto_seed_scenario: bool
    db_wait_seconds: int
    jwt_secret: str
    jwt_secret_is_ephemeral: bool
    access_token_minutes: int
    cookie_secure: bool
    enable_api_docs: bool
    trusted_proxy_hops: int
    rate_limit_per_minute: int
    rate_limit_write_per_minute: int
    login_max_failures: int
    login_window_seconds: int
    password_scrypt_log_n: int
    bootstrap_admin_username: str | None
    bootstrap_admin_password: str | None
    ml_artifact_dir: Path
    ml_reports_dir: Path
    ml_pins: dict = field(default_factory=dict)
    forecast_model_mode: str = "auto"
    ml_recompute_timeout_s: float = 30.0
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def load(env: Mapping[str, str] | None = None, *, root: Path | None = None) -> Settings:
    env = os.environ if env is None else env
    root = root or Path(__file__).resolve().parents[2]
    problems: list[str] = []

    app_env = (env.get("APP_ENV") or "development").strip().lower()
    if app_env not in ENVIRONMENTS:
        problems.append(f"APP_ENV must be one of {', '.join(ENVIRONMENTS)} (got {app_env!r})")
        app_env = "production"          # validate as strictly as possible when the profile itself is unclear
    prod = app_env == "production"

    # ---- database ---------------------------------------------------------------------------------------------
    db_url = normalise_database_url((env.get("DATABASE_URL") or "").strip())
    if not db_url:
        if prod:
            problems.append("DATABASE_URL is required in production (postgresql+psycopg://USER:PASSWORD@HOST:5432/DB)")
        db_url = DEFAULT_DEV_DATABASE_URL
    elif not db_url.startswith("postgresql+psycopg://"):
        problems.append("DATABASE_URL must start with postgresql+psycopg://, postgresql:// or postgres://")
    if prod and db_url != DEFAULT_DEV_DATABASE_URL:
        pw = database_password(db_url)
        if not pw:
            problems.append("DATABASE_URL has no password; production databases must require one")
        elif pw.lower() in _KNOWN_WEAK_PASSWORDS or _PLACEHOLDER.search(pw) or len(pw) < 12:
            problems.append("DATABASE_URL uses a weak, default or placeholder password (need >= 12 characters, not a known default)")

    # least privilege: optional separate (DDL-capable) connection used only for migrations / seeding / privilege grants
    mig_url = normalise_database_url((env.get("MIGRATION_DATABASE_URL") or "").strip()) or None
    if mig_url and not mig_url.startswith("postgresql+psycopg://"):
        problems.append("MIGRATION_DATABASE_URL must start with postgresql+psycopg:// (or postgresql://)")
    if prod and mig_url:
        mpw = database_password(mig_url)
        if not mpw or mpw.lower() in _KNOWN_WEAK_PASSWORDS or _PLACEHOLDER.search(mpw) or len(mpw) < 12:
            problems.append("MIGRATION_DATABASE_URL uses a missing, weak, default or placeholder password")
    auto_migrate = _bool(env, "AUTO_MIGRATE", True)
    if not auto_migrate and mig_url is None and prod:
        pass        # allowed: migrations are then applied by a separate release step (python -m app.cli migrate with MIGRATION_DATABASE_URL)

    # ---- CORS -------------------------------------------------------------------------------------------------
    cors_raw = env.get("CORS_ORIGINS")
    if cors_raw is None or not cors_raw.strip():
        if prod:
            problems.append("CORS_ORIGINS is required in production (comma-separated exact origins, e.g. https://logistics.example.org)")
        cors_raw = "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173"
    cors = tuple(o.strip().rstrip("/") for o in cors_raw.split(",") if o.strip())
    for o in cors:
        u = urlsplit(o)
        if "*" in o:
            problems.append("CORS_ORIGINS must not contain wildcards")
        elif u.scheme not in ("http", "https") or not u.netloc or u.path not in ("", "/"):
            problems.append(f"CORS_ORIGINS entry {o!r} is not a valid origin (scheme://host[:port])")
        elif prod and u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1"):
            problems.append(f"CORS_ORIGINS entry {o!r} must use https in production")

    # ---- JWT --------------------------------------------------------------------------------------------------
    jwt_secret = (env.get("JWT_SECRET") or "").strip()
    ephemeral = False
    if not jwt_secret:
        if prod:
            problems.append("JWT_SECRET is required in production (generate: python -c \"import secrets; print(secrets.token_urlsafe(48))\")")
        jwt_secret, ephemeral = secrets.token_urlsafe(48), True      # development/test: random per process, never a fixed value
    else:
        if len(jwt_secret) < 32:
            problems.append("JWT_SECRET must be at least 32 characters")
        if _PLACEHOLDER.search(jwt_secret) or len(set(jwt_secret)) < 8:
            problems.append("JWT_SECRET looks like a placeholder or has too little variety; generate a random value")

    # ---- misc security knobs ----------------------------------------------------------------------------------
    ttl = _int(env, "ACCESS_TOKEN_MINUTES", 60, problems, 5, 1440)
    cookie_secure = _bool(env, "COOKIE_SECURE", prod)
    if prod and not cookie_secure:
        problems.append("COOKIE_SECURE must not be disabled in production")
    docs = _bool(env, "ENABLE_API_DOCS", not prod)
    hops = _int(env, "TRUSTED_PROXY_HOPS", 0, problems, 0, 5)
    rl = _int(env, "RATE_LIMIT_PER_MINUTE", 600, problems, 10, 100000)
    rlw = _int(env, "RATE_LIMIT_WRITE_PER_MINUTE", 60, problems, 1, 10000)
    lmax = _int(env, "LOGIN_MAX_FAILURES", 5, problems, 1, 100)
    lwin = _int(env, "LOGIN_WINDOW_SECONDS", 900, problems, 10, 86400)
    logn = _int(env, "PASSWORD_SCRYPT_LOG_N", 15, problems, 10, 20)
    if prod and logn < 15:
        problems.append("PASSWORD_SCRYPT_LOG_N must be >= 15 in production")
    admin_u = (env.get("BOOTSTRAP_ADMIN_USERNAME") or "").strip() or None
    admin_p = env.get("BOOTSTRAP_ADMIN_PASSWORD") or None
    if (admin_u is None) != (admin_p is None):
        problems.append("BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD must be set together (or both left unset)")

    # ---- data / ML ---------------------------------------------------------------------------------------------
    seed = _bool(env, "AUTO_SEED_SCENARIO", _bool(env, "AUTO_INIT_DB", not prod and app_env != "test"))
    wait = _int(env, "DB_WAIT_SECONDS", 60, problems, 0, 3600)
    ml_dir = Path(env.get("ML_DIR") or str(root / "ml"))
    mode = (env.get("FORECAST_MODEL_MODE") or "auto").strip().lower()
    if mode not in ("auto", "ml", "statistical"):
        problems.append("FORECAST_MODEL_MODE must be one of: auto, ml, statistical")
        mode = "auto"
    pins = {}
    for kind in ("forecast", "shortage"):
        v = (env.get(f"ML_{kind.upper()}_SHA256") or "").strip().lower()
        if v:
            if not re.fullmatch(r"[0-9a-f]{64}", v):
                problems.append(f"ML_{kind.upper()}_SHA256 must be a 64-character hex SHA-256 digest")
            else:
                pins[kind] = v
    timeout = _float(env, "ML_RECOMPUTE_TIMEOUT_S", 30.0, problems)

    level = (env.get("LOG_LEVEL") or "INFO").strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        problems.append("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        level = "INFO"

    if problems:
        raise ConfigError(problems)
    db_dir = Path(env.get("DB_DIR") or str(root / "db"))
    return Settings(
        app_env=app_env, database_url=db_url, cors_origins=cors, db_dir=db_dir,
        migrations_dir=Path(env.get("MIGRATIONS_DIR") or str(db_dir / "migrations")), migration_database_url=mig_url, auto_migrate=auto_migrate,
        auto_seed_scenario=seed, db_wait_seconds=wait, jwt_secret=jwt_secret, jwt_secret_is_ephemeral=ephemeral,
        access_token_minutes=ttl, cookie_secure=cookie_secure, enable_api_docs=docs, trusted_proxy_hops=hops,
        rate_limit_per_minute=rl, rate_limit_write_per_minute=rlw, login_max_failures=lmax, login_window_seconds=lwin,
        password_scrypt_log_n=logn, bootstrap_admin_username=admin_u, bootstrap_admin_password=admin_p,
        ml_artifact_dir=Path(env.get("ML_ARTIFACT_DIR") or str(ml_dir / "artifacts")),
        ml_reports_dir=Path(env.get("ML_REPORTS_DIR") or str(ml_dir / "reports")),
        ml_pins=pins, forecast_model_mode=mode, ml_recompute_timeout_s=timeout, log_level=level,
        log_json=_bool(env, "LOG_JSON", True))


# ---------------------------------------------------------------------------------------------------------------------
# Module-level view used by the rest of the application (``config.DATABASE_URL`` etc.). Loading happens at import time so a
# production process with a bad configuration stops immediately and says why.
settings = load()
APP_ENV = settings.app_env
DATABASE_URL = settings.database_url
CORS_ORIGINS = list(settings.cors_origins)
DB_DIR = settings.db_dir
MIGRATIONS_DIR = settings.migrations_dir
AUTO_SEED_SCENARIO = settings.auto_seed_scenario
DB_WAIT_SECONDS = settings.db_wait_seconds
ML_ARTIFACT_DIR = settings.ml_artifact_dir
ML_REPORTS_DIR = settings.ml_reports_dir
FORECAST_MODEL_MODE = settings.forecast_model_mode
ML_RECOMPUTE_TIMEOUT_S = settings.ml_recompute_timeout_s

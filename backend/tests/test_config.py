"""Configuration profiles: production must fail clearly on missing/weak secrets; development stays convenient but never ships a fixed secret."""
import pytest

from app import config

STRONG_DB = "postgresql+psycopg://svc_logistics:Zk7!pQ2vL9xTn4Rw@db.internal:5432/logistics"
GOOD_PROD = {"APP_ENV": "production", "DATABASE_URL": STRONG_DB, "JWT_SECRET": "k3J9-vB2mQx7LpZ4tR8nW1yH6cF0dS5aG-uE", "CORS_ORIGINS": "https://logistics.example.org"}


def prod(**over):
    e = dict(GOOD_PROD)
    e.update(over)
    return e


def problems(env):
    with pytest.raises(config.ConfigError) as ei:
        config.load(env)
    return " | ".join(ei.value.problems)


def test_valid_production_profile_loads_with_safe_defaults():
    s = config.load(GOOD_PROD)
    assert s.is_production and s.cookie_secure and not s.enable_api_docs and not s.auto_seed_scenario
    assert s.password_scrypt_log_n >= 15 and not s.jwt_secret_is_ephemeral


def test_production_reports_every_missing_required_setting_at_once():
    p = problems({"APP_ENV": "production"})
    assert "DATABASE_URL is required" in p and "JWT_SECRET is required" in p and "CORS_ORIGINS is required" in p


@pytest.mark.parametrize("secret", ["short", "changeme" * 6, "your-secret-" + "x" * 30, "a" * 40, "example-secret-value-1234567890-abcdef"])
def test_weak_or_placeholder_jwt_secrets_are_rejected(secret):
    assert "JWT_SECRET" in problems(prod(JWT_SECRET=secret))


@pytest.mark.parametrize("url", ["postgresql+psycopg://logistics:logistics@db:5432/logistics", "postgresql+psycopg://u:postgres@db/x",
                                 "postgresql+psycopg://u@db/x", "postgresql+psycopg://u:CHANGE_ME_please_123@db/x", "postgresql+psycopg://u:short@db/x"])
def test_default_or_weak_database_credentials_are_rejected_in_production(url):
    assert "DATABASE_URL" in problems(prod(DATABASE_URL=url))


@pytest.mark.parametrize("origins,frag", [("*", "wildcard"), ("http://logistics.example.org", "https"), ("logistics.example.org", "not a valid origin"),
                                          ("https://a.example.org/path", "not a valid origin")])
def test_cors_rules(origins, frag):
    assert frag in problems(prod(CORS_ORIGINS=origins))


def test_insecure_cookie_and_cheap_hashing_are_refused_in_production():
    assert "COOKIE_SECURE" in problems(prod(COOKIE_SECURE="0"))
    assert "PASSWORD_SCRYPT_LOG_N" in problems(prod(PASSWORD_SCRYPT_LOG_N="12"))


def test_development_defaults_are_convenient_but_secrets_are_never_fixed():
    a, b = config.load({}), config.load({})
    assert a.app_env == "development" and a.enable_api_docs and not a.cookie_secure and a.auto_seed_scenario
    assert a.jwt_secret_is_ephemeral and a.jwt_secret != b.jwt_secret and len(a.jwt_secret) >= 32      # random per load, no hard-coded value
    assert "logistics:logistics" not in a.database_url                                                    # no default password anywhere


def test_test_profile_never_auto_seeds():
    assert config.load({"APP_ENV": "test"}).auto_seed_scenario is False


def test_unknown_profile_is_validated_as_production():
    p = problems({"APP_ENV": "staging"})
    assert "APP_ENV must be one of" in p and "JWT_SECRET is required" in p


def test_admin_bootstrap_pair_and_pins_and_numbers_are_validated():
    assert "must be set together" in problems(prod(BOOTSTRAP_ADMIN_USERNAME="root"))
    assert "64-character" in problems(prod(ML_FORECAST_SHA256="abc"))
    assert "integer" in problems(prod(RATE_LIMIT_PER_MINUTE="lots"))
    assert config.load(prod(ML_FORECAST_SHA256="A" * 64)).ml_pins == {"forecast": "a" * 64}


def test_database_target_never_contains_credentials():
    t = config.database_target(STRONG_DB)
    assert t == "db.internal:5432/logistics" and "Zk7" not in t and "svc_logistics" not in t


def test_error_message_does_not_echo_secret_values():
    secret = "short-secret-VALUE"
    with pytest.raises(config.ConfigError) as ei:
        config.load(prod(JWT_SECRET=secret))
    assert secret not in str(ei.value)


def test_migration_connection_is_validated_separately_and_auto_migrate_is_configurable():
    s = config.load(prod(MIGRATION_DATABASE_URL="postgresql+psycopg://owner:Zk7!pQ2vL9xTn4Rw@db.internal:5432/logistics", AUTO_MIGRATE="0"))
    assert s.auto_migrate is False and s.migration_database_url.startswith("postgresql+psycopg://owner:")
    assert config.load(GOOD_PROD).auto_migrate is True and config.load(GOOD_PROD).migration_database_url is None
    assert "MIGRATION_DATABASE_URL" in problems(prod(MIGRATION_DATABASE_URL="postgresql+psycopg://owner:postgres@db/x"))
    assert "MIGRATION_DATABASE_URL" in problems(prod(MIGRATION_DATABASE_URL="mysql://x"))


@pytest.mark.parametrize("given", ["postgres://svc_logistics:Zk7!pQ2vL9xTn4Rw@db.internal:5432/logistics", "postgresql://svc_logistics:Zk7!pQ2vL9xTn4Rw@db.internal:5432/logistics"])
def test_hosted_style_database_urls_are_normalised_to_the_psycopg3_driver(given):
    s = config.load(prod(DATABASE_URL=given, MIGRATION_DATABASE_URL=given))
    assert s.database_url.startswith("postgresql+psycopg://svc_logistics:") and s.migration_database_url.startswith("postgresql+psycopg://")
    from sqlalchemy import create_engine
    assert create_engine(s.database_url).dialect.driver == "psycopg"          # the engine really uses psycopg 3
    assert "weak" in problems(prod(DATABASE_URL="postgres://u:postgres@db/x"))                    # the password rules still apply after normalising
    assert "DATABASE_URL must start" in problems(prod(DATABASE_URL="mysql://u:Zk7!pQ2vL9xTn4Rw@db/x"))

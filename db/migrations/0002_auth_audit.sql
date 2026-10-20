-- 0002 users, roles and audit trail. Passwords are stored only as salted scrypt hashes (never plain text).
CREATE TABLE IF NOT EXISTS users (
    id             serial PRIMARY KEY,
    username       text NOT NULL CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,39}$'),
    password_hash  text NOT NULL,
    role           text NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
    is_active      boolean NOT NULL DEFAULT true,
    token_version  integer NOT NULL DEFAULT 0,        -- bumped on password change / deactivation: invalidates issued tokens
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    last_login_at  timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_uq ON users (username);

-- security-relevant events only (logins, user changes, state-changing operations); never stores passwords or tokens
CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    actor       text,                                  -- user name, or NULL for anonymous attempts
    action      text NOT NULL,
    target      text,
    outcome     text NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
    client_ip   text,
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_ts_ix ON audit_log (ts DESC);

"""Operational commands.

    python -m app.cli check-config                      validate the environment (exit 1 and list every problem)
    python -m app.cli migrate                           apply pending migrations
    python -m app.cli seed-scenario                     load the illustrative scenario into an EMPTY database
    python -m app.cli grant-app-role ROLE               least-privilege grants for the application's database role
    python -m app.cli verify-schema                     read-only check that migrations are current
    python -m app.cli create-user NAME --role admin     create a user (password is read from the prompt or PLSD_NEW_PASSWORD)
    python -m app.cli set-password NAME                 change a user's password (revokes their sessions)
    python -m app.cli reset-database --confirm NAME     DESTRUCTIVE, development/test databases only
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config")
    sub.add_parser("migrate")
    sub.add_parser("seed-scenario")
    ga = sub.add_parser("grant-app-role", help="give an existing LOGIN role least-privilege access (DML only) to the application tables")
    ga.add_argument("role")
    sub.add_parser("verify-schema", help="check that the database is at the newest migration (read-only)")
    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("--role", choices=["viewer", "operator", "admin"], default="viewer")
    sp = sub.add_parser("set-password")
    sp.add_argument("username")
    rd = sub.add_parser("reset-database")
    rd.add_argument("--confirm", required=True, help="type the database name to confirm")
    a = ap.parse_args(argv)

    from . import config
    if a.cmd == "check-config":
        s = config.settings
        print(f"configuration OK: env={s.app_env} database={config.database_target(s.database_url)} cors={list(s.cors_origins)} docs={s.enable_api_docs} cookie_secure={s.cookie_secure}")
        return 0
    from . import migrate
    if a.cmd == "migrate":
        done = migrate.migrate()
        print("applied:", ", ".join(done) if done else "nothing (up to date)", "| version:", migrate.current_version(migrate.migration_url()))
        return 0
    if a.cmd == "grant-app-role":
        migrate.grant_app_privileges(a.role)
        print(f"role {a.role} now has data access only (no DDL, no TRUNCATE, read-only migration history)")
        return 0
    if a.cmd == "verify-schema":
        print("schema OK at version", migrate.verify_schema())
        return 0
    if a.cmd == "seed-scenario":
        print("scenario loaded" if migrate.seed_scenario() else "scenario already present; nothing changed")
        return 0
    if a.cmd == "reset-database":
        migrate.reset_database(confirm_database_name=a.confirm)
        print("database reset; run: python -m app.cli migrate")
        return 0
    from . import auth, models as m, security as sec
    from .database import SessionLocal
    password = os.environ.get("PLSD_NEW_PASSWORD") or getpass.getpass("Password: ")
    with SessionLocal() as db:
        if a.cmd == "create-user":
            u = auth.create_user(db, a.username, password, a.role)
            auth.audit(None, "user_create_cli", "success", target=u.username, detail={"role": a.role})
            print(f"created {u.role} {u.username!r}")
            return 0
        if a.cmd == "set-password":
            from sqlalchemy import select
            u = db.scalar(select(m.UserRow).where(m.UserRow.username == a.username.strip().lower()))
            if u is None:
                print("no such user", file=sys.stderr)
                return 1
            sec.validate_new_password(password, u.username)
            u.password_hash = sec.hash_password(password, config.settings.password_scrypt_log_n)
            u.token_version += 1
            db.commit()
            auth.audit(None, "password_set_cli", "success", target=u.username)
            print("password updated; existing sessions revoked")
            return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001 - print a clean message instead of a traceback for operational errors
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

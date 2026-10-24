#!/usr/bin/env python3
"""Write a .env with freshly generated secrets for `docker compose`. Refuses to overwrite an existing .env.

    python scripts/generate_env.py [--admin NAME]

The generated administrator password is printed once and stored in .env as BOOTSTRAP_ADMIN_PASSWORD; remove that line after the first sign-in.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", default="admin", help="user name of the first administrator")
    a = ap.parse_args(argv)
    target = ROOT / ".env"
    admin_pw = secrets.token_urlsafe(18)
    lines = []
    for line in (ROOT / ".env.example").read_text().splitlines():
        key = line.split("=", 1)[0]
        if key in ("POSTGRES_PASSWORD", "OWNER_DB_PASSWORD", "APP_DB_PASSWORD"):
            line = f"{key}={secrets.token_hex(24)}"      # hex: always safe inside a database URL
        elif key == "JWT_SECRET":
            line = f"JWT_SECRET={secrets.token_urlsafe(48)}"
        elif key == "BOOTSTRAP_ADMIN_USERNAME":
            line = f"BOOTSTRAP_ADMIN_USERNAME={a.admin}"
        elif key == "BOOTSTRAP_ADMIN_PASSWORD":
            line = f"BOOTSTRAP_ADMIN_PASSWORD={admin_pw}"
        lines.append(line)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"{target} already exists; not overwriting it.", file=sys.stderr)
        return 1
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    print(f"Wrote {target} (mode 600).\nFirst administrator: {a.admin} / {admin_pw}\nSign in, then delete the BOOTSTRAP_ADMIN_PASSWORD line from .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

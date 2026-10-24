#!/usr/bin/env python3
"""Simulated ESP32 / RFID inventory scanner (software only - no hardware is connected).

Generates deterministic RECEIVE / ISSUE / COUNT scans and POSTs them to the FastAPI ingest endpoint
(POST /api/iot/update), exactly as an ESP32 + RFID reader would over HTTP. Uses only the standard library.

    python iot-simulator/simulator.py --count 10 --interval 0.5
    python iot-simulator/simulator.py --location Base_04 --supply Medical --event RECEIVE --quantity 2000
"""
import argparse
import os
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LOCS = ["Base_01", "Base_02", "Base_03", "Base_04", "Base_05"]
SUPS = ["Food", "Fuel", "Water", "Medical", "Maintenance", "Engineering", "Clothing", "Comms", "Spares", "Shelter"]


_token = os.environ.get("PLSD_TOKEN", "")


def validate_api_url(api: str) -> str:
    """Validate API URL: allow loopback HTTP and remote HTTPS; reject remote plain HTTP and other schemes."""
    p = urllib.parse.urlsplit(api)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"Invalid API URL scheme: {p.scheme!r}. Must be http or https.")
    host = p.hostname or ""
    if p.scheme == "http":
        is_loopback = host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".localhost")
        if not is_loopback:
            raise ValueError(f"Insecure API URL '{api}': plain HTTP is only allowed for loopback hosts (localhost, 127.0.0.1). Use HTTPS for remote hosts.")
    return api


def _login(api: str) -> str:
    """Sign in with PLSD_USER / PLSD_PASSWORD (an account with the operator role) and return a bearer token. Credentials are never accepted on the command line."""
    validate_api_url(api)
    user, pw = os.environ.get("PLSD_USER", ""), os.environ.get("PLSD_PASSWORD", "")
    if not user or not pw:
        raise SystemExit("Authentication required: set PLSD_USER and PLSD_PASSWORD (operator or admin account) or PLSD_TOKEN.")
    req = urllib.request.Request(api.rstrip("/") + "/api/auth/login", data=json.dumps({"username": user, "password": pw}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]


def build_post_request(api: str, body: dict, token: str) -> urllib.request.Request:
    validate_api_url(api)
    req = urllib.request.Request(
        api.rstrip("/") + "/api/iot/update",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    req.add_unredirected_header("Authorization", "Bearer " + token)
    return req


def post(api: str, body: dict) -> dict:
    global _token
    validate_api_url(api)
    if not _token:
        _token = _login(api)
    req = build_post_request(api, body, _token)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--interval", type=float, default=0.0, help="seconds between scans")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="ESP32-SIM-01")
    ap.add_argument("--location"); ap.add_argument("--supply")
    ap.add_argument("--event", choices=["RECEIVE", "ISSUE", "COUNT"]); ap.add_argument("--quantity", type=float)
    a = ap.parse_args()
    try:
        validate_api_url(a.api)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    rng = random.Random(a.seed)
    for k in range(a.count):
        body = {"device_id": a.device, "tag_id": f"RFID-SIM-{rng.randint(1000, 9999)}",
                "event_type": a.event or rng.choice(["RECEIVE", "ISSUE", "ISSUE"]),
                "location_id": a.location or rng.choice(LOCS), "supply_id": a.supply or rng.choice(SUPS),
                "quantity": a.quantity if a.quantity is not None else rng.choice([100, 200, 500, 1000]), "note": "cli simulator (SIMULATED)"}
        try:
            r = post(a.api, body)
        except urllib.error.HTTPError as e:
            print(f"[{k + 1}] HTTP {e.code}: {e.read().decode()[:160]}"); return 1
        except urllib.error.URLError as e:
            print(f"backend unreachable: {e.reason}"); return 2
        print(f"[{k + 1}] {body['event_type']:7s} {body['location_id']}/{body['supply_id']:11s} x{body['quantity']:>7.0f}  "
              f"stock {r['stock_before']:.0f} -> {r['stock_after']:.0f}  status={r['item']['status'] if r['item'] else '-'}  critical_items={r['dashboard']['critical_items']}  (SIMULATED)")
        if a.interval: time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())

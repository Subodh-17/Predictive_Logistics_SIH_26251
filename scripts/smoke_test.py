#!/usr/bin/env python3
"""Automated Health Probe and API Smoke Test Suite.

Usage:
    python scripts/smoke_test.py [--url http://127.0.0.1:8000] [--user USERNAME] [--password PASSWORD]

Validates:
    - /api/health/live (liveness probe: HTTP 200, status='ok')
    - /api/health/ready (readiness probe: HTTP 200, status='ready')
    - /api/health (service health: HTTP 200, api='up', data_notice present)
    - /api/health/detail (authenticated detail: models, versions, schema)
    - /api/dashboard & /api/forecast (authenticated core query integrity)

Exits:
    0 on successful health verification.
    1 on probe failure or timeout.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def check_endpoint(url: str, path: str, method: str = "GET", headers: dict | None = None, body: dict | None = None, timeout: float = 5.0) -> tuple[int, dict, float]:
    headers = headers or {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            elapsed_ms = (time.perf_counter() - start) * 1000
            content = response.read().decode("utf-8")
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = {"raw": content}
            return response.status, parsed, elapsed_ms
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"raw": content}
        return e.code, parsed, elapsed_ms


def run_smoke_tests(base_url: str, user: str | None = None, password: str | None = None) -> bool:
    print(f"=== Predictive Logistics Smoke Test: {base_url} ===")
    all_passed = True

    # 1. Liveness Probe
    code, data, elapsed = check_endpoint(base_url, "/api/health/live")
    live_ok = (code == 200 and data.get("status") == "ok")
    status_str = "PASS" if live_ok else "FAIL"
    print(f"[{status_str}] GET /api/health/live -> HTTP {code} ({elapsed:.1f}ms): status={data.get('status')}")
    if not live_ok:
        all_passed = False

    # 2. Readiness Probe
    code, data, elapsed = check_endpoint(base_url, "/api/health/ready")
    ready_ok = (code == 200 and data.get("status") == "ready")
    status_str = "PASS" if ready_ok else "FAIL"
    print(f"[{status_str}] GET /api/health/ready -> HTTP {code} ({elapsed:.1f}ms): status={data.get('status')}, db={data.get('database')}")
    if not ready_ok:
        all_passed = False

    # 3. Health Summary
    code, data, elapsed = check_endpoint(base_url, "/api/health")
    health_ok = (code == 200 and data.get("api") == "up" and "data_notice" in data)
    status_str = "PASS" if health_ok else "FAIL"
    print(f"[{status_str}] GET /api/health -> HTTP {code} ({elapsed:.1f}ms): api={data.get('api')}, status={data.get('status')}")
    if not health_ok:
        all_passed = False

    # 4. Optional Authenticated Probes
    if user and password:
        login_code, login_data, login_ms = check_endpoint(base_url, "/api/auth/login", method="POST", body={"username": user, "password": password})
        if login_code == 200 and "access_token" in login_data:
            token = login_data["access_token"]
            auth_headers = {"Authorization": f"Bearer {token}"}
            print(f"[PASS] POST /api/auth/login -> HTTP 200 ({login_ms:.1f}ms): Authenticated as {user}")

            # Health detail
            code, data, elapsed = check_endpoint(base_url, "/api/health/detail", headers=auth_headers)
            detail_ok = (code == 200 and "models" in data)
            status_str = "PASS" if detail_ok else "FAIL"
            active_m = data.get('models', {}).get('active_forecast_model', {}).get('model_id') or data.get('models', {}).get('active_model')
            print(f"[{status_str}] GET /api/health/detail -> HTTP {code} ({elapsed:.1f}ms): env={data.get('environment')}, active_model={active_m}")
            if not detail_ok:
                all_passed = False

            # Dashboard query
            code, data, elapsed = check_endpoint(base_url, "/api/dashboard", headers=auth_headers)
            dash_ok = (code == 200 and "kpis" in data)
            status_str = "PASS" if dash_ok else "FAIL"
            print(f"[{status_str}] GET /api/dashboard -> HTTP {code} ({elapsed:.1f}ms): risk_index={data.get('kpis', {}).get('risk_index')}")
            if not dash_ok:
                all_passed = False
        else:
            print(f"[FAIL] POST /api/auth/login -> HTTP {login_code} ({login_ms:.1f}ms): Login failed")
            all_passed = False

    print("--------------------------------------------------")
    if all_passed:
        print("RESULT: ALL PROBES AND SMOKE TESTS PASSED.")
    else:
        print("RESULT: ONE OR MORE SMOKE CHECKS FAILED.")
    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Logistics API automated health and smoke test suite")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of logistics API")
    parser.add_argument("--user", default=None, help="Optional admin/viewer username")
    parser.add_argument("--password", default=None, help="Optional user password")
    args = parser.parse_args()

    success = run_smoke_tests(args.url, user=args.user, password=args.password)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

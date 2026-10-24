#!/usr/bin/env python3
"""Regression sweep over EVERY operation in the live OpenAPI spec, plus expected-error cases.

    python backend/scripts/api_sweep.py [http://localhost:8000]
Exit 0 only if every operation answers as expected. State-changing IoT calls are reset at the end.
"""
import json, sys, urllib.error, urllib.request

B = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
def call(method, path, body=None):
    req = urllib.request.Request(B + path, method=method, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]

spec = call("GET", "/openapi.json")[1]
Q = {"destination": "Base_04", "location": "Base_04", "supply": "Medical"}
PATH = {"location_id": "Base_04"}
BODY = {("post", "/api/simulation/run"): {"demand_increase": 0.3, "weather_severity": 1, "road_degradation": 1, "vehicle_availability": 0.6},
        ("post", "/api/iot/update"): {"device_id": "ESP32-SIM-01", "tag_id": "RFID-SIM-1234", "event_type": "ISSUE", "location_id": "Base_04", "supply_id": "Medical", "quantity": 10},
        ("post", "/api/iot/simulate"): {"count": 2}}
fails, n = [], 0
for path, ops in sorted(spec["paths"].items()):
    for m, op in ops.items():
        q = {p["name"]: Q[p["name"]] for p in op.get("parameters", []) if p["in"] == "query" and p.get("required")}
        url = path.format(**PATH) + ("?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else "")
        st, body = call(m.upper(), url, BODY.get((m, path)))
        n += 1; ok = st == 200; print(("PASS" if ok else "FAIL"), m.upper().ljust(4), url, st); (not ok) and fails.append((m, url, st))
print(f"--- {n} operations in the OpenAPI spec")
EXPECT = [("GET", "/api/inventory?risk=BAD", 422), ("GET", "/api/routes/compare?destination=Nope", 404), ("GET", "/api/locations/Nope", 404),
          ("POST", "/api/simulation/run", 422, {"demand_increase": 0.9}), ("POST", "/api/iot/update", 404, {"device_id": "ESP32-SIM-01", "tag_id": "RFID-SIM-1", "event_type": "ISSUE", "location_id": "Nowhere", "supply_id": "Medical", "quantity": 5}),
          ("POST", "/api/iot/update", 422, {"device_id": "ESP32-SIM-01", "tag_id": "RFID-SIM-1", "event_type": "BAD", "location_id": "Base_04", "supply_id": "Medical", "quantity": 5}),
          ("GET", "/api/dashboard?demand=0.9", 422), ("GET", "/api/forecast?horizon=99", 200)]
for e in EXPECT:
    st, _ = call(e[0], e[1], e[3] if len(e) > 3 else None); ok = st == e[2]; print(("PASS" if ok else "FAIL"), "expected", e[2], e[0], e[1], "->", st); (not ok) and fails.append(e)
call("POST", "/api/iot/reset")
print("API SWEEP:", "PASS" if not fails else f"FAIL {fails}"); sys.exit(1 if fails else 0)

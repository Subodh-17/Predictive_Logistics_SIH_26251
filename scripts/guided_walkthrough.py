#!/usr/bin/env python3
"""Deterministic evaluator walkthrough of the core workflow, driven through the real API (no external services).

    PLSD_URL=http://localhost:8080 PLSD_USER=<admin account> PLSD_PASSWORD=<password> python scripts/guided_walkthrough.py [--keep]

Needs an ADMIN account because step 0 restores the seeded inventory baseline (so every run starts, and with --keep does not end, differently).
All data is the fictional illustrative scenario with simulated telemetry. Prints each step with the numbers the application returned; it
asserts the invariants an evaluator should be able to rely on and exits non-zero if one fails.
"""
import json, os, sys, urllib.error, urllib.request

URL = os.environ.get("PLSD_URL", "http://localhost:8080").rstrip("/")
USER, PW = os.environ.get("PLSD_USER", ""), os.environ.get("PLSD_PASSWORD", "")
TOKEN = ""
KEEP = "--keep" in sys.argv


def call(method, path, body=None):
    req = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:200]}")


def step(n, title):
    print(f"\n[{n}] {title}")


def check(ok, msg):
    print(("   ok   " if ok else "   FAIL ") + msg)
    if not ok:
        sys.exit(1)


if not USER or not PW:
    sys.exit("set PLSD_USER and PLSD_PASSWORD (an admin account)")
step(1, "Sign in with a local account")
TOKEN = call("POST", "/api/auth/login", {"username": USER, "password": PW})["access_token"]
me = call("GET", "/api/auth/me")["user"]
check(me["role"] == "admin", f"signed in as {me['username']} ({me['role']}); data notice: {call('GET', '/api/health')['data_notice']}")
call("POST", "/api/iot/reset")
print("   inventory restored to the seeded baseline")

step(2, "Inspect inventory and demand")
dash = call("GET", "/api/dashboard")
inv = call("GET", "/api/inventory")
crit = sorted([i for i in inv if i["status"] == "CRITICAL"], key=lambda i: i["days_left"])
print(f"   {len(inv)} inventory positions; {len(crit)} CRITICAL, {sum(i['status'] == 'WARNING' for i in inv)} WARNING; dashboard KPIs: {json.dumps(dash['kpis'])[:200]}")
check(len(crit) > 0, "the baseline contains at-risk items to work with")
worst = crit[0]
print(f"   most urgent: {worst['supply']} at {worst['location']}: stock {worst['stock']:.0f}, forecast use {worst['daily_use']:.1f}/day, {worst['days_left']:.1f} days of supply, lead time {worst['lead_days']:.1f} d, predicted 14-day shortage {worst['shortage_14d']}")
check(abs(worst["stock"] / worst["daily_use"] - worst["days_left"]) < 0.02, "days of supply = stock / forecast daily use (recomputed here)")

step(3, "Generate and explain a forecast")
f = call("GET", f"/api/forecast?location={worst['location']}&supply={worst['supply']}&horizon=14")
print(f"   model in use: {f['model']['label']} ({f['model']['id']}); backtest: {json.dumps(f['backtest'])[:160]}")
fc = f["forecast"]
check(len(fc) == 14 and all(r["lo"] <= r["value"] <= r["hi"] for r in fc), "14-day forecast with an ordered 80% interval for every day")
check(abs(sum(r["value"] for r in fc[:7]) / 7 - worst["daily_use"]) / worst["daily_use"] < 0.02, "the risk views use exactly this forecast (first 7 days)")
print(f"   methodology: {str(f['methodology'])[:200]}")

step(4, "Identify the shortage and explain the risk basis")
b = call("GET", "/api/inventory/risk-basis")
print(f"   horizon {b['horizon_days']} d; rules: {json.dumps(b['status_rules'])[:200]}")
print(f"   shortage-onset ML model used for status: {b['shortage_onset_model']['integrated_with_inventory_status']} ({b['shortage_onset_model']['reason'][:110]}...)")
proj = call("GET", f"/api/inventory/projection?location={worst['location']}&supply={worst['supply']}")
print(f"   projected stock-out: {proj['days_left']:.1f} days; below safety stock from day {next((i for i, v in enumerate(proj['projected_stock']) if v < proj['safety_stock']), 'n/a')}")

step(5, "Replenishment recommendation and stock allocation")
pr = call("GET", "/api/priority")
top = pr[0]
print(f"   priority #1: {top['supply']} at {top['location']} (score {top['score']}), replenish {top['replenish_qty']} units via {top['best_route']}")
al = call("GET", "/api/allocation")
check(al["allocated"] + al["unmet"] == al["total_need"], f"conservation: allocated {al['allocated']} + unmet {al['unmet']} = need {al['total_need']}")
used = sum(d["used"] for d in al["depot_stock_used"])
check(al["allocated"] <= al["fleet_capacity"] and abs(used - al["allocated"]) < 1 and all(d["used"] <= d["start"] and d["remaining"] == d["start"] - d["used"] for d in al["depot_stock_used"]),
      f"allocation within fleet capacity ({al['fleet_capacity']}); depot stock leaving ({used:.0f}) equals units allocated, and no depot ships more than it holds")
print(f"   unmet by binding constraint: {json.dumps(al['unmet_by_reason'])}")

step(6, "Plan the shipment: routes, capacity, ETA")
cmp_ = call("GET", f"/api/routes/compare?destination={top['location']}")
sel = next(r for r in cmp_["routes"] if r["id"] == cmp_["selected"])
print(f"   selected {sel['id']} from {sel['depot']}: {sel['distance_km']} km, ETA {sel['eta_h']} h (nominal {sel['distance_km'] / sel['nominal_speed_kmh']:.1f} h), risk {sel['risk_level']}, capacity {sel['vehicle_capacity']}")
print(f"   why: {cmp_['reason']}")
print("   assumptions: feasible = a vehicle is available AND the corridor is not weather-closed (risk < 0.85); no escort, fuel, bridge-load or time-window limits are modelled.")
check(sel["feasible"] and sel["eta_h"] >= sel["distance_km"] / sel["nominal_speed_kmh"] - 1e-6, "selected route is feasible and ETA is not faster than nominal")

step(7, "Compare scenarios (stored runs, same baseline)")
r1 = call("POST", "/api/simulation/run", {"weather_severity": 0.2})["run_id"]
r2 = call("POST", "/api/simulation/run", {"weather_severity": 1.0, "demand_increase": 0.3, "vehicle_availability": 0.6})["run_id"]
c = call("GET", f"/api/simulation/compare?a={r1}&b={r2}")
check(c["same_baseline"], c["note"])
for m in c["metrics"]:
    if m["metric"] in ("critical_items", "overall_risk_index", "unmet_after_allocation", "mean_eta_delay_h", "transport_capacity"):
        print(f"   {m['label']:34s} A={m['a']:<10} B={m['b']:<10} B-A={m['delta']:+}  better: {m['better']}")
check(next(m for m in c["metrics"] if m["metric"] == "overall_risk_index")["b"] >= next(m for m in c["metrics"] if m["metric"] == "overall_risk_index")["a"], "the harsher scenario does not lower overall risk")
storm = call("GET", f"/api/routes/compare?destination={top['location']}&weather=1")
print("   under maximum weather severity: " + ", ".join(f"{r['id']}={r['decision']}" for r in storm["routes"]))

step(8, "Inspect the data and calculations behind the recommendation")
w = call("GET", "/api/priority/weights")
print(f"   priority score = weighted components {json.dumps(w)[:220]}")
print(f"   components of #1: {json.dumps(top['components'])}")
ev = call("GET", "/api/iot/events?limit=5")
print(f"   simulated inventory events recorded so far: {len(ev)} (telemetry is generated by a software simulator; no hardware)")
audit = call("GET", "/api/audit-log?limit=3")
print("   audit trail (latest): " + "; ".join(f"{a['action']}({a['outcome']})" for a in audit))
if not KEEP:
    call("POST", "/api/iot/reset")
print("\nwalkthrough completed: all checks passed")

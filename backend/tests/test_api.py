"""Integration tests: FastAPI + PostgreSQL/PostGIS (skipped automatically if the database is unreachable)."""
import pytest

pytestmark = pytest.mark.db


def test_health(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["database"]["connected"] and r["database"]["postgis"].startswith("3.")
    assert r["database"]["counts"]["consumption"] >= 5500 and r["simulated_iot"] is True
    assert "fictional" in r["data_notice"] and "not operational records" in r["data_notice"]


def test_locations_routes_vehicles(client):
    locs = client.get("/api/locations").json()
    assert sum(l["kind"] == "DEPOT" for l in locs) == 3 and sum(l["kind"] == "FORWARD" for l in locs) == 5
    assert client.get("/api/locations/Base_04").json()["location"]["status"] == "CRITICAL"
    routes = client.get("/api/routes").json()
    assert len(routes) == 8 and all(len(r["coordinates"]) >= 3 and r["geo_length_km"] > 0 for r in routes)
    assert len(client.get("/api/vehicles").json()) == 8


def test_inventory_filters(client):
    all_ = client.get("/api/inventory").json()
    assert len(all_) == 50
    crit = client.get("/api/inventory", params={"risk": "CRITICAL"}).json()
    assert crit and all(i["status"] == "CRITICAL" for i in crit) and len(crit) < len(all_)
    one = client.get("/api/inventory", params={"location": "Base_04", "supply": "Medical"}).json()
    assert len(one) == 1 and one[0]["days_left"] == pytest.approx(2.8, abs=0.05)
    assert client.get("/api/inventory", params={"risk": "BAD"}).status_code == 422


def test_forecast_horizons_and_filters(client):
    for h in (7, 14, 30):
        f = client.get("/api/forecast", params={"horizon": h}).json()
        assert len(f["forecast"]) == h and f["backtest"]["mape"] < 10 and 0 <= f["confidence"]["value"] <= 100
    a = client.get("/api/forecast", params={"location": "Base_04", "supply": "Medical"}).json()
    b = client.get("/api/forecast").json()
    assert a["totals"]["d14"] < b["totals"]["d14"]
    ch = client.get("/api/forecast/challenger").json()
    assert ch["statistical_mape"] < ch["rf_mape"]        # the v3 finding is reproduced


def test_route_comparison_selects_with_reason(client):
    c = client.get("/api/routes/compare", params={"destination": "Base_04"}).json()
    assert c["selected"] == "R03" and len(c["routes"]) == 2 and "lowest combined score" in c["reason"]
    assert client.get("/api/routes/compare", params={"destination": "Nope"}).status_code == 404


def test_priority_allocation_insights(client):
    p = client.get("/api/priority").json()
    assert len(p) == 14 and p[0]["score"] >= p[-1]["score"]
    a = client.get("/api/allocation").json()
    assert a["allocated"] <= a["fleet_capacity"] and a["allocated"] + a["unmet"] == a["total_need"]
    i = client.get("/api/insights").json()
    assert i["top"]["source"] and i["top"]["reason"] and i["why_at_risk"]


def test_scenario_query_changes_results(client):
    base = client.get("/api/dashboard").json()["kpis"]
    stress = client.get("/api/dashboard", params={"demand": 0.3, "weather": 1, "road": 1, "vehicles": 0.6}).json()
    assert stress["kpis"]["risk_index"] > base["risk_index"] and stress["scenario_active"]


def test_simulation_endpoint_persists_run(client):
    body = {"demand_increase": 0.3, "weather_severity": 1, "road_degradation": 1, "vehicle_availability": 0.6}
    out = client.post("/api/simulation/run", json=body).json()
    assert out["after"]["overall_risk_index"] > out["before"]["overall_risk_index"] and out["run_id"] > 0
    assert client.get("/api/simulation/runs").json()[0]["id"] == out["run_id"]
    assert client.post("/api/simulation/run", json={"demand_increase": 0.9}).status_code == 422


def test_iot_update_flows_to_inventory_dashboard_and_alerts(client):
    before = client.get("/api/dashboard").json()["kpis"]["critical_shortages"]
    body = {"device_id": "ESP32-SIM-01", "tag_id": "RFID-SIM-4001", "event_type": "RECEIVE", "location_id": "Base_04", "supply_id": "Medical", "quantity": 2000}
    r = client.post("/api/iot/update", json=body).json()
    assert r["simulated"] and r["stock_after"] == r["stock_before"] + 2000 and r["item"]["status"] == "NORMAL"
    inv = client.get("/api/inventory", params={"location": "Base_04", "supply": "Medical"}).json()[0]
    assert inv["stock"] == r["stock_after"] and inv["status"] == "NORMAL"
    assert client.get("/api/dashboard").json()["kpis"]["critical_shortages"] == before - 1
    alerts = client.get("/api/alerts").json()
    assert alerts["source"] == "database" and not any(a["location"] == "Base_04" and a["supply"] == "Medical" for a in alerts["alerts"])
    ev = client.get("/api/iot/events").json()[0]
    assert ev["simulated"] and ev["stock_after"] == r["stock_after"]
    assert client.post("/api/iot/update", json={**body, "location_id": "Nowhere"}).status_code == 404
    assert client.post("/api/iot/update", json={**body, "event_type": "BAD"}).status_code == 422
    assert client.post("/api/iot/update", json={**body, "quantity": 0}).status_code == 422
    client.post("/api/iot/reset")
    assert client.get("/api/dashboard").json()["kpis"]["critical_shortages"] == before


def test_iot_simulator_endpoint(client):
    out = client.post("/api/iot/simulate", json={"count": 3}).json()
    assert out["generated"] == 3 and all(e["simulated"] for e in out["events"])
    client.post("/api/iot/reset")

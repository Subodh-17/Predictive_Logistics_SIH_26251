"""API error handling, input validation, security headers, CORS, rate limiting, transactional behaviour, health layering and observability."""
import json
import logging

import pytest
from sqlalchemy import func, select, text

from app import auth, bootstrap, config, models as m, repository as repo
from app import main as app_main
from app.database import SessionLocal
from app.security import SlidingWindowLimiter

IOT = dict(device_id="ESP32-SIM-01", tag_id="RFID-SIM-1234", event_type="ISSUE", location_id="Base_04", supply_id="Medical", quantity=50)


# --------------------------------------------------------------------------------------------------------------- unseen identifiers
@pytest.mark.parametrize("url", ["/api/forecast?location=NOPE", "/api/forecast?supply=NOPE", "/api/inventory?location=NOPE", "/api/inventory?supply=NOPE",
                                 "/api/locations/NOPE", "/api/routes/compare?destination=NOPE", "/api/inventory/projection?location=NOPE&supply=Food"])
def test_unknown_identifiers_give_404_not_500_or_empty_success(client, url):
    r = client.get(url)
    assert r.status_code == 404, (url, r.status_code, r.text[:100])
    assert r.json()["code"] == "HTTP_404"


@pytest.mark.parametrize("url", ["/api/forecast?horizon=999", "/api/forecast?horizon=0", "/api/forecast?horizon=abc", "/api/iot/events?limit=-5",
                                 "/api/iot/events?limit=100000", "/api/simulation/runs?limit=0", "/api/priority?limit=-1", "/api/inventory?demand=9",
                                 "/api/inventory?risk=EXPLODING", "/api/inventory?vehicles=0.1"])
def test_out_of_range_parameters_are_rejected_not_silently_corrected(client, url):
    assert client.get(url).status_code == 422, url


def test_sql_metacharacters_in_filters_are_inert(client):
    for evil in ["x' OR '1'='1", "'; DROP TABLE inventory; --", "Base_04%27--", "\x00"]:
        r = client.get("/api/inventory", params={"location": evil})
        assert r.status_code == 422, (evil, r.status_code)
    assert client.get("/api/inventory").status_code == 200 and len(client.get("/api/inventory").json()) == 50


def test_request_bodies_are_validated_strictly(operator_client):
    bad = [dict(IOT, quantity=-1), dict(IOT, quantity=1e12), dict(IOT, event_type="STEAL"), dict(IOT, device_id="<script>alert(1)</script>"),
           dict(IOT, tag_id="a b"), dict(IOT, location_id="x'; drop"), dict(IOT, simulated=False), dict(IOT, id=1), dict(IOT, note="n" * 500),
           {k: v for k, v in IOT.items() if k != "supply_id"}]
    for b in bad:
        assert operator_client.post("/api/iot/update", json=b).status_code == 422, b
    for b in [{"demand_increase": 0.9}, {"demand_increase": "abc"}, {"vehicle_availability": 0.1}, {"unknown": 1}]:
        assert operator_client.post("/api/simulation/run", json=b).status_code == 422, b
    assert operator_client.post("/api/iot/update", content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 422


def test_unknown_inventory_pair_is_404_and_changes_nothing(operator_client, client):
    before = client.get("/api/iot/events").json()
    r = operator_client.post("/api/iot/update", json=dict(IOT, supply_id="Unobtainium"))
    assert r.status_code == 404 and client.get("/api/iot/events").json() == before


def test_validation_errors_do_not_echo_input_or_leak_internals(client):
    r = client.post("/api/ml/shortage-risk", json={"demand": ["secret-looking-value"]})
    assert r.status_code == 422 and "secret-looking-value" not in r.text
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR" and all(set(e) == {"loc", "msg", "type"} for e in body["detail"])


# ------------------------------------------------------------------------------------------------------------------- transactions
def _stock(supply="Medical", loc="Base_04"):
    with SessionLocal() as db:
        return float(db.scalar(select(m.InventoryRow.stock).where(m.InventoryRow.location_id == loc, m.InventoryRow.supply_id == supply)))


def _n_events():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(m.IotEventRow))


def test_failure_after_the_stock_update_rolls_everything_back(operator_client, client, monkeypatch):
    client.post("/api/iot/reset")
    stock0, ev0 = _stock(), _n_events()

    def boom(*a, **k):
        raise ValueError("simulated failure while refreshing derived tables")
    monkeypatch.setattr(repo, "persist_baseline", boom)
    r = operator_client.post("/api/iot/update", json=IOT)
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"
    assert "simulated failure" not in r.text and "Traceback" not in r.text            # no internals to the caller
    assert _stock() == stock0 and _n_events() == ev0                                   # stock and event log untouched
    monkeypatch.undo()
    assert operator_client.post("/api/iot/update", json=IOT).status_code == 200 and _stock() == stock0 - 50


def test_batch_simulation_is_all_or_nothing(operator_client, client, monkeypatch):
    client.post("/api/iot/reset")
    stock0, ev0 = _stock(), _n_events()
    calls = {"n": 0}
    real = repo.persist_baseline

    def fail_on_third(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(repo, "persist_baseline", fail_on_third)
    assert operator_client.post("/api/iot/simulate", json={"count": 5}).status_code in (500, 503)
    monkeypatch.undo()
    assert _n_events() == ev0 and _stock() == stock0                                   # events 1 and 2 were rolled back as well


def test_inventory_reset_is_atomic(client, operator_client, monkeypatch):
    operator_client.post("/api/iot/update", json=IOT)
    low = _stock()
    monkeypatch.setattr(repo, "persist_baseline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert client.post("/api/iot/reset").status_code in (500, 503)
    monkeypatch.undo()
    assert _stock() == low and _n_events() >= 1                                        # nothing half-reset
    assert client.post("/api/iot/reset").status_code == 200 and _n_events() == 0


# --------------------------------------------------------------------------------------------------------------------- headers
def test_security_headers_and_request_id(anon_client):
    r = anon_client.get("/api/health/live", headers={"X-Request-ID": "abcd-1234-efgh"})
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert h["cache-control"] == "no-store" and "permissions-policy" in h and h["x-request-id"] == "abcd-1234-efgh"
    assert anon_client.get("/api/health/live", headers={"X-Request-ID": "bad id\r\ninjected"}).headers["x-request-id"] != "bad id"   # unsafe ids replaced


def test_cors_allows_only_configured_origins_and_never_wildcard(anon_client):
    ok = anon_client.options("/api/auth/login", headers={"Origin": config.CORS_ORIGINS[0], "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == config.CORS_ORIGINS[0] and ok.headers.get("access-control-allow-credentials") == "true"
    bad = anon_client.options("/api/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers
    assert anon_client.get("/api/health/live", headers={"Origin": "https://evil.example"}).headers.get("access-control-allow-origin") is None
    assert "*" not in config.CORS_ORIGINS


def test_unhandled_exception_returns_generic_error_with_reference(client, monkeypatch):
    monkeypatch.setattr(repo, "load_snapshot", lambda db: (_ for _ in ()).throw(ZeroDivisionError("internal detail /srv/app/secret.py")))
    r = client.get("/api/locations")
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR" and "secret.py" not in r.text
    assert r.headers["x-request-id"] in r.json()["detail"]                              # the reference matches the log line


def test_runtime_not_ready_message_is_generic(client, monkeypatch):
    monkeypatch.setattr(repo, "load_snapshot", lambda db: (_ for _ in ()).throw(RuntimeError("PostgreSQL not reachable at 10.1.2.3 user=svc")))
    r = client.get("/api/locations")
    assert r.status_code == 503 and r.json()["code"] == "NOT_READY" and "10.1.2.3" not in r.text


# ------------------------------------------------------------------------------------------------------------------- rate limits
def test_general_and_write_rate_limits(anon_client, operator_client, monkeypatch):
    monkeypatch.setattr(app_main, "_rate", SlidingWindowLimiter(5, 60))
    codes = [anon_client.get("/api/dashboard").status_code for _ in range(8)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429] * 3                           # throttled before authentication work is done
    r = anon_client.get("/api/dashboard")
    assert r.json()["code"] == "RATE_LIMITED" and int(r.headers["retry-after"]) >= 1
    assert anon_client.get("/api/health/live").status_code == 200                      # probes are never throttled
    monkeypatch.setattr(app_main, "_rate", SlidingWindowLimiter(1000, 60))
    monkeypatch.setattr(app_main, "_rate_write", SlidingWindowLimiter(2, 60))
    codes = [operator_client.post("/api/simulation/run", json={}).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]


# ----------------------------------------------------------------------------------------------------------------------- health
def test_health_distinguishes_api_database_models_and_startup(client, anon_client):
    j = client.get("/api/health").json()
    assert j["status"] == "ok" and j["api"] == "up" and j["database"]["connected"] is True and j["database"]["postgis"].startswith("3.")
    comps = j["components"]
    assert comps["api"]["status"] == "up" and comps["database"]["status"] == "up" and comps["startup"]["status"] == "complete"
    assert comps["forecast_model"]["status"] in ("statistical_selected", "trained_model_active", "fallback_to_statistical")
    assert comps["shortage_model"]["status"] in ("loaded", "unavailable")
    assert anon_client.get("/api/health/ready").json() == {"status": "ready", "database": True, "startup_complete": True}


def test_health_reports_database_outage_as_degraded_503_while_liveness_stays_up(client, anon_client, monkeypatch):
    monkeypatch.setattr(app_main, "_db_check", lambda db: (False, "OperationalError"))
    r = anon_client.get("/api/health")
    assert r.status_code == 503 and r.json()["status"] == "degraded" and r.json()["database"]["connected"] is False
    assert r.json()["components"]["api"]["status"] == "up" and r.json()["components"]["database"]["status"] == "down"
    assert anon_client.get("/api/health/ready").status_code == 503
    assert anon_client.get("/api/health/live").status_code == 200


def test_health_degraded_until_startup_completes(anon_client, monkeypatch):
    monkeypatch.setitem(bootstrap._state, "ready", False)
    assert anon_client.get("/api/health").status_code == 503 and anon_client.get("/api/health/ready").status_code == 503


def test_health_detail_exposes_model_freshness_and_counters_but_no_secrets(client):
    j = client.get("/api/health/detail").json()
    assert j["environment"] == "test" and j["startup"]["complete"] is True and j["database"]["schema_version"] == "0004"
    assert j["model_state"]["active_model_id"] and "forecasts_generated_at" in j["data_freshness"] and j["data_freshness"]["history_through"]
    assert "counters" in j["operational"] and j["models"]["demand_forecast"]["loaded_at"]
    blob = json.dumps(j)
    assert config.settings.jwt_secret not in blob and "testpw_local_only" not in blob and "password" not in blob.lower().replace("passwords", "")


def test_database_host_is_shown_to_administrators_only(client, viewer_client):
    assert "target" in client.get("/api/health/detail").json()["database"]
    v = viewer_client.get("/api/health/detail")
    assert v.status_code == 200 and "target" not in v.json()["database"] and "localhost" not in json.dumps(v.json()["database"])


def test_inference_failures_and_fallbacks_are_counted(client, monkeypatch):
    from app.services import model_service as ms
    from app.observability import metrics
    before = metrics.snapshot()["counters"].get("forecast_fallbacks_to_statistical", 0)
    ms.force_statistical("RuntimeError: simulated")
    try:
        c = client.get("/api/health/detail").json()
        assert c["model_state"]["fallback_reason"].startswith("trained model failed at run time")
        assert client.get("/api/health").json()["components"]["forecast_model"]["status"] == "fallback_to_statistical"
    finally:
        client.post("/api/forecast/recompute")                                              # admin recompute clears the sticky fallback
    assert metrics.snapshot()["counters"]["forecast_fallbacks_to_statistical"] == before + 1
    assert client.get("/api/health").json()["components"]["forecast_model"]["status"] != "fallback_to_statistical"


# ----------------------------------------------------------------------------------------------------------------- logging hygiene
def test_logs_never_contain_credentials(client, caplog):
    from app.observability import scrub
    assert "hunter2" not in scrub("password=hunter2 token: abc.def.ghi") and "s3cr3t" not in scrub("postgresql+psycopg://svc:s3cr3t@db:5432/x")
    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/login", json={"username": "t_viewer", "password": "wrong-password-LOGGED?"})
    assert "wrong-password-LOGGED?" not in caplog.text


def test_json_log_line_shape_and_redaction():
    from app.observability import JsonFormatter, request_id_var
    request_id_var.set("req-123")
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "login attempt token=abc123", (), None)
    rec.password = "hunter2"
    line = json.loads(JsonFormatter().format(rec))
    assert line["request_id"] == "req-123" and line["password"] == "***" and "abc123" not in line["msg"] and line["level"] == "INFO"


# ------------------------------------------------------------------------------------------------------------ production profile
def test_production_profile_disables_interactive_docs_and_enables_hsts():
    s = config.load({"APP_ENV": "production", "DATABASE_URL": "postgresql+psycopg://svc:Zk7!pQ2vL9xTn4Rw@db:5432/x", "JWT_SECRET": "k3J9-vB2mQx7LpZ4tR8nW1yH6cF0dS5aG-uE",
                     "CORS_ORIGINS": "https://a.example.org"})
    assert s.enable_api_docs is False and s.cookie_secure is True


def test_docs_are_not_exposed_when_disabled(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    off = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    c = TestClient(off)
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404

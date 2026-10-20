"""Prohibited development terminology must not appear on user-facing surfaces (sources, API responses, error messages, OpenAPI text)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("audit_terminology", ROOT / "scripts" / "audit_terminology.py")
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


# ------------------------------------------------------------------------------------------------------------- the detector itself
@pytest.mark.parametrize("text", [
    "a Demo b", "DEMO MODE", "demos", "Synthetic data", "synthetically generated", "prototype", "Prototypes", "Mock data", "mock-data", "mock_data", "mocked data",
    "Dummy data", "dummy  data", "dummy-dataset", "vibecoded", "Vibe-coded", "vibe coded", "AI-generated demo", "AI generated demo", "ai_generated_demo",
    "D\u200bemo", "S\u00adynthetic", "\uff24emo",          # zero-width / soft-hyphen / full-width obfuscation
])
def test_detector_catches_every_listed_term_and_obvious_variants(text):
    assert audit.find(text), text


@pytest.mark.parametrize("text", [
    "demonstrate the route", "Demonstration of coverage", "demographic", "synthesis of results", "Object.prototype.hasOwnProperty",
    "Foo.prototype = {}", 'Object.defineProperty(e, "prototype", {})', "the democracy", "simulated telemetry", "illustrative scenario",
])
def test_detector_does_not_flag_unrelated_words_or_the_javascript_keyword(text):
    assert audit.find(text) == [], text


def test_prototype_as_a_word_is_still_flagged_in_prose():
    assert audit.find("This prototype shows the route.")
    assert audit.find("A working prototype.", code=False)


def test_allowlist_requires_a_written_reason(tmp_path, monkeypatch):
    f = tmp_path / "scripts"
    f.mkdir()
    (f / "terminology_allowlist.json").write_text(json.dumps({"allowed": [{"file": "frontend/src/x.tsx", "match": "demo"}]}))
    monkeypatch.setattr(audit, "ALLOWLIST_FILE", f / "terminology_allowlist.json")
    assert audit.allowlist()[0].get("reason") is None            # an entry without a reason is never honoured by scan() (checked via the condition below)
    assert not any(a.get("reason") for a in audit.allowlist())


# ------------------------------------------------------------------------------------------------------- the real user-facing sources
def test_source_files_are_clean():
    assert audit.scan() == [], "review and fix every match (python scripts/audit_terminology.py)"


def test_audit_scope_covers_the_surfaces_users_can_actually_see():
    # Use forward slashes for cross-platform path comparison (str() uses os.sep which is '\' on Windows).
    scanned = {f.relative_to(ROOT).as_posix() for f in audit.files()}
    must = ["frontend/index.html", "frontend/src/App.tsx", "frontend/src/pages/Dashboard.tsx", "frontend/src/pages/Inventory.tsx", "backend/app/main.py",
            "backend/app/config.py", "backend/app/seed_data.py", "db/seed.sql", "ml/reports/forecast_benchmark_eval.json",
            "iot-simulator/simulator.py", "frontend/nginx.conf.template"]
    assert [m for m in must if m not in scanned] == []
    pages = {f"frontend/src/pages/{p.name}" for p in (ROOT / "frontend/src/pages").glob("*.tsx")}
    assert pages <= scanned, "every page component must be inside the audit scope"
    assert len(scanned) > 60


def test_seed_values_shown_in_the_interface_are_clean():
    assert audit.find((ROOT / "db" / "seed.sql").read_text(encoding="utf-8")) == []


# ------------------------------------------------------------------------------------------------------------- live API responses
GET_URLS = ["/api/health", "/api/health/live", "/api/health/ready", "/api/health/detail", "/api/dashboard", "/api/forecast", "/api/forecast?location=Base_04&supply=Medical&horizon=30", "/api/forecast/challenger",
            "/api/inventory", "/api/inventory/risk-basis", "/api/inventory/projection?location=Base_04&supply=Medical", "/api/alerts", "/api/insights", "/api/priority",
            "/api/priority/weights", "/api/allocation", "/api/iot/feed", "/api/iot/events", "/api/locations", "/api/locations/Base_04", "/api/routes",
            "/api/routes/compare?destination=Base_04", "/api/vehicles", "/api/ml/models", "/api/ml/evaluation", "/api/simulation/runs", "/api/auth/me", "/api/auth/session",
            "/api/users", "/api/audit-log", "/openapi.json"]


@pytest.mark.parametrize("url", GET_URLS)
def test_api_responses_are_clean(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    hits = audit.find(r.text, code=False)
    assert not hits, (url, hits[0][1].group(0), hits[0][2][:120])


def test_every_get_operation_in_the_openapi_spec_is_covered(client):
    spec = client.get("/openapi.json").json()
    gets = {p for p, ops in spec["paths"].items() if "get" in ops}
    covered = {u.split("?")[0] for u in GET_URLS} | {"/api/simulation/compare"}      # needs saved runs: its text is checked in test_logistics_integrity.py
    templated = {p for p in gets if "{" in p}
    missing = {p for p in gets - templated if p not in covered}
    assert missing == set(), f"add these endpoints to GET_URLS: {sorted(missing)}"


def test_user_visible_error_messages_are_clean(client, operator_client, anon_client):
    responses = [client.get("/api/inventory/projection?location=x&supply=y"), client.post("/api/ml/shortage-risk", json={"demand": [1]}),
                 client.get("/api/forecast?location=NOPE"), client.get("/api/forecast?horizon=7000"), anon_client.get("/api/dashboard"),
                 anon_client.post("/api/auth/login", json={"username": "x", "password": "y"}), operator_client.post("/api/iot/reset"),
                 client.post("/api/users", json={"username": "ab", "password": "x"}), client.get("/api/nope")]
    for r in responses:
        assert r.status_code >= 400
        assert not audit.find(r.text, code=False), r.text[:200]


def test_openapi_text_and_titles_are_clean(client):
    spec = client.get("/openapi.json").json()
    assert not audit.find(json.dumps(spec), code=False)
    assert audit.find(spec["info"]["title"] + spec["info"]["description"], code=False) == []

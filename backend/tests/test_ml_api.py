"""API integration of the trained model: attribution, consistency across engines, opt-in mode, run-time fallback, input validation.
Needs PostgreSQL/PostGIS (skipped without it; fails when REQUIRE_DB=1)."""
import json

import pytest

from app import config, repository as repo
from app.database import SessionLocal
from app.ml.forecaster import MLForecaster
from app.services import model_service as ms


@pytest.fixture()
def restore(client):
    yield
    config.FORECAST_MODEL_MODE = "auto"
    ms.reset_cache()
    with SessionLocal() as db:
        repo.ensure_forecasts(db)
        repo.persist_baseline(db)


def _use_mode(mode):
    config.FORECAST_MODEL_MODE = mode
    ms.reset_cache()
    with SessionLocal() as db:
        repo.ensure_forecasts(db)
        repo.persist_baseline(db)


def test_forecast_reports_model_attribution(client, restore):
    r = client.get("/api/forecast?horizon=7").json()
    m = r["model"]
    assert m["id"] and m["family"] in ("statistical", "machine_learning") and m["generated_at"] and m["history_through"]
    assert m["interval"]["level"] == 0.8 and r["methodology"]["accuracy_caveat"]
    if m["family"] == "statistical":
        assert "ewma" in m["id"] and m["fallback_reason"]
    assert len(r["forecast"]) == 7 and all(p["lo"] <= p["value"] <= p["hi"] for p in r["forecast"])


def test_models_endpoint_and_evaluation_reports(client):
    m = client.get("/api/ml/models").json()
    assert m["demand_forecast"]["loaded"] and m["shortage_risk"]["used_by_application_status"] is False
    assert m["demand_forecast"]["artefact"]["licence"] == "CC-BY-4.0"
    e = client.get("/api/ml/evaluation").json()
    assert e["available"] and "simulator-generated" in e["disclosure"]
    b = e["reports"]["benchmark_forecast"]["test"]
    assert {"lightgbm", "statistical_ewma (existing)", "seasonal_naive_7"} <= set(b["overall"])
    assert e["reports"]["supply_csv_profile"]["rows"] == 36000


def test_ml_mode_stores_model_id_and_interval_and_stays_consistent(client, restore):
    _use_mode("ml")
    f = client.get("/api/forecast?horizon=14").json()
    assert f["model"]["family"] == "machine_learning" and f["model"]["id"].startswith("lightgbm") and f["trained_model_preview"] is None
    with SessionLocal() as db:
        meta = repo.forecast_meta(db)
        assert set(meta["models"]) == {f["model"]["id"]} and meta["models"][f["model"]["id"]] == 50
    # one source of truth: inventory daily use (mean of first 7 forecast days) x 7 summed over all positions == dashboard/forecast d7 total
    inv = client.get("/api/inventory").json()
    assert sum(i["daily_use"] for i in inv) * 7 == pytest.approx(f["totals"]["d7"], rel=1e-3)
    dash = client.get("/api/dashboard").json()
    assert dash["system_status"][1]["ok"] and client.get("/api/alerts").status_code == 200
    one = client.get("/api/forecast?location=Base_04&supply=Fuel&horizon=7").json()
    assert all(p["lo"] <= p["value"] <= p["hi"] for p in one["forecast"])


def test_switching_back_regenerates_with_the_statistical_model(client, restore):
    _use_mode("ml")
    _use_mode("statistical")
    r = client.get("/api/forecast").json()
    assert r["model"]["family"] == "statistical" and "configuration" in r["model"]["fallback_reason"]
    assert r["trained_model_preview"] is not None and r["trained_model_preview"]["model_id"].startswith("lightgbm")


def test_runtime_model_failure_degrades_visibly(client, restore, monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("simulated inference failure")
    monkeypatch.setattr(MLForecaster, "predict", boom)
    config.FORECAST_MODEL_MODE = "ml"
    ms.reset_cache()
    with SessionLocal() as db:
        repo.ensure_forecasts(db, force=True)
        repo.persist_baseline(db)
    r = client.get("/api/forecast").json()
    assert r["model"]["family"] == "statistical" and r["model"]["id"] == ms.STATISTICAL_ID
    assert "failed at run time" in r["model"]["fallback_reason"] and "simulated inference failure" in r["model"]["fallback_reason"]
    assert "lightgbm" not in json.dumps(client.get("/api/forecast").json()["model"]["series_by_model"])


def _body(n=40, **kw):
    b = {"demand": [100.0] * n, "on_hand": [400.0] * n, "in_transit": [100.0] * n, "backlog": [0.0] * n, "new_backlog": [0.0] * n}
    b.update(kw)
    return b


def test_shortage_endpoint_validates_inputs(client):
    ok = client.post("/api/ml/shortage-risk", json=_body())
    assert ok.status_code == 200 and 0 <= ok.json()["probability"] <= 1
    assert client.post("/api/ml/shortage-risk", json=_body(40, backlog=[0.0] * 39 + [9.0])).json()["applicable"] is False
    assert client.post("/api/ml/shortage-risk", json={"demand": [1.0]}).status_code == 422
    assert client.post("/api/ml/shortage-risk", json=_body(40, on_hand=[-1.0] * 40)).status_code == 422
    assert client.post("/api/ml/shortage-risk", json=_body(40, demand=[1.0] * 39)).status_code in (200, 422)
    assert client.post("/api/ml/shortage-risk", json=_body(500)).status_code == 422


def test_shortage_endpoint_reports_unavailable_model_as_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ML_ARTIFACT_DIR", tmp_path)
    ms.reset_cache()
    try:
        r = client.post("/api/ml/shortage-risk", json=_body())
        assert r.status_code == 503 and r.json()["code"] == "MODEL_UNAVAILABLE"
    finally:
        monkeypatch.undo()
        ms.reset_cache()

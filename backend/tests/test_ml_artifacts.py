"""Artefact verification, inference behaviour, model selection and fallback (no database needed)."""
import json
import shutil

import numpy as np
import pytest

from app import config
from app.ml import features as F
from app.ml.artifacts import ArtifactError
from app.ml.forecaster import MLForecaster
from app.ml.shortage import ShortageModel, build_record
from app.services import model_service as ms

ARTS = config.ML_ARTIFACT_DIR


@pytest.fixture()
def art(tmp_path):
    dst = tmp_path / "artifacts"
    shutil.copytree(ARTS, dst)
    return dst


@pytest.fixture(autouse=True)
def _reset():
    ms.reset_cache()
    yield
    ms.reset_cache()


def _meta_path(root):
    v = (root / "forecast" / "CURRENT").read_text().strip()
    return root / "forecast" / v / "metadata.json"


def test_shipped_artifact_loads_and_describes_its_provenance():
    f = MLForecaster.load(ARTS)
    m = f.meta
    assert m["feature_names"] == F.FEATURE_NAMES and m["training_data"]["licence"] == "CC-BY-4.0"
    assert "simulator-generated" in m["training_data"]["nature"] and "demand_signals" in m["training_data"]["target"]
    assert m["training_data"]["seed"] == 42 and len(m["model_sha256"]) == 64


def test_tampered_model_file_is_rejected(art):
    v = (art / "forecast" / "CURRENT").read_text().strip()
    with open(art / "forecast" / v / "model.txt", "a") as fh:
        fh.write("\n# tampered\n")
    with pytest.raises(ArtifactError, match="checksum"):
        MLForecaster.load(art)


def test_incompatible_schema_or_features_are_rejected(art):
    p = _meta_path(art); meta = json.loads(p.read_text())
    meta["schema_version"] = 99; p.write_text(json.dumps(meta))
    with pytest.raises(ArtifactError, match="schema"):
        MLForecaster.load(art)
    meta["schema_version"] = F.SCHEMA_VERSION; meta["feature_names"] = meta["feature_names"][:-1]; p.write_text(json.dumps(meta))
    with pytest.raises(ArtifactError, match="feature list"):
        MLForecaster.load(art)


def test_missing_or_invalid_registry_is_rejected(tmp_path, art):
    with pytest.raises(ArtifactError):
        MLForecaster.load(tmp_path / "nothing")
    (art / "forecast" / "CURRENT").write_text("../../etc\n")
    with pytest.raises(ArtifactError, match="invalid version"):
        MLForecaster.load(art)


def test_wrong_kind_is_rejected(art):
    with pytest.raises(ArtifactError, match="kind"):
        from app.ml.artifacts import current_version_dir, read_verified
        read_verified(current_version_dir(art, "forecast"), expected_kind="shortage_risk")


def test_prediction_shape_bounds_and_determinism():
    f = MLForecaster.load(ARTS)
    h = np.random.default_rng(1).poisson(150, 80).astype(float)
    a, b = f.predict(h, 30), f.predict(h, 30)
    assert a.values.shape == (30,) and np.array_equal(a.values, b.values)
    assert np.all(a.values >= 0) and np.all(a.lo <= a.values) and np.all(a.values <= a.hi)
    assert a.model_id.startswith("lightgbm-direct-multihorizon@")


def test_one_step_fit_equals_direct_prediction_at_the_same_origin():
    f = MLForecaster.load(ARTS)
    h = np.random.default_rng(2).poisson(150, 90).astype(float)
    fits = f.one_step_fits(h)
    assert np.all(np.isnan(fits[:F.MIN_HISTORY])) and np.all(np.isfinite(fits[F.MIN_HISTORY:]))
    assert fits[60] == pytest.approx(f.predict(h[:60], 1).values[0])      # fit at day 60 uses days 0..59 only


@pytest.mark.parametrize("bad", [[1.0] * 5, [float("nan")] * 40, [-3.0] * 40])
def test_inference_rejects_invalid_input_instead_of_fabricating(bad):
    with pytest.raises(F.InputError):
        MLForecaster.load(ARTS).predict(bad, 7)


def test_inference_rejects_bad_horizon_and_factors():
    f, h = MLForecaster.load(ARTS), [100.0] * 40
    with pytest.raises(F.InputError):
        f.predict(h, 31)
    with pytest.raises(F.InputError):
        f.predict(h, 7, past_factors=[1.0] * 39)
    with pytest.raises(F.InputError):
        f.predict(h, 7, past_factors=[0.0] * 40)


def test_known_factors_are_divided_out_and_reapplied():
    f, h = MLForecaster.load(ARTS), np.full(60, 200.0)
    plain = f.predict(h, 7)
    adj = f.predict(h * 1.5, 7, past_factors=np.full(60, 1.5), future_factors=np.full(7, 2.0))
    assert np.allclose(adj.values, plain.values * 2.0, rtol=1e-6)


# ---- selection / fallback
def test_auto_mode_uses_statistical_when_not_promoted_and_says_why(monkeypatch):
    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "auto")
    r = ms.resolve_forecast()
    promo = ms.forecaster()[0].meta["promotion"]
    if promo["status"] != "promoted":
        assert r.family == "statistical" and r.forecaster is None and "not promoted" in r.reason


def test_ml_mode_uses_trained_model_and_statistical_mode_never_does(monkeypatch):
    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "ml")
    r = ms.resolve_forecast()
    assert r.family == "machine_learning" and r.reason is None and r.model_id.startswith("lightgbm")
    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "statistical")
    r = ms.resolve_forecast()
    assert r.family == "statistical" and r.model_id == ms.STATISTICAL_ID and "configuration" in r.reason


def test_unloadable_model_falls_back_visibly_never_labelled_as_ml(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "ml")
    monkeypatch.setattr(config, "ML_ARTIFACT_DIR", tmp_path)
    r = ms.resolve_forecast()
    assert r.family == "statistical" and r.model_id == ms.STATISTICAL_ID and "unavailable" in r.reason
    st = ms.registry_status()
    assert st["demand_forecast"]["loaded"] is False and st["active_forecast_model"]["family"] == "statistical"


def test_runtime_failure_override_is_exposed(monkeypatch):
    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "ml")
    ms.force_statistical("RuntimeError: boom")
    r = ms.resolve_forecast()
    assert r.family == "statistical" and "failed at run time" in r.reason and "boom" in r.reason


# ---- shortage model
def _hist(n=40, **kw):
    base = dict(demand=[100.0] * n, on_hand=[400.0] * n, in_transit=[100.0] * n, backlog=[0.0] * n, new_backlog=[0.0] * n)
    base.update(kw)
    return base


def test_shortage_model_scores_probability_and_flags_threshold():
    m = ShortageModel.load(ARTS)
    r = m.score_record(**_hist())
    assert r["applicable"] and 0.0 <= r["probability"] <= 1.0 and r["horizon_days"] == 7 and isinstance(r["flag"], bool)
    starving = m.score_record(**_hist(on_hand=[20.0] * 40, in_transit=[0.0] * 40))
    assert starving["probability"] > r["probability"]


def test_shortage_model_declines_when_backlog_exists_and_rejects_bad_input():
    m = ShortageModel.load(ARTS)
    r = m.score_record(**_hist(backlog=[0.0] * 39 + [50.0]))
    assert r["applicable"] is False and "onset" in r["reason"]
    for bad in (_hist(demand=[1.0] * 5), _hist(on_hand=[float("nan")] * 40), _hist(demand=[1.0] * 39)):
        with pytest.raises(F.InputError):
            build_record(**bad)


def test_shortage_features_ignore_the_future():
    from app.ml import shortage as S
    rng = np.random.default_rng(0)
    d, o, b, t, n = (rng.poisson(100, (200, 2)).astype(float) for _ in range(5))
    X1 = S.build(d, o, b, t, n, [1], [120])
    d2, o2, b2, t2, n2 = (a.copy() for a in (d, o, b, t, n))
    for a in (d2, o2, b2, t2, n2):
        a[121:, 1] = 9e5
    assert np.array_equal(X1, S.build(d2, o2, b2, t2, n2, [1], [120]))

def test_malformed_metadata_raises_artifact_error(monkeypatch, art):
    p = _meta_path(art)
    meta = json.loads(p.read_text())

    # 1. Missing required key
    meta_missing = dict(meta)
    del meta_missing["interval"]
    p.write_text(json.dumps(meta_missing))
    with pytest.raises(ArtifactError, match="model metadata is incomplete or malformed"):
        MLForecaster.load(art)

    # 2. Invalid types inside metadata
    meta_bad_type = dict(meta)
    meta_bad_type["interval"] = {"ratio_lo": "invalid_not_array", "ratio_hi": [1.0], "level": 0.8}
    p.write_text(json.dumps(meta_bad_type))
    with pytest.raises(ArtifactError, match="model metadata is incomplete or malformed"):
        MLForecaster.load(art)

    # 3. Verify model_service cleanly falls back to statistical when metadata is malformed
    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "ml")
    monkeypatch.setattr(config, "ML_ARTIFACT_DIR", art)
    ms.reset_cache()
    r = ms.resolve_forecast()
    assert r.family == "statistical" and r.is_fallback is True
    assert "malformed" in (r.reason or "")

def test_interval_array_length_and_value_validation(monkeypatch, art):
    p = _meta_path(art)
    meta = json.loads(p.read_text())

    # Empty array
    meta_empty = json.loads(json.dumps(meta))
    meta_empty["interval"]["ratio_lo"] = []
    p.write_text(json.dumps(meta_empty))
    with pytest.raises(ArtifactError, match="must have exactly 30 elements"):
        MLForecaster.load(art)

    # Incorrect length (10 elements instead of 30)
    meta_short = json.loads(json.dumps(meta))
    meta_short["interval"]["ratio_lo"] = [0.9] * 10
    p.write_text(json.dumps(meta_short))
    with pytest.raises(ArtifactError, match="must have exactly 30 elements"):
        MLForecaster.load(art)

    # Incorrect length (35 elements instead of 30)
    meta_long = json.loads(json.dumps(meta))
    meta_long["interval"]["ratio_hi"] = [1.2] * 35
    p.write_text(json.dumps(meta_long))
    with pytest.raises(ArtifactError, match="must have exactly 30 elements"):
        MLForecaster.load(art)

    # Non-finite values (NaN)
    meta_nan = json.loads(json.dumps(meta))
    meta_nan["interval"]["ratio_lo"][5] = float("nan")
    p.write_text(json.dumps(meta_nan))
    with pytest.raises(ArtifactError, match="finite numeric values"):
        MLForecaster.load(art)

    # Non-numeric string value
    meta_str = json.loads(json.dumps(meta))
    meta_str["interval"]["ratio_lo"][0] = "invalid_string"
    p.write_text(json.dumps(meta_str))
    with pytest.raises(ArtifactError, match="incomplete or malformed"):
        MLForecaster.load(art)



@pytest.mark.parametrize(
    "payload",
    [
        [1, 2, 3],
        None,
        "scalar string",
        42,
        3.14,
        True,
    ],
)
def test_non_dict_metadata_raises_artifact_error(monkeypatch, art, payload):
    p = _meta_path(art)
    p.write_text(json.dumps(payload))

    from app.ml.artifacts import current_version_dir, read_verified

    d = current_version_dir(art, "forecast")
    with pytest.raises(ArtifactError, match="metadata.json root must be a JSON object"):
        read_verified(d, expected_kind="demand_forecast")

    with pytest.raises(ArtifactError, match="metadata.json root must be a JSON object"):
        MLForecaster.load(art)

    monkeypatch.setattr(config, "FORECAST_MODEL_MODE", "ml")
    monkeypatch.setattr(config, "ML_ARTIFACT_DIR", art)
    ms.reset_cache()
    r = ms.resolve_forecast()
    assert r.family == "statistical" and r.is_fallback is True
    assert "must be a JSON object" in (r.reason or "")

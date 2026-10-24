"""V6 regression tests for the ML integration: training/inference feature parity, temporal-leakage guard on the evaluation protocol,
metric correctness against hand calculations, invalid inputs, unseen identifiers, pinned/linked/corrupted artefacts, and the honest
shortage-model integration status through the API."""
import json
import shutil

import numpy as np
import pytest

from app import config
from app.ml import features as F, metrics as M
from app.ml.artifacts import ArtifactError, sha256_file
from app.ml.forecaster import MLForecaster
from app.ml.shortage import ShortageModel
from app.services import model_service as ms

ARTS = config.ML_ARTIFACT_DIR


@pytest.fixture()
def art(tmp_path):
    dst = tmp_path / "artifacts"
    shutil.copytree(ARTS, dst)
    ms.reset_cache()
    yield dst
    ms.reset_cache()


def _series(n=90, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 200 + 20 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 5, n)


# ---------------------------------------------------------------- training / inference feature consistency
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_inference_features_are_identical_to_the_training_matrix_builder(seed):
    """The API builds features with build_single(); training builds them with build(). They must agree bit for bit for every horizon."""
    a = _series(80, seed)
    X1, scale1 = F.build_single(a, F.MAX_HORIZON)
    origin = np.full(F.MAX_HORIZON, a.size - 1)
    X2, scale2 = F.build(a[:, None], np.zeros(F.MAX_HORIZON, int), origin, np.arange(1, F.MAX_HORIZON + 1))
    np.testing.assert_array_equal(X1, X2)
    assert np.all(np.asarray(scale1) == np.asarray(scale2)) or np.allclose(scale1, scale2)
    assert X1.shape[1] == len(F.FEATURE_NAMES) == MLForecaster.load(ARTS).booster.num_feature()


def test_changing_future_values_cannot_change_a_forecast():
    a = _series(80)
    f = MLForecaster.load(ARTS)
    base = f.predict(a[:60], 14).values
    again = f.predict(np.concatenate([a[:60]]), 14).values
    np.testing.assert_array_equal(base, again)                                     # deterministic
    # the 'future' (days 60..79) is simply not an input: appending it changes the origin, truncating it never leaks into earlier forecasts
    assert not np.allclose(f.predict(a[:70], 14).values, base)


# ---------------------------------------------------------------- evaluation protocol: chronological, purged, no leakage
@pytest.fixture(scope="module")
def pipeline_common():
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[2] / "ml")
    sys.path.insert(0, root)
    try:
        import common
        return common
    finally:
        sys.path.remove(root)


def test_split_boundaries_are_ordered_and_training_labels_never_reach_later_segments(pipeline_common):
    T = 52560
    sp = pipeline_common.chronological_split(T)
    assert sp["train"][0] == 0 and sp["train"][1] == sp["val"][0] and sp["val"][1] == sp["test"][0] and sp["test"][1] == T
    rng = np.random.default_rng(0)
    for name in ("train", "val"):
        lo, hi = sp[name]
        items, origins, h = pipeline_common.sample_triples(rng, 50, lo, hi, 20000)
        assert (origins + h).max() < hi                      # every TARGET day lies inside its own segment (purge by construction)
        assert origins.min() >= max(lo, F.MIN_HISTORY - 1)
    items, origins, h = pipeline_common.test_grid(T, sp["test"][0], 50, 13)
    assert origins.min() >= sp["test"][0] and (origins + h).max() < T and set(np.unique(h)) == set(range(1, 31))


def test_shipped_benchmark_report_records_increasing_split_boundaries():
    rep = json.loads((config.ML_REPORTS_DIR / "forecast_benchmark_eval.json").read_text())
    blob = json.dumps(rep)
    assert "36792" in blob and "44676" in blob and "52560" in blob                     # train / validation / test boundaries of the 52,560-day series


# ---------------------------------------------------------------- metric correctness (hand-computed)
def test_metrics_against_hand_calculation():
    y, f = [100, 200, 0, 50], [110, 180, 10, 40]
    assert M.mae(y, f) == pytest.approx((10 + 20 + 10 + 10) / 4)
    assert M.rmse(y, f) == pytest.approx(np.sqrt((100 + 400 + 100 + 100) / 4))
    assert M.wape(y, f) == pytest.approx(50 / 350)                                      # sum|y-f| / sum|y|
    assert M.bias(y, f) == pytest.approx((10 - 20 + 10 - 10) / 350)                     # sum(f-y) / sum|y|
    m, n_zero = M.mape(y, f)
    assert n_zero == 1 and m == pytest.approx((10 / 100 + 20 / 200 + 10 / 50) / 3)       # zero actuals excluded and counted
    assert M.interval_coverage([1, 5, 9], [0, 0, 0], [2, 4, 10]) == pytest.approx(2 / 3)
    assert M.brier([1, 0], [1.0, 0.0]) == 0 and M.brier([1, 0], [0.0, 1.0]) == 1


def test_seasonal_naive_baseline_is_the_right_benchmark_on_seasonal_data():
    from app.ml.baselines import seasonal_naive, naive_last
    t = np.arange(70)
    a = 100 + 30 * np.sin(2 * np.pi * t / 7)
    truth = 100 + 30 * np.sin(2 * np.pi * np.arange(70, 77) / 7)
    assert M.wape(truth, seasonal_naive(a, 7)) < 1e-9 < M.wape(truth, naive_last(a, 7))


# ---------------------------------------------------------------- invalid values / missing features
@pytest.mark.parametrize("bad", [[], [1.0] * 10, [1.0] * 27, [1.0] * 40 + [float("nan")], [1.0] * 40 + [float("inf")], [1.0] * 40 + [-3.0], [None] * 40,
                                 ["a"] * 40, [[1.0] * 40], np.zeros((5, 5))])
def test_forecaster_rejects_unusable_history_with_a_clear_error(bad):
    with pytest.raises((F.InputError, ValueError)):
        MLForecaster.load(ARTS).predict(bad, 7)


def test_forecaster_rejects_missing_or_mismatched_known_factors():
    f, a = MLForecaster.load(ARTS), _series(60)
    with pytest.raises(F.InputError):
        f.predict(a, 7, past_factors=np.ones(59))
    with pytest.raises(F.InputError):
        f.predict(a, 7, future_factors=np.ones(3))
    with pytest.raises(F.InputError):
        f.predict(a, 7, past_factors=np.zeros(60))


def test_intermittent_or_unseen_series_are_not_sent_to_the_trained_model():
    ok, why = F.eligibility([0] * 40)
    assert not ok and why
    ok2, _ = F.eligibility(list(_series(60)))
    assert ok2


# ---------------------------------------------------------------- corrupted / incompatible / pinned / linked artefacts
def test_truncated_model_file_is_rejected_by_checksum(art):
    p = art / "forecast" / "v1" / "model.txt"
    p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])
    with pytest.raises(ArtifactError, match="checksum"):
        MLForecaster.load(art)


def test_corrupt_but_checksum_consistent_model_file_is_rejected_on_parse(art):
    d = art / "forecast" / "v1"
    (d / "model.txt").write_text("this is not a lightgbm model\n")
    meta = json.loads((d / "metadata.json").read_text())
    meta["model_sha256"] = sha256_file(d / "model.txt")
    (d / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ArtifactError, match="could not be parsed"):
        MLForecaster.load(art)


def test_unreadable_metadata_is_rejected(art):
    (art / "shortage" / "v1" / "metadata.json").write_text("{not json")
    with pytest.raises(ArtifactError, match="unreadable metadata"):
        ShortageModel.load(art)


def test_path_traversal_in_the_registry_pointer_is_refused(art):
    (art / "forecast" / "CURRENT").write_text("../shortage/v1\n")
    with pytest.raises(ArtifactError, match="invalid version"):
        MLForecaster.load(art)


def test_pinned_digest_must_match_even_if_metadata_is_rewritten(art):
    good = sha256_file(art / "forecast" / "v1" / "model.txt")
    assert MLForecaster.load(art, pin=good).model_id
    d = art / "forecast" / "v1"                                      # an attacker replaces model AND metadata consistently ...
    (d / "model.txt").write_bytes((d / "model.txt").read_bytes() + b"\n")
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    meta["model_sha256"] = sha256_file(d / "model.txt")
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    assert MLForecaster.load(art)                                    # ... which the unpinned check cannot notice,
    with pytest.raises(ArtifactError, match="pinned"):               # but the out-of-band pin does
        MLForecaster.load(art, pin=good)


def test_symlinked_artefacts_are_refused(art, tmp_path):
    d = art / "forecast" / "v1"
    outside = tmp_path / "elsewhere.txt"
    shutil.copy(d / "model.txt", outside)
    (d / "model.txt").unlink()
    try:
        (d / "model.txt").symlink_to(outside)
    except OSError as e:
        if getattr(e, "winerror", None) == 1314:
            pytest.skip("Windows SeCreateSymbolicLinkPrivilege required to test symlink creation")
        raise
    with pytest.raises(ArtifactError, match="symbolic"):
        MLForecaster.load(art)


def test_incompatible_shortage_schema_is_rejected(art):
    p = art / "shortage" / "v1" / "metadata.json"
    meta = json.loads(p.read_text())
    meta["feature_names"] = meta["feature_names"][:-1]
    p.write_text(json.dumps(meta))
    with pytest.raises(ArtifactError):
        ShortageModel.load(art)


# ---------------------------------------------------------------- shortage model: probabilities, threshold, baseline
def test_shipped_shortage_metadata_records_calibration_threshold_and_a_baseline():
    meta = json.loads((ARTS / "shortage" / "v1" / "metadata.json").read_text())
    x, y = meta["calibration"]["x"], meta["calibration"]["y"]
    assert x == sorted(x) and y == sorted(y) and 0 <= min(y) and max(y) <= 1          # isotonic: monotone, valid probabilities
    assert 0 < meta["operating_point"]["threshold"] < 1
    rep = json.loads((config.ML_REPORTS_DIR / "shortage_benchmark_eval.json").read_text())
    blob = json.dumps(rep).lower()
    assert "cover" in blob and "constant" in blob and "brier" in blob                       # days-of-cover rule and constant base-rate baselines, calibration metrics


def test_shortage_probabilities_are_monotone_in_cover_and_always_valid():
    s = ShortageModel.load(ARTS)
    rng = np.random.default_rng(0)
    for _ in range(50):
        n = 40
        d = rng.uniform(80, 250, n)
        oh = rng.uniform(0, 3000, n)
        p = s.score_record(d, oh, rng.uniform(0, 500, n), np.zeros(n), np.zeros(n))
        assert p["applicable"] and 0.0 <= p["probability"] <= 1.0 and p["flag"] == (p["probability"] >= p["threshold"])
    lean = s.score_record(np.full(40, 100.0), np.full(40, 20.0), np.zeros(40), np.zeros(40), np.zeros(40))["probability"]
    rich = s.score_record(np.full(40, 100.0), np.full(40, 3000.0), np.full(40, 700.0), np.zeros(40), np.zeros(40))["probability"]
    assert lean >= rich


# ---------------------------------------------------------------- API: honest integration status and risk basis
def test_risk_basis_explains_source_horizon_rules_and_limitations(client):
    j = client.get("/api/inventory/risk-basis").json()
    assert j["horizon_days"] == 14 and "deterministic" in j["method"] and set(j["status_rules"]) == {"CRITICAL", "WARNING", "NORMAL"}
    assert len(j["limitations"]) >= 3 and "not probabilities" in " ".join(j["limitations"])
    assert j["forecast_model"]["model_id"]
    s = j["shortage_onset_model"]
    assert s["integrated_with_inventory_status"] is False and s["available_in_application"]["in_transit"] is False and s["required_inputs"]


def test_risk_basis_thresholds_match_the_classifier_actually_used():
    from app.services import inventory as inv
    assert inv.classify(2.9, 0.0, 1e9, 0) == "CRITICAL" and inv.classify(3.1, 0.0, 1e9, 0) != "CRITICAL"
    lead = 4.0
    assert inv.classify(lead + 0.9, lead, 1e9, 0) == "CRITICAL" and inv.classify(lead + 1.1, lead, 1e9, 0) == "WARNING"
    assert inv.classify(lead + 3.1, lead, 1e9, 0) == "NORMAL" and inv.classify(lead + 3.1, lead, 5, 10) == "WARNING"
    rb = inv.risk_basis()
    assert "3" in rb["status_rules"]["CRITICAL"] and str(int(inv.SHORTAGE_HORIZON_DAYS)) in rb["predicted_shortage"]


def test_models_endpoint_reports_that_the_shortage_model_does_not_drive_status(client):
    j = client.get("/api/ml/models").json()["shortage_risk"]
    assert j["used_by_application_status"] is False and j["integration"]["integrated_with_inventory_status"] is False
    assert client.get("/api/inventory").json()[0]["status"] in ("CRITICAL", "WARNING", "NORMAL")


def test_inventory_status_does_not_change_when_the_shortage_model_is_unavailable(client, monkeypatch, tmp_path):
    before = client.get("/api/inventory").json()
    monkeypatch.setattr(config, "ML_ARTIFACT_DIR", tmp_path)
    ms.reset_cache()
    try:
        assert client.get("/api/inventory").json() == before                      # status is rule-based, independent of the shortage model
        assert client.get("/api/ml/models").json()["shortage_risk"]["loaded"] is False
    finally:
        monkeypatch.undo()
        ms.reset_cache()


def test_forecast_api_unseen_identifiers_and_consistency_with_inventory(client):
    assert client.get("/api/forecast?location=Base_99").status_code == 404
    f = client.get("/api/forecast?location=Base_04&supply=Medical&horizon=7").json()
    inv = next(i for i in client.get("/api/inventory?location=Base_04&supply=Medical").json())
    first7 = f["forecast"][:7]
    assert len(first7) == 7 and all(r["lo"] <= r["value"] <= r["hi"] for r in first7)
    assert inv["daily_use"] == pytest.approx(sum(r["value"] for r in first7) / 7, rel=0.02)      # risk views use the very forecast the forecast page shows

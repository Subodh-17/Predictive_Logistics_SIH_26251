"""Features, metrics, baselines: leakage safety, zero-demand handling, input validation."""
import math

import numpy as np
import pytest

from app.ml import baselines as B, features as F, metrics as M


def _Y(seed=0, T=300, C=3, lam=100):
    return np.random.default_rng(seed).poisson(lam, (T, C)).astype(float)


def test_feature_names_match_matrix_width():
    X, scale = F.build(_Y(), np.array([0, 1]), np.array([60, 90]), np.array([1, 30]))
    assert X.shape == (2, len(F.FEATURE_NAMES)) and np.all(scale >= F.SCALE_FLOOR)


@pytest.mark.parametrize("h", [1, 6, 7, 8, 14, 15, 29, 30])
def test_features_never_read_the_future(h):
    """Changing every observation after the origin must not change a single feature."""
    Y = _Y(); o = 120
    X1, _ = F.build(Y, np.array([1]), np.array([o]), np.array([h]))
    Y2 = Y.copy(); Y2[o + 1:, 1] = 1e6
    X2, _ = F.build(Y2, np.array([1]), np.array([o]), np.array([h]))
    assert np.array_equal(X1, X2)


def test_seasonal_lag_index_is_in_the_past_and_same_weekday():
    o = np.full(30, 100); h = np.arange(1, 31)
    for j in range(1, F.N_SEASONAL + 1):
        idx = F.seasonal_lag_index(o, h, j)
        assert np.all(idx <= o) and np.all((o + h - idx) % 7 == 0) and np.all(idx >= o - 27)


def test_target_only_read_when_requested_and_bounds_checked():
    Y = _Y(T=100)
    with pytest.raises(F.InputError):
        F.build(Y, np.array([0]), np.array([95]), np.array([10]), with_target=True)
    F.build(Y, np.array([0]), np.array([95]), np.array([10]))          # fine without target (inference)
    with pytest.raises(F.InputError):
        F.build(Y, np.array([0]), np.array([5]), np.array([1]))         # not enough history
    with pytest.raises(F.InputError):
        F.build(Y, np.array([0]), np.array([50]), np.array([31]))       # horizon too long


@pytest.mark.parametrize("bad", [[1.0] * 10, [1.0] * 27 + [float("nan")], [1.0] * 27 + [-1.0], [[1.0] * 30]])
def test_invalid_history_is_rejected(bad):
    with pytest.raises(F.InputError):
        F.validate_history(bad)


def test_eligibility_flags_zero_and_intermittent_demand():
    assert F.eligibility([100.0] * 40)[0]
    ok, why = F.eligibility([0.0] * 40)
    assert not ok and "below 1" in why
    ok, why = F.eligibility(([0.0, 0.0, 50.0, 80.0] * 10))
    assert not ok and "intermittent" in why


def test_all_zero_series_does_not_divide_by_zero():
    X, s = F.build(np.zeros((60, 1)), np.array([0]), np.array([40]), np.array([5]))
    assert np.all(np.isfinite(X)) and s[0] == F.SCALE_FLOOR


# ---- metrics
def test_metric_definitions():
    y, f = np.array([100.0, 200.0]), np.array([110.0, 180.0])
    assert M.mae(y, f) == 15 and M.rmse(y, f) == pytest.approx(math.sqrt(250))
    assert M.wape(y, f) == pytest.approx(30 / 300) and M.bias(y, f) == pytest.approx(-10 / 300)


def test_zero_denominator_handling():
    assert math.isnan(M.wape([0, 0], [1, 2])) and math.isnan(M.bias([0, 0], [1, 2]))
    v, excluded = M.mape([0, 2, 4], [1, 1, 5])
    assert v == pytest.approx((0.5 + 0.25) / 2) and excluded == 1
    v, excluded = M.mape([0, 0], [1, 1])
    assert math.isnan(v) and excluded == 2
    with pytest.raises(ValueError):
        M.mae([], [])
    with pytest.raises(ValueError):
        M.mae([1, 2], [1])


def test_interval_coverage_and_calibration_helpers():
    assert M.interval_coverage([1, 5, 9], [0, 0, 0], [2, 4, 10]) == pytest.approx(2 / 3)
    assert M.brier([1, 0], [1.0, 0.0]) == 0 and M.expected_calibration_error([1, 0, 1, 0], [0.5] * 4) == pytest.approx(0.0)


# ---- baselines
def test_seasonal_naive_uses_same_weekday_and_is_exact_on_periodic_data():
    hist = np.tile([10.0, 20, 30, 40, 50, 60, 70], 8)
    assert np.array_equal(B.seasonal_naive(hist, 14), np.tile([10.0, 20, 30, 40, 50, 60, 70], 2))


def test_naive_and_trailing_mean():
    h = np.arange(1.0, 41.0)
    assert np.all(B.naive_last(h, 5) == 40) and B.trailing_mean(h, 3)[0] == h[-28:].mean()

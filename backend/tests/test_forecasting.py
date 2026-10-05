import math

import pytest

from app.services import forecasting as F
from app.services.domain import ND, NF

FLAT_W = [0.0] * (ND + NF)


def test_constant_history_gives_flat_forecast_up_to_season():
    hist = [100.0] * ND
    fit, fut = F.fit_and_forecast(hist, 0.0, FLAT_W)
    assert fit[0] is None and len(fit) == ND and len(fut) == NF
    # de-seasonalised level is ~constant, so the forecast is just the weekly season around ~100
    for k, v in enumerate(fut):
        assert v == pytest.approx(100 * F.weekly_season(ND + k) / F.weekly_season(0) * 1.0, rel=0.12)


def test_weather_raises_forecast_for_sensitive_supply_only():
    hist = [100.0] * ND
    w = [0.2] * ND + [0.9] * NF
    _, sens = F.fit_and_forecast(hist, 0.6, w)
    _, insens = F.fit_and_forecast(hist, 0.0, w)
    assert sum(sens) > sum(insens) * 1.1


def test_model_generated_series_has_low_backtest_error():
    w = [0.3 + 0.2 * math.sin(d / 8) for d in range(ND + NF)]
    hist = [round(200 * (1 + 0.6 * 0.5 * w[d]) * F.weekly_season(d)) for d in range(ND)]
    fit, _ = F.fit_and_forecast(hist, 0.5, w)
    bt = F.backtest(hist, fit)
    assert bt.mape < 3 and 0 <= bt.coverage <= 100 and bt.rmse >= 0


def test_confidence_formula_and_labels():
    assert F.confidence(3.7, 7)["value"] == round(100 - 3.7 * (1 + 7 / 30))
    assert F.confidence(0.0, 30)["label"] == "HIGH"
    assert F.confidence(20, 30)["value"] < F.confidence(20, 7)["value"]      # longer horizon -> lower confidence
    assert F.confidence(80, 30)["value"] == 0 and F.confidence(80, 30)["label"] == "LOW"   # clamped at 0


def test_interval_band_widens_with_horizon():
    band = F.interval_band([100] * 30, 10)
    assert band[0][0] < 100 < band[0][1]
    assert (band[29][1] - band[29][0]) > (band[0][1] - band[0][0])


def test_forecast_matches_v3_golden(snap):
    import json, pathlib
    g = json.loads((pathlib.Path(__file__).parent / "golden_v3.json").read_text())
    for it in g["items"]:
        p = next(p for p in snap.positions if p.location_id == it["l"] and p.supply_id == it["t"])
        assert p.f7 == pytest.approx(it["f7"], abs=1e-9)


def test_seven_14_30_day_totals_increase():
    _, fut = F.fit_and_forecast([100] * ND, 0.2, FLAT_W)
    assert sum(fut[:7]) < sum(fut[:14]) < sum(fut[:30])

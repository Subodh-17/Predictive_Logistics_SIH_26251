import pytest

from app.services import inventory as inv


def test_days_of_supply():
    assert inv.days_of_supply(1000, 250) == 4.0
    assert inv.days_of_supply(0, 100) == 0
    assert inv.days_of_supply(100, 0) == float("inf")


@pytest.mark.parametrize("days,lead,stock,safety,expected", [
    (2.9, 1.0, 500, 100, "CRITICAL"),     # < 3 d cover
    (5.0, 4.5, 500, 100, "CRITICAL"),     # cover below lead time + 1 d
    (5.0, 1.5, 50, 100, "WARNING"),       # below safety stock
    (4.0, 1.5, 500, 100, "WARNING"),      # cover below lead + 3 d
    (9.0, 1.5, 500, 100, "NORMAL"),
])
def test_risk_classification(days, lead, stock, safety, expected):
    assert inv.classify(days, lead, stock, safety) == expected


def test_boundaries():
    assert inv.classify(3.0, 1.0, 500, 100) == "WARNING"      # exactly 3 d is not critical
    assert inv.classify(4.5, 1.5, 500, 100) == "NORMAL"       # exactly lead+3 is normal


def test_predicted_shortage():
    assert inv.predicted_shortage(100, 400, 14) == 1000
    assert inv.predicted_shortage(100, 5000, 14) == 0         # never negative


def test_replenishment_qty_rounds_to_50_and_zero_when_normal():
    assert inv.replenishment_qty("NORMAL", 100, 100, 2, 50) == 0
    q = inv.replenishment_qty("CRITICAL", 400, 100, 2, 100)   # 400 + 700 - 100 = 1000
    assert q == 1000 and q % 50 == 0
    assert inv.replenishment_qty("CRITICAL", 10, 1, 1, 5000) == 0   # oversupplied -> never negative


def test_location_status_rules():
    assert inv.location_status(2, 0) == "CRITICAL"
    assert inv.location_status(1, 0) == "WARNING"
    assert inv.location_status(0, 3) == "WARNING"
    assert inv.location_status(0, 2) == "NORMAL"


def test_overall_risk_index_bounds_and_monotonic():
    lo = inv.overall_risk_index(0, 0, 50, 0.1, 0, 100)
    hi = inv.overall_risk_index(20, 10, 50, 0.8, 90, 100)
    assert 0 <= lo < hi <= 100
    assert inv.risk_band(10)[0] == "LOW" and inv.risk_band(50)[0] == "HIGH" and inv.risk_band(80)[0] == "SEVERE"


def test_engine_items_use_inventory_rules(snap):
    from app.services import engine
    from app.services.domain import Params
    r = engine.compute(snap, Params())
    for i in r.items:
        assert i.days == pytest.approx(i.stock / i.dem)
        assert i.status == inv.classify(i.days, i.lead, i.stock, i.safety)

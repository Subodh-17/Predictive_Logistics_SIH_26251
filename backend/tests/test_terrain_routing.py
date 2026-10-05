import pytest

from app.services import routing as rt
from app.services import terrain as T
from app.services.domain import Params, Route


def test_terrain_risk_formula():
    assert T.terrain_risk(0.3, 1) == pytest.approx(0.31)
    assert T.terrain_risk(0.85, 3) == pytest.approx(0.895)
    assert T.terrain_risk(0, 0) == 0


def test_terrain_slows_vehicles_and_raises_eta():
    flat = T.effective_speed(50, 0.2, 0.0, 0.3)
    hilly = T.effective_speed(50, 0.2, 0.8, 0.3)
    assert hilly < flat
    assert 100 / hilly > 100 / flat


def test_speed_monotonic_in_road_and_weather_and_floor():
    assert T.effective_speed(50, 0.8, 0.3, 0.2) < T.effective_speed(50, 0.1, 0.3, 0.2)
    assert T.effective_speed(50, 0.2, 0.3, 0.9) < T.effective_speed(50, 0.2, 0.3, 0.1)
    assert T.effective_speed(10, 1, 1, 1) == 8.0


def test_route_risk_is_bounded_and_terrain_sensitive():
    assert 0 <= T.route_risk(1, 1, 1, 500) <= 1
    assert T.route_risk(0.3, 0.3, 0.9, 100) > T.route_risk(0.3, 0.3, 0.1, 100)


def _route(rid, depot, dest, km, road, speed, td, el):
    return Route(rid, depot, dest, km, road, speed, "t", td, el, "x")


def test_evaluate_route_terrain_changes_eta_and_risk():
    a = rt.evaluate_route(_route("A", "D", "B", 100, 0.2, 50, 0.1, 0), 0.3, Params())
    b = rt.evaluate_route(_route("B", "D", "B", 100, 0.2, 50, 0.9, 3), 0.3, Params())
    assert b.eta > a.eta and b.risk > a.risk and b.terrain_risk > a.terrain_risk


def test_scenario_road_and_weather_raise_eta(snap):
    r = snap.routes[0]
    base = rt.evaluate_route(r, 0.3, Params())
    assert rt.evaluate_route(r, 0.3, Params(road=1.0)).eta > base.eta
    assert rt.evaluate_route(r, 0.9, Params()).eta > base.eta


def test_route_selection_prefers_lowest_score_and_reports_reason():
    fast = rt.evaluate_route(_route("FAST", "D1", "B", 60, 0.1, 55, 0.1, 0), 0.3, Params())
    slow = rt.evaluate_route(_route("SLOW", "D2", "B", 150, 0.6, 34, 0.7, 2), 0.3, Params())
    veh = {"V1": ("D1", 5000), "V2": ("D2", 5000)}
    rows = rt.rank_routes([slow, fast], veh, "B")
    assert rows[0]["ev"].id == "FAST" and rows[0]["feasible"]
    reason = rt.explain_selection(rows, "B")
    assert "FAST" in reason and "lowest combined score" in reason


def test_route_without_vehicle_is_infeasible_and_never_selected():
    fast = rt.evaluate_route(_route("FAST", "D1", "B", 60, 0.1, 55, 0.1, 0), 0.3, Params())
    slow = rt.evaluate_route(_route("SLOW", "D2", "B", 150, 0.6, 34, 0.7, 2), 0.3, Params())
    rows = rt.rank_routes([fast, slow], {"V1": ("D1", 0), "V2": ("D2", 4000)}, "B")
    assert rows[0]["ev"].id == "SLOW" and not rows[1]["feasible"]
    assert "only feasible corridor" in rt.explain_selection(rows, "B")
    assert "No feasible route" in rt.explain_selection(rt.rank_routes([fast, slow], {"V1": ("D1", 0)}, "B"), "B")


def test_capacity_penalty_changes_score_when_capacity_is_short():
    ev = rt.evaluate_route(_route("A", "D1", "B", 60, 0.1, 55, 0.1, 0), 0.3, Params())
    assert rt.score_route(ev, 1000, 5000) > rt.score_route(ev, 10000, 5000) == pytest.approx(rt.score_route(ev, 10000, 0))
    assert rt.score_route(ev, 1000, 5000) - rt.score_route(ev, 1000, 0) <= rt.CAPACITY_PENALTY_WEIGHT + 1e-9


def test_capacity_can_flip_route_choice():
    a = rt.evaluate_route(_route("A", "D1", "B", 60, 0.1, 55, 0.1, 0), 0.3, Params())   # best risk/eta, tiny capacity
    b = rt.evaluate_route(_route("B", "D2", "B", 75, 0.15, 52, 0.15, 0), 0.3, Params())
    veh = {"V1": ("D1", 100), "V2": ("D2", 9000)}
    assert rt.rank_routes([a, b], veh, "B", 0)[0]["ev"].id == "A"
    assert rt.rank_routes([a, b], veh, "B", 5000)[0]["ev"].id == "B"

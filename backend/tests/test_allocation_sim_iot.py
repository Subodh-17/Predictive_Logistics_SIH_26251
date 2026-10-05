import json
import pathlib

import pytest

from app.services import engine, iot, priority, simulation
from app.services.allocation import allocate
from app.services.domain import Params, Snapshot

GOLD = json.loads((pathlib.Path(__file__).parent / "golden_v3.json").read_text())


# ---------------- vehicle capacity
def test_effective_capacity_scales_with_availability_and_skips_unavailable(snap):
    base = engine.compute(snap, Params())
    half = engine.compute(snap, Params(vehicles=0.5))
    assert base.capacity == 34000          # V008 (3,500) is in maintenance
    assert base.vehicles_eff["V008"][1] == 0
    assert half.capacity == pytest.approx(17000, abs=10)
    assert half.deficit > base.deficit


# ---------------- v3 parity (golden values produced by running the original v3 JavaScript)
@pytest.mark.parametrize("k", range(3))
def test_engine_matches_v3_golden_scenarios(snap, k):
    s = GOLD["scenarios"][k]
    p = s["p"]
    r = engine.compute(snap, Params(p["d"], p["w"], p["r"], p["v"]))
    assert (r.n_critical, r.n_warning, r.shortage_locations, r.capacity, r.need, r.deficit, r.risk_index, r.short_total) == \
           (s["crit"], s["warn"], s["sloc"], s["cap"], s["need"], s["deficit"], s["risk"], s["short"])
    assert r.avg_route_risk == pytest.approx(s["ar"], abs=1e-9) and r.mean_delay == pytest.approx(s["delay"], abs=1e-9)


def test_baseline_headline_case_matches_v3(snap):
    r = engine.compute(snap, Params())
    i = next(i for i in r.items if i.location_id == "Base_04" and i.supply_id == "Medical")
    assert i.days == pytest.approx(2.8, abs=0.01) and i.status == "CRITICAL"


# ---------------- priority
def test_priority_sorted_scores_in_range_and_only_at_risk(snap):
    r = engine.compute(snap, Params())
    p = priority.prioritise(r)
    assert len(p) == r.n_critical + r.n_warning
    assert [x.score for x in p] == sorted((x.score for x in p), reverse=True)
    assert all(0 <= x.score <= 100 for x in p)
    assert sum(priority.WEIGHTS.values()) == pytest.approx(1.0)


def test_priority_rises_when_transport_is_lost(snap):
    base = {(p.item.location_id, p.item.supply_id): p.score for p in priority.prioritise(engine.compute(snap, Params()))}
    worse = {(p.item.location_id, p.item.supply_id): p.score for p in priority.prioritise(engine.compute(snap, Params(vehicles=0.5, weather=0.8)))}
    common = set(base) & set(worse)
    assert common and sum(worse[k] for k in common) > sum(base[k] for k in common)


# ---------------- allocation
def test_allocation_never_exceeds_vehicle_capacity_or_need(snap):
    for p in (Params(), Params(.3, 1, 1, .6), Params(.5, .5, .5, .5)):
        r = engine.compute(snap, p)
        a = allocate(r, snap)
        per_vehicle = {}
        for row in a.rows:
            assert row.allocated + row.unmet == row.need and row.allocated <= row.need
            for g in row.legs:
                per_vehicle[g.vehicle] = per_vehicle.get(g.vehicle, 0) + g.quantity
        for vid, used in per_vehicle.items():
            assert used <= r.vehicles_eff[vid][1]
        assert a.used == sum(per_vehicle.values()) and a.used + a.capacity_left == r.capacity


def test_allocation_respects_depot_stock(snap):
    """Cut a depot's stock of one supply to a small amount; allocation must not ship more than that depot holds."""
    s = Snapshot(snap.locations, snap.supplies, snap.routes, snap.vehicles, snap.positions, dict(snap.depot_stock), snap.weather)
    for d in ("Depot_A", "Depot_B", "Depot_C"):
        s.depot_stock[(d, "Water")] = 100
    r = engine.compute(s, Params())
    a = allocate(r, s)
    shipped = {}
    for row in a.rows:
        for g in row.legs:
            if row.prio.item.supply_id == "Water":
                shipped[g.depot] = shipped.get(g.depot, 0) + g.quantity
    assert shipped and all(v <= 100 for v in shipped.values())
    water_rows = [x for x in a.rows if x.prio.item.supply_id == "Water"]
    assert any(x.unmet and x.unmet_reason == "DEPOT STOCK" for x in water_rows)
    assert all(a.depot_stock_after[k] >= 0 for k in a.depot_stock_after)


def test_allocation_with_no_vehicles_serves_nothing(snap):
    r = engine.compute(snap, Params())
    r.vehicles_eff = {k: (d, 0) for k, (d, _) in r.vehicles_eff.items()}
    a = allocate(r, snap)
    assert a.used == 0 and a.unmet == sum(x.need for x in a.rows)
    assert {x.unmet_reason for x in a.rows} == {"NO FEASIBLE ROUTE"}


def test_unserved_need_only_when_serving_depots_are_exhausted(snap):
    """Ranking is by priority, but a vehicle can only serve routes from its own depot, so a lower-ranked item on another
    depot may be served first. Whenever an item is left short for VEHICLE CAPACITY, every depot that can serve it must be out of capacity."""
    r = engine.compute(snap, Params(vehicles=0.5))
    a = allocate(r, snap)
    used = {}
    for row in a.rows:
        for g in row.legs:
            used[g.vehicle] = used.get(g.vehicle, 0) + g.quantity
    left_by_depot = {}
    for vid, (dep, cap) in r.vehicles_eff.items():
        left_by_depot[dep] = left_by_depot.get(dep, 0) + cap - used.get(vid, 0)
    assert [x.prio.score for x in a.rows] == sorted((x.prio.score for x in a.rows), reverse=True)   # plan is processed in priority order
    short = [x for x in a.rows if x.unmet and x.unmet_reason == "VEHICLE CAPACITY"]
    assert short
    for row in short:
        for d in {e.depot_id for e in r.routes_to(row.prio.item.location_id)}:
            assert left_by_depot.get(d, 0) == 0, f"{row.prio.item.location_id} left short while {d} still has capacity"


# ---------------- simulation
def test_baseline_simulation_has_no_change(snap):
    out = simulation.run(snap, Params())
    assert out["before"] == out["after"]
    assert all(l["before"] == l["after"] for l in out["locations"])
    assert "No location changed status" in out["explanation"][-1]


def test_simulation_worsens_every_risk_metric_under_stress(snap):
    out = simulation.run(snap, Params(.3, 1, 1, .6))
    b, a = out["before"], out["after"]
    assert a["critical_items"] > b["critical_items"] and a["transport_capacity"] < b["transport_capacity"]
    assert a["mean_route_risk"] > b["mean_route_risk"] and a["mean_eta_delay_h"] > b["mean_eta_delay_h"]
    assert a["capacity_deficit"] > b["capacity_deficit"] and a["unmet_after_allocation"] > b["unmet_after_allocation"]
    assert a["overall_risk_index"] > b["overall_risk_index"] and a["expected_shortage_units"] > b["expected_shortage_units"]
    text = " ".join(out["explanation"])
    for needle in ("Demand +30%", "Severe weather", "Poor road", "Fleet availability 60%", "Terrain amplifies"):
        assert needle in text
    assert any(l["before"] != l["after"] for l in out["locations"])


@pytest.mark.parametrize("p,metric,direction", [
    (Params(demand=.5), "critical_items", 1), (Params(road=1), "mean_eta_delay_h", 1),
    (Params(weather=1), "mean_route_risk", 1), (Params(vehicles=.5), "transport_capacity", -1)])
def test_each_lever_moves_its_metric(snap, p, metric, direction):
    out = simulation.run(snap, p)
    delta = out["after"][metric] - out["before"][metric]
    assert delta * direction > 0


def test_simulation_is_deterministic(snap):
    assert simulation.run(snap, Params(.2, .5, .5, .8)) == simulation.run(snap, Params(.2, .5, .5, .8))


# ---------------- IoT
def test_iot_receive_issue_count():
    assert iot.apply_event(100, "RECEIVE", 50).after == 150
    assert iot.apply_event(100, "ISSUE", 30).after == 70
    assert iot.apply_event(100, "COUNT", 80).after == 80
    x = iot.apply_event(100, "ISSUE", 500)
    assert x.after == 0 and x.clipped and x.delta == -100


@pytest.mark.parametrize("t,q", [("BOGUS", 5), ("ISSUE", -1), ("RECEIVE", 0)])
def test_iot_rejects_bad_events(t, q):
    with pytest.raises(iot.IotError):
        iot.apply_event(100, t, q)


def test_iot_event_changes_inventory_risk(snap):
    """A RECEIVE scan on the critical Base_04 Medical item should lift it out of CRITICAL."""
    key = ("Base_04", "Medical")
    before = engine.compute(snap, Params())
    stock = next(p.stock for p in snap.positions if (p.location_id, p.supply_id) == key)
    from app.seed_data import snapshot_from_dataset, build_dataset
    new = snapshot_from_dataset(build_dataset(), {key: iot.apply_event(stock, "RECEIVE", 2000).after})
    after = engine.compute(new, Params())
    gi = lambda r: next(i for i in r.items if (i.location_id, i.supply_id) == key)
    assert gi(before).status == "CRITICAL" and gi(after).status == "NORMAL"
    assert after.n_critical == before.n_critical - 1


def test_iot_generator_is_deterministic_and_valid(snap):
    r = engine.compute(snap, Params())
    a = allocate(r, snap)
    e1, e2 = iot.generate_events(r, a, 10, 7), iot.generate_events(r, a, 10, 7)
    assert e1 == e2 and len(e1) == 10
    assert all(e["event_type"] in iot.EVENT_TYPES and e["quantity"] > 0 and e["device_id"].startswith("ESP32-SIM") for e in e1)
    assert all(c["simulated"] for c in iot.feed_from_allocation(a))

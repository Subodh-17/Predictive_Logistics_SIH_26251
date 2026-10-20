"""V7 logistics correctness: allocation conservation, insufficient stock, route feasibility/closure, delayed shipments, scenario fairness,
idempotent events, concurrent updates and inventory-ledger consistency."""
import copy
import threading
from collections import defaultdict
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from app import models as m
from app.database import SessionLocal
from app.services import engine, routing as rt, simulation
from app.services.allocation import allocate
from app.services.domain import Params

SCENARIOS = [Params(), Params(.2, .3, .2, .9), Params(.5, 1, 1, .5), Params(0, 1, 0, 1), Params(.5, 0, 1, .5), Params(.1, .6, .4, .7)]


# ------------------------------------------------------------------------------------------------------ allocation invariants
@pytest.mark.parametrize("p", SCENARIOS)
def test_allocation_conserves_quantities_and_respects_every_constraint(snap, p):
    r = engine.compute(snap, p)
    a = allocate(r, snap)
    per_vehicle, per_depot_supply = defaultdict(float), defaultdict(float)
    feasible_routes = {e.id for e in r.routes if e.weather_risk < rt.CLOSURE_WEATHER_RISK}
    for row in a.rows:
        assert row.allocated + row.unmet == row.need and 0 <= row.allocated <= row.need
        assert sum(g.quantity for g in row.legs) == row.allocated
        assert (row.unmet == 0) == (row.unmet_reason == "") and row.status in ("FULL", "PARTIAL", "NOT SERVED")
        for g in row.legs:
            assert g.quantity > 0 and g.route in feasible_routes, "a leg may only use a feasible, open route"
            per_vehicle[g.vehicle] += g.quantity
            per_depot_supply[(g.depot, row.prio.item.supply_id)] += g.quantity
    for v, used in per_vehicle.items():
        assert used <= r.vehicles_eff[v][1] + 1e-9
    for k, used in per_depot_supply.items():
        assert used <= snap.depot_stock.get(k, 0) + 1e-9
        assert a.depot_stock_after[k] == snap.depot_stock[k] - used            # stock leaving a depot is exactly what was allocated
    assert all(v >= 0 for v in a.depot_stock_after.values())


def test_allocation_is_deterministic_and_does_not_mutate_the_snapshot(snap):
    before = copy.deepcopy(snap.depot_stock)
    r = engine.compute(snap, Params(.3, .5, .3, .8))
    a1, a2 = allocate(r, snap), allocate(r, snap)
    assert snap.depot_stock == before
    assert [(x.prio.item.location_id, x.prio.item.supply_id, x.allocated) for x in a1.rows] == [(x.prio.item.location_id, x.prio.item.supply_id, x.allocated) for x in a2.rows]


def test_insufficient_depot_stock_is_reported_with_its_binding_constraint(snap):
    empty = replace(snap, depot_stock={k: 0 for k in snap.depot_stock})
    a = allocate(engine.compute(empty, Params(.3, 0, 0, 1)), empty)
    assert a.used == 0 and a.unmet > 0
    assert {r.unmet_reason for r in a.rows} == {"DEPOT STOCK"} and all(r.status == "NOT SERVED" and not r.legs for r in a.rows)


def test_half_stock_serves_partially_never_more_than_exists(snap):
    half = replace(snap, depot_stock={k: v // 2 for k, v in snap.depot_stock.items()})
    a = allocate(engine.compute(half, Params()), half)
    used = defaultdict(float)
    for row in a.rows:
        for g in row.legs:
            used[(g.depot, row.prio.item.supply_id)] += g.quantity
    assert all(u <= half.depot_stock[k] for k, u in used.items())
    full_unmet = allocate(engine.compute(snap, Params()), snap).unmet
    assert a.unmet >= full_unmet and a.used <= sum(half.depot_stock.values())      # less stock can never serve more demand


# --------------------------------------------------------------------------------------------------------- route feasibility
def test_baseline_has_no_closed_corridor_and_extreme_weather_closes_only_the_most_exposed(snap):
    assert all(e.weather_risk < rt.CLOSURE_WEATHER_RISK for e in engine.compute(snap, Params()).routes)
    storm = engine.compute(snap, Params(0, 1, 0, 1))
    closed = [e for e in storm.routes if e.weather_risk >= rt.CLOSURE_WEATHER_RISK]
    assert 1 <= len(closed) < len(storm.routes)


def test_a_graph_path_alone_is_not_feasibility(snap):
    storm = engine.compute(snap, Params(0, 1, 0, 1))
    closed = next(e for e in storm.routes if e.weather_risk >= rt.CLOSURE_WEATHER_RISK)
    rows = rt.rank_routes(storm.routes, storm.vehicles_eff, closed.dest_id)
    me = next(r for r in rows if r["ev"].id == closed.id)
    assert me["capacity"] > 0 and me["feasible"] is False and me["blocked_reason"] == "ROUTE CLOSED"       # vehicles exist, the route still is not usable
    assert rows[-1]["ev"].id == closed.id or all(r["feasible"] is False or r["ev"].id != closed.id for r in rows)
    assert not any(g.route == closed.id for row in allocate(storm, snap).rows for g in row.legs)


def test_no_available_vehicle_makes_every_route_of_that_depot_infeasible(snap):
    r = engine.compute(snap, Params())
    zero = {vid: (d, 0) for vid, (d, _) in r.vehicles_eff.items()}
    rows = rt.rank_routes(r.routes, zero, r.routes[0].dest_id)
    assert rows and all(not x["feasible"] and x["blocked_reason"] == "NO AVAILABLE VEHICLE" for x in rows)
    assert rt.explain_selection(rows, r.routes[0].dest_id).startswith("No feasible route")


def test_destination_without_corridors_has_no_feasible_route(snap):
    r = engine.compute(snap, Params())
    assert rt.rank_routes(r.routes, r.vehicles_eff, "Base_DOES_NOT_EXIST") == []
    assert "no corridor serves this location" in rt.explain_selection([], "Base_DOES_NOT_EXIST")


def test_delays_are_never_negative_and_eta_never_falls_as_weather_or_roads_worsen(snap):
    prev = {}
    for w in (0, .25, .5, .75, 1):
        for e in engine.compute(snap, Params(0, w, 0, 1)).routes:
            assert e.delay >= -1e-9 and e.eta >= e.route.distance_km / e.route.nominal_speed - 1e-9
            assert e.eta >= prev.get(("w", e.id), 0) - 1e-9
            prev[("w", e.id)] = e.eta
    for rd in (0, .5, 1):
        for e in engine.compute(snap, Params(0, 0, rd, 1)).routes:
            assert e.eta >= prev.get(("r", e.id), 0) - 1e-9
            prev[("r", e.id)] = e.eta


def test_scenario_comparison_is_reproducible_and_baseline_is_shared(snap):
    p = Params(.3, .6, .4, .7)
    a, b = simulation.run(snap, p), simulation.run(snap, p)
    assert a["before"] == b["before"] and a["after"] == b["after"]                  # same inputs, same outputs
    assert a["before"] == simulation.run(snap, Params(.5, 1, 1, .5))["before"]       # every scenario is compared with the SAME baseline
    assert simulation.run(snap, Params())["before"] == simulation.run(snap, Params())["after"]


# ------------------------------------------------------------------------------------------- idempotency / ledger / concurrency
EVT = dict(device_id="ESP32-SIM-01", tag_id="RFID-SIM-1234", event_type="ISSUE", location_id="Base_04", supply_id="Medical", quantity=10)


def _stock(loc="Base_04", sup="Medical"):
    with SessionLocal() as db:
        return float(db.scalar(select(m.InventoryRow.stock).where(m.InventoryRow.location_id == loc, m.InventoryRow.supply_id == sup)))


def test_duplicate_event_id_is_rejected_and_stock_changes_once(operator_client, client):
    client.post("/api/iot/reset")
    s0 = _stock()
    body = dict(EVT, event_id="evt-0001-unique")
    assert operator_client.post("/api/iot/update", json=body).status_code == 200
    dup = operator_client.post("/api/iot/update", json=body)
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_EVENT"
    assert _stock() == s0 - 10
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.IotEventRow).where(m.IotEventRow.event_id == "evt-0001-unique")) == 1
    assert operator_client.post("/api/iot/update", json=dict(EVT, event_id="evt-0002-unique")).status_code == 200      # a different key is a new event
    assert operator_client.post("/api/iot/update", json=EVT).status_code == 200 and operator_client.post("/api/iot/update", json=EVT).status_code == 200   # no key: V6 behaviour
    assert operator_client.post("/api/iot/update", json=dict(EVT, event_id="x")).status_code == 422                  # malformed key
    client.post("/api/iot/reset")


def test_concurrent_events_on_one_item_never_lose_an_update(app_ctx, client):
    app, tokens = app_ctx
    from fastapi.testclient import TestClient
    client.post("/api/iot/reset")
    s0, n_threads, per = _stock(), 6, 5
    assert s0 >= 10 * n_threads * per, "scenario stock must cover the test so clipping at zero cannot mask a lost update"
    codes = []

    def worker():
        c = TestClient(app, raise_server_exceptions=False, headers={"Authorization": "Bearer " + tokens["t_operator"]})
        for _ in range(per):
            codes.append(c.post("/api/iot/update", json=EVT).status_code)

    ts = [threading.Thread(target=worker) for _ in range(n_threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ok = codes.count(200)
    assert ok == n_threads * per, codes                                         # nothing failed
    assert _stock() == s0 - 10 * ok                                             # exactly the sum of the issued quantities (no lost updates)
    client.post("/api/iot/reset")


def test_concurrent_duplicates_with_one_key_apply_exactly_once(app_ctx, client):
    app, tokens = app_ctx
    from fastapi.testclient import TestClient
    client.post("/api/iot/reset")
    s0, codes = _stock(), []

    def worker():
        c = TestClient(app, raise_server_exceptions=False, headers={"Authorization": "Bearer " + tokens["t_operator"]})
        codes.append(c.post("/api/iot/update", json=dict(EVT, event_id="evt-race-0001")).status_code)

    ts = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes).count(200) == 1 and all(c in (200, 409) for c in codes), codes
    assert _stock() == s0 - 10
    client.post("/api/iot/reset")


def test_event_ledger_is_a_consistent_chain_and_matches_current_stock(operator_client, client):
    client.post("/api/iot/reset")
    s0 = _stock()
    seq = [("ISSUE", 40), ("RECEIVE", 15), ("ISSUE", 5), ("COUNT", 77), ("ISSUE", 1)]
    for t, q in seq:
        assert operator_client.post("/api/iot/update", json=dict(EVT, event_type=t, quantity=q)).status_code == 200
    with SessionLocal() as db:
        rows = list(db.scalars(select(m.IotEventRow).where(m.IotEventRow.location_id == "Base_04", m.IotEventRow.supply_id == "Medical").order_by(m.IotEventRow.id)))
    assert len(rows) == len(seq) and float(rows[0].stock_before) == s0
    for prev, cur in zip(rows, rows[1:]):
        assert float(cur.stock_before) == float(prev.stock_after)                 # no gap, no overlap in the ledger
    assert float(rows[-1].stock_after) == _stock() == 76
    client.post("/api/iot/reset")


def test_issue_beyond_available_stock_clips_at_zero_and_says_so(operator_client, client):
    client.post("/api/iot/reset")
    r = operator_client.post("/api/iot/update", json=dict(EVT, quantity=900_000))
    assert r.status_code == 200 and r.json()["stock_after"] == 0 and r.json()["clipped_at_zero"] is True and _stock() == 0
    client.post("/api/iot/reset")


def test_api_route_comparison_reports_closure_under_a_storm_scenario(client):
    rows = client.get("/api/routes/compare?destination=Base_04&weather=1").json()["routes"]
    assert all(r["decision"] in ("SELECTED", "ALTERNATIVE", "NO VEHICLE", "ROUTE CLOSED") for r in rows)
    for r in client.get("/api/routes?weather=1").json():
        assert (r["blocked_reason"] == "ROUTE CLOSED") == (r["weather_risk"] >= rt.CLOSURE_WEATHER_RISK)
        assert r["feasible"] == (r["blocked_reason"] == "")


def test_saved_scenarios_can_be_compared_fairly(operator_client, client):
    client.post("/api/iot/reset")
    r1 = operator_client.post("/api/simulation/run", json={"weather_severity": 0.2}).json()["run_id"]
    r2 = operator_client.post("/api/simulation/run", json={"weather_severity": 1, "demand_increase": 0.3, "vehicle_availability": 0.5}).json()["run_id"]
    c = client.get(f"/api/simulation/compare?a={r1}&b={r2}").json()
    assert c["same_baseline"] is True and "caused by the scenario" in c["note"]
    by = {m["metric"]: m for m in c["metrics"]}
    assert by["critical_items"]["b"] >= by["critical_items"]["a"] and by["critical_items"]["better"] in ("a", "same")      # the harsher scenario is never "better"
    assert by["transport_capacity"]["b"] < by["transport_capacity"]["a"] and by["transport_capacity"]["better"] == "a"
    for m in c["metrics"]:
        assert m["delta"] == round(m["b"] - m["a"], 3)
    from tests.test_terminology import audit
    assert not audit.find(client.get(f"/api/simulation/compare?a={r1}&b={r2}").text, code=False)
    assert client.get(f"/api/simulation/compare?a={r1}&b={r1}").json()["metrics"][0]["delta"] == 0
    assert client.get("/api/simulation/compare?a=999999&b=1").status_code == 404 and client.get("/api/simulation/compare?a=0&b=1").status_code == 422
    operator_client.post("/api/iot/update", json=dict(EVT, quantity=500))              # stock changes between runs -> unfair comparison is flagged
    r3 = operator_client.post("/api/simulation/run", json={"weather_severity": 0.2}).json()["run_id"]
    c2 = client.get(f"/api/simulation/compare?a={r1}&b={r3}").json()
    assert c2["same_baseline"] is False and c2["note"].startswith("WARNING")
    client.post("/api/iot/reset")

from app import seed_data as S


def test_dataset_meets_ps_requirements(dataset):
    assert len(S.DEPOTS) >= 3 and len(S.BASES) >= 5 and len(S.SUPPLY_ROWS) == 10
    assert len(S.ROUTES) == 8 and len(S.VEHICLES) == 8
    assert sum(len(v) for v in dataset["history"].values()) >= 5500


def test_seed_is_deterministic():
    assert S.build_dataset()["history"] == S.build_dataset()["history"]


def test_relationships_in_consumption(dataset):
    h = dataset["history"]
    # location factor: Base_04 (1.3) consumes more than Base_01 (0.7) of the same supply
    assert sum(h[("Base_04", "Food")]) > sum(h[("Base_01", "Food")]) * 1.5
    # supply type: Water (900 base) > Comms (60 base)
    assert sum(h[("Base_02", "Water")]) > sum(h[("Base_02", "Comms")]) * 5
    # weather: Water (sensitivity .6) responds more to the rain event (days 112-117 are outlook; use sin-driven high-weather days) than Comms (.05)
    W = dataset["weather"]
    hi = sorted(range(110), key=lambda d: W[d])[-15:]
    lo = sorted(range(110), key=lambda d: W[d])[:15]
    ratio = lambda k: (sum(h[k][d] for d in hi) / 15) / (sum(h[k][d] for d in lo) / 15)
    assert ratio(("Base_02", "Water")) > ratio(("Base_02", "Comms"))


def test_locations_are_fictional_and_geo(dataset):
    for l in S.locations():
        assert "fictional" in l.name
        assert 21.0 < l.lat < 23.5 and 78.0 < l.lon < 81.0
    for r in S.routes():
        assert len(r.coords) >= 3

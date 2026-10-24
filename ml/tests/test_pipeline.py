"""Training pipeline: dataset validation, chronological splits and leakage prevention, reproducibility, labels, metrics wiring."""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

import common as C
import profile_supply_csv as P
import train_shortage as TS
from app.ml import features as F, metrics as M


# ---------------- splits / leakage
def test_chronological_split_is_ordered_and_exhaustive():
    sp = C.chronological_split(52560)
    assert sp["train"] == (0, 36792) and sp["val"] == (36792, 44676) and sp["test"] == (44676, 52560)
    assert sp["train"][1] == sp["val"][0] and sp["val"][1] == sp["test"][0]
    with pytest.raises(C.DatasetError):
        C.chronological_split(60)


def test_training_labels_never_reach_validation_or_test():
    rng = np.random.default_rng(0)
    sp = C.chronological_split(5000)
    i, o, h = C.sample_triples(rng, 4, 0, sp["train"][1], 20000)
    assert (o + h).max() < sp["train"][1] and o.min() >= F.MIN_HISTORY - 1
    i, o, h = C.sample_triples(rng, 4, sp["val"][0], sp["val"][1], 20000)
    assert o.min() >= sp["val"][0] and (o + h).max() < sp["val"][1]


def test_test_grid_stays_inside_data_and_uses_all_horizons():
    T, b = 3000, 2100
    items, o, h = C.test_grid(T, b, 3, 13)
    assert o.min() == b and (o + h).max() <= T - 1 and set(h) == set(range(1, 31)) and set(items) == {0, 1, 2}
    assert len(items) == len(o) == len(h) and 13 % 7 != 0


def test_future_values_cannot_change_training_features():
    rng = np.random.default_rng(1)
    Y = rng.poisson(100, (400, 2)).astype(float)
    i, o, h = np.array([0, 1]), np.array([150, 200]), np.array([5, 20])
    X1, _, _ = F.build(Y, i, o, h, with_target=True)
    Y2 = Y.copy(); Y2[201:, :] = -5       # corrupt everything after the latest origin; targets for these rows lie before it
    Y2[150 + 5, 0] = Y[155, 0]; Y2[200 + 20, 1] = Y[220, 1]
    X2, _, _ = F.build(np.where(Y2 < 0, 7777.0, Y2), i, o, h, with_target=True)
    assert np.array_equal(X1, X2)


# ---------------- reproducibility
def _tiny_model(seed):
    rng = np.random.default_rng(seed)
    Y = rng.poisson(120, (900, 5)).astype(float)
    sp = C.chronological_split(900)
    tr = C.sample_triples(rng, 5, 0, sp["train"][1], 5000)
    X, _, y = F.build(Y, *tr, with_target=True)
    m = lgb.LGBMRegressor(n_estimators=40, num_leaves=8, learning_rate=0.1, random_state=seed, n_jobs=1, verbose=-1, bagging_fraction=0.8, bagging_freq=1, feature_fraction=0.8)
    m.fit(X, y)
    Xt, _ = F.build(Y, np.array([0, 1, 2]), np.array([800, 810, 820]), np.array([1, 7, 30]))
    return m.predict(Xt)


def test_training_is_reproducible_with_a_fixed_seed():
    assert np.array_equal(_tiny_model(7), _tiny_model(7))
    assert not np.array_equal(_tiny_model(7), _tiny_model(8))


# ---------------- ISOMORPH loading / validation
def _write_rollout(tmp_path, items=("I01", "I02"), T=40, drop_col=None, dup=False):
    d = tmp_path / "output_item50"; d.mkdir()
    rows = [{"day": t, "item": it, "demand": 10 + t, "served_from_stock": 10 + t, "new_backlog_today": 0, "dest_on_hand_end_before_ship": 100, "dest_backlog_end_before_ship": 0}
            for t in range(T) for it in items]
    df = pd.DataFrame(rows)
    if drop_col:
        df = df.drop(columns=[drop_col])
    if dup:
        df = pd.concat([df, df.iloc[:1]])
    df.to_parquet(d / "daily_records.parquet")
    (d / "demand_signals_cols.txt").write_text(",".join(items))
    (d / "scenario.json").write_text(json.dumps({"name": "t", "seed": 1}))
    return tmp_path


def test_loader_reads_observed_demand_and_provenance(tmp_path):
    Y, items, prov = C.load_isomorph_demand(_write_rollout(tmp_path))
    assert Y.shape == (40, 2) and items == ["I01", "I02"] and Y[3, 0] == 13
    assert prov["licence"] == "CC-BY-4.0" and "simulator-generated" in prov["nature"] and len(prov["files_sha256"]["daily_records.parquet"]) == 64


@pytest.mark.parametrize("kw, msg", [({"drop_col": "demand"}, "missing columns"), ({"dup": True}, "duplicate")])
def test_loader_rejects_malformed_files(tmp_path, kw, msg):
    with pytest.raises(C.DatasetError, match=msg):
        C.load_isomorph_demand(_write_rollout(tmp_path, **kw))


def test_loader_rejects_missing_dataset(tmp_path):
    with pytest.raises(C.DatasetError):
        C.find_rollout(tmp_path / "nope")


def test_loader_rejects_gaps_in_the_day_index(tmp_path):
    root = _write_rollout(tmp_path)
    p = root / "output_item50" / "daily_records.parquet"
    df = pd.read_parquet(p); df = df[df.day != 10]; df.to_parquet(p)
    with pytest.raises(C.DatasetError, match="contiguous"):
        C.load_isomorph_demand(root)


# ---------------- shortage labels
def test_shortage_labels_look_strictly_forward():
    nb = np.zeros((20, 1)); nb[10, 0] = 5
    y = TS.make_labels(nb, 7)
    assert y[3, 0] == 1 and y[9, 0] == 1 and y[10, 0] == 0 and y[2, 0] == 0     # day t counts days t+1..t+7, not t itself
    assert np.all(np.isnan(y[13:, 0]))                                           # no full look-ahead window -> no label


# ---------------- supply CSV profile
def _csv_df():
    rng = np.random.default_rng(0)
    return pd.DataFrame({c: v for c, v in zip(P.EXPECTED, [rng.integers(450, 600, 500), rng.choice(["Fresh", "Refrigerated"], 500), np.repeat(np.arange(1, 13), 42)[:500], rng.uniform(15, 35, 500),
                                                           rng.uniform(0, 100, 500), rng.integers(1, 11, 500), rng.uniform(5, 50, 500), rng.uniform(1, 5, 500), rng.uniform(8, 15, 500), rng.choice(["Low", "High"], 500)])})


def test_csv_schema_validation_and_profile_conclusion():
    df = _csv_df(); P.validate_schema(df)
    p = P.profile(df)
    assert p["has_date_or_year"] is False and p["has_item_or_sku_identifier"] is False and p["max_abs_pairwise_correlation"] < 0.2
    assert "Not suitable" in p["conclusion"] and "no evidence of real-world provenance" in p["conclusion"]
    with pytest.raises(P.CsvSchemaError):
        P.validate_schema(df.drop(columns=["Month"]))
    bad = df.copy(); bad.loc[0, "Month"] = 13
    with pytest.raises(P.CsvSchemaError):
        P.validate_schema(bad)


def test_csv_reader_decodes_the_degree_sign(tmp_path):
    p = tmp_path / "s.csv"; df = _csv_df().iloc[:5]
    df.to_csv(p, index=False, encoding="mac_roman")
    assert list(P.read_csv(p).columns)[3] == "Average Temperature (°C)"


# ---------------- reports present and honest
def test_shipped_reports_state_their_provenance():
    r = json.loads((C.ML_DIR / "reports" / "forecast_benchmark_eval.json").read_text())
    assert r["data"]["provenance"]["licence"] == "CC-BY-4.0" and "split" in r["data"]
    ov = r["test"]["overall"]
    assert {"lightgbm", "random_forest", "statistical_ewma (existing)", "seasonal_naive_7"} <= set(ov)
    assert M.wape([1, 2], [1, 2]) == 0

"""Shared helpers for the training scripts: dataset loading + validation, chronological splits, provenance."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent
ROOT = ML_DIR.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.ml import features as F  # noqa: E402

REQUIRED_DAILY = {"day": "int", "item": "str", "demand": "int", "served_from_stock": "int", "new_backlog_today": "int",
                  "dest_on_hand_end_before_ship": "int", "dest_backlog_end_before_ship": "int"}


class DatasetError(ValueError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def find_rollout(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    for cand in (data_dir, data_dir / "output_item50"):
        if (cand / "daily_records.parquet").is_file():
            return cand
    hits = list(data_dir.rglob("daily_records.parquet"))
    if hits:
        return hits[0].parent
    raise DatasetError(f"daily_records.parquet not found under {data_dir}")


def validate_daily_schema(columns: list) -> None:
    missing = [c for c in REQUIRED_DAILY if c not in columns]
    if missing:
        raise DatasetError(f"daily_records.parquet is missing columns: {missing}")


def load_daily(rollout: Path, columns: list):
    """Read selected columns of daily_records.parquet and validate structure. Returns a pandas DataFrame."""
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(rollout / "daily_records.parquet")
    validate_daily_schema(pf.schema_arrow.names)
    df = pf.read(columns=columns).to_pandas()
    df["item"] = df["item"].astype(str)
    if df.duplicated(["day", "item"]).any():
        raise DatasetError("duplicate (day, item) rows in daily_records")
    return df


def pivot(df, value: str, items: list, T: int) -> np.ndarray:
    p = df.pivot(index="day", columns="item", values=value)
    if list(p.index) != list(range(T)):
        raise DatasetError("days are not a contiguous 0..T-1 range")
    return p[items].to_numpy()


def load_isomorph_demand(data_dir: Path):
    """Observed per-item daily demand (T, C) from daily_records.demand + provenance.

    NOTE: demand_signals.npy is NOT used as a target. It holds the simulator's latent Poisson intensity (non-integer,
    noise-free), which is not an observable quantity (see ml/DATA_CARD.md).
    """
    rollout = find_rollout(data_dir)
    items = (rollout / "demand_signals_cols.txt").read_text().strip().split(",")
    df = load_daily(rollout, ["day", "item", "demand"])
    T = int(df["day"].max()) + 1
    if df["item"].nunique() != len(items) or set(df["item"]) != set(items):
        raise DatasetError("item identifiers in daily_records do not match demand_signals_cols.txt")
    Y = pivot(df, "demand", items, T).astype(np.float64)
    if np.any(Y < 0) or not np.all(np.isfinite(Y)):
        raise DatasetError("negative or non-finite demand values")
    prov = provenance(rollout)
    return Y, items, prov


def provenance(rollout: Path) -> dict:
    root = rollout.parent if rollout.name.startswith("output_") else rollout
    scen = json.loads((rollout / "scenario.json").read_text())
    lic = root / "LICENSE"
    return {
        "dataset": "ISOMORPH Sample (single baseline rollout)", "licence": "CC-BY-4.0",
        "attribution": "\"ISOMORPH Sample\" dataset by the ISOMORPH authors, licensed under CC-BY-4.0 (paper under submission, NeurIPS 2026 Datasets & Benchmarks).",
        "nature": "simulator-generated research benchmark (digital-twin supply chain); not observed operational data",
        "scenario": scen, "licence_file_sha256": sha256(lic) if lic.is_file() else None,
        "files_sha256": {n: sha256(rollout / n) for n in ("daily_records.parquet", "scenario.json", "demand_signals_cols.txt")},
    }


def chronological_split(T: int, train: float = 0.70, val: float = 0.15) -> dict:
    """Index boundaries: train [0,a) val [a,b) test [b,T). Purely positional - rows are never shuffled."""
    a, b = int(T * train), int(T * (train + val))
    if not (F.MIN_HISTORY < a < b < T - F.MAX_HORIZON):
        raise DatasetError("series too short for the requested split")
    return {"train": (0, a), "val": (a, b), "test": (b, T)}


def sample_triples(rng, n_items: int, seg_start: int, seg_end: int, n: int):
    """Random (item, origin, horizon) with origin >= max(seg_start, MIN_HISTORY-1) and the TARGET day inside [.., seg_end).

    For training, seg_start=0 and seg_end=train_end: no label ever falls in validation or test (purged by construction).
    For validation, origins start at the segment start (features may look back into earlier history; labels are in-segment).
    """
    lo = max(seg_start, F.MIN_HISTORY - 1)
    h = rng.integers(1, F.MAX_HORIZON + 1, n)
    hi = seg_end - h                              # exclusive upper bound for origin so that origin + h <= seg_end - 1
    o = lo + np.floor(rng.random(n) * (hi - lo)).astype(np.int64)
    return rng.integers(0, n_items, n), o, h


def test_grid(T: int, seg_start: int, n_items: int, stride: int):
    """All items x origins (stride apart; 13 is coprime with 7) x horizons 1..30 whose targets stay inside the data."""
    origins = np.arange(seg_start, T - F.MAX_HORIZON, stride)
    items = np.repeat(np.arange(n_items), len(origins) * F.MAX_HORIZON)
    o = np.tile(np.repeat(origins, F.MAX_HORIZON), n_items)
    h = np.tile(np.tile(np.arange(1, F.MAX_HORIZON + 1), len(origins)), n_items)
    return items, o, h


def load_destination_state(data_dir: Path):
    """Destination-node daily state per item: demand, on_hand, backlog, in_transit, new_backlog (each (T, C)) + items + provenance.

    on_hand / backlog come from daily_records (dest_*_end_before_ship), which were verified identical to the NewYork rows of
    inventory_history / backlog_history. in_transit is the (destination-only) intransit_history table.
    """
    import pyarrow.parquet as pq
    rollout = find_rollout(data_dir)
    items = (rollout / "demand_signals_cols.txt").read_text().strip().split(",")
    df = load_daily(rollout, list(REQUIRED_DAILY))
    T = int(df["day"].max()) + 1
    out = {k: pivot(df, c, items, T).astype(np.float64) for k, c in
           (("demand", "demand"), ("on_hand", "dest_on_hand_end_before_ship"), ("backlog", "dest_backlog_end_before_ship"), ("new_backlog", "new_backlog_today"))}
    it = pq.read_table(rollout / "intransit_history.parquet", columns=["day", "item", "in_transit"]).to_pandas()
    it["item"] = it["item"].astype(str)
    out["in_transit"] = pivot(it, "in_transit", items, T).astype(np.float64)
    # identity checks that make the target definition valid
    if not np.array_equal(out["demand"], pivot(df, "served_from_stock", items, T) + out["new_backlog"]):
        raise DatasetError("demand != served_from_stock + new_backlog_today; shortage target definition would be invalid")
    if any(np.any(v < 0) for v in out.values()):
        raise DatasetError("negative values in destination state")
    return out, items, provenance(rollout)

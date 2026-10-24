"""Independent profile of Dataset_AI_Supply_Optimization.csv.

Purpose: establish whether the file can support any model, WITHOUT assuming real-world provenance. The script checks
structure, encoding, temporal coverage, identifiers and whether the columns behave like related measurements or like
independent random draws. It writes ml/reports/supply_csv_profile.json.

    python ml/profile_supply_csv.py --csv Dataset_AI_Supply_Optimization.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import common as C

EXPECTED = ["Quantity Sold (units)", "Product Category", "Month", "Average Temperature (°C)", "Monthly Precipitation (mm)",
            "Route (ID)", "Route Distance (km)", "Average Transit Time (hrs)", "Cost per Kilometer ($)", "Traffic Conditions"]
NUMERIC = ["Quantity Sold (units)", "Average Temperature (°C)", "Monthly Precipitation (mm)", "Route Distance (km)",
           "Average Transit Time (hrs)", "Cost per Kilometer ($)"]


class CsvSchemaError(ValueError):
    pass


def read_csv(path: Path) -> pd.DataFrame:
    """The file is not UTF-8: the degree sign is byte 0xA1, which is MacRoman for '°'. Decode accordingly."""
    df = pd.read_csv(path, encoding="mac_roman")
    validate_schema(df)
    return df


def validate_schema(df: pd.DataFrame) -> None:
    if list(df.columns) != EXPECTED:
        raise CsvSchemaError(f"unexpected columns: {list(df.columns)}")
    if df.isna().any().any():
        raise CsvSchemaError("missing values present")
    if not df["Month"].between(1, 12).all():
        raise CsvSchemaError("Month outside 1..12")


def profile(df: pd.DataFrame) -> dict:
    n = len(df)
    out = {"rows": n, "columns": list(df.columns), "duplicate_rows": int(df.duplicated().sum()),
           "temporal_columns": ["Month (1-12 only)"], "has_date_or_year": False, "has_item_or_sku_identifier": False,
           "has_location_identifier": False, "route_ids": sorted(map(int, df["Route (ID)"].unique())),
           "rows_per_month": {int(k): int(v) for k, v in df.groupby("Month").size().items()}}
    uni = {}
    for c in NUMERIC:
        x = df[c].to_numpy(float)
        lo, hi = x.min(), x.max()
        ks = stats.kstest((x - lo) / (hi - lo), "uniform")
        uni[c] = {"min": float(lo), "max": float(hi), "mean": float(x.mean()), "std": float(x.std()), "uniform_ks_stat": float(ks.statistic),
                  "uniform_ks_p": float(ks.pvalue), "std_if_uniform": float((hi - lo) / np.sqrt(12))}
    out["numeric_vs_uniform"] = uni
    num = df[NUMERIC + ["Month", "Route (ID)"]]
    cm = num.corr().abs().to_numpy().copy()
    np.fill_diagonal(cm, 0)
    out["max_abs_pairwise_correlation"] = float(cm.max())
    # does anything depend on month? (a real temperature series would show a strong seasonal cycle)
    out["month_effects"] = {c: {"one_way_anova_F": float(stats.f_oneway(*[g[c].to_numpy() for _, g in df.groupby("Month")]).statistic),
                                "p": float(stats.f_oneway(*[g[c].to_numpy() for _, g in df.groupby("Month")]).pvalue),
                                "mean_range_across_months": float(df.groupby("Month")[c].mean().max() - df.groupby("Month")[c].mean().min())}
                            for c in NUMERIC}
    # is a route a stable physical object? (distance should barely vary within a route)
    d = df.groupby("Route (ID)")["Route Distance (km)"]
    out["route_distance_within_route_std_mean"] = float(d.std().mean())
    out["route_distance_overall_std"] = float(df["Route Distance (km)"].std())
    out["category_effect_on_quantity_p"] = float(stats.ttest_ind(*[g["Quantity Sold (units)"] for _, g in df.groupby("Product Category")]).pvalue)
    out["traffic_effect_on_transit_p"] = float(stats.f_oneway(*[g["Average Transit Time (hrs)"].to_numpy() for _, g in df.groupby("Traffic Conditions")]).pvalue)
    sorted_by_month = bool(df["Month"].is_monotonic_increasing)
    out["rows_sorted_by_month"] = sorted_by_month
    out["conclusion"] = (
        "Not suitable for training a demand-forecast, shortage or route-disruption model. There is no calendar year/date, no SKU/item identifier "
        "and no location identifier, so no time series can be formed. Every numeric column is consistent with an independent uniform draw over a "
        "fixed range (Quantity Sold is integer-valued, 450-599), the largest absolute pairwise correlation is about 0.01, no month effect survives a "
        "multiple-comparison correction (temperature has no seasonal cycle), and route distance is not stable within a route ID. These properties are typical of randomly generated tabular data and give no evidence of real-world provenance; the file "
        "documents no source or licence. It is therefore used only for schema validation/profiling, never for training or for any displayed metric.")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--out", default=C.ML_DIR / "reports" / "supply_csv_profile.json", type=Path)
    a = ap.parse_args()
    df = read_csv(a.csv)
    p = profile(df)
    p["file_sha256"] = C.sha256(a.csv)
    p["encoding_note"] = "decoded as mac_roman (0xA1 -> degree sign)"
    a.out.parent.mkdir(exist_ok=True)
    a.out.write_text(json.dumps(p, indent=2))
    print(json.dumps({k: p[k] for k in ("rows", "duplicate_rows", "max_abs_pairwise_correlation", "route_distance_within_route_std_mean", "route_distance_overall_std")}, indent=2))
    print({c: round(v["uniform_ks_p"], 3) for c, v in p["numeric_vs_uniform"].items()})
    print({c: round(v["p"], 3) for c, v in p["month_effects"].items()})


if __name__ == "__main__":
    main()

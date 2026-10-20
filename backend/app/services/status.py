"""System status checks, data coverage and pipeline summary (computed, not hard-coded)."""
from __future__ import annotations

import math

from .recommendation import recommend


def fin(a) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in a)


def engine_status(snap, result, base_result, record_count: int, mape: float, n_series: int) -> list:
    at_risk = [i for i in result.items if i.status != "NORMAL"]
    expected = len(snap.forward) * len(snap.supplies) * snap.nd
    return [
        {"engine": "Data Engine", "ok": record_count == expected and all(fin(p.fut) for p in snap.positions),
         "detail": f"{record_count:,} records validated"},
        {"engine": "Forecast Engine", "ok": all(fin(p.fut) for p in snap.positions), "detail": f"backtest MAPE {mape:.1f}% \u00b7 {n_series} series"},
        {"engine": "Inventory Risk Engine", "ok": len(result.items) == len(snap.positions) and fin([i.days for i in result.items]),
         "detail": f"{len(result.items)} positions scored"},
        {"engine": "Route Optimizer", "ok": fin([r.eta for r in result.routes]), "detail": f"{len(result.routes)} routes evaluated"},
        {"engine": "Recommendation Engine", "ok": all(recommend(result, i)["source"] for i in at_risk), "detail": f"{len(at_risk)} actions routed"},
        {"engine": "Simulation Engine", "ok": math.isfinite(base_result.risk_index) and math.isfinite(result.risk_index),
         "detail": "baseline scenario" if result.params.is_baseline else "scenario active"},
    ]

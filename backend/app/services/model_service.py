"""Model registry for the application: loads the trained artefacts once, decides which forecaster drives the application and
reports - transparently - which model produced the numbers and why.

Selection (config.FORECAST_MODEL_MODE):
  statistical  statistical baseline only
  ml           trained model whenever it loads; otherwise statistical *with the reason exposed*
  auto         trained model only if its metadata carries promotion.status == "promoted" (set by ml/evaluate_app_series.py
               from a pre-registered holdout rule); otherwise statistical with the reason exposed
A baseline result is never labelled as an ML prediction.
"""
from __future__ import annotations

import json
import re
import logging
import threading
import time
from dataclasses import dataclass

from .. import config
from ..ml.artifacts import ArtifactError
from ..ml.forecaster import MLForecaster
from ..ml.shortage import ShortageModel
from ..observability import metrics

log = logging.getLogger("logistics.ml")
STATISTICAL_ID = "ewma-weather-seasonal-v1"   # id stored in forecasts.model (unchanged from the original schema)
_lock = threading.Lock()
_cache: dict = {}
_loaded_at: dict = {}
_override: dict = {}       # set when the trained model fails at run time; makes the fallback visible and sticky until reset


@dataclass
class Resolution:
    forecaster: MLForecaster | None
    model_id: str
    family: str                  # "machine_learning" | "statistical"
    reason: str | None           # why the statistical model is in use (None when ML is in use)
    adapter: str                 # "plain" | "weather" (how known application effects are passed to the ML model)
    is_fallback: bool = False    # True only when the statistical model is in use BECAUSE the trained model failed to load or run


def _load(kind: str, cls):
    with _lock:
        if kind not in _cache:
            try:
                _cache[kind] = (cls.load(config.ML_ARTIFACT_DIR, pin=config.settings.ml_pins.get(kind)), None)
                _loaded_at[kind] = time.time()
                metrics.stamp(f"{kind}_model_loaded")
                log.info("loaded %s model %s", kind, _cache[kind][0].model_id)
            except ArtifactError as e:
                _cache[kind] = (None, str(e))
                metrics.inc(f"{kind}_model_load_failures")
                log.warning("%s model unavailable: %s", kind, e)
        return _cache[kind]


def reset_cache() -> None:
    with _lock:
        _cache.clear()
        _loaded_at.clear()
        _override.clear()


def force_statistical(reason: str) -> None:
    """Record that the trained model failed during inference and the statistical model was used instead."""
    with _lock:
        _override["reason"] = safe_error(reason) or "unknown error"
    metrics.inc("forecast_inference_failures")
    metrics.inc("forecast_fallbacks_to_statistical")
    log.error("falling back to the statistical model: %s", reason)


def forecaster() -> tuple[MLForecaster | None, str | None]:
    return _load("forecast", MLForecaster)


def shortage_model() -> tuple[ShortageModel | None, str | None]:
    return _load("shortage", ShortageModel)


def resolve_forecast() -> Resolution:
    mode = config.FORECAST_MODEL_MODE
    stat = lambda why, fb=False: Resolution(None, STATISTICAL_ID, "statistical", why, "plain", fb)
    if _override.get("reason"):
        return stat("trained model failed at run time: " + _override["reason"], True)
    if mode == "statistical":
        return stat("statistical model selected by configuration (FORECAST_MODEL_MODE=statistical)")
    f, err = forecaster()
    if f is None:
        return stat(f"trained model unavailable: {safe_error(err)}", True)
    promo = f.meta.get("promotion", {})
    if mode == "auto" and promo.get("status") != "promoted":
        return stat(f"trained model not promoted: {promo.get('reason') or 'no promotion decision recorded'}")
    return Resolution(f, f.model_id, "machine_learning", None, promo.get("adapter", "plain"))


SHORTAGE_REQUIRED_INPUTS = {
    "demand": "daily demand history (>= 28 days)",
    "on_hand": "daily on-hand stock history (>= 28 days)",
    "in_transit": "daily in-transit quantity history (>= 28 days)",
    "backlog": "daily backlog history (>= 28 days)",
    "new_backlog": "daily new-backlog history (>= 28 days)",
}


def shortage_integration() -> dict:
    """Why the shortage-onset model does not drive the application's inventory status, stated from the data model.

    The model needs five daily histories. The application stores a 110-day consumption history, but only the CURRENT stock level
    (no daily on-hand history), and has no in-transit or backlog ledger at all. Filling those inputs with reconstructed or invented
    values would make the probabilities meaningless, so the model is available only for records that really contain them."""
    s, err = shortage_model()
    return {
        "integrated_with_inventory_status": False,
        "model_loaded": s is not None,
        "load_error": safe_error(err),
        "reason": ("The model's inputs (daily on-hand, in-transit and backlog histories) do not exist in this application's data; "
                   "the inventory risk views therefore use the documented rules."),
        "required_inputs": SHORTAGE_REQUIRED_INPUTS,
        "available_in_application": {"demand": True, "on_hand": False, "in_transit": False, "backlog": False, "new_backlog": False},
        "what_is_available": "POST /api/ml/shortage-risk scores a record that supplies all five histories (benchmark format); the Model Evaluation page offers the same check.",
    }


def registry_status() -> dict:
    r = resolve_forecast()
    f, ferr = forecaster()
    s, serr = shortage_model()
    summary = lambda m: None if m is None else {
        "model_id": m.model_id, "kind": m.meta["kind"], "created_utc": m.meta["created_utc"], "sha256": m.meta.get("model_sha256"), "libraries": m.meta.get("libraries"),
        "training_dataset": m.meta["training_data"]["dataset"], "licence": m.meta["training_data"]["licence"],
        "attribution": m.meta["training_data"]["attribution"], "nature": m.meta["training_data"]["nature"],
        "applicability": m.meta.get("applicability"), "hyperparameters": m.meta.get("hyperparameters")}
    return {
        "mode": config.FORECAST_MODEL_MODE,
        "active_forecast_model": {"model_id": r.model_id, "family": r.family, "fallback_reason": r.reason, "adapter": r.adapter},
        "demand_forecast": {"loaded": f is not None, "error": safe_error(ferr), "loaded_at": _iso(_loaded_at.get("forecast")), "promotion": None if f is None else f.meta.get("promotion"), "artefact": summary(f)},
        "shortage_risk": {"loaded": s is not None, "error": safe_error(serr), "loaded_at": _iso(_loaded_at.get("shortage")), "artefact": summary(s),
                          "used_by_application_status": False, "integration": shortage_integration(),
                          "note": "Benchmark-format scoring only: the application's own status classification is rule-based because the illustrative scenario has no backlog or in-transit ledger."},
    }


def safe_error(err):
    """Artefact error text for display: the server's directory layout is replaced by a placeholder."""
    if err is None:
        return None
    s = str(err)
    for root in {str(config.ML_ARTIFACT_DIR), str(config.ML_ARTIFACT_DIR.resolve())}:
        s = s.replace(root, "<artifacts>")
    return re.sub(r"(/[\w.\-]+){2,}", "<path>", s)


def _iso(t):
    from datetime import datetime, timezone
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def read_report(name: str) -> dict | None:
    p = config.ML_REPORTS_DIR / name
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None

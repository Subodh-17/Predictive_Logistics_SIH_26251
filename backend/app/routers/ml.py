"""Model registry, evaluation reports and benchmark-format shortage scoring."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ..ml.features import InputError
from ..ml.shortage import WINDOW
from ..services import model_service as ms

router = APIRouter(prefix="/api/ml", tags=["machine-learning"])
MAX_HISTORY = 400


@router.get("/models")
def models():
    """Which trained models are loaded, which one drives the application, and why (including any fallback)."""
    return ms.registry_status()


@router.get("/evaluation")
def evaluation():
    """Measured evaluation reports produced by the training pipeline (benchmark test split, illustrative-scenario holdout, shortage model)."""
    reports = {"benchmark_forecast": ms.read_report("forecast_benchmark_eval.json"), "scenario_forecast": ms.read_report("forecast_scenario_eval.json"),
               "shortage_benchmark": ms.read_report("shortage_benchmark_eval.json"), "supply_csv_profile": ms.read_report("supply_csv_profile.json")}
    return {"available": any(reports.values()), "reports": reports,
            "disclosure": ("ISOMORPH is a simulator-generated research benchmark (CC-BY-4.0); results measure performance on that benchmark and on the "
                           "illustrative scenario in this application, not on real operations.")}


class ShortageRequest(BaseModel):
    """Five equally long daily histories at one node for one item (oldest first, last element = today)."""
    demand: list[float] = Field(min_length=WINDOW, max_length=MAX_HISTORY)
    on_hand: list[float] = Field(min_length=WINDOW, max_length=MAX_HISTORY)
    in_transit: list[float] = Field(min_length=WINDOW, max_length=MAX_HISTORY)
    backlog: list[float] = Field(min_length=WINDOW, max_length=MAX_HISTORY)
    new_backlog: list[float] = Field(min_length=WINDOW, max_length=MAX_HISTORY)

    @field_validator("demand", "on_hand", "in_transit", "backlog", "new_backlog")
    @classmethod
    def finite_non_negative(cls, v):
        if any(x != x or x in (float("inf"), float("-inf")) or x < 0 for x in v):
            raise ValueError("values must be finite and non-negative")
        return v


@router.post("/shortage-risk")
def shortage_risk(req: ShortageRequest):
    """7-day shortage-onset probability for a benchmark-format record. The application's own inventory status is not driven by this model."""
    model, err = ms.shortage_model()
    if model is None:
        return JSONResponse(status_code=503, content={"code": "MODEL_UNAVAILABLE", "detail": f"Shortage-risk model unavailable: {ms.safe_error(err)}"})
    try:
        return model.score_record(req.demand, req.on_hand, req.in_transit, req.backlog, req.new_backlog)
    except InputError as e:
        return JSONResponse(status_code=422, content={"code": "INVALID_INPUT", "detail": str(e)})

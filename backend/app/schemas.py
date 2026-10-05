"""Pydantic request / response models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScenarioIn(BaseModel):
    """What-If scenario. All fields are optional; defaults are the baseline."""
    demand_increase: float = Field(0.0, ge=0.0, le=0.5, description="0..0.5 = +0%..+50% demand")
    weather_severity: float = Field(0.0, ge=0.0, le=1.0, description="0 normal .. 1 severe")
    road_degradation: float = Field(0.0, ge=0.0, le=1.0, description="0 good .. 1 poor")
    vehicle_availability: float = Field(1.0, ge=0.5, le=1.0, description="share of fleet capacity available, 0.5..1")


class IotUpdateIn(BaseModel):
    """A simulated ESP32 / RFID scan reported to the backend."""
    model_config = ConfigDict(json_schema_extra={"example": {"device_id": "ESP32-SIM-01", "tag_id": "RFID-SIM-1234", "event_type": "ISSUE",
                                                             "location_id": "Base_04", "supply_id": "Medical", "quantity": 50}})
    device_id: str = Field(min_length=3, max_length=40)
    tag_id: str = Field(min_length=3, max_length=60)
    event_type: Literal["RECEIVE", "ISSUE", "COUNT"]
    location_id: str
    supply_id: str
    quantity: float = Field(ge=0, le=1_000_000)
    note: str | None = Field(None, max_length=200)


class IotSimulateIn(BaseModel):
    count: int = Field(5, ge=1, le=50)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    api: str
    database: dict
    data_notice: str
    simulated_iot: bool = True


class LocationOut(BaseModel):
    id: str
    name: str
    kind: str
    lat: float
    lon: float
    status: str | None
    n_critical: int = 0
    n_warning: int = 0
    n_normal: int = 0
    min_days: float | None = None
    min_supply: str | None = None
    short_units: int = 0
    demand_per_day: float = 0
    best_route: str | None = None
    best_route_risk: float | None = None
    available_capacity: int | None = None


class VehicleOut(BaseModel):
    id: str
    depot_id: str
    vehicle_type: str
    capacity: int
    effective_capacity: int
    available: bool


class InventoryOut(BaseModel):
    location: str
    supply: str
    stock: float
    safety_stock: float
    daily_use: float
    days_left: float
    shortage_14d: int
    status: str
    lead_days: float
    stockout_date: str
    replenish_qty: int
    below_safety: bool


class AlertOut(BaseModel):
    location: str
    supply: str
    severity: str
    days_cover: float
    stockout_date: str | None
    lead_days: float
    message: str


class PriorityOut(BaseModel):
    rank: int
    location: str
    supply: str
    status: str
    score: int
    components: dict
    days_cover: float
    stockout_date: str
    replenish_qty: int
    best_route: str | None
    route_feasible: bool


class IotEventOut(BaseModel):
    id: int
    event_time: str
    device_id: str
    tag_id: str
    event_type: str
    location_id: str
    supply_id: str
    quantity: float
    stock_before: float
    stock_after: float
    simulated: bool
    clipped_at_zero: bool = False

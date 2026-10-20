"""SQLAlchemy ORM models for the PostgreSQL/PostGIS schema defined by db/migrations (all scenario data is fictional and simulated)."""
from __future__ import annotations

from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, Float, ForeignKey, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SupplyRow(Base):
    __tablename__ = "supplies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    base_daily_demand: Mapped[float] = mapped_column(Numeric(10, 2))
    weather_sensitivity: Mapped[float] = mapped_column(Numeric(4, 2))
    criticality_weight: Mapped[float] = mapped_column(Numeric(4, 2))
    unit: Mapped[str] = mapped_column(String, default="units")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class LocationRow(Base):
    __tablename__ = "locations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    geom = mapped_column(Geometry("POINT", srid=4326))
    demand_factor: Mapped[float] = mapped_column(Numeric(5, 2), default=1)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class DepotRow(Base):
    __tablename__ = "depots"
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    depot_class: Mapped[str] = mapped_column(String)
    storage_capacity_units: Mapped[int] = mapped_column(Integer)


class VehicleRow(Base):
    __tablename__ = "vehicles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.location_id"))
    vehicle_type: Mapped[str] = mapped_column(String)
    capacity_units: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class RouteRow(Base):
    __tablename__ = "routes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.location_id"))
    destination_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    distance_km: Mapped[float] = mapped_column(Numeric(7, 1))
    road_condition: Mapped[float] = mapped_column(Numeric(4, 2))
    nominal_speed_kmh: Mapped[float] = mapped_column(Numeric(5, 1))
    geom = mapped_column(Geometry("LINESTRING", srid=4326))


class TerrainRow(Base):
    __tablename__ = "terrain"
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), primary_key=True)
    terrain_type: Mapped[str] = mapped_column(String)
    difficulty: Mapped[float] = mapped_column(Numeric(4, 2))
    elevation_band: Mapped[int] = mapped_column(SmallInteger)
    elevation_label: Mapped[str] = mapped_column(String)
    terrain_risk: Mapped[float] = mapped_column(Numeric(5, 4), Computed("0.7 * difficulty + 0.3 * elevation_band / 3.0", persisted=True))


class WeatherRow(Base):
    __tablename__ = "weather"
    day_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    obs_date: Mapped[date] = mapped_column(Date)
    severity_index: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String)


class ConsumptionRow(Base):
    __tablename__ = "consumption"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"))
    day_index: Mapped[int] = mapped_column(ForeignKey("weather.day_index"))
    consumption_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)


class InventoryRow(Base):
    __tablename__ = "inventory"
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"), primary_key=True)
    stock: Mapped[float] = mapped_column(Numeric(12, 1))
    safety_stock: Mapped[float] = mapped_column(Numeric(12, 1), default=0)
    initial_stock: Mapped[float] = mapped_column(Numeric(12, 1))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForecastRow(Base):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"))
    day_index: Mapped[int] = mapped_column(Integer)
    forecast_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String, default="ewma-weather-seasonal-v1")
    lo: Mapped[float | None] = mapped_column(Float, nullable=True)
    hi: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scenario_key: Mapped[str] = mapped_column(String, default="baseline")
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"))
    severity: Mapped[str] = mapped_column(String)
    days_cover: Mapped[float] = mapped_column(Float)
    stockout_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_days: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String)


class PriorityScoreRow(Base):
    __tablename__ = "priority_scores"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scenario_key: Mapped[str] = mapped_column(String, default="baseline")
    rank: Mapped[int] = mapped_column(Integer)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"))
    score: Mapped[int] = mapped_column(Integer)
    components = mapped_column(JSONB)


class AllocationRow(Base):
    __tablename__ = "allocations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scenario_key: Mapped[str] = mapped_column(String, default="baseline")
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"))
    route_id: Mapped[str | None] = mapped_column(ForeignKey("routes.id"), nullable=True)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    need: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    unmet: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    unmet_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class IotEventRow(Base):
    __tablename__ = "iot_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    device_id: Mapped[str] = mapped_column(String)
    tag_id: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    supply_id: Mapped[str] = mapped_column(ForeignKey("supplies.id"))
    quantity: Mapped[float] = mapped_column(Numeric(12, 1))
    stock_before: Mapped[float] = mapped_column(Numeric(12, 1))
    stock_after: Mapped[float] = mapped_column(Numeric(12, 1))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    payload = mapped_column(JSONB, default=dict)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)


class SimulationRunRow(Base):
    __tablename__ = "simulation_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    params = mapped_column(JSONB)
    before = mapped_column(JSONB)
    after = mapped_column(JSONB)
    explanation = mapped_column(JSONB)


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLogRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str] = mapped_column(String)
    client_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    detail = mapped_column(JSONB, default=dict)

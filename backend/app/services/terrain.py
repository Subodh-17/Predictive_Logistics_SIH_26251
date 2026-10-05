"""Terrain, weather and road effects on route speed, ETA and risk (fictional model)."""
from __future__ import annotations

from .domain import clamp

ELEVATION_LABELS = ["Low (<500 m)", "Moderate (500-1,500 m)", "High (1,500-3,000 m)", "Very high (>3,000 m)"]


def terrain_risk(difficulty: float, elevation_band: int) -> float:
    """Terrain risk score 0..1 = 0.7 * difficulty + 0.3 * elevation_band / 3."""
    return 0.7 * difficulty + 0.3 * elevation_band / 3


def route_weather_risk(weather: float, terr_risk: float) -> float:
    """Weather risk on a route: the weather index, amplified by terrain exposure."""
    return weather * (0.5 + 0.5 * terr_risk)


def effective_speed(nominal: float, road: float, terr_risk: float, weather_risk: float) -> float:
    """Effective convoy speed (km/h). Road, terrain and weather each reduce nominal speed; floor 8 km/h."""
    v = nominal * (1 - 0.45 * road) * (1 - 0.35 * terr_risk) * (1 - 0.3 * weather_risk)
    return max(v, 8.0)


def route_risk(road: float, weather_risk: float, terr_risk: float, distance_km: float) -> float:
    """Route risk 0..1 = 0.25 road + 0.25 weather + 0.30 terrain + 0.20 distance factor."""
    return clamp(0.25 * road + 0.25 * weather_risk + 0.30 * terr_risk + 0.20 * min(1.0, distance_km / 160), 0, 1)


def road_label(road: float) -> str:
    return "Good" if road < 0.25 else "Fair" if road < 0.5 else "Poor"


def risk_level(r: float) -> str:
    return "LOW" if r < 0.3 else "MODERATE" if r < 0.5 else "HIGH"

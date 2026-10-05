"""Inventory calculations: days of supply, shortage prediction, GREEN/YELLOW/RED (NORMAL/WARNING/CRITICAL) risk."""
from __future__ import annotations

from .domain import CRITICAL, OK, WARNING, js_round


def days_of_supply(stock: float, daily_demand: float) -> float:
    """Days of supply = stock / daily demand. Infinite when demand is zero."""
    if daily_demand <= 0:
        return float("inf")
    return stock / daily_demand


def classify(days: float, lead_days: float, stock: float, safety: float) -> str:
    """CRITICAL (red): <3 d cover or cover below lead time + 1 d.
    WARNING (yellow): cover below lead time + 3 d, or stock under safety stock. Otherwise NORMAL (green)."""
    if days < 3 or days < lead_days + 1:
        return CRITICAL
    if days < lead_days + 3 or stock < safety:
        return WARNING
    return OK


def predicted_shortage(daily_demand: float, stock: float, horizon_days: int = 14) -> int:
    """Units short over the horizon: max(0, demand x horizon - stock)."""
    return max(0, js_round(daily_demand * horizon_days - stock))


def replenishment_qty(status: str, safety: float, daily_demand: float, lead_days: float, stock: float) -> int:
    """Quantity to move = safety + demand over (lead + 5 d buffer) - stock, rounded to 50-unit loads."""
    if status == OK:
        return 0
    return max(0, js_round((safety + daily_demand * (lead_days + 5) - stock) / 50) * 50)


def location_status(n_critical: int, n_warning: int) -> str:
    if n_critical >= 2:
        return CRITICAL
    if n_critical >= 1 or n_warning >= 3:
        return WARNING
    return OK


def overall_risk_index(crit: int, warn: int, n_items: int, avg_route_risk: float, deficit: float, need: float) -> int:
    """0..100 index = 100 x min(1, 2.2 crit/N + 0.8 warn/N + 0.3 route risk + 0.2 capacity-deficit share)."""
    v = 2.2 * crit / n_items + 0.8 * warn / n_items + 0.3 * avg_route_risk + 0.2 * min(1.0, deficit / max(need, 1))
    return js_round(min(100.0, 100 * v))


def risk_band(index: int) -> tuple:
    return ("LOW", "ok") if index < 25 else ("MODERATE", "wr") if index < 45 else ("HIGH", "cr") if index < 65 else ("SEVERE", "cr")

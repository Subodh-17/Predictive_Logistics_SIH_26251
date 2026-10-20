"""Inventory calculations: days of supply, shortage prediction, GREEN/YELLOW/RED (NORMAL/WARNING/CRITICAL) risk."""
from __future__ import annotations

from .domain import CRITICAL, OK, WARNING, js_round

# Single source of truth for the risk rules: used by classify()/predicted_shortage() below AND by the /api/inventory/risk-basis explanation.
CRITICAL_MIN_DAYS = 3.0           # cover below this many days is CRITICAL
CRITICAL_LEAD_MARGIN_DAYS = 1.0   # ... or cover below lead time + this margin
WARNING_LEAD_MARGIN_DAYS = 3.0    # cover below lead time + this margin (or stock below safety stock) is WARNING
SHORTAGE_HORIZON_DAYS = 14
DEMAND_WINDOW_DAYS = 7            # daily demand = mean of the first 7 forecast days


def days_of_supply(stock: float, daily_demand: float) -> float:
    """Days of supply = stock / daily demand. Infinite when demand is zero."""
    if daily_demand <= 0:
        return float("inf")
    return stock / daily_demand


def classify(days: float, lead_days: float, stock: float, safety: float) -> str:
    """CRITICAL (red): <3 d cover or cover below lead time + 1 d.
    WARNING (yellow): cover below lead time + 3 d, or stock under safety stock. Otherwise NORMAL (green)."""
    if days < CRITICAL_MIN_DAYS or days < lead_days + CRITICAL_LEAD_MARGIN_DAYS:
        return CRITICAL
    if days < lead_days + WARNING_LEAD_MARGIN_DAYS or stock < safety:
        return WARNING
    return OK


def predicted_shortage(daily_demand: float, stock: float, horizon_days: int = SHORTAGE_HORIZON_DAYS) -> int:
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


def risk_basis() -> dict:
    """Plain-language source, horizon, rules and limitations of every inventory risk estimate shown by the application."""
    return {
        "method": "deterministic business rules over a demand forecast",
        "source": "Days of supply = current stock / mean daily forecast demand over the next %d days; lead time comes from the best feasible route's ETA." % DEMAND_WINDOW_DAYS,
        "horizon_days": SHORTAGE_HORIZON_DAYS,
        "status_rules": {
            "CRITICAL": f"days of supply < {CRITICAL_MIN_DAYS:g} OR days of supply < lead time + {CRITICAL_LEAD_MARGIN_DAYS:g} day",
            "WARNING": f"days of supply < lead time + {WARNING_LEAD_MARGIN_DAYS:g} days OR stock below safety stock",
            "NORMAL": "none of the above",
        },
        "predicted_shortage": f"max(0, mean daily demand x {SHORTAGE_HORIZON_DAYS} - current stock), in units",
        "limitations": [
            "These are rule-based indicators, not probabilities: they say nothing about how likely a shortage is.",
            "The thresholds are documented assumptions of this application, not calibrated against real operations.",
            "Only current stock and the consumption forecast are used; transport already under way and supply that is on order are not modelled.",
            "The forecast inherits its own error (see the Demand Forecast page); a more accurate forecast changes these figures.",
        ],
    }

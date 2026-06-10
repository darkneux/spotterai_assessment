"""Strategy factory: maps a configured identifier to a planner instance."""

from __future__ import annotations

from django.conf import settings

from .base import FuelPlannerStrategy
from .domain import Vehicle
from .dp import DPFuelPlanner
from .greedy import GreedyFuelPlanner

_REGISTRY: dict[str, type[FuelPlannerStrategy]] = {
    GreedyFuelPlanner.name: GreedyFuelPlanner,
    DPFuelPlanner.name: DPFuelPlanner,
}

AVAILABLE_STRATEGIES = tuple(_REGISTRY.keys())


def build_vehicle(
    max_range_miles: float | None = None,
    miles_per_gallon: float | None = None,
) -> Vehicle:
    return Vehicle(
        max_range_miles=float(
            max_range_miles
            if max_range_miles is not None
            else settings.FUEL_MAX_RANGE_MILES
        ),
        miles_per_gallon=float(
            miles_per_gallon
            if miles_per_gallon is not None
            else settings.FUEL_MILES_PER_GALLON
        ),
    )


def get_fuel_planner(
    strategy: str | None = None,
    *,
    vehicle: Vehicle | None = None,
) -> FuelPlannerStrategy:
    """
    Return a planner for ``strategy`` (defaults to settings.FUEL_PLANNER_STRATEGY).

    Raises ValueError on an unknown strategy so the API layer can return a 400.
    """
    key = (strategy or settings.FUEL_PLANNER_STRATEGY).lower()
    if key not in _REGISTRY:
        raise ValueError(
            f"Unknown fuel planner strategy '{key}'. "
            f"Available: {', '.join(AVAILABLE_STRATEGIES)}."
        )
    return _REGISTRY[key](vehicle or build_vehicle())

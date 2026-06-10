"""
Provider-agnostic domain objects shared by the routing service, the station
repository, and the fuel planners. Keeping these as plain dataclasses (no Django
imports) makes the planning algorithms trivially unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Vehicle:
    """The fuel model. tank_capacity is derived: range / mpg."""

    max_range_miles: float
    miles_per_gallon: float

    @property
    def tank_capacity_gallons(self) -> float:
        return self.max_range_miles / self.miles_per_gallon

    def miles_for_gallons(self, gallons: float) -> float:
        return gallons * self.miles_per_gallon

    def gallons_for_miles(self, miles: float) -> float:
        return miles / self.miles_per_gallon


@dataclass
class RoutePoint:
    lat: float
    lng: float
    distance_from_start_miles: float


@dataclass
class Route:
    """A fixed driving route returned by the routing provider."""

    points: list[RoutePoint]
    distance_miles: float
    duration_minutes: Optional[float] = None
    polyline: Optional[str] = None
    provider: str = ""

    @property
    def coordinates(self) -> list[tuple[float, float]]:
        return [(p.lat, p.lng) for p in self.points]

    @property
    def cumulative(self) -> list[float]:
        return [p.distance_from_start_miles for p in self.points]


@dataclass
class CandidateStation:
    """A fuel station projected onto the route, ready for planning."""

    station_id: int
    name: str
    lat: float
    lng: float
    price_per_gallon: float
    distance_along_route_miles: float
    offset_miles: float = 0.0


@dataclass
class FuelStop:
    station_id: int
    name: str
    lat: float
    lng: float
    distance_along_route_miles: float
    price_per_gallon: float
    gallons_purchased: float
    cost: float


@dataclass
class FuelPlan:
    vehicle: Vehicle
    stops: list[FuelStop] = field(default_factory=list)
    total_gallons: float = 0.0
    total_cost: float = 0.0
    feasible: bool = True
    strategy: str = ""
    candidate_count: int = 0
    reason: Optional[str] = None

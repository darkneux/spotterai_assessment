"""
Fuel planner interface plus the shared route/station preprocessing used by every
strategy.

Modeling notes (see README §"Fuel model" for the full discussion):

* The vehicle starts empty at the origin and pays for every gallon it consumes,
  so ``total_gallons == total_distance / mpg`` exactly.
* The leg from the origin (mile 0) to the first candidate station can only be
  powered by fuel purchased at that first station's price -- there is nothing
  "behind" those early miles. We therefore charge that leg as a fixed pre-cost
  attributed to the first station and run the classic fixed-route refueling
  problem over the real station nodes with an empty tank at the first station.
  This removes any need to invent an origin price, and makes the greedy and DP
  strategies provably optimal *and* identical (the DP is an independent
  cross-check of the greedy result in the tests).
* A leg between consecutive fuel opportunities may never exceed the vehicle
  range; otherwise the trip is infeasible.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional

from .domain import CandidateStation, FuelPlan, FuelStop, Route, Vehicle

# Numerical slack (miles) to absorb floating-point error in range/gap checks.
EPS = 1e-6


@dataclass
class _Node:
    """An internal planning node: a real station, or the synthetic destination."""

    position: float  # distance along route, miles
    price: float  # price per gallon (inf for destination -> never buy)
    station: Optional[CandidateStation]  # None for the destination node


class FuelPlannerStrategy(abc.ABC):
    """Common interface: plan(route, stations) -> FuelPlan."""

    name: str = "base"

    def __init__(self, vehicle: Vehicle):
        self.vehicle = vehicle

    @abc.abstractmethod
    def _solve(
        self, nodes: list[_Node], total_distance: float
    ) -> tuple[float, dict[int, float]]:
        """
        Return (algorithm_cost, purchases) where purchases maps node index ->
        gallons bought at that node, for the sub-problem that starts with an
        EMPTY tank at nodes[0] (the first station). The origin->first-station
        leg is handled by the caller as a fixed pre-cost.
        """

    # ---- shared orchestration -------------------------------------------------

    def plan(self, route: Route, stations: list[CandidateStation]) -> FuelPlan:
        vehicle = self.vehicle
        mpg = vehicle.miles_per_gallon
        rng = vehicle.max_range_miles
        total = route.distance_miles

        plan = FuelPlan(vehicle=vehicle, strategy=self.name, candidate_count=len(stations))

        # Trivial trip: start == end (or negligible distance).
        if total <= EPS:
            return plan

        ordered = sorted(
            (s for s in stations if -EPS <= s.distance_along_route_miles <= total + EPS),
            key=lambda s: (s.distance_along_route_miles, s.price_per_gallon, s.station_id),
        )

        if not ordered:
            plan.feasible = False
            plan.reason = "No fuel stations found along the route corridor."
            return plan

        # Feasibility: every gap between consecutive fuel opportunities
        # (origin -> s1 -> ... -> sM -> destination) must be within range.
        positions = [0.0] + [s.distance_along_route_miles for s in ordered] + [total]
        for a, b in zip(positions, positions[1:]):
            if b - a > rng + EPS:
                plan.feasible = False
                plan.reason = (
                    f"Infeasible: a {b - a:.1f}-mile gap exceeds the "
                    f"{rng:.0f}-mile vehicle range."
                )
                return plan

        # Build station nodes + synthetic destination. The first station is the
        # empty-tank start of the classic sub-problem.
        nodes = [
            _Node(position=s.distance_along_route_miles, price=s.price_per_gallon, station=s)
            for s in ordered
        ]
        nodes.append(_Node(position=total, price=float("inf"), station=None))

        algorithm_cost, purchases = self._solve(nodes, total)

        # Fixed pre-cost: power the origin -> first station leg at the first
        # station's price, attributed to the first station.
        first = ordered[0]
        prefix_gallons = first.distance_along_route_miles / mpg
        purchases[0] = purchases.get(0, 0.0) + prefix_gallons
        total_cost = algorithm_cost + prefix_gallons * first.price_per_gallon

        stops: list[FuelStop] = []
        total_gallons = 0.0
        for idx, node in enumerate(nodes):
            gallons = purchases.get(idx, 0.0)
            if node.station is None or gallons <= EPS:
                continue
            s = node.station
            cost = gallons * s.price_per_gallon
            total_gallons += gallons
            stops.append(
                FuelStop(
                    station_id=s.station_id,
                    name=s.name,
                    lat=s.lat,
                    lng=s.lng,
                    distance_along_route_miles=round(s.distance_along_route_miles, 3),
                    price_per_gallon=s.price_per_gallon,
                    gallons_purchased=round(gallons, 4),
                    cost=round(cost, 2),
                )
            )

        stops.sort(key=lambda st: st.distance_along_route_miles)
        plan.stops = stops
        plan.total_gallons = round(total_gallons, 4)
        plan.total_cost = round(total_cost, 2)
        return plan

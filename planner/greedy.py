"""
Greedy look-ahead fuel planner (default strategy, design §11).

At the current station, look ahead within range:
  * If a strictly cheaper station is reachable, buy only enough to reach the
    nearest such station, then move there.
  * Otherwise the current station is the cheapest within the horizon, so buy as
    much as is useful -- a full tank, capped by the fuel still needed to finish
    the trip so we never overbuy near the destination -- then advance to the
    next station and re-evaluate.

This is the classic optimal refueling rule for a fixed route with time-invariant
prices and a tank capacity equal to the range; an exchange argument (README)
shows it minimizes total cost.
"""

from __future__ import annotations

from .base import EPS, FuelPlannerStrategy, _Node


class GreedyFuelPlanner(FuelPlannerStrategy):
    name = "greedy"

    def _solve(self, nodes: list[_Node], total_distance: float):
        rng = self.vehicle.max_range_miles
        mpg = self.vehicle.miles_per_gallon
        purchases: dict[int, float] = {}

        i = 0
        fuel_miles = 0.0  # range still available on the fuel currently in the tank
        last = len(nodes) - 1  # destination node index

        while i < last:
            pos = nodes[i].position
            price = nodes[i].price

            # Stations reachable from here within range (excludes destination's
            # infinite price as a "cheaper" target, but destination is a valid
            # place to stop driving).
            cheaper = None
            for j in range(i + 1, len(nodes)):
                if nodes[j].position - pos > rng + EPS:
                    break
                if nodes[j].price < price - EPS:
                    cheaper = j
                    break

            if cheaper is not None:
                gap = nodes[cheaper].position - pos
                buy = max(0.0, gap - fuel_miles)
                if buy > EPS:
                    purchases[i] = purchases.get(i, 0.0) + buy / mpg
                fuel_miles = fuel_miles + buy - gap
                i = cheaper
            else:
                # No cheaper station within reach: fill here (cheapest in the
                # horizon), capped by what is still needed to finish the trip.
                need = total_distance - pos
                target = min(rng, need)
                buy = max(0.0, target - fuel_miles)
                if buy > EPS:
                    purchases[i] = purchases.get(i, 0.0) + buy / mpg
                    fuel_miles += buy
                # Advance one node and re-evaluate with the same rule.
                gap = nodes[i + 1].position - pos
                fuel_miles -= gap
                i += 1

        cost = sum(
            gallons * nodes[idx].price for idx, gallons in purchases.items()
        )
        return cost, purchases

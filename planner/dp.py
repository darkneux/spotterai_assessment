"""
Reference fuel planner -- an independent optimum used to cross-check the greedy
planner (design §24).

Design note / deliberate deviation: the design document proposes a station-graph
DP with the state "minimum cost to arrive at station i with an empty tank". That
formulation is in fact *suboptimal* for this model: when a station lies within
range but the next cheaper station is beyond range, the trip is forced to stop at
the intermediate station, and an "arrive-empty" state cannot carry cheap fuel
*through* that forced stop -- even though the vehicle physically can. (Verified:
on randomized routes the arrive-empty DP returns a strictly higher cost than the
greedy planner.)

The true optimum follows directly from the exchange argument the design cites:
every mile of the trip should be powered by the cheapest station that can reach
it -- i.e. the cheapest station whose position is at most that mile and within
one tank range behind it. This planner computes that optimum by sweeping the
route, splitting it at the points where the set of in-range stations changes, and
charging each segment to its cheapest in-range supplier. It is a completely
different computation from the greedy heap, so agreement between the two is a
meaningful validation that both are correct.
"""

from __future__ import annotations

from .base import EPS, FuelPlannerStrategy, _Node


class DPFuelPlanner(FuelPlannerStrategy):
    name = "dp"

    def _solve(self, nodes: list[_Node], total_distance: float):
        rng = self.vehicle.max_range_miles
        mpg = self.vehicle.miles_per_gallon

        # Real station nodes (exclude the synthetic destination).
        stations = [(idx, n) for idx, n in enumerate(nodes) if n.station is not None]
        start = stations[0][1].position  # first station; subproblem starts empty here

        # Breakpoints where the active (in-range) station set can change.
        marks = {start, total_distance}
        for _, n in stations:
            marks.add(n.position)
            if n.position + rng < total_distance:
                marks.add(n.position + rng)
        points = sorted(m for m in marks if start - EPS <= m <= total_distance + EPS)

        purchases: dict[int, float] = {}
        cost = 0.0
        for a, b in zip(points, points[1:]):
            if b - a <= EPS:
                continue
            mid = (a + b) / 2.0
            # Cheapest station that can supply mile `mid`: position <= mid and
            # within one range behind it.
            best_idx, best_price = None, float("inf")
            for idx, n in stations:
                if n.position <= mid + EPS and mid - n.position <= rng + EPS:
                    if n.price < best_price - EPS:
                        best_price, best_idx = n.price, idx
            if best_idx is None:
                continue  # feasibility is guaranteed by base.py; defensive only
            gallons = (b - a) / mpg
            purchases[best_idx] = purchases.get(best_idx, 0.0) + gallons
            cost += gallons * best_price

        return cost, purchases

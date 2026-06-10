"""
Unit tests for the fuel planners. These cover the design's §16 scenarios and,
crucially, assert that the independent greedy and DP strategies produce the same
total cost (the §24 cross-check) on randomized inputs.
"""

from __future__ import annotations

import random

from django.test import SimpleTestCase

from planner.domain import CandidateStation, Route, RoutePoint, Vehicle
from planner.dp import DPFuelPlanner
from planner.greedy import GreedyFuelPlanner

VEHICLE = Vehicle(max_range_miles=500.0, miles_per_gallon=10.0)


def make_route(distance_miles: float) -> Route:
    """A straight west->east route of the given length (1 mile ~ 1/69 deg lng)."""
    end_lng = -100.0 + distance_miles / 69.0
    return Route(
        points=[
            RoutePoint(lat=39.0, lng=-100.0, distance_from_start_miles=0.0),
            RoutePoint(lat=39.0, lng=end_lng, distance_from_start_miles=distance_miles),
        ],
        distance_miles=distance_miles,
    )


def station(idx, along, price) -> CandidateStation:
    return CandidateStation(
        station_id=idx,
        name=f"S{idx}",
        lat=39.0,
        lng=-100.0,
        price_per_gallon=price,
        distance_along_route_miles=along,
    )


class GreedyPlannerTests(SimpleTestCase):
    def plan(self, distance, stations):
        return GreedyFuelPlanner(VEHICLE).plan(make_route(distance), stations)

    def test_trip_shorter_than_range_one_cheap_fill(self):
        # 300-mile trip, well within range: all fuel bought at the first station.
        plan = self.plan(300, [station(1, 20, 3.00), station(2, 150, 4.00)])
        self.assertTrue(plan.feasible)
        self.assertAlmostEqual(plan.total_gallons, 30.0, places=3)
        # 30 gallons at the only sensibly-priced source ($3.00).
        self.assertAlmostEqual(plan.total_cost, 90.0, places=2)

    def test_zero_distance_no_stops(self):
        plan = self.plan(0, [station(1, 0, 3.0)])
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0.0)

    def test_total_gallons_equals_distance_over_mpg(self):
        plan = self.plan(
            900,
            [station(1, 50, 3.5), station(2, 400, 3.0), station(3, 700, 4.0)],
        )
        self.assertTrue(plan.feasible)
        self.assertAlmostEqual(plan.total_gallons, 90.0, places=2)

    def test_prefers_cheaper_reachable_station(self):
        # First station expensive, a cheaper one is within range: buy minimal at
        # the first, fill at the cheaper one.
        plan = self.plan(
            600,
            [station(1, 10, 4.00), station(2, 300, 3.00)],
        )
        self.assertTrue(plan.feasible)
        # 60 gallons total. Miles [0,300] powered at $4 (30 gal -> $120),
        # miles [300,600] powered at $3 (30 gal -> $90) => $210.
        self.assertAlmostEqual(plan.total_cost, 210.0, places=2)

    def test_does_not_backtrack_to_cheaper_behind(self):
        # The cheapest station is early; later legs cannot reuse it once its
        # range is exhausted, so cost reflects forward-only purchasing.
        plan = self.plan(
            800,
            [station(1, 10, 2.00), station(2, 450, 5.00)],
        )
        self.assertTrue(plan.feasible)
        # prefix [0,10] @ $2 = 1 gal -> $2. The $2 station (mile 10) can power up
        # to mile 510 (50 gal -> $100). Miles [510,800] = 290 mi must come from
        # the $5 station (29 gal -> $145). Total = $247.
        self.assertAlmostEqual(plan.total_cost, 247.0, places=2)

    def test_infeasible_gap_exceeds_range(self):
        plan = self.plan(700, [station(1, 10, 3.0)])  # mile 10 -> 700 = 690 > 500
        self.assertFalse(plan.feasible)
        self.assertIn("range", plan.reason)

    def test_no_stations(self):
        plan = self.plan(300, [])
        self.assertFalse(plan.feasible)
        self.assertIn("No fuel stations", plan.reason)

    def test_identical_prices_deterministic(self):
        p1 = self.plan(400, [station(1, 50, 3.0), station(2, 200, 3.0)])
        p2 = self.plan(400, [station(2, 200, 3.0), station(1, 50, 3.0)])
        self.assertEqual(p1.total_cost, p2.total_cost)


class GreedyDPEquivalenceTests(SimpleTestCase):
    """The DP is an independent optimum; greedy must match it everywhere."""

    def test_random_equivalence(self):
        rng = random.Random(1234)
        for trial in range(300):
            distance = rng.uniform(50, 1500)
            n = rng.randint(0, 12)
            # Place stations so the largest gap stays within range when possible.
            alongs = sorted(rng.uniform(0, distance) for _ in range(n))
            stations = [
                station(i + 1, a, round(rng.uniform(2.5, 4.5), 3))
                for i, a in enumerate(alongs)
            ]
            route = make_route(distance)
            g = GreedyFuelPlanner(VEHICLE).plan(route, stations)
            d = DPFuelPlanner(VEHICLE).plan(route, stations)
            self.assertEqual(g.feasible, d.feasible, msg=f"trial {trial}")
            if g.feasible:
                self.assertAlmostEqual(
                    g.total_cost, d.total_cost, places=4,
                    msg=f"trial {trial}: greedy {g.total_cost} != dp {d.total_cost}",
                )
                self.assertAlmostEqual(g.total_gallons, d.total_gallons, places=4)

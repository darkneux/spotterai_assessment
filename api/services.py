"""
Orchestration: ties the routing service, station repository, and fuel planner
together for a single request. Kept free of HTTP concerns so it is easy to test
and reuse.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from fuelstations.repository import StationRepository
from planner.domain import FuelPlan, Route
from planner.factory import build_vehicle, get_fuel_planner

from routing.service import RoutingService

logger = logging.getLogger("fuelroute.planning")


class EmptyDatasetError(Exception):
    """No geocoded stations are available at all (-> 503)."""


@dataclass
class PlanningResult:
    route: Route
    plan: FuelPlan
    cache_hit: bool


def _plan_cache_key(start, end, max_range, mpg, strategy, initial_fuel) -> str:
    raw = (
        f"{round(start.lat, 4)},{round(start.lng, 4)}:"
        f"{round(end.lat, 4)},{round(end.lng, 4)}:"
        f"range={max_range}:mpg={mpg}:strategy={strategy}:init={initial_fuel}"
    )
    return "plan:" + hashlib.sha1(raw.encode()).hexdigest()


def plan_route_with_fuel(data: dict, strategy: str | None = None) -> PlanningResult:
    """
    Run the full pipeline. Raises GeocodingError/OutsideUSAError/RoutingError
    (from the routing layer), ValueError (bad strategy), or EmptyDatasetError.
    A feasibility failure is returned as plan.feasible == False, not raised.
    """
    routing_service = RoutingService()

    start = routing_service.resolve_point(
        data.get("start"), data.get("start_lat"), data.get("start_lng")
    )
    end = routing_service.resolve_point(
        data.get("end"), data.get("end_lat"), data.get("end_lng")
    )

    max_range = data.get("max_range_miles")
    mpg = data.get("miles_per_gallon")
    strat = strategy or data.get("strategy")
    initial_fuel = data.get("initial_fuel_gallons")

    cache_key = _plan_cache_key(start, end, max_range, mpg, strat, initial_fuel)
    cached_result = cache.get(cache_key)
    
    if cached_result is not None:
        logger.info("plan cache hit %s", cache_key)
        # It's a full hit, we don't need to do any math or DB queries.
        # But we do want to tell the user it was a cache hit.
        cached_result.cache_hit = True 
        return cached_result

    repo = StationRepository(corridor_width_km=settings.ROUTE_CORRIDOR_WIDTH_KM)
    if not repo.has_stations():
        raise EmptyDatasetError(
            "No geocoded fuel stations are loaded. Run import_stations + "
            "geocode_stations first."
        )

    route, route_cache_hit = routing_service.get_route(start, end)
    candidates = repo.candidates_for_route(route)

    vehicle = build_vehicle(max_range_miles=max_range)
    planner = get_fuel_planner(strat, vehicle=vehicle)
    plan = planner.plan(route, candidates)

    if plan.feasible and initial_fuel:
        _apply_initial_fuel(plan, vehicle, float(initial_fuel))

    logger.info(
        "plan: strategy=%s feasible=%s stops=%d cost=%.2f candidates=%d route_cache_hit=%s",
        plan.strategy,
        plan.feasible,
        len(plan.stops),
        plan.total_cost,
        plan.candidate_count,
        route_cache_hit,
    )
    
    result = PlanningResult(route=route, plan=plan, cache_hit=False)
    # Cache the full mathematical result
    cache.set(cache_key, result, settings.ROUTING_CACHE_TTL_SECONDS)
    
    return result


def _apply_initial_fuel(plan: FuelPlan, vehicle, initial_fuel_gallons: float) -> None:
    """
    The vehicle starts with some fuel already in the tank, so it skips buying the
    first `initial_fuel_gallons`. Those gallons cover the earliest miles, which
    are powered by the lowest-position purchases -- refund them in route order.
    """
    remaining = min(initial_fuel_gallons, vehicle.tank_capacity_gallons)
    new_stops = []
    for stop in sorted(plan.stops, key=lambda s: s.distance_along_route_miles):
        if remaining > 0:
            refund = min(remaining, stop.gallons_purchased)
            stop.gallons_purchased = round(stop.gallons_purchased - refund, 4)
            stop.cost = round(stop.gallons_purchased * stop.price_per_gallon, 2)
            remaining -= refund
        if stop.gallons_purchased > 0:
            new_stops.append(stop)
    plan.stops = new_stops
    plan.total_gallons = round(sum(s.gallons_purchased for s in new_stops), 4)
    plan.total_cost = round(sum(s.cost for s in new_stops), 2)

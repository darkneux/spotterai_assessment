"""
The route-with-fuel endpoints:

    POST /api/route-with-fuel/         (strategy from FUEL_PLANNER_STRATEGY)
    POST /api/route-with-fuel/greedy/  (forces GreedyFuelPlanner)
    POST /api/route-with-fuel/dp/      (forces DPFuelPlanner)
    GET  /api/health/

Strategy-specific endpoints give reviewers a deterministic way to compare the
two planners (design §17).
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuelstations.models import FuelStation
from routing.exceptions import GeocodingError, OutsideUSAError, RoutingError

from .exceptions import error_response
from .serializers import (
    RouteRequestSerializer,
    RouteWithFuelResponseSerializer,
)
from .services import EmptyDatasetError, PlanningResult, plan_route_with_fuel


def _serialize_result(result: PlanningResult) -> dict:
    route, plan = result.route, result.plan
    return {
        "route": {
            "distance_miles": route.distance_miles,
            "duration_minutes": route.duration_minutes,
            "polyline": route.polyline,
            "provider": route.provider,
            "points": [
                {
                    "lat": p.lat,
                    "lng": p.lng,
                    "distance_from_start_miles": p.distance_from_start_miles,
                }
                for p in route.points
            ],
        },
        "fuel_plan": {
            "vehicle": {
                "max_range_miles": plan.vehicle.max_range_miles,
                "miles_per_gallon": plan.vehicle.miles_per_gallon,
            },
            "strategy": plan.strategy,
            "candidate_count": plan.candidate_count,
            "stops": [
                {
                    "station_id": s.station_id,
                    "name": s.name,
                    "lat": s.lat,
                    "lng": s.lng,
                    "distance_along_route_miles": s.distance_along_route_miles,
                    "price_per_gallon": s.price_per_gallon,
                    "gallons_purchased": s.gallons_purchased,
                    "cost": s.cost,
                }
                for s in plan.stops
            ],
            "total_gallons": plan.total_gallons,
            "total_cost": plan.total_cost,
        },
        "meta": {"cache_hit": result.cache_hit},
    }


class RouteWithFuelView(APIView):
    """Compute a route and the cost-optimal fuel plan along it."""

    forced_strategy: str | None = None

    @extend_schema(
        request=RouteRequestSerializer,
        responses={
            200: RouteWithFuelResponseSerializer,
            400: OpenApiResponse(description="Validation / geocoding / region error"),
            422: OpenApiResponse(description="Trip infeasible under the vehicle range"),
            502: OpenApiResponse(description="Routing provider failure"),
            503: OpenApiResponse(description="Station dataset unavailable"),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = plan_route_with_fuel(data, strategy=self.forced_strategy)
        except OutsideUSAError as exc:
            return error_response("outside_usa", str(exc), status.HTTP_400_BAD_REQUEST, request)
        except GeocodingError as exc:
            return error_response("geocoding_failed", str(exc), status.HTTP_400_BAD_REQUEST, request)
        except ValueError as exc:  # unknown strategy
            return error_response("invalid_strategy", str(exc), status.HTTP_400_BAD_REQUEST, request)
        except RoutingError as exc:
            return error_response("routing_failed", str(exc), status.HTTP_502_BAD_GATEWAY, request)
        except EmptyDatasetError as exc:
            return error_response("no_dataset", str(exc), status.HTTP_503_SERVICE_UNAVAILABLE, request)

        if not result.plan.feasible:
            code = "no_stations" if "No fuel stations" in (result.plan.reason or "") else "infeasible_trip"
            return error_response(
                code,
                result.plan.reason or "Trip is not feasible.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                request,
                details={"distance_miles": result.route.distance_miles},
            )

        return Response(_serialize_result(result), status=status.HTTP_200_OK)


class GreedyRouteWithFuelView(RouteWithFuelView):
    forced_strategy = "greedy"


class DPRouteWithFuelView(RouteWithFuelView):
    forced_strategy = "dp"


class HealthView(APIView):
    @extend_schema(responses={200: OpenApiResponse(description="Service health")})
    def get(self, request, *args, **kwargs):
        return Response(
            {
                "status": "ok",
                "stations_loaded": FuelStation.objects.count(),
                "stations_geocoded": FuelStation.objects.filter(
                    geocode_status__in=["OK", "APPROXIMATE"]
                ).count(),
            }
        )

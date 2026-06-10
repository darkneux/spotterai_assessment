"""Request/response serializers for the route-with-fuel endpoint."""

from __future__ import annotations

from rest_framework import serializers

from planner.factory import AVAILABLE_STRATEGIES


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(required=False, allow_blank=True)
    end = serializers.CharField(required=False, allow_blank=True)

    start_lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    start_lng = serializers.FloatField(required=False, min_value=-180, max_value=180)
    end_lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    end_lng = serializers.FloatField(required=False, min_value=-180, max_value=180)

    # Optional overrides (design §26).
    strategy = serializers.ChoiceField(
        choices=list(AVAILABLE_STRATEGIES), required=False
    )
    max_range_miles = serializers.FloatField(required=False, min_value=1)
    initial_fuel_gallons = serializers.FloatField(required=False, min_value=0)

    def _has_point(self, data, prefix):
        text = data.get(prefix)
        lat = data.get(f"{prefix}_lat")
        lng = data.get(f"{prefix}_lng")
        has_coords = lat is not None and lng is not None
        has_text = bool(text and text.strip())
        if not (has_coords or has_text):
            return False
        if (lat is None) != (lng is None):
            raise serializers.ValidationError(
                {prefix: f"Both {prefix}_lat and {prefix}_lng must be provided together."}
            )
        return True

    def validate(self, data):
        if not self._has_point(data, "start"):
            raise serializers.ValidationError(
                {"start": "Provide a 'start' location or start_lat/start_lng."}
            )
        if not self._has_point(data, "end"):
            raise serializers.ValidationError(
                {"end": "Provide an 'end' location or end_lat/end_lng."}
            )
        return data


# --- Response serializers (used for OpenAPI schema generation) ---------------

class RoutePointSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    distance_from_start_miles = serializers.FloatField()


class RouteSerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_minutes = serializers.FloatField(allow_null=True)
    polyline = serializers.CharField(allow_null=True)
    provider = serializers.CharField()
    points = RoutePointSerializer(many=True)


class FuelStopSerializer(serializers.Serializer):
    station_id = serializers.IntegerField()
    name = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    distance_along_route_miles = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    cost = serializers.FloatField()


class VehicleSerializer(serializers.Serializer):
    max_range_miles = serializers.FloatField()
    miles_per_gallon = serializers.FloatField()


class FuelPlanSerializer(serializers.Serializer):
    vehicle = VehicleSerializer()
    strategy = serializers.CharField()
    candidate_count = serializers.IntegerField()
    stops = FuelStopSerializer(many=True)
    total_gallons = serializers.FloatField()
    total_cost = serializers.FloatField()


class RouteWithFuelResponseSerializer(serializers.Serializer):
    route = RouteSerializer()
    fuel_plan = FuelPlanSerializer()
    meta = serializers.DictField()

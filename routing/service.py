"""
RoutingService: resolves start/end to coordinates, then fetches the route from
the configured provider with at most one external call per request. Results are
cached (Django cache framework: locmem by default, Redis if configured) keyed by
a normalized start/end so repeated popular routes skip the provider entirely.
"""

from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache

from planner.domain import Route, RoutePoint

from .exceptions import GeocodingError, OutsideUSAError
from .geocoding import GeoPoint, _check_usa, get_geocoder
from .providers import get_routing_provider

logger = logging.getLogger("fuelroute.routing")


class RoutingService:
    def __init__(self, provider=None, geocoder=None):
        self.provider = provider or get_routing_provider()
        self.geocoder = geocoder or get_geocoder()

    # ---- coordinate resolution -----------------------------------------------

    def resolve_point(self, text: str | None, lat: float | None, lng: float | None) -> GeoPoint:
        """Coordinates take precedence over text (design §26)."""
        if lat is not None and lng is not None:
            _check_usa(lat, lng)
            return GeoPoint(lat, lng)
        if text:
            return self.geocoder.geocode(text)
        raise GeocodingError("A location requires either text or lat/lng coordinates.")

    # ---- routing with cache --------------------------------------------------

    def _cache_key(self, start: GeoPoint, end: GeoPoint) -> str:
        raw = (
            f"{self.provider.name}:"
            f"{round(start.lat, 4)},{round(start.lng, 4)}:"
            f"{round(end.lat, 4)},{round(end.lng, 4)}"
        )
        return "route:" + hashlib.sha1(raw.encode()).hexdigest()

    def get_route(self, start: GeoPoint, end: GeoPoint) -> tuple[Route, bool]:
        """Return (route, cache_hit)."""
        key = self._cache_key(start, end)
        cached = cache.get(key)
        if cached is not None:
            logger.info("route cache hit %s", key)
            return self._deserialize(cached), True

        route = self.provider.route((start.lat, start.lng), (end.lat, end.lng))
        cache.set(key, self._serialize(route), settings.ROUTING_CACHE_TTL_SECONDS)
        logger.info(
            "routed via %s: %.1f miles, %d points",
            route.provider,
            route.distance_miles,
            len(route.points),
        )
        return route, False

    # ---- (de)serialization for the cache -------------------------------------

    @staticmethod
    def _serialize(route: Route) -> dict:
        return {
            "distance_miles": route.distance_miles,
            "duration_minutes": route.duration_minutes,
            "polyline": route.polyline,
            "provider": route.provider,
            "points": [
                [p.lat, p.lng, p.distance_from_start_miles] for p in route.points
            ],
        }

    @staticmethod
    def _deserialize(data: dict) -> Route:
        return Route(
            points=[
                RoutePoint(lat=p[0], lng=p[1], distance_from_start_miles=p[2])
                for p in data["points"]
            ],
            distance_miles=data["distance_miles"],
            duration_minutes=data["duration_minutes"],
            polyline=data["polyline"],
            provider=data["provider"],
        )

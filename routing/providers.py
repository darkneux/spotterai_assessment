"""
Routing providers. Each takes start/end coordinates and returns a Route with at
most one external call. Selected via ROUTING_PROVIDER.

* offline - deterministic densified great-circle path, no network, no key.
            Distances are realistic enough to exercise the fuel planner and make
            the demo/tests fully reproducible.
* ors     - OpenRouteService directions (free tier, requires ORS_API_KEY).
* osrm    - OSRM directions (no key; public demo server or self-hosted).

All providers request/produce GeoJSON-style coordinate lists so no polyline
decoding is needed on the request path; an encoded polyline is added to the
response for convenience.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from planner.domain import Route, RoutePoint
from planner.geo import cumulative_distances, haversine_miles

from . import polyline as polyline_codec
from .exceptions import RoutingError

logger = logging.getLogger("fuelroute.routing")

_AVG_SPEED_MPH = 60.0


def _build_route(coords: list[tuple[float, float]], provider: str,
                 duration_minutes: float | None = None) -> Route:
    if len(coords) < 2:
        raise RoutingError("Route has fewer than two points.")
    cum = cumulative_distances(coords)
    total = cum[-1]
    points = [
        RoutePoint(lat=lat, lng=lng, distance_from_start_miles=round(c, 4))
        for (lat, lng), c in zip(coords, cum)
    ]
    if duration_minutes is None:
        duration_minutes = (total / _AVG_SPEED_MPH) * 60.0
    return Route(
        points=points,
        distance_miles=round(total, 4),
        duration_minutes=round(duration_minutes, 1),
        polyline=polyline_codec.encode(coords),
        provider=provider,
    )


class BaseRoutingProvider:
    name = "base"

    def route(self, start: tuple[float, float], end: tuple[float, float]) -> Route:
        raise NotImplementedError  # pragma: no cover


class OfflineRoutingProvider(BaseRoutingProvider):
    name = "offline"

    def route(self, start, end):
        (lat1, lng1), (lat2, lng2) = start, end
        total = haversine_miles(lat1, lng1, lat2, lng2)
        # Densify so corridor projection has a realistic polyline to work with.
        steps = max(2, min(200, int(total / 10) + 2))
        coords = [
            (lat1 + (lat2 - lat1) * i / steps, lng1 + (lng2 - lng1) * i / steps)
            for i in range(steps + 1)
        ]
        return _build_route(coords, self.name)


class ORSRoutingProvider(BaseRoutingProvider):
    name = "ors"

    def route(self, start, end):
        if not settings.ORS_API_KEY:
            raise RoutingError("ORS_API_KEY is not configured.")
        base = settings.ORS_BASE_URL.rstrip("/")
        url = f"{base}/v2/directions/driving-car/geojson"
        # ORS expects [lng, lat] ordering.
        body = {"coordinates": [[start[1], start[0]], [end[1], end[0]]]}
        try:
            resp = requests.post(
                url,
                json=body,
                headers={"Authorization": settings.ORS_API_KEY},
                timeout=15,
            )
            resp.raise_for_status()
            feature = resp.json()["features"][0]
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise RoutingError(f"OpenRouteService routing failed: {exc}") from exc

        coords = [(lat, lng) for lng, lat in feature["geometry"]["coordinates"]]
        summary = feature.get("properties", {}).get("summary", {})
        duration = summary.get("duration")
        duration_minutes = duration / 60.0 if duration else None
        return _build_route(coords, self.name, duration_minutes)


class OSRMRoutingProvider(BaseRoutingProvider):
    name = "osrm"

    def route(self, start, end):
        base = settings.OSRM_BASE_URL.rstrip("/")
        # OSRM expects lng,lat;lng,lat in the path.
        coord_str = f"{start[1]},{start[0]};{end[1]},{end[0]}"
        url = f"{base}/route/v1/driving/{coord_str}"
        try:
            resp = requests.get(
                url,
                params={"overview": "full", "geometries": "geojson"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            route0 = data["routes"][0]
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise RoutingError(f"OSRM routing failed: {exc}") from exc

        coords = [(lat, lng) for lng, lat in route0["geometry"]["coordinates"]]
        duration = route0.get("duration")
        duration_minutes = duration / 60.0 if duration else None
        return _build_route(coords, self.name, duration_minutes)


_PROVIDERS = {
    OfflineRoutingProvider.name: OfflineRoutingProvider,
    ORSRoutingProvider.name: ORSRoutingProvider,
    OSRMRoutingProvider.name: OSRMRoutingProvider,
}


def get_routing_provider(provider: str | None = None) -> BaseRoutingProvider:
    key = (provider or settings.ROUTING_PROVIDER).lower()
    if key not in _PROVIDERS:
        raise ValueError(f"Unknown routing provider '{key}'.")
    return _PROVIDERS[key]()

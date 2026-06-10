"""
Station repository: the only place that talks to the FuelStation table.

It performs a single indexed corridor query per request -- a bounding box around
the route's extent, padded by the corridor half-width -- then projects each
returned station onto the route polyline in Python and keeps those within the
corridor width. For the ~8k-row dataset this is one fast query plus in-memory
work on a small candidate set, matching the design's performance goal.
"""

from __future__ import annotations

import logging

from django.db.models import QuerySet

from planner.domain import CandidateStation, Route
from planner.geo import km_to_miles, project_point_to_route

from .models import FuelStation, GeocodeStatus

logger = logging.getLogger("fuelroute.repository")

# Degrees of latitude per mile (~constant). Longitude is corrected by latitude.
_MILES_PER_DEG_LAT = 69.0


def _bbox(route: Route, pad_miles: float) -> tuple[float, float, float, float]:
    lats = [p.lat for p in route.points]
    lngs = [p.lng for p in route.points]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    lat_pad = pad_miles / _MILES_PER_DEG_LAT
    # Use the higher-magnitude latitude for a conservative (wider) longitude pad.
    import math

    cos_lat = max(0.01, math.cos(math.radians(max(abs(min_lat), abs(max_lat)))))
    lng_pad = pad_miles / (_MILES_PER_DEG_LAT * cos_lat)
    return (
        min_lat - lat_pad,
        max_lat + lat_pad,
        min_lng - lng_pad,
        max_lng + lng_pad,
    )


class StationRepository:
    def __init__(self, corridor_width_km: float):
        self.corridor_width_miles = km_to_miles(corridor_width_km)

    def _locatable(self) -> QuerySet[FuelStation]:
        return FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            geocode_status__in=[GeocodeStatus.OK, GeocodeStatus.APPROXIMATE],
        )

    def has_stations(self) -> bool:
        return self._locatable().exists()

    def candidates_for_route(self, route: Route) -> list[CandidateStation]:
        """
        Return stations within the corridor, each projected onto the route and
        tagged with distance_along_route. Single DB query; projection in memory.
        """
        min_lat, max_lat, min_lng, max_lng = _bbox(route, self.corridor_width_miles)

        rows = list(
            self._locatable()
            .filter(
                latitude__gte=min_lat,
                latitude__lte=max_lat,
                longitude__gte=min_lng,
                longitude__lte=max_lng,
            )
            .values("id", "name", "latitude", "longitude", "retail_price")
        )

        coords = route.coordinates
        cum = route.cumulative

        candidates: list[CandidateStation] = []
        for row in rows:
            along, offset = project_point_to_route(
                (row["latitude"], row["longitude"]), coords, cum
            )
            if offset > self.corridor_width_miles:
                continue
            candidates.append(
                CandidateStation(
                    station_id=row["id"],
                    name=row["name"],
                    lat=row["latitude"],
                    lng=row["longitude"],
                    price_per_gallon=float(row["retail_price"]),
                    distance_along_route_miles=along,
                    offset_miles=offset,
                )
            )

        logger.info(
            "corridor query returned %d stations, %d within corridor",
            len(rows),
            len(candidates),
        )
        return candidates

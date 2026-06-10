"""
Geospatial helpers used to turn a route polyline + station coordinates into the
1-D abstraction the fuel planner needs: a route of length ``total_distance`` and
each station mapped to a ``distance_along_route``.

Distances use the haversine great-circle formula in miles. Projection of a
station onto the route is a point-to-polyline nearest-segment computation done in
local equirectangular coordinates, which is accurate enough at corridor scale
(tens of km) and avoids any PostGIS dependency so the project runs on plain
SQLite/Postgres. The PostGIS equivalents (ST_LineLocatePoint / ST_DWithin) are
documented in the README as a drop-in optimization.
"""

from __future__ import annotations

import math
from typing import Sequence

EARTH_RADIUS_MILES = 3958.7613
MILES_PER_KM = 0.621371


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def cumulative_distances(points: Sequence[tuple[float, float]]) -> list[float]:
    """Cumulative miles from the first point to each point in ``points``."""
    cum = [0.0]
    for i in range(1, len(points)):
        lat1, lng1 = points[i - 1]
        lat2, lng2 = points[i]
        cum.append(cum[-1] + haversine_miles(lat1, lng1, lat2, lng2))
    return cum


def _local_xy(lat: float, lng: float, lat0: float) -> tuple[float, float]:
    """Equirectangular projection to local miles around reference latitude lat0."""
    x = math.radians(lng) * math.cos(math.radians(lat0)) * EARTH_RADIUS_MILES
    y = math.radians(lat) * EARTH_RADIUS_MILES
    return x, y


def project_point_to_route(
    point: tuple[float, float],
    points: Sequence[tuple[float, float]],
    cum: Sequence[float],
) -> tuple[float, float]:
    """
    Project ``point`` onto the route polyline.

    Returns ``(distance_along_route_miles, perpendicular_offset_miles)`` where the
    distance is measured from the route start to the nearest point on the polyline,
    and the offset is how far the station sits off the route.
    """
    plat, plng = point
    best_along = 0.0
    best_offset = float("inf")

    for i in range(len(points) - 1):
        a_lat, a_lng = points[i]
        b_lat, b_lng = points[i + 1]
        lat0 = (a_lat + b_lat) / 2.0

        ax, ay = _local_xy(a_lat, a_lng, lat0)
        bx, by = _local_xy(b_lat, b_lng, lat0)
        px, py = _local_xy(plat, plng, lat0)

        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0.0:
            t = 0.0
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))

        proj_x, proj_y = ax + t * dx, ay + t * dy
        offset = math.hypot(px - proj_x, py - proj_y)

        if offset < best_offset:
            best_offset = offset
            segment_miles = cum[i + 1] - cum[i]
            best_along = cum[i] + t * segment_miles

    return best_along, best_offset


def km_to_miles(km: float) -> float:
    return km * MILES_PER_KM

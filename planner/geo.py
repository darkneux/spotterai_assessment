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

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

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


def simplify_route_rdp(points: list[tuple[float, float]], epsilon_miles: float) -> list[int]:
    """
    Ramer-Douglas-Peucker algorithm to simplify a path.
    Returns the indices of the essential points.
    """
    if len(points) < 3:
        return list(range(len(points)))

    def find_furthest(start_idx, end_idx):
        max_dist = 0.0
        pivot = start_idx
        a_lat, a_lng = points[start_idx]
        b_lat, b_lng = points[end_idx]
        
        for i in range(start_idx + 1, end_idx):
            # Cheap planar distance approximation for simplification
            p_lat, p_lng = points[i]
            # cross product for point-to-line distance
            dist = abs((b_lng - a_lng) * p_lat - (b_lat - a_lat) * p_lng + b_lat * a_lng - b_lng * a_lat) / \
                   math.sqrt((b_lng - a_lng)**2 + (b_lat - a_lat)**2 + 1e-9)
            if dist > max_dist:
                max_dist = dist
                pivot = i
        return pivot, max_dist

    indices = {0, len(points) - 1}

    def split(start, end):
        pivot, dist = find_furthest(start, end)
        if dist > (epsilon_miles / 69.0): # Convert miles to rough degrees
            indices.add(pivot)
            split(start, pivot)
            split(pivot, end)

    split(0, len(points) - 1)
    return sorted(list(indices))


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
    Returns ``(distance_along_route_miles, perpendicular_offset_miles)``.
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


def project_points_to_route_numpy(
    station_coords: np.ndarray, 
    route_coords: np.ndarray, 
    route_cum: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    NumPy-vectorized projection. 
    station_coords: (S, 2) array of [lat, lng]
    route_coords: (P, 2) array of [lat, lng]
    route_cum: (P,) array of cumulative distances
    
    Returns: (along_array, offset_array) both shape (S,)
    """
    S = station_coords.shape[0]
    P = route_coords.shape[0]
    
    # Extract segments
    A = route_coords[:-1] # Start of each segment (P-1, 2)
    B = route_coords[1:]  # End of each segment (P-1, 2)
    
    # Calculate mid-lat for each segment for local projection
    lat0 = (A[:, 0] + B[:, 0]) / 2.0
    cos_lat0 = np.cos(np.radians(lat0))
    
    # Convert segments to local XY miles
    # R is constant, so we can ignore it for 't' calculation
    # ax = rad(lng) * cos(lat0) * R
    # ay = rad(lat) * R
    
    def to_xy(coords, c_lat0):
        # coords is (N, 2) or (1, 2)
        # returns (N, 2) in local planar miles relative to R
        # We'll work in units of radians*R for simplicity
        y = np.radians(coords[..., 0]) * EARTH_RADIUS_MILES
        x = np.radians(coords[..., 1]) * EARTH_RADIUS_MILES * c_lat0
        return np.stack([x, y], axis=-1)

    # For every station (S) and every segment (P-1), we need local XY.
    # This is the memory-intensive part. We'll do it per station to keep RAM low.
    
    best_along = np.zeros(S)
    best_offset = np.full(S, np.inf)
    
    # Pre-calculate segment deltas
    # Since each segment has its own lat0, we must do this carefully.
    # To keep it efficient AND accurate, we'll iterate over stations
    # but vectorize the search over all route segments.
    
    for s_idx in range(S):
        p = station_coords[s_idx]
        
        # Local XY for all segments relative to their own midpoints
        # ax, ay (P-1, 2)
        ax = np.radians(A[:, 1]) * EARTH_RADIUS_MILES * cos_lat0
        ay = np.radians(A[:, 0]) * EARTH_RADIUS_MILES
        bx = np.radians(B[:, 1]) * EARTH_RADIUS_MILES * cos_lat0
        by = np.radians(B[:, 0]) * EARTH_RADIUS_MILES
        px = np.radians(p[1]) * EARTH_RADIUS_MILES * cos_lat0
        py = np.radians(p[0]) * EARTH_RADIUS_MILES
        
        dx = bx - ax
        dy = by - ay
        
        dpx = px - ax
        dpy = py - ay
        
        seg_len_sq = dx*dx + dy*dy
        # Avoid div by zero
        seg_len_sq[seg_len_sq == 0] = 1e-9
        
        t = (dpx*dx + dpy*dy) / seg_len_sq
        t = np.clip(t, 0.0, 1.0)
        
        proj_x = ax + t * dx
        proj_y = ay + t * dy
        
        offsets = np.hypot(px - proj_x, py - proj_y)
        
        best_seg_idx = np.argmin(offsets)
        best_offset[s_idx] = offsets[best_seg_idx]
        
        t_best = t[best_seg_idx]
        seg_start_cum = route_cum[best_seg_idx]
        seg_end_cum = route_cum[best_seg_idx + 1]
        best_along[s_idx] = seg_start_cum + t_best * (seg_end_cum - seg_start_cum)
        
    return best_along, best_offset


def km_to_miles(km: float) -> float:
    return km * MILES_PER_KM


def get_grid_cells_for_route(
    points: Sequence[tuple[float, float]], 
    grid_size_deg: float
) -> set[tuple[int, int]]:
    """
    Return a set of (lat_bin, lng_bin) indices that the route crosses.
    """
    cells = set()
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i+1]
        
        # Add start and end cells
        cells.add((int(p1[0] / grid_size_deg), int(p1[1] / grid_size_deg)))
        cells.add((int(p2[0] / grid_size_deg), int(p2[1] / grid_size_deg)))
        
        # Simple linear interpolation for long segments to ensure we don't miss cells
        dist = haversine_miles(p1[0], p1[1], p2[0], p2[1])
        if dist > (grid_size_deg * 69.0):
            steps = int(dist / (grid_size_deg * 30.0)) + 1
            for s in range(1, steps):
                frac = s / steps
                lat = p1[0] + (p2[0] - p1[0]) * frac
                lng = p1[1] + (p2[1] - p1[1]) * frac
                cells.add((int(lat / grid_size_deg), int(lng / grid_size_deg)))
                
    return cells


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
from collections import defaultdict
from typing import ClassVar

from django.db.models import QuerySet

from planner.domain import CandidateStation, Route
from planner.geo import (
    km_to_miles, 
    project_point_to_route, 
    simplify_route_rdp, 
    get_grid_cells_for_route
)

from .models import FuelStation, GeocodeStatus

logger = logging.getLogger("fuelroute.repository")

# Degrees of latitude per mile (~constant). Longitude is corrected by latitude.
_MILES_PER_DEG_LAT = 69.0
GRID_SIZE_DEG = 0.5 # ~35 miles per cell


class GridStationIndex:
    """
    In-memory spatial index of all locatable fuel stations.
    Trades ~10-20MB of RAM for near-instant station discovery.
    """
    _instance: ClassVar[GridStationIndex | None] = None

    def __init__(self):
        self.grid = defaultdict(list)
        self.load_count = 0
        self.refresh()

    @classmethod
    def get_instance(cls) -> GridStationIndex:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def refresh(self):
        """Load all locatable stations from DB into the grid."""
        self.grid.clear()
        stations = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            geocode_status__in=[GeocodeStatus.OK, GeocodeStatus.APPROXIMATE],
        ).values("id", "name", "latitude", "longitude", "retail_price")
        
        for s in stations:
            lat_bin = int(s["latitude"] / GRID_SIZE_DEG)
            lng_bin = int(s["longitude"] / GRID_SIZE_DEG)
            self.grid[(lat_bin, lng_bin)].append(s)
            
        self.load_count = len(stations)
        logger.info("Spatial grid loaded with %d stations", self.load_count)

    def get_candidates_in_cells(self, cells: set[tuple[int, int]]) -> list[dict]:
        """Return all stations in the specified cells + their 8 neighbors."""
        expanded_cells = set()
        for lat, lng in cells:
            for d_lat in [-1, 0, 1]:
                for d_lng in [-1, 0, 1]:
                    expanded_cells.add((lat + d_lat, lng + d_lng))
        
        candidates = []
        for cell in expanded_cells:
            candidates.extend(self.grid.get(cell, []))
        return candidates


class StationRepository:
    def __init__(self, corridor_width_km: float):
        self.corridor_width_miles = km_to_miles(corridor_width_km)
        self.index = GridStationIndex.get_instance()

    def has_stations(self) -> bool:
        return self.index.load_count > 0

    def candidates_for_route(self, route: Route) -> list[CandidateStation]:
        """
        Return stations within the corridor using Spatial Grid Hashing and RDP Simplification.
        1. Simplify the route (reduce 14k points to ~500).
        2. Identify grid cells the route touches.
        3. Only project stations in those grid cells.
        """
        # Optimization 1: Simplify the route polyline (RDP)
        # Using a 0.5 mile epsilon - accurate enough for a 30km corridor search.
        raw_coords = route.coordinates
        essential_indices = simplify_route_rdp(raw_coords, epsilon_miles=0.5)
        
        simple_coords = [raw_coords[i] for i in essential_indices]
        simple_cum = [route.cumulative[i] for i in essential_indices]
        
        logger.info("RDP Simplified route: %d points -> %d points", len(raw_coords), len(simple_coords))

        # Optimization 2: Grid Hashing lookup
        route_cells = get_grid_cells_for_route(simple_coords, GRID_SIZE_DEG)
        rows = self.index.get_candidates_in_cells(route_cells)

        candidates: list[CandidateStation] = []
        for row in rows:
            # We use the simplified line for the projection math (huge speedup)
            along, offset = project_point_to_route(
                (row["latitude"], row["longitude"]), simple_coords, simple_cum
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
            "Spatial lookup returned %d stations, %d within corridor",
            len(rows),
            len(candidates),
        )
        return candidates

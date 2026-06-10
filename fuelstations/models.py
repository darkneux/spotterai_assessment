"""
FuelStation model: one row per truck stop from the fuel-price CSV.

Coordinates are populated by the offline geocoding pipeline
(`manage.py geocode_stations`), never at request time. We store plain numeric
latitude/longitude with B-tree indexes and do corridor selection with a
bounding-box query, which keeps the project free of a PostGIS dependency while
remaining fast for the ~8k-row dataset. The README documents the PostGIS
PointField + GiST index drop-in for higher query throughput.
"""

from __future__ import annotations

from django.db import models


class GeocodeStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    OK = "OK", "Ok"
    APPROXIMATE = "APPROXIMATE", "Approximate (city/state centroid)"
    FAILED = "FAILED", "Failed"


class FuelStation(models.Model):
    opis_id = models.IntegerField("OPIS Truckstop ID", db_index=True)
    name = models.CharField("Truckstop Name", max_length=255)
    address = models.CharField(max_length=512, blank=True)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=2, blank=True, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True, db_index=True)
    retail_price = models.DecimalField(max_digits=7, decimal_places=4)

    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    geocode_status = models.CharField(
        max_length=12,
        choices=GeocodeStatus.choices,
        default=GeocodeStatus.PENDING,
        db_index=True,
    )
    geocode_attempts = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # Composite index supporting the corridor bounding-box scan.
            models.Index(fields=["latitude", "longitude"], name="station_lat_lng_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.city}, {self.state}) @ ${self.retail_price}"

    @property
    def is_locatable(self) -> bool:
        return (
            self.latitude is not None
            and self.longitude is not None
            and self.geocode_status in (GeocodeStatus.OK, GeocodeStatus.APPROXIMATE)
        )

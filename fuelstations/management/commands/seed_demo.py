"""
Seed a small, fully-geocoded demo dataset whose stations lie along the offline
SF -> Denver route, so `POST /api/route-with-fuel/` returns a multi-stop plan
with no network access or geocoding. Purely for demos/tests; the real workflow
is import_stations + geocode_stations.

Usage:
    python manage.py seed_demo
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from fuelstations.models import FuelStation, GeocodeStatus
from routing.geocoding import _KNOWN_CITIES
from routing.providers import OfflineRoutingProvider

# (distance fraction along route, name, price/gal). Prices vary so the planner
# has meaningful choices; note the cheap station near the middle.
_STATIONS = [
    (0.04, "Bay Gateway Fuel", "3.95"),
    (0.12, "Altamont Truck Plaza", "3.79"),
    (0.22, "Central Valley Stop", "4.10"),
    (0.30, "Sierra Foothills Fuel", "3.65"),
    (0.41, "High Desert Pumps", "3.49"),  # cheapest
    (0.52, "Basin & Range Fuel", "3.88"),
    (0.63, "Salt Flats Travel Center", "3.72"),
    (0.74, "Wasatch Crossing", "4.05"),
    (0.83, "Rockies West Fuel", "3.99"),
    (0.93, "Front Range Stop", "3.84"),
]


class Command(BaseCommand):
    help = "Create a small geocoded demo dataset along the SF -> Denver route."

    def handle(self, *args, **options):
        start = _KNOWN_CITIES["san francisco, ca"]
        end = _KNOWN_CITIES["denver, co"]
        route = OfflineRoutingProvider().route(start, end)
        coords = route.coordinates
        cum = route.cumulative
        total = route.distance_miles

        def point_at(fraction: float):
            target = fraction * total
            for i in range(len(cum) - 1):
                if cum[i] <= target <= cum[i + 1]:
                    seg = cum[i + 1] - cum[i] or 1.0
                    t = (target - cum[i]) / seg
                    lat = coords[i][0] + (coords[i + 1][0] - coords[i][0]) * t
                    lng = coords[i][1] + (coords[i + 1][1] - coords[i][1]) * t
                    return lat, lng
            return coords[-1]

        FuelStation.objects.filter(opis_id__gte=900000).delete()
        created = 0
        for idx, (frac, name, price) in enumerate(_STATIONS, start=1):
            lat, lng = point_at(frac)
            FuelStation.objects.update_or_create(
                opis_id=900000 + idx,
                defaults=dict(
                    name=name,
                    address=f"Mile {round(frac * total)} demo corridor",
                    city="Demo",
                    state="NV",
                    retail_price=Decimal(price),
                    latitude=lat,
                    longitude=lng,
                    geocode_status=GeocodeStatus.OK,
                ),
            )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} demo stations along the "
                f"{total:.0f}-mile SF -> Denver corridor."
            )
        )

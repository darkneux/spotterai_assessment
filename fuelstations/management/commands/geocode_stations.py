"""
Offline geocoding pass: convert station address/city/state into lat/lng.

Usage:
    python manage.py geocode_stations                 # all PENDING/FAILED
    python manage.py geocode_stations --provider census --limit 500 --sleep 0.2

Runs out-of-band (never at request time). Records geocode_status and increments
geocode_attempts so transient failures can be retried, and falls back to a
city/state centroid (flagged APPROXIMATE) when a precise match is unavailable.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from fuelstations.models import FuelStation, GeocodeStatus
from routing.exceptions import GeocodingError, OutsideUSAError
from routing.geocoding import get_geocoder


class Command(BaseCommand):
    help = "Geocode fuel stations that do not yet have coordinates."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default=None,
                            help="offline | census | nominatim (default: settings).")
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--sleep", type=float, default=0.0,
                            help="Seconds to wait between calls (rate limiting).")
        parser.add_argument("--retry-failed", action="store_true",
                            help="Also re-attempt previously FAILED stations.")

    def handle(self, *args, **options):
        geocoder = get_geocoder(options["provider"])

        statuses = [GeocodeStatus.PENDING]
        if options["retry_failed"]:
            statuses.append(GeocodeStatus.FAILED)
        qs = FuelStation.objects.filter(Q(geocode_status__in=statuses))
        if options["limit"]:
            qs = qs[: options["limit"]]

        ok = approx = failed = 0
        for station in qs.iterator():
            station.geocode_attempts += 1
            full = ", ".join(p for p in [station.address, station.city, station.state] if p)
            city_state = ", ".join(p for p in [station.city, station.state] if p)

            point = None
            status_val = GeocodeStatus.FAILED
            # Try the full address first, then the city/state centroid.
            for query, fallback in ((full, False), (city_state, True)):
                if not query:
                    continue
                try:
                    point = geocoder.geocode(query)
                    status_val = GeocodeStatus.APPROXIMATE if fallback else GeocodeStatus.OK
                    break
                except (GeocodingError, OutsideUSAError):
                    continue

            if point is not None:
                station.latitude = point.lat
                station.longitude = point.lng
                station.geocode_status = status_val
                if status_val == GeocodeStatus.OK:
                    ok += 1
                else:
                    approx += 1
            else:
                station.geocode_status = GeocodeStatus.FAILED
                failed += 1

            station.save(update_fields=[
                "latitude", "longitude", "geocode_status", "geocode_attempts", "updated_at"
            ])
            if options["sleep"]:
                time.sleep(options["sleep"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Geocoding complete: {ok} exact, {approx} approximate, {failed} failed."
            )
        )

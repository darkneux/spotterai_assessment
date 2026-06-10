"""
Import the fuel-price CSV into the FuelStation table.

Usage:
    python manage.py import_stations data/fuel-prices-for-be-assessment.csv
    python manage.py import_stations data/sample_fuel_prices.csv --truncate

Column names are matched case-insensitively and tolerate minor header variants.
Existing rows (matched by OPIS Truckstop ID) are updated; new rows are created.
Coordinates are left blank for the geocoding pass unless lat/lng columns exist.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuelstations.models import FuelStation, GeocodeStatus

# Map model field -> list of acceptable CSV header names (lowercased).
COLUMN_ALIASES = {
    "opis_id": ["opis truckstop id", "opis_id", "opis id"],
    "name": ["truckstop name", "name"],
    "address": ["address"],
    "city": ["city"],
    "state": ["state"],
    "rack_id": ["rack id", "rack_id"],
    "retail_price": ["retail price", "retail_price", "price"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon", "long"],
}


def _build_header_index(fieldnames: list[str]) -> dict[str, str]:
    lower_to_actual = {name.strip().lower(): name for name in fieldnames}
    resolved: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_to_actual:
                resolved[field] = lower_to_actual[alias]
                break
    return resolved


class Command(BaseCommand):
    help = "Import fuel station rows from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete all existing stations before importing.",
        )
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        path = options["csv_path"]
        try:
            f = open(path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Cannot open {path}: {exc}")

        with f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")
            cols = _build_header_index(reader.fieldnames)
            for required in ("opis_id", "name", "retail_price"):
                if required not in cols:
                    raise CommandError(
                        f"CSV is missing a column for '{required}'. "
                        f"Found headers: {reader.fieldnames}"
                    )

            if options["truncate"]:
                deleted, _ = FuelStation.objects.all().delete()
                self.stdout.write(f"Truncated existing stations ({deleted} rows).")

            created = updated = skipped = 0
            batch: list[FuelStation] = []
            existing_ids = set(FuelStation.objects.values_list("opis_id", flat=True))

            def flush(objs):
                if objs:
                    FuelStation.objects.bulk_create(objs, batch_size=options["batch_size"])

            with transaction.atomic():
                for row in reader:
                    try:
                        opis_id = int(float(row[cols["opis_id"]]))
                        price = Decimal(str(row[cols["retail_price"]]).strip())
                    except (ValueError, InvalidOperation, KeyError):
                        skipped += 1
                        continue

                    lat = lng = None
                    status_val = GeocodeStatus.PENDING
                    if "latitude" in cols and "longitude" in cols:
                        try:
                            lat = float(row[cols["latitude"]])
                            lng = float(row[cols["longitude"]])
                            status_val = GeocodeStatus.OK
                        except (ValueError, TypeError):
                            lat = lng = None

                    fields = dict(
                        opis_id=opis_id,
                        name=(row.get(cols.get("name", ""), "") or "").strip()[:255],
                        address=(row.get(cols.get("address", ""), "") or "").strip()[:512],
                        city=(row.get(cols.get("city", ""), "") or "").strip()[:128],
                        state=(row.get(cols.get("state", ""), "") or "").strip()[:2].upper(),
                        retail_price=price,
                        latitude=lat,
                        longitude=lng,
                        geocode_status=status_val,
                    )
                    rack_raw = row.get(cols.get("rack_id", ""), "")
                    try:
                        fields["rack_id"] = int(float(rack_raw)) if rack_raw else None
                    except (ValueError, TypeError):
                        fields["rack_id"] = None

                    if opis_id in existing_ids:
                        FuelStation.objects.filter(opis_id=opis_id).update(**fields)
                        updated += 1
                    else:
                        batch.append(FuelStation(**fields))
                        existing_ids.add(opis_id)
                        created += 1
                        if len(batch) >= options["batch_size"]:
                            flush(batch)
                            batch = []
                flush(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {created} created, {updated} updated, "
                f"{skipped} skipped."
            )
        )

"""
Geocoding providers for free-text locations (start/end inputs and station
addresses). Selected via the GEOCODING_PROVIDER setting.

* offline   - no network; resolves a built-in table of well-known US cities.
              Ideal for tests and the zero-setup demo. Unknown locations raise
              GeocodingError, prompting the caller to pass explicit coordinates.
* census    - US Census Bureau one-line geocoder (no key, US-only).
* nominatim - OpenStreetMap Nominatim (public endpoint is 1 req/s).

USA bounds are enforced so out-of-country coordinates are rejected early.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

from .exceptions import GeocodingError, OutsideUSAError

logger = logging.getLogger("fuelroute.geocoding")

# Generous bounding box for the contiguous USA + AK/HI margins.
USA_BOUNDS = {"min_lat": 18.0, "max_lat": 72.0, "min_lng": -180.0, "max_lng": -66.0}

# A small built-in gazetteer so the demo/tests need no network or API key.
_KNOWN_CITIES: dict[str, tuple[float, float]] = {
    "san francisco, ca": (37.7749, -122.4194),
    "los angeles, ca": (34.0522, -118.2437),
    "san diego, ca": (32.7157, -117.1611),
    "sacramento, ca": (38.5816, -121.4944),
    "las vegas, nv": (36.1699, -115.1398),
    "phoenix, az": (33.4484, -112.0740),
    "denver, co": (39.7392, -104.9903),
    "salt lake city, ut": (40.7608, -111.8910),
    "dallas, tx": (32.7767, -96.7970),
    "houston, tx": (29.7604, -95.3698),
    "austin, tx": (30.2672, -97.7431),
    "oklahoma city, ok": (35.4676, -97.5164),
    "chicago, il": (41.8781, -87.6298),
    "st louis, mo": (38.6270, -90.1994),
    "kansas city, mo": (39.0997, -94.5786),
    "new york, ny": (40.7128, -74.0060),
    "boston, ma": (42.3601, -71.0589),
    "atlanta, ga": (33.7490, -84.3880),
    "miami, fl": (25.7617, -80.1918),
    "seattle, wa": (47.6062, -122.3321),
    "portland, or": (45.5152, -122.6784),
    "minneapolis, mn": (44.9778, -93.2650),
    "nashville, tn": (36.1627, -86.7816),
    "memphis, tn": (35.1495, -90.0490),
    "albuquerque, nm": (35.0844, -106.6504),
    "amarillo, tx": (35.2220, -101.8313),
    "flagstaff, az": (35.1983, -111.6513),
    "barstow, ca": (34.8958, -117.0173),
}


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


def _check_usa(lat: float, lng: float) -> None:
    if not (
        USA_BOUNDS["min_lat"] <= lat <= USA_BOUNDS["max_lat"]
        and USA_BOUNDS["min_lng"] <= lng <= USA_BOUNDS["max_lng"]
    ):
        raise OutsideUSAError(
            f"Coordinate ({lat:.4f}, {lng:.4f}) is outside the supported USA region."
        )


class BaseGeocoder:
    def geocode(self, location: str) -> GeoPoint:  # pragma: no cover - interface
        raise NotImplementedError


class OfflineGeocoder(BaseGeocoder):
    def geocode(self, location: str) -> GeoPoint:
        key = " ".join(location.lower().replace(".", "").split())
        if key in _KNOWN_CITIES:
            lat, lng = _KNOWN_CITIES[key]
            _check_usa(lat, lng)
            return GeoPoint(lat, lng)
        raise GeocodingError(
            f"Offline geocoder does not know '{location}'. Provide explicit "
            f"start_lat/start_lng/end_lat/end_lng, or set GEOCODING_PROVIDER=census."
        )


class CensusGeocoder(BaseGeocoder):
    URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

    def geocode(self, location: str) -> GeoPoint:
        try:
            resp = requests.get(
                self.URL,
                params={"address": location, "benchmark": "Public_AR_Current", "format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            matches = resp.json()["result"]["addressMatches"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise GeocodingError(f"Census geocoding failed for '{location}': {exc}") from exc
        if not matches:
            raise GeocodingError(f"No Census match for '{location}'.")
        coords = matches[0]["coordinates"]
        lat, lng = float(coords["y"]), float(coords["x"])
        _check_usa(lat, lng)
        return GeoPoint(lat, lng)


class NominatimGeocoder(BaseGeocoder):
    def geocode(self, location: str) -> GeoPoint:
        base = settings.NOMINATIM_BASE_URL.rstrip("/")
        try:
            resp = requests.get(
                f"{base}/search",
                params={"q": location, "countrycodes": "us", "format": "json", "limit": 1},
                headers={"User-Agent": "fuelroute-api/1.0"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise GeocodingError(f"Nominatim geocoding failed for '{location}': {exc}") from exc
        if not data:
            raise GeocodingError(f"No Nominatim match for '{location}'.")
        lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
        _check_usa(lat, lng)
        return GeoPoint(lat, lng)


_PROVIDERS = {
    "offline": OfflineGeocoder,
    "census": CensusGeocoder,
    "nominatim": NominatimGeocoder,
}


def get_geocoder(provider: str | None = None) -> BaseGeocoder:
    key = (provider or settings.GEOCODING_PROVIDER).lower()
    if key not in _PROVIDERS:
        raise ValueError(f"Unknown geocoding provider '{key}'.")
    return _PROVIDERS[key]()

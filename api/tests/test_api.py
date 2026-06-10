"""
Integration tests for the route-with-fuel API using the offline routing provider
and a seeded demo dataset (no network). Covers happy path, validation, the
single-routing-call guarantee + caching, strategy parity, and error paths.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from fuelstations.models import FuelStation, GeocodeStatus

SF = {"start_lat": 37.7749, "start_lng": -122.4194}
DENVER = {"end_lat": 39.7392, "end_lng": -104.9903}


@override_settings(ROUTING_PROVIDER="offline", GEOCODING_PROVIDER="offline")
class RouteWithFuelAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        call_command("seed_demo", verbosity=0)

    def _body(self, **extra):
        return {**SF, **DENVER, **extra}

    def test_happy_path_returns_route_and_plan(self):
        resp = self.client.post("/api/route-with-fuel/", self._body(), format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.json()
        self.assertGreater(data["route"]["distance_miles"], 800)
        self.assertEqual(data["route"]["provider"], "offline")
        self.assertTrue(data["fuel_plan"]["stops"])
        # total_gallons == distance / mpg
        expected_gal = data["route"]["distance_miles"] / 10.0
        self.assertAlmostEqual(data["fuel_plan"]["total_gallons"], expected_gal, places=1)
        self.assertGreater(data["fuel_plan"]["total_cost"], 0)

    def test_greedy_and_dp_endpoints_agree(self):
        g = self.client.post("/api/route-with-fuel/greedy/", self._body(), format="json").json()
        d = self.client.post("/api/route-with-fuel/dp/", self._body(), format="json").json()
        self.assertAlmostEqual(
            g["fuel_plan"]["total_cost"], d["fuel_plan"]["total_cost"], places=2
        )
        self.assertEqual(g["fuel_plan"]["strategy"], "greedy")
        self.assertEqual(d["fuel_plan"]["strategy"], "dp")

    def test_single_routing_call_and_cache_hit(self):
        from routing.providers import OfflineRoutingProvider

        original = OfflineRoutingProvider.route
        with mock.patch.object(
            OfflineRoutingProvider, "route", autospec=True, side_effect=original
        ) as spy:
            r1 = self.client.post("/api/route-with-fuel/", self._body(), format="json")
            r2 = self.client.post("/api/route-with-fuel/", self._body(), format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Exactly one provider call across two identical requests (second cached).
        self.assertEqual(spy.call_count, 1)
        self.assertFalse(r1.json()["meta"]["cache_hit"])
        self.assertTrue(r2.json()["meta"]["cache_hit"])

    def test_text_geocoding_offline(self):
        resp = self.client.post(
            "/api/route-with-fuel/",
            {"start": "San Francisco, CA", "end": "Denver, CO"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_missing_locations_400(self):
        resp = self.client.post("/api/route-with-fuel/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "validation_error")

    def test_unknown_text_location_400(self):
        resp = self.client.post(
            "/api/route-with-fuel/",
            {"start": "Nowheresville, ZZ", "end": "Denver, CO"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "geocoding_failed")

    def test_outside_usa_400(self):
        resp = self.client.post(
            "/api/route-with-fuel/",
            {"start_lat": 48.8566, "start_lng": 2.3522, **DENVER},  # Paris
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "outside_usa")

    def test_empty_dataset_503(self):
        FuelStation.objects.all().delete()
        resp = self.client.post("/api/route-with-fuel/", self._body(), format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "no_dataset")

    def test_infeasible_trip_422(self):
        # Remove all but one far station so a >500-mile gap exists.
        FuelStation.objects.exclude(opis_id=900001).delete()
        FuelStation.objects.filter(opis_id=900001).update(
            latitude=37.77, longitude=-122.40, geocode_status=GeocodeStatus.OK
        )
        resp = self.client.post("/api/route-with-fuel/", self._body(), format="json")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "infeasible_trip")

    def test_short_trip_within_range(self):
        # An endpoint ~200 miles out along the demo corridor: within the 500-mile
        # range (no stop strictly required) but the plan still buys all the fuel.
        from routing.providers import OfflineRoutingProvider

        route = OfflineRoutingProvider().route(
            (SF["start_lat"], SF["start_lng"]), (DENVER["end_lat"], DENVER["end_lng"])
        )
        cum = route.cumulative
        i = next(k for k, c in enumerate(cum) if c >= 200)
        end = route.points[i]
        resp = self.client.post(
            "/api/route-with-fuel/",
            {**SF, "end_lat": end.lat, "end_lng": end.lng},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.json()
        self.assertLess(data["route"]["distance_miles"], 500)
        self.assertGreater(data["fuel_plan"]["total_cost"], 0)
        self.assertAlmostEqual(
            data["fuel_plan"]["total_gallons"],
            data["route"]["distance_miles"] / 10.0,
            places=1,
        )

    def test_health_endpoint(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertGreater(resp.json()["stations_geocoded"], 0)


@override_settings(ROUTING_PROVIDER="offline", GEOCODING_PROVIDER="offline")
class ManagementCommandTests(TestCase):
    def test_import_and_geocode_sample_csv(self):
        call_command("import_stations", "data/sample_fuel_prices.csv", "--truncate", verbosity=0)
        self.assertEqual(FuelStation.objects.count(), 15)
        # All sample cities are in the offline gazetteer -> geocodable.
        call_command("geocode_stations", verbosity=0)
        located = FuelStation.objects.filter(
            geocode_status__in=[GeocodeStatus.OK, GeocodeStatus.APPROXIMATE]
        ).count()
        self.assertEqual(located, 15)

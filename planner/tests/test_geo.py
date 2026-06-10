from django.test import SimpleTestCase

from planner.geo import (
    cumulative_distances,
    haversine_miles,
    project_point_to_route,
)


class GeoTests(SimpleTestCase):
    def test_haversine_known_distance(self):
        # SF -> LA is ~347 miles great-circle.
        d = haversine_miles(37.7749, -122.4194, 34.0522, -118.2437)
        self.assertAlmostEqual(d, 347, delta=10)

    def test_cumulative_monotonic(self):
        pts = [(39.0, -100.0), (39.0, -99.0), (39.0, -98.0)]
        cum = cumulative_distances(pts)
        self.assertEqual(cum[0], 0.0)
        self.assertLess(cum[0], cum[1])
        self.assertLess(cum[1], cum[2])

    def test_projection_onto_route(self):
        # A point just north of the midpoint projects near the middle, small offset.
        pts = [(39.0, -100.0), (39.0, -98.0)]
        cum = cumulative_distances(pts)
        along, offset = project_point_to_route((39.05, -99.0), pts, cum)
        self.assertAlmostEqual(along, cum[-1] / 2, delta=cum[-1] * 0.05)
        self.assertLess(offset, 10)

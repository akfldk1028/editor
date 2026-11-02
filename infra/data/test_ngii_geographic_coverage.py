import math
import unittest

from prepare_ngii_national_release import GEOGRAPHIC_PROBES, KNOWN_SOURCE_GAPS, geographic_presence


def owner(point):
    lon, lat = point
    return f'14/{int((lon + 180) / 360 * 16384)}/{int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 16384)}'


class GeographicCoverageTests(unittest.TestCase):
    def test_received_regions_must_include_known_inhabited_edge_neighborhoods(self):
        actual = {owner(point): 1 for point in GEOGRAPHIC_PROBES.values()}
        proof = geographic_presence(actual)
        self.assertEqual(len(proof['points']), 8)
        self.assertTrue(all(p['buildings'] > 0 for p in proof['points']))

    def test_known_source_gaps_are_recorded_not_hidden(self):
        # NGII B021 has no buildings at these probes; a release must say so instead of failing or pretending coverage.
        for missing in sorted(KNOWN_SOURCE_GAPS):
            with self.subTest(missing=missing):
                actual = {owner(point): 1 for name, point in GEOGRAPHIC_PROBES.items() if name != missing}
                self.assertIn(missing, geographic_presence(actual)['sourceCoverageGaps'])

    def test_full_received_inventory_cannot_hide_other_missing_edges(self):
        for missing in sorted(set(GEOGRAPHIC_PROBES) - KNOWN_SOURCE_GAPS):
            with self.subTest(missing=missing):
                actual = {owner(point): 1 for name, point in GEOGRAPHIC_PROBES.items() if name != missing}
                with self.assertRaisesRegex(ValueError, missing):
                    geographic_presence(actual)

    def test_neighbor_owner_counts_as_presence_without_exact_point_building(self):
        actual = {}
        for point in GEOGRAPHIC_PROBES.values():
            _, x, y = owner(point).split('/')
            actual[f'14/{int(x) + 1}/{y}'] = 2
        proof = geographic_presence(actual)
        self.assertTrue(all(p['buildings'] == 2 for p in proof['points']))

    def test_empty_and_zero_count_owners_are_not_coverage(self):
        for actual in ({}, {owner(point): 0 for point in GEOGRAPHIC_PROBES.values()}):
            with self.assertRaisesRegex(ValueError, 'geographic'):
                geographic_presence(actual)

import unittest
from queue_building_geometry import catalog_inventory, pending_regions, REVISION


class GeometryQueueTests(unittest.TestCase):
    def test_pending_is_resumable_and_preserves_all_coordinates(self):
        rows = [{'z': 14, 'x': 1, 'y': 2}, {'z': 14, 'x': 2, 'y': 2, 'meshRevision': REVISION}]
        plan = {'source': 'fixed', 'allCoordinates': ['14/1/2', '14/2/2'], 'targets': ['14/1/2']}
        self.assertEqual(pending_regions(plan, {'source': 'fixed', 'regions': rows}), ['14/1/2'])
        rows[0]['meshRevision'] = REVISION
        self.assertEqual(pending_regions(plan, {'source': 'fixed', 'regions': rows}), [])
        with self.assertRaisesRegex(ValueError, 'coverage changed'):
            pending_regions(plan, {'source': 'fixed', 'regions': rows[:1]})
        with self.assertRaisesRegex(ValueError, 'source changed'):
            pending_regions(plan, {'source': 'other', 'regions': rows})

    def test_duplicate_or_invalid_region_aborts_before_scheduling(self):
        row = {'z': 14, 'x': 1, 'y': 2}
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            catalog_inventory({'regions': [row, row]})
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            catalog_inventory({'regions': [{'z': 16, 'x': 1, 'y': 2}]})


if __name__ == '__main__':
    unittest.main()

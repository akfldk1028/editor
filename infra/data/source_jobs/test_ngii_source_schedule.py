import unittest
from ngii_source_schedule import needs_refresh, undiscovered, area_query_form

class ScheduleTests(unittest.TestCase):
    def test_area_query_supplies_polygon_instead_of_point_only_bounds(self):
        form = area_query_form(1, 2, 3, 4)
        self.assertEqual(form['wkt'], 'POLYGON((1 2,3 2,3 4,1 4,1 2))')
        self.assertEqual(form['maxx'], '3')

    def test_success_expires_and_failures_retry(self):
        self.assertFalse(needs_refresh({'state':'checked','checkedAt':100},200))
        self.assertTrue(needs_refresh({'state':'checked','checkedAt':100},4000))
        self.assertTrue(needs_refresh({'state':'checked'},200))
        self.assertTrue(needs_refresh({'state':'request_failed','checkedAt':100},200))

    def test_downloaded_sheet_removed_from_old_candidates(self):
        self.assertEqual(undiscovered([{'num':'a'},{'num':'b'}],{'a'}),[{'num':'b'}])

if __name__=='__main__':unittest.main()

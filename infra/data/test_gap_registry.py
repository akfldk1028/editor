import unittest
from gap_registry import reconcile, original_status
from audit_building_regions import incomplete_region, within_publication_bounds

class GapRegistryTests(unittest.TestCase):
    def test_original_receipt_never_claims_ground_filled_or_wrong_edition_received(self):
        receipt={'state':'received','downloadedYears':['2009']}
        self.assertEqual(original_status({'year':20091109},receipt),'same_year_received_edition_unverified')
        self.assertEqual(original_status({'year':2020},receipt),'other_edition_received_ground_pending')
    def test_historical_absence_is_not_permanent_unavailability(self):
        self.assertEqual(original_status({},None),'historical_omission_not_reverified')
        self.assertEqual(original_status({},{'state':'not_reverified'}),'historical_omission_not_reverified')
        self.assertEqual(original_status({},{'state':'now_listed_not_downloaded'}),'listed_order_pending')
    def test_service_scope_keeps_gosan_and_dokdo_excludes_eastern_outliers(self):
        self.assertTrue(within_publication_bounds('14/13976/6335'))
        self.assertTrue(within_publication_bounds('14/14193/6363'))
        self.assertFalse(within_publication_bounds('14/14203/6508'))
    def test_missing_entire_leaf_remains_partial_without_partial_mesh_entries(self):
        region={'z':14,'x':1,'y':1,'coverage':['16/4/4'],'partialCoverage':[]}
        self.assertTrue(incomplete_region(region))
        region['coverage']=[f'16/{x}/{y}' for x in range(4,8) for y in range(4,8)]
        self.assertFalse(incomplete_region(region))
    def test_absence_never_resolves_a_gap(self):
        rows=reconcile([{'id':'a','state':'source_nodata','firstObservedAt':1}],[])
        self.assertEqual(rows[0]['state'],'not_rechecked');self.assertEqual(rows[0]['previousState'],'source_nodata')
    def test_stable_identifier_preserves_first_observation(self):
        rows=reconcile([{'id':'a','state':'source_nodata','firstObservedAt':1}],[{'id':'a','state':'source_nodata','evidenceSHA256':'new'}])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['firstObservedAt'],1);self.assertEqual(rows[0]['evidenceSHA256'],'new')

if __name__=='__main__':unittest.main()

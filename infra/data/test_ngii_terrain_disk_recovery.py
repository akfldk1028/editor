import unittest
from unittest.mock import patch
import numpy as np
from ngii_terrain_candidate import supported_tin
from ngii_terrain_disk_recovery import recover_disk_queries


class DiskRecoveryTests(unittest.TestCase):
    def test_disk_resolves_where_square_halo_exceeds_same_budget(self):
        rng = np.random.default_rng(71)
        xy = rng.uniform(-2000, 2000, (3000, 2))
        p = np.column_stack([xy, xy[:, 0]/20+xy[:, 1]/30])
        self.assertGreater(len(p), 2500)
        actual, resolved, audit = recover_disk_queries(p, [[0,0]], (-2000,-2000,2000,2000), point_budget=2500)
        self.assertTrue(resolved[0])
        self.assertLess(audit['sourceCounts'][0], 2500)
        self.assertAlmostEqual(actual[0], 0, places=9)

    def test_disk_matches_global_with_far_dense_sources_and_order(self):
        rng = np.random.default_rng(913)
        xy = rng.uniform(-3000, 3000, (5000, 2))
        p = np.column_stack([xy, np.sin(xy[:, 0]/100)+xy[:, 1]/20])
        q = np.array([[0, 0], [5, 5], [-20, 10]])
        expected, _ = supported_tin(p, q)
        actual, resolved, audit = recover_disk_queries(p, q, (-4000,-4000,4000,4000))
        np.testing.assert_allclose(actual, expected, atol=1e-9)
        self.assertTrue(resolved.all())
        reverse, _, _ = recover_disk_queries(p[::-1], q[::-1], (-4000,-4000,4000,4000))
        np.testing.assert_array_equal(actual, reverse[::-1])
        self.assertEqual(audit['budgetLimitedCells'], 0)

    def test_budget_or_incomplete_halo_never_becomes_confirmed_nodata(self):
        p = np.array([[0,0,0],[1,0,1],[0,1,1]])
        with patch('ngii_terrain_disk_recovery.supported_tin', side_effect=AssertionError('over budget')):
            _, ok, _ = recover_disk_queries(p, [[0,0]], (-3000,-3000,3000,3000), point_budget=2)
            self.assertFalse(ok[0])
            _, ok, _ = recover_disk_queries(p, [[0,0]], (-100,-100,100,100))
            self.assertFalse(ok[0])

    def test_conflicts_outside_hull_and_zero_preserve_source_policy(self):
        p = np.array([[0,0,0],[100,0,0],[0,100,0],[3000,3000,10]])
        actual, ok, _ = recover_disk_queries(p, [[10,10],[500,500]], (-4000,-4000,4000,4000))
        self.assertTrue(ok.all()); self.assertEqual(actual[0], 0); self.assertTrue(np.isnan(actual[1]))
        conflicting = np.vstack([p, [0,0,10]])
        actual, ok, _ = recover_disk_queries(conflicting, [[10,10]], (-4000,-4000,4000,4000))
        self.assertTrue(ok[0]); self.assertTrue(np.isnan(actual[0]))


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import patch
import numpy as np
from shapely.geometry import LineString, Point
from ngii_terrain_candidate import elevation_points, supported_tin, elevation_layer, adaptive_tin, centered_tin, CENTERED_RECIPE


class TerrainCandidateTests(unittest.TestCase):
    def test_centered_kernel_keeps_absolute_coordinates_out_of_qhull(self):
        xy=np.array([[0,0],[100,0],[0,100],[100,100]],dtype=float)
        points=np.column_stack([xy+[184000,580000],[0,10,20,30]])
        query=np.array([[184025,580025],[188000,584000]])
        values,audit=centered_tin(points,query,(184000,580000,185000,581000))
        self.assertAlmostEqual(values[0],7.5)
        self.assertTrue(np.isnan(values[1]))
        self.assertEqual(audit['coordinateOrigin5186'],[184000,580000])
        self.assertEqual(audit['kernel'],CENTERED_RECIPE)

    def test_single_tin_matches_adaptive_and_preserves_boundary_nodata(self):
        rng=np.random.default_rng(84)
        xy=rng.uniform(-500,1500,(1200,2))
        points=np.column_stack([xy,0.2*xy[:,0]+0.1*xy[:,1]+np.sin(xy[:,0]/25)])
        query=np.vstack([rng.uniform(0,1000,(100,2)),[[3000,3000]]])
        old,_=adaptive_tin(points,query)
        fast,audit=adaptive_tin(points,query,read_bounds=(-2000,-2000,3000,3000))
        np.testing.assert_array_equal(np.isfinite(fast),np.isfinite(old))
        np.testing.assert_allclose(fast,old,atol=1e-10,equal_nan=True)
        reverse,_=adaptive_tin(points[::-1],query[::-1],read_bounds=(-2000,-2000,3000,3000))
        np.testing.assert_array_equal(fast,reverse[::-1])
        self.assertEqual(audit['triangulationMode'],'single-bounded-patch')
        edge,_=adaptive_tin([[0,0,1],[100,0,1],[0,100,1]],np.array([[1,1]]),read_bounds=(0,0,100,100))
        self.assertTrue(np.isnan(edge[0]))

    def test_outside_hull_queries_skip_repeated_local_triangulation(self):
        points=np.array([[0,0,1],[100,0,1],[0,100,1]])
        with patch('ngii_terrain_candidate.supported_tin',side_effect=AssertionError('unnecessary TIN')):
            values,_=adaptive_tin(points,np.array([[150,150],[3000,3000]]))
        self.assertTrue(np.isnan(values).all())

    def test_split_member_suffix_is_not_an_absent_contour_layer(self):
        self.assertEqual(elevation_layer('N3L_F0010000/N3L_F0010000_02.shp'), 'N3L_F0010000')
        self.assertIsNone(elevation_layer('N3L_F0010000_other.shp'))

    def test_source_fields_preserve_zero_and_reject_absent_height(self):
        points, reason = elevation_points({'CONT': 0}, LineString([(0, 0), (10, 0)]), 'N3L_F0010000', lambda x, y: (x, y))
        self.assertIsNone(reason)
        self.assertTrue(np.all(points[:, 2] == 0))
        self.assertEqual(elevation_points({}, Point(0, 0), 'N3P_F0020000', lambda x, y: (x, y))[1], 'missing-elevation')

    def test_native_prefilter_only_skips_vertices_already_outside_requested_halo(self):
        line=LineString([(-10000,0),(0,0),(10,0),(10000,0)])
        points,reason=elevation_points({'CONT':7},line,'N3L_F0010000',lambda x,y:(x+100,y),(-5,-5,15,5))
        self.assertIsNone(reason)
        np.testing.assert_array_equal(points,[[100,0,7],[110,0,7]])

    def test_linear_supported_surface_and_outside_hull(self):
        points = [[0, 0, 0], [100, 0, 100], [0, 100, 100], [100, 100, 200]]
        values, _ = supported_tin(points, np.array([[25, 25], [200, 200]]))
        self.assertAlmostEqual(values[0], 50)
        self.assertTrue(np.isnan(values[1]))

    def test_conflicts_and_large_triangles_are_not_invented_support(self):
        values, audit = supported_tin([[0, 0, 10], [0, 0, 20], [100, 0, 10], [0, 100, 10]], np.array([[20, 20]]))
        self.assertTrue(np.isnan(values[0])); self.assertEqual(audit['conflictingCoordinates'], 1)
        values, _ = supported_tin([[0, 0, 10], [10000, 0, 10], [0, 10000, 10]], np.array([[10, 10]]))
        self.assertTrue(np.isnan(values[0]))

    def test_adaptive_halo_preserves_the_same_surface_for_different_query_order(self):
        x, y = np.meshgrid(np.arange(-200, 401, 25), np.arange(-200, 401, 25))
        points = np.column_stack([x.ravel(), y.ravel(), (x+y).ravel()])
        query = np.array([[99, 50], [101, 50], [250, 250]])
        first, audit = adaptive_tin(points, query)
        reverse, _ = adaptive_tin(points, query[::-1])
        np.testing.assert_allclose(first, [149, 151, 500])
        np.testing.assert_array_equal(first, reverse[::-1])
        self.assertEqual(audit['budgetLimitedCells'], 0)


if __name__ == '__main__':
    unittest.main()

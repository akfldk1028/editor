import unittest
from ngii_sheet_match import select_sheet, elevation_kind

class SheetMatchTests(unittest.TestCase):
    def row(self, **changes):
        return dict(dict(sheet='34703039', year='20260313', scale='5000', projection='GRS80', minx=1, miny=2, maxx=3, maxy=4), **changes)

    def test_catalogue_date_does_not_drop_older_original(self):
        row=self.row()
        self.assertEqual(select_sheet([row], '34703039', '2025'), row)

    def test_conflicting_bounds_rejected(self):
        with self.assertRaises(ValueError):
            select_sheet([self.row(), self.row(minx=5)], '34703039', '2025')

    def test_serialization_roundoff_is_same_spatial_sheet(self):
        first=self.row(minx=932534.6726, maxx=932980.1332)
        second=dict(first,minx=932534.6726000002)
        self.assertEqual(select_sheet([first,second], '34703039', '2025'), first)

    def test_wrong_sheet_and_coarse_data_not_selected(self):
        self.assertIsNone(select_sheet([self.row(sheet='11111111'), self.row(scale='25000')], '34703039', '2025'))

    def test_both_precise_and_continuous_layer_prefixes(self):
        self.assertEqual(elevation_kind('folder/N1L_F0010000.shp'), 'contour')
        self.assertEqual(elevation_kind('N1P_F0020000.shp'), 'spot')
        self.assertEqual(elevation_kind('N3L_F0010000.shp'), 'contour')
        self.assertIsNone(elevation_kind('N1L_F0030000.shp'))

if __name__ == '__main__':
    unittest.main()

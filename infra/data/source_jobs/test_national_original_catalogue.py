import unittest
import national_original_catalogue as subject


class NationalOriginalCatalogueTests(unittest.TestCase):
    def test_municipality_search_does_not_fall_back_to_lower_left_point(self):
        form = subject.search_form(dict(geom='1,2,3,4',sigunguCodePck='11110'), '0')
        self.assertEqual(form['sigu'], '11110')

    def test_provider_combined_province_splits_without_changing_order_codes(self):
        self.assertEqual(subject.province_code('12', '12210'), '29')
        self.assertEqual(subject.province_code('12', '12190'), '46')
        self.assertEqual(subject.province_code('45', '45111'), '52')

    def test_selects_precise_downloadable_variant_and_excludes_existing_sheet(self):
        rows = [dict(num='a', scale=5000, fileExt='ngi'),
                dict(num='a', scale=5000, fileExt='dxf'),
                dict(num='b', scale=25000, fileExt='zip'),
                dict(num='c', scale=1000, fileExt='zip')]
        self.assertEqual(subject.select_candidates(rows, {'c'}), [rows[1]])


if __name__ == '__main__':
    unittest.main()

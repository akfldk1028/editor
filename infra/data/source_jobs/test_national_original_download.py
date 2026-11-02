import unittest
from national_original_download import choose_files


class DownloadSelectionTests(unittest.TestCase):
    def test_ngi_keeps_required_nda_attribute_companion(self):
        rows=[dict(name='map_12345678_2025_a.'+ext,bytes=5) for ext in ['ngi','nda','xml']]
        rows.append(dict(name='12345678_2025_a.xlsx',bytes=5))
        self.assertEqual({r['name'] for r in choose_files(rows,{'12345678'},set())},{r['name'] for r in rows})

    def test_selects_one_geometry_with_metadata_and_skips_existing_sheets(self):
        rows = [dict(name='map_12345678_2025_a.'+ext, bytes=5) for ext in ['zip','dxf','xml']]
        rows += [dict(name='map_87654321_2025_a.zip',bytes=5)]
        chosen = choose_files(rows, {'12345678','87654321'}, {'87654321'})
        self.assertEqual([r['name'] for r in chosen], ['map_12345678_2025_a.zip','map_12345678_2025_a.xml'])


if __name__ == '__main__':unittest.main()

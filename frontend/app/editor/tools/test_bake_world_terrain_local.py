import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

spec = importlib.util.spec_from_file_location('bake', Path(__file__).with_name('bake-world-terrain-local.py'))
bake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bake)


class GridTests(unittest.TestCase):
    def test_catalog_publication_retries_a_temporary_windows_reader_lock(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'catalog.json'
            target.write_text('{"old":true}')
            replace = bake.os.replace
            calls = 0
            def locked_then_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls < 3:
                    self.assertEqual(target.read_text(), '{"old":true}')
                    raise PermissionError('reader holds file')
                replace(source, destination)
            with patch.object(bake.os, 'replace', locked_then_replace), patch.object(bake.time, 'sleep'):
                bake.atomic_json(target, {'new': True})
            self.assertEqual(target.read_text(), '{"new":true}')
            self.assertEqual(calls, 3)

    def test_grid_matches_cesium_north_to_south_and_shared_edges(self):
        a = bake.grid_points(17, 223533, 38180)
        b = bake.grid_points(17, 223534, 38180)
        self.assertEqual(len(a), 1089)
        self.assertGreater(a[0][1], a[-1][1])
        self.assertEqual([a[i * 33 + 32] for i in range(33)], [b[i * 33] for i in range(33)])
        bounds = [a[0][0], a[-1][1], a[-1][0], a[0][1]]
        self.assertEqual(list(bake.tile_keys(bounds, 17, 17)), [(17, 223533, 38180)])

    def test_missing_samples_never_become_complete_tiles(self):
        for bad in (None, float('nan'), -9999, True):
            self.assertFalse(bake.valid_tile({'size': 33, 'heights': [bad] + [10] * 1088}))
        self.assertTrue(bake.valid_tile({'size': 33, 'heights': [10.25] * 1089}))

    def test_resume_rejects_changed_dem_and_identifies_legacy_tiles(self):
        with self.assertRaises(ValueError):
            bake.verify_resume_source({'dataset': {'vrt_sha256': 'old'}}, {'vrt_sha256': 'new'})
        self.assertFalse(bake.verify_resume_source({'dataset': {'vrt_sha256': 'same'}}, {'vrt_sha256': 'same'}))
        self.assertTrue(bake.verify_resume_source({}, {'vrt_sha256': 'new'}))


if __name__ == '__main__':
    unittest.main()

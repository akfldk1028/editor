import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
import importlib.util
import numpy as np
import rasterio
from rasterio.transform import from_origin

spec = importlib.util.spec_from_file_location('sampler', Path(__file__).with_name('sample-building-dem.py'))
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)


class DEMTest(unittest.TestCase):
    def test_measured_interpolation_nodata_and_outside(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dem.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=3, height=3, count=1,
                               dtype='float32', crs='EPSG:4326', nodata=-9999,
                               transform=from_origin(127, 38, .01, .01)) as dst:
                dst.write(np.array([[10, 20, -9999], [30, 40, -9999], [-9999, -9999, -9999]], dtype='float32'), 1)
            result = sampler.sample(path, [[127.01, 37.99], [127.025, 37.975], [128, 37], [127.005, 37.995]])
            self.assertEqual(result['heights'], [25, None, None, 10])
            self.assertEqual(result['source']['crs'], 'EPSG:4326')

    def test_source_changed_during_sampling_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dem.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=1, height=1, count=1,
                               dtype='float32', crs='EPSG:4326',
                               transform=from_origin(127, 38, .01, .01)) as dst:
                dst.write(np.array([[10]], dtype='float32'), 1)
            with patch.object(sampler, 'source_signature', side_effect=['before', 'after']):
                with self.assertRaisesRegex(ValueError, 'DEM source changed'):
                    sampler.sample(path, [])


if __name__ == '__main__':
    unittest.main()

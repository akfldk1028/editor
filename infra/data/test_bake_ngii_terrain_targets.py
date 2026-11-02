import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
from bake_ngii_terrain_targets import merge_precision
from ngii_terrain_candidate import sha


class LayeringTests(unittest.TestCase):
    def test_precision_nodata_preserves_base_and_zero_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = dict(driver='GTiff', crs='EPSG:5186', transform=from_origin(0,10,5,5), width=2,height=2,count=1,dtype='float32',nodata=-9999)
            for name, data in [('base',[[10,20],[30,40]]), ('precision',[[0,-9999],[-9999,80]])]:
                with rasterio.open(root/f'{name}.tif','w',**profile) as target:
                    target.write(np.array(data,dtype='float32'),1)
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps({'sources':[{'path':'precision.tif','sha256':sha((root/'precision.tif').read_bytes())}]}))
            config=root/'active.json'; config.write_text(json.dumps({'manifest':{'path':'manifest.json','sha256':sha(manifest.read_bytes())},'sources':['precision.tif']}))
            with patch('bake_ngii_terrain_targets.reserve'):
                receipt = merge_precision(root/'base.tif',root/'layered.tif',config,sha(config.read_bytes()))
                self.assertEqual(merge_precision(root/'base.tif',root/'layered.tif',config,sha(config.read_bytes())), receipt)
            with rasterio.open(root/'layered.tif') as result:
                np.testing.assert_array_equal(result.read(1),[[0,20],[30,80]])


if __name__=='__main__':unittest.main()

import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


worker = load('native_worker', 'ngii-native-height-worker.py')
legacy = load('legacy_sampler', 'sample-building-dem.py')


class NativeTests(unittest.TestCase):
    def test_fake_raster_groups_reads_and_preserves_containing_nodata(self):
        from types import SimpleNamespace
        from affine import Affine
        data=np.ma.array(np.full((520,520),50,dtype='float32'),mask=False)
        data.mask[4,4]=True
        calls=[]
        def read(band,window,masked):
            calls.append(window)
            return data[int(window.row_off):int(window.row_off+window.height),int(window.col_off):int(window.col_off+window.width)]
        sampler=worker.NativeSampler.__new__(worker.NativeSampler)
        sampler.verify=lambda **kwargs:None
        sampler.src=SimpleNamespace(width=520,height=520,transform=Affine.identity(),read=read)
        sampler.transformer=SimpleNamespace(transform=lambda x,y:(x*10,y*10))
        self.assertEqual(sampler.sample([[.41,.41],[.45,.45],[.51,.41],[51.21,51.21]]),[None,None,50,50])
        self.assertEqual(len(calls),2)

    def test_jsonl_ready_batch_close_and_pin_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=self.raster(Path(folder))
            digest=worker.hashlib.sha256(path.read_bytes()).hexdigest()
            command=[sys.executable,str(Path(__file__).with_name('ngii-native-height-worker.py')),'--vrt',str(path),'--source-vrt-sha256',digest]
            result=subprocess.run(command,input='{"id":1,"points":[[0,0]]}\n{"id":2,"op":"close"}\n',text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            ready,batch,closed=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(ready['type'],'ready');self.assertEqual(batch['heights'],[None])
            self.assertEqual(closed['sourceVrtSHA256'],digest)
            command[-1]='bad'
            result=subprocess.run(command,input='',text=True,capture_output=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(json.loads(result.stdout)['type'],'error')

    def raster(self, root, crs='EPSG:4326'):
        path = root/'source.tif'
        rng = np.random.default_rng(123)
        data = (rng.random((520, 520))*600).astype('float32')
        data[4, 4] = -9999; data[510:514, 510] = np.nan
        transform = from_origin(126, 38, .0001, .0001) if crs == 'EPSG:4326' else from_origin(200000, 600000, 5, 5)
        with rasterio.open(path, 'w', driver='GTiff', width=520, height=520, count=1,
                           dtype='float32', crs=crs, transform=transform, nodata=-9999) as dst:
            dst.write(data, 1)
        return path, transform

    def test_seeded_bilinear_nodata_edges_block_halo_and_crs_match_existing_sampler(self):
        with tempfile.TemporaryDirectory() as folder:
            for crs in ('EPSG:4326', 'EPSG:5186'):
                path, transform = self.raster(Path(folder), crs)
                rng = np.random.default_rng(44)
                cells = list(rng.random((2000, 2))*520)
                cells += [(0,0),(.01,.01),(519.99,519.99),(4.1,4.1),(4.7,4.7),(511.9,511.9),(512.1,512.1),(-1,-1)]
                convert = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
                points = [[float(v) for v in convert.transform(*(transform*tuple(cell)))] for cell in cells]
                sampler = worker.NativeSampler(path)
                try:
                    expected = legacy.sample(path, points)['heights']
                    self.assertEqual(sampler.sample(points), expected)
                    self.assertEqual(sampler.sample([]), [])
                    self.assertEqual(sampler.fingerprint['sourceFilesSHA256'], worker.signature(worker.source_stamps(path)))
                finally:
                    sampler.close()

    def test_source_change_pin_and_invalid_coordinate_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.raster(Path(folder))
            with self.assertRaisesRegex(ValueError, 'Pinned source'):
                worker.NativeSampler(path, {'sourceVrtSHA256':'bad'})
            sampler = worker.NativeSampler(path)
            with self.assertRaisesRegex(ValueError, 'Invalid coordinate'):
                sampler.sample([[float('nan'),0]])
            import os
            stamp=path.stat();os.utime(path, ns=(stamp.st_atime_ns,stamp.st_mtime_ns+10000000))
            with self.assertRaisesRegex(ValueError, 'changed'):sampler.sample([[126,38]])
            with self.assertRaisesRegex(ValueError, 'changed'):sampler.close()


if __name__ == '__main__':
    unittest.main()

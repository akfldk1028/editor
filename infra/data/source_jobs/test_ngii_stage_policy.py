import tempfile
import unittest
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import numpy as np
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
from ngii_stage_policy import should_retry, may_stage, supported_values, acquire_stage_lock,load_source_list,attribute_companion_arrived


class StagePolicyTests(unittest.TestCase):
    def test_ngi_companion_arrival_retries_missing_file_but_not_invalid_hash(self):
        from pyproj import Transformer
        from test_ngii_ngi import layer
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'files').mkdir();source=root/'files/original_12345678_2026_test.ngi'
            source.write_text(layer('F0010000','$RECORD 1\nLINESTRING\n2\n200000 450000\n200100 450000\n$RECORD 2\nLINESTRING\n2\n200000 450100\n200100 450100'),encoding='cp949')
            source.with_suffix('.ngi.receipt.json').write_text(json.dumps({'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}))
            x,y=Transformer.from_crs(5186,5179,always_xy=True).transform([200000,200100],[450000,450100])
            (root/'test-catalogue.json').write_text(json.dumps([{'sheet':'12345678','year':'2026','projection':'GRS80','scale':1000,'minx':min(x),'maxx':max(x),'miny':min(y),'maxy':max(y)}]))
            (root/'national-gap-exact-points.json').write_text('[]')
            env=dict(os.environ,NGII_ORIGINAL_ROOT=str(root),NGII_DEM_ROOT=str(root))
            command=[sys.executable,str(Path(__file__).with_name('stage-ngii-dxf-ground.py')),'--refine-existing','--once']
            subprocess.run(command,env=env,check=True,capture_output=True,timeout=30)
            report=root/'terrain-stage-status.json';failed=json.loads(report.read_text())['results'][source.name]
            self.assertEqual(failed['errorType'],'FileNotFoundError')
            self.assertFalse(attribute_companion_arrived(source.name,failed,root))
            nda=source.with_suffix('.nda');nda.write_text(layer('F0010000','$RECORD 1\n10\n$RECORD 2\n20','ATTRIB("등고수치",NUMERIC,9,2,TRUE)'),encoding='cp949')
            receipt=nda.with_suffix('.nda.receipt.json');receipt.write_text(json.dumps({'sha256':hashlib.sha256(nda.read_bytes()).hexdigest()}))
            self.assertTrue(attribute_companion_arrived(source.name,failed,root))
            subprocess.run(command,env=env,check=True,capture_output=True,timeout=30)
            staged=json.loads(report.read_text())['results'][source.name];self.assertEqual(staged['state'],'staged',staged)
            report.write_text(json.dumps({'results':{source.name:failed}}));receipt.write_text(json.dumps({'sha256':'wrong'}))
            subprocess.run(command,env=env,check=True,capture_output=True,timeout=30)
            rejected=json.loads(report.read_text())['results'][source.name]
            self.assertEqual(rejected['errorType'],'ValueError')
            self.assertFalse(attribute_companion_arrived(source.name,rejected,root))

    def test_target_source_list_refuses_unknown_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'files').mkdir();listing=root/'sources.json'
            for names in [['missing.dxf'],['../outside.dxf'],['a/b.dxf'],['C:\\outside.dxf'],[]]:
                listing.write_text(json.dumps(names))
                with self.assertRaises(ValueError):load_source_list(listing,root)
            (root/'files/a.dxf').write_bytes(b'source');(root/'files/a.dxf.receipt.json').write_text('{}')
            listing.write_text('["a.dxf"]');self.assertEqual(load_source_list(listing,root),{'a.dxf'})
    def test_real_stager_retries_no_missing_source_only_with_opt_in(self):
        import ezdxf
        import rasterio
        from pyproj import Transformer
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'files').mkdir()
            source = root / 'files' / 'original_12345678_2026_test.dxf'
            doc = ezdxf.new()
            for north, z in [(450000, 10), (450100, 20)]:
                doc.modelspace().add_polyline2d([(200000, north), (200100, north)],
                    dxfattribs={'layer': 'F0010000', 'elevation': (0,0,z)})
            doc.saveas(source)
            source.with_suffix('.dxf.receipt.json').write_text(json.dumps({'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}))
            x, y = Transformer.from_crs(5186, 5179, always_xy=True).transform([200000, 200100], [450000, 450100])
            catalogue=json.dumps([{'sheet': '12345678', 'year': '2026',
                'projection': 'GRS80', 'scale': 1000, 'minx': min(x), 'maxx': max(x), 'miny': min(y), 'maxy': max(y)}])
            (root / 'download-status.json').write_text(json.dumps({'state': 'finished'}))
            (root / 'national-gap-exact-points.json').write_text('[]')
            env = dict(os.environ, NGII_ORIGINAL_ROOT=str(root), NGII_DEM_ROOT=str(root))
            command = [sys.executable, str(Path(__file__).with_name('stage-ngii-dxf-ground.py'))]
            subprocess.run(command, env=env, check=True, capture_output=True, timeout=30)
            report = json.loads((root / 'terrain-stage-status.json').read_text())
            self.assertEqual(report['results'][source.name]['state'], 'no_precise_catalogue_match')
            (root / 'test-catalogue.json').write_text(catalogue)
            (root / 'download-status.json').write_text(json.dumps({'state': 'running'}))
            subprocess.run(command + ['--refine-existing', '--once'], env=env, check=True, capture_output=True, timeout=30)
            report = json.loads((root / 'terrain-stage-status.json').read_text())
            item = report['results'][source.name]
            self.assertEqual(item['state'], 'staged', item)
            self.assertEqual(item['verifiedKeys'], [])
            self.assertEqual(report['verifiedMissingRecords'], 0)
            self.assertEqual(report['precisionStagedPatches'], 1)
            self.assertEqual(report['state'], 'finished')
            self.assertEqual(item['sourceSHA256'], hashlib.sha256(source.read_bytes()).hexdigest())
            with rasterio.open(item['file']) as raster:
                self.assertGreater(raster.read(1, masked=True).count(), 0)
            self.assertEqual(item['contours'],2)
            new_path=Path(item['file']); new_stamp=new_path.stat().st_mtime_ns
            legacy=root/'terrain-staging'/'legacy-frozen.tif';legacy.write_bytes(b'old frozen raster')
            item.pop('parserVersion');item['file']=str(legacy);item['contours']=0;item['sourceVertices']=3
            unrelated={'state':'staged','file':'unchanged.tif','sourceSHA256':'old','contours':0}
            report['results']['unselected.dxf']=unrelated
            (root/'terrain-stage-status.json').write_text(json.dumps(report))
            listing=root/'source-list.json';listing.write_text(json.dumps([source.name]))
            subprocess.run(command+['--refine-existing','--once','--source-list',str(listing)],env=env,check=True,capture_output=True,timeout=30)
            refreshed=json.loads((root/'terrain-stage-status.json').read_text())['results']
            self.assertEqual(refreshed['unselected.dxf'],unrelated)
            reparsed=refreshed[source.name]
            self.assertEqual(reparsed['contours'],2)
            self.assertEqual(reparsed['parserVersion'],'dxf-polyline-v2')
            self.assertEqual(reparsed['supersedes']['file'],str(legacy))
            self.assertEqual(reparsed['sourceSHA256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(legacy.read_bytes(),b'old frozen raster')
            self.assertEqual(new_path.stat().st_mtime_ns,new_stamp)

    def test_missing_point_gates_are_bypassed_only_for_precision_mode(self):
        self.assertFalse(may_stage(0, False))
        self.assertTrue(may_stage(0, True))
        self.assertTrue(may_stage(1, False))

    def test_retry_only_cached_missing_point_exclusions(self):
        for state in ['no_known_missing_point_in_sheet', 'no_missing_point_supported', 'no_precise_catalogue_match']:
            self.assertTrue(should_retry(state, True))
            self.assertFalse(should_retry(state, False))
        for state in ['staged', 'ambiguous_crs_rejected', 'conflicting_elevations_rejected', 'failed']:
            self.assertFalse(should_retry(state, True))

    def test_precision_keeps_convex_hull_and_1000m_support_limit(self):
        xy = np.array([[0, 0], [4000, 0], [0, 4000]])
        values = supported_values(LinearNDInterpolator(xy, [10, 20, 30]), cKDTree(xy),
                                  np.array([[5, 5], [1100, 1100], [-5, -5]]))
        self.assertTrue(np.isfinite(values[0]))
        self.assertTrue(np.isnan(values[1]))
        self.assertTrue(np.isnan(values[2]))

    def test_lock_excludes_another_writer_and_is_released_on_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'terrain-stage.lock'
            first = acquire_stage_lock(path)
            try:
                with self.assertRaises(OSError):
                    acquire_stage_lock(path)
            finally:
                first.close()
            acquire_stage_lock(path).close()


if __name__ == '__main__':
    unittest.main()

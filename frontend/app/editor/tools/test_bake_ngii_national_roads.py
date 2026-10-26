import importlib.util
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import shapely
from PIL import Image
from pmtiles.reader import Reader
from pyproj import Transformer
from shapely.geometry import box, Polygon
from shapely.ops import transform

spec=importlib.util.spec_from_file_location('national_roads',Path(__file__).with_name('bake-ngii-national-roads.py'))
road=importlib.util.module_from_spec(spec);spec.loader.exec_module(road)


class NationalRoadTests(unittest.TestCase):
    def test_batch_projection_and_mask_equal_scalar_reference_with_repair_audit(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(road.common,'space'):
            root=Path(tmp);bounds=[126.97,37.56,126.99,37.58];grid=road.layout(bounds)
            x,y=Transformer.from_crs(4326,5179,always_xy=True).transform(126.978,37.567)
            geometries=[box(x-100,y-100,x+100,y+100).difference(box(x-30,y-30,x+30,y+30)),
                        Polygon([(x,y),(x+60,y+60),(x,y+60),(x+60,y),(x,y)])]
            rows=[dict(wkb=shapely.to_wkb(g),fid=i,UFID=str(i)) for i,g in enumerate(geometries)]
            project=Transformer.from_crs(5179,3857,always_xy=True).transform
            coverage=box(*Transformer.from_crs(4326,3857,always_xy=True).transform_bounds(*bounds))
            batch_audit=[];batch=road.project_road_batch(rows,'wkb','fid',{'sourceId':'same'},coverage,project,batch_audit.append)
            scalar=[];scalar_audit=[]
            for i,g in enumerate(geometries):
                fixed,audit=road.repair_road_geometry(g)
                if audit:scalar_audit.append(dict(sourceId='same',FID=i,UFID=str(i),status='repaired',**audit))
                scalar.append(transform(project,fixed).intersection(coverage))
            self.assertEqual(batch_audit,scalar_audit)
            a=road.Mask(root/'a',grid,65536);b=road.Mask(root/'b',grid,65536)
            try:
                for g in scalar:a.burn(g)
                b.burn_batch(batch);a.flush();b.flush()
                self.assertEqual(road.common.sha(a.path),road.common.sha(b.path))
            finally:a.close();b.close()

    def test_invalid_polygon_repair_reports_area_and_holes_and_rejects_collapsed_residue(self):
        geometry=Polygon([(0,0),(2,2),(0,2),(2,0),(0,0)])
        result,audit=road.repair_road_geometry(geometry)
        self.assertTrue(result.is_valid);self.assertEqual(result.area,2)
        self.assertEqual(audit['originalAreaM2'],0);self.assertEqual(audit['areaDeltaM2'],2)
        self.assertEqual(audit['parts'],2)
        valid=box(0,0,5,5).difference(box(1,1,2,2))
        restored,audit=road.repair_road_geometry(valid)
        self.assertIsNone(audit);self.assertEqual(len(restored.interiors),1)
        for invalid in [None,Polygon([(0,0),(1,0),(2,0),(0,0)])]:
            with self.assertRaises(road.RoadGeometryError):road.repair_road_geometry(invalid)
    def item(self,root):
        source=root/'source.zip';source.write_bytes(b'unchanged official source')
        receipt=root/'source.receipt.json';receipt.write_text('{}')
        stamp=source.stat()
        return dict(path=str(source),receipt=str(receipt),receiptSHA256=road.common.sha(receipt),
                    sha256=road.common.sha(source),bytes=stamp.st_size,mtimeNs=str(stamp.st_mtime_ns),
                    sourceId='a'*64,features=2,aliases=['11'])

    def test_mask_bounded_lru_holes_and_idempotent_overlap(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(road.common,'space'):
            grid=road.layout([126.9,37.5,127.1,37.7]);mask=road.Mask(Path(tmp)/'mask',grid,cache_bytes=65536)
            try:
                x,y=grid['x0'],grid['y0'];w,s,e,n=road.common.tile_bounds(12,x,y)
                dx=(e-w)/256;dy=(n-s)/256
                geometry=box(w+10*dx,s+10*dy,w+110*dx,s+110*dy).difference(box(w+30*dx,s+30*dy,w+90*dx,s+90*dy))
                mask.burn(geometry);mask.burn(geometry)
                mask.block((x+1,y));self.assertLessEqual(len(mask.cache),1)
                mask.flush();a=mask.read((x,y))
                self.assertEqual(int((a==255).sum()),6400)
                self.assertEqual(mask.path.stat().st_size,grid['width']*grid['height'])
            finally:mask.close()

    def test_interrupted_source_replays_or_without_duplicate_coverage_and_archive_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(road.common,'space'),patch.object(road.common,'source'):
            root=Path(tmp);item=self.item(root);bounds=[126.975,37.564,126.982,37.570]
            project=Transformer.from_crs(4326,3857,always_xy=True)
            x,y=project.transform(126.978,37.567);geometry=box(x-100,y-100,x+100,y+100)
            def interrupted(item,coverage):
                yield geometry
                raise OSError('simulated stop')
            with self.assertRaisesRegex(OSError,'simulated'):road.run([item],root/'resume',bounds,iterator=interrupted)
            checkpoint=next((root/'resume').glob('*/checkpoint.json'))
            self.assertEqual(json.loads(checkpoint.read_bytes())['completedSources'],[])
            stream=lambda item,coverage:iter([geometry])
            original_compress=gzip.compress
            with patch('gzip.compress',lambda data:original_compress(data,mtime=123)):
                resumed=road.run([item],root/'resume',bounds,iterator=stream)
            with patch('gzip.compress',lambda data:original_compress(data,mtime=999)):
                uninterrupted=road.run([item],root/'fresh',bounds,iterator=stream)
            self.assertEqual(resumed['sha256'],uninterrupted['sha256'])
            self.assertEqual(resumed['observedFeatures'],1)
            archive=Path(resumed['archive']);stamp=archive.stat().st_mtime_ns
            self.assertEqual(road.run([item],root/'resume',bounds,iterator=stream),resumed)
            self.assertEqual(archive.stat().st_mtime_ns,stamp)
            data=archive.read_bytes();reader=Reader(lambda o,n:data[o:o+n])
            self.assertIsNone(reader.get(12,0,0))
            self.assertIsNotNone(reader.get(0,0,0))
            self.assertTrue(resumed['sampleOnly']);self.assertFalse(resumed['completeCoverage'])
            Path(item['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'source changed'):road.run([item],root/'resume',bounds,iterator=stream)

    def test_incomplete_input_cannot_claim_national_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'Incomplete national'):road.run([],tmp,complete=True)

    def test_plan_deduplicates_alias_by_archive_sha_not_province_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'national-continuous-source-inventory.json').write_text(json.dumps(dict(productCode='B021',scale=5000,year=2024,format='SHP',crs='EPSG:5179',canonicalLayers=['N3A_A0010000'])))
            for area in sorted(road.AREAS):
                rows=[]
                for variant in range(2 if area=='12' else 1):
                    for alias in range(2 if area=='12' else 1):
                        path=root/f'{area}-{variant}-{alias}.zip';path.write_bytes(f'{area}-{variant}'.encode())
                        receipt={'sha256':road.common.sha(path),'provider':'NGII','format':'SHP','requestedScale':5000,'requestedYear':2024}
                        Path(str(path)+'.receipt.json').write_text(json.dumps(receipt))
                        rows.append(dict(path=path.name,shp='N3A_A0010000.shp',features=123))
                (root/f'{area}-source-inventory.json').write_text(json.dumps(rows))
            items=road.plan_sources(root)
            self.assertEqual(len(items),17)
            self.assertEqual(len([item for item in items if '12' in item['aliases']]),2)
            self.assertEqual(len({item['sourceId'] for item in items}),17)
            (root/'11-source-inventory.json').unlink()
            with self.assertRaisesRegex(ValueError,'Incomplete official'):road.plan_sources(root)

    def test_native_hole_persists_in_png_and_far_pyramid_retains_occupancy(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(road.common,'space'):
            root=Path(tmp);grid=road.layout([126.97,37.56,126.99,37.58]);mask=road.Mask(root/'mask',grid)
            try:
                x,y=grid['x0'],grid['y0'];a=mask.block((x,y));a[20:120,20:120]=255;a[40:100,40:100]=0;mask.flush()
                meta=dict(bounds=[126.97,37.56,126.99,37.58])
                road.pack(mask,root/'roads.pmtiles',meta)
                data=(root/'roads.pmtiles').read_bytes();reader=Reader(lambda o,n:data[o:o+n])
                png=np.array(Image.open(io.BytesIO(reader.get(12,x,y))))
                self.assertEqual(png.shape,(256,256,4));self.assertEqual(int(png[60,60,3]),0)
                self.assertEqual(int(png[30,30,3]),255)
                self.assertGreater(int(np.array(Image.open(io.BytesIO(reader.get(0,0,0))))[:,:,3].sum()),0)
            finally:mask.close()


if __name__=='__main__':unittest.main()

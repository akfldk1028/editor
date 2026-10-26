import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image
from shapely.geometry import box
from pmtiles.reader import Reader

spec=importlib.util.spec_from_file_location('road_baker',Path(__file__).with_name('bake-ngii-road-archive.py'))
road=importlib.util.module_from_spec(spec);spec.loader.exec_module(road)


class RoadArchiveTests(unittest.TestCase):
    def test_two_official_receipt_schemas_keep_exact_scale_and_year_requirements(self):
        for values in [dict(scale=5000,year=2024),dict(requestedScale=5000,requestedYear=2024),dict(requestedScale='5000',requestedYear='2024')]:
            receipt=dict(provider='NGII',format='SHP',**values)
            road.validate_receipt_product(receipt)
            self.assertEqual({k:receipt[k] for k in values},values)
        for values in [dict(scale=5000,year=2023),dict(requestedScale=25000,requestedYear=2024),dict(scale=5000,year=2024,requestedYear=2023),dict(scale=5000.0,year=2024),dict(scale=True,year=2024),{}]:
            with self.assertRaises(ValueError):road.validate_receipt_product(dict(provider='NGII',format='SHP',**values))
    def test_bounds_and_national_limit(self):
        self.assertLess(len(road.jobs([126.97,37.56,126.99,37.58],0,12)),30)
        for args in [([124,33,132,39],0,12),([127,37,126,38],0,12),([126,37,127,38],0,13)]:
            with self.assertRaises(ValueError):road.jobs(*args)

    def test_rgba_clipping_holes_and_empty_transparency(self):
        tile=(12,3492,1586);bounds=road.tile_bounds(*tile)
        w,s,e,n=bounds;dx=(e-w)/4;dy=(n-s)/4
        coverage=box(w,s,w+2*dx,n)
        polygon=box(w+dx,s+dy,e,n-dy).difference(box(w+1.2*dx,s+1.2*dy,w+1.8*dx,n-1.2*dy))
        iterator=lambda item,clip:iter([polygon.intersection(clip)])
        png,filled=road.raster_tile([{}],tile,coverage,iterator)
        rgba=np.array(Image.open(io.BytesIO(png)))
        self.assertTrue(filled);self.assertEqual(rgba.shape,(256,256,4))
        self.assertEqual(int(rgba[:,129:,3].sum()),0)
        self.assertEqual(int(rgba[128,96,3]),0)
        self.assertEqual(set(np.unique(rgba[:,:,3])),{0,255})
        empty,filled=road.raster_tile([],tile,coverage)
        self.assertFalse(filled);self.assertEqual(int(np.array(Image.open(io.BytesIO(empty)))[:,:,3].sum()),0)

    def test_official_receipt_cannot_admit_buildings_or_unrequested_centerlines(self):
        with tempfile.TemporaryDirectory() as temp:
            for layer in ['N3A_B0010000','N3L_A0020000']:
                path=Path(temp)/('(B021)'+layer+'.zip')
                with zipfile.ZipFile(path,'w') as archive:archive.writestr(layer+'.shp',b'not-read')
                receipt=Path(str(path)+'.json');receipt.write_text(json.dumps(dict(provider='NGII',scale=5000,year=2024,format='SHP',bytes=path.stat().st_size,sha256=road.sha(path))))
                with self.assertRaisesRegex(ValueError,'Only road'):road.source(path,receipt)

    def test_streaming_batches_keep_earlier_road_pixels(self):
        tile=(12,3492,1586);w,s,e,n=road.tile_bounds(*tile)
        dx=(e-w)/256;dy=(n-s)/256
        first=box(w+10*dx,s+10*dy,w+20*dx,s+20*dy)
        last=box(w+200*dx,s+200*dy,w+210*dx,s+210*dy)
        iterator=lambda item,clip:iter([first]*256+[last])
        png,_=road.raster_tile([{}],tile,box(w,s,e,n),iterator)
        alpha=np.array(Image.open(io.BytesIO(png)))[:,:,3]
        self.assertEqual(int((alpha==255).sum()),200)

    def test_sample_archive_receipt_resume_and_missing_tiles(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);original=root/'source';original.write_bytes(b'immutable')
            stamp=original.stat()
            item=dict(path=str(original),stamp=(stamp.st_size,stamp.st_mtime_ns),provenance={'sha256':road.sha(original)},member='N3A_A0010000.shp',receiptSHA256='a'*64,area=True)
            rgba=np.zeros((256,256,4),dtype=np.uint8);rgba[10:20,10:20]=[206,205,199,255]
            stream=io.BytesIO();Image.fromarray(rgba).save(stream,format='PNG');png=stream.getvalue()
            with patch.object(road,'space'),patch.object(road,'raster_tile',return_value=(png,True)):
                receipt=road.bake([item],root/'out',[126.97,37.56,126.99,37.58],12,12)
                target=Path(receipt['archive']);mtime=target.stat().st_mtime_ns
                self.assertEqual(road.bake([item],root/'out',[126.97,37.56,126.99,37.58],12,12),receipt)
                self.assertEqual(target.stat().st_mtime_ns,mtime)
                data=target.read_bytes();reader=Reader(lambda offset,length:data[offset:offset+length])
                tile=road.jobs([126.97,37.56,126.99,37.58],12,12)[0]
                self.assertEqual(reader.get(*tile),png)
                self.assertIsNone(reader.get(12,0,0))
                self.assertTrue(receipt['sampleOnly']);self.assertFalse(receipt['publishable'])
                target.write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'mismatch'):road.bake([item],root/'out',[126.97,37.56,126.99,37.58],12,12)


if __name__=='__main__':unittest.main()

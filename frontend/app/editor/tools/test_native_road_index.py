import importlib.util
from contextlib import closing
import io
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib
import numpy as np
from PIL import Image
from pyproj import Transformer
import shapely
from shapely.geometry import box, Polygon

spec=importlib.util.spec_from_file_location('index',Path(__file__).with_name('native-road-index.py'))
index=importlib.util.module_from_spec(spec);spec.loader.exec_module(index)

class IndexTests(unittest.TestCase):
 def test_resume_lossless_geometry_holes_and_png(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(index,'space'),patch.object(index.road,'assert_sources'):
   item={'sourceId':'a','features':3};x,y=Transformer.from_crs(4326,5179,always_xy=True).transform(127.108,37.73)
   gs=[box(x-100,y-100,x+100,y+100).difference(box(x-35,y-35,x+35,y+35)),box(x+200,y,x+220,y+20),box(x+300,y,x+320,y+20)]
   def stream(item,cursor):yield [{'wkb':shapely.to_wkb(g),'fid':i} for i,g in enumerate(gs) if i>=cursor],'wkb','fid'
   a=index.build([item],{},tmp,max_rows=1,iterator=stream);self.assertEqual(a['rows'],1);self.assertFalse(a['complete'])
   b=index.build([item],{},tmp,max_rows=3,iterator=stream);self.assertEqual(b['rowsAdded'],2);self.assertFalse(b['complete'])
   with closing(sqlite3.connect(b['file'])) as db:
    self.assertEqual(db.execute('SELECT count(*) FROM bounds').fetchone()[0],3)
    g=shapely.from_wkb(zlib.decompress(db.execute('SELECT wkb FROM roads WHERE id=?',(index.road_id(1,0),)).fetchone()[0]))
    world=index.road.common.HALF_WORLD
    expected=index.road.project_road_batch([{'wkb':shapely.to_wkb(gs[0]),'fid':0}],'wkb','fid',item,box(-world,-world,world,world),Transformer.from_crs(5179,3857,always_xy=True).transform)[0]
    self.assertEqual(shapely.to_wkb(g),shapely.to_wkb(expected));self.assertEqual(len(g.interiors),1)
   tx=int((127.108+180)/360*2**17);ty=int((1-math.asinh(math.tan(math.radians(37.73)))/math.pi)/2*2**17)
   raw,count=index.query_png(b['file'],17,tx,ty);image=np.array(Image.open(io.BytesIO(raw)))
   self.assertGreater(count,0);self.assertEqual(image.shape,(256,256,4));self.assertTrue((image[:,:,3]==0).any());self.assertTrue((image[:,:,3]==255).any())
 def test_repair_provenance_and_rollback(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(index,'space'),patch.object(index.road,'assert_sources'):
   item={'sourceId':'a','features':1};g=Polygon([(950000,1950000),(950010,1950010),(950000,1950010),(950010,1950000),(950000,1950000)])
   _,audit=index.road.repair_road_geometry(g);record={'sourceId':'a','FID':0,'UFID':'repair-only','status':'repaired',**audit}
   stream=lambda item,cursor:iter([([{'wkb':shapely.to_wkb(g),'fid':0,'UFID':'repair-only'}],'wkb','fid')])
   with self.assertRaisesRegex(ValueError,'Repair differs'):index.build([item],{},Path(tmp)/'bad',iterator=stream)
   r=index.build([item],{('a',0):record},Path(tmp)/'good',iterator=stream);self.assertEqual(r['repairs'],1)
   with closing(sqlite3.connect(r['file'])) as db:self.assertEqual(json.loads(db.execute('SELECT record FROM repairs').fetchone()[0]),record)
 def test_space_and_source_guards(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(index,'space',side_effect=OSError('needs_storage')):
   with self.assertRaisesRegex(OSError,'needs_storage'):index.build([{'sourceId':'a','features':1}],{},tmp)
  with tempfile.TemporaryDirectory() as tmp,patch.object(index,'space'),patch.object(index.road,'assert_sources',side_effect=ValueError('changed')):
   with self.assertRaisesRegex(ValueError,'changed'):index.build([{'sourceId':'a','features':1}],{},tmp)
 def test_packed_identity_boundaries_and_source_recovery(self):
  for ordinal in (1,17):
   for fid in (0,2**32-1):
    key=index.road_id(ordinal,fid)
    self.assertEqual(index.restore_id(key,{ordinal:'source-sha'}),('source-sha',fid))
  for fid in (-1,2**32,1.5,True):
   with self.assertRaises(ValueError):index.road_id(1,fid)
  for ordinal in (0,18):
   with self.assertRaises(ValueError):index.road_id(ordinal,0)
  with self.assertRaises(ValueError):index.restore_id(index.road_id(2,0),{1:'a'})
 def test_duplicate_fid_rejected_and_same_fid_other_source_retained(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(index,'space'),patch.object(index.road,'assert_sources'):
   items=[{'sourceId':'b','features':1},{'sourceId':'a','features':1}]
   g=box(950000,1950000,950010,1950010)
   stream=lambda item,cursor:iter([([{'wkb':shapely.to_wkb(g),'fid':7}],'wkb','fid')])
   result=index.build(items,{},Path(tmp)/'good',iterator=stream)
   with closing(sqlite3.connect(result['file'])) as db:
    ids=[r[0] for r in db.execute('SELECT id FROM roads ORDER BY id')]
    sources=dict(db.execute('SELECT ordinal,sourceId FROM sources'))
    self.assertEqual([index.restore_id(k,sources) for k in ids],[('a',7),('b',7)])
    self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(roads)')],['id','wkb'])
   duplicate=lambda item,cursor:iter([([{'wkb':shapely.to_wkb(g),'fid':7}]*2,'wkb','fid')])
   with self.assertRaises(sqlite3.IntegrityError):index.build(items[:1],{},Path(tmp)/'bad',iterator=duplicate)

if __name__=='__main__':unittest.main()

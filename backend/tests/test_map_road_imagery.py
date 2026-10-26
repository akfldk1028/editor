import asyncio
import hashlib
import io
import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
from shapely.geometry import box
import shapely
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.modules.land import map_road_imagery as m
from backend.app.modules.land.routers.map import create_land_map_router


def fixture(root):
 version='a'*64;folder=root/'world-ground/road-index'/version;folder.mkdir(parents=True)
 path=folder/'roads.sqlite';db=sqlite3.connect(path)
 db.executescript('CREATE TABLE sources(sourceId,ordinal,expected,next_row); CREATE TABLE metadata(identity); CREATE TABLE repairs(record); CREATE TABLE roads(id INTEGER PRIMARY KEY,wkb BLOB); CREATE VIRTUAL TABLE bounds USING rtree(id,minx,maxx,miny,maxy);')
 for i in range(17):
  n=8976641 if i==0 else 0;db.execute('INSERT INTO sources VALUES(?,?,?,?)',(str(i),i+1,n,n))
 db.execute('INSERT INTO metadata VALUES(?)',(json.dumps({'schema':'ngii-native-road-index-v2','nationalSelection':True}),))
 db.executemany('INSERT INTO repairs VALUES(?)',[(str(i),) for i in range(37)])
 world=np.pi*6378137;span=2*world/2**15;x=27953;y=12670;w=-world+x*span;s=world-(y+1)*span
 g=box(w+100,s+100,w+800,s+800).difference(box(w+300,s+300,w+600,s+600))
 db.execute('INSERT INTO roads VALUES(?,?)',(1,zlib.compress(shapely.to_wkb(g),1)));a,b,c,d=g.bounds;db.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(1,a,c,b,d));db.commit();db.close()
 pointer={'schema':'ngii-native-road-index-pointer-v1','version':version,'file':'roads.sqlite','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'complete':True,'sourceCount':17,'rows':8976641,'repairs':37,'rejected':0}
 latest=folder.parent/'latest.json';latest.write_text(json.dumps(pointer))
 return path,latest,pointer


def test_png_exact_reference_hole_and_cache_epoch(tmp_path,monkeypatch):
 path,latest,pointer=fixture(tmp_path);service=m.RoadImagery(data_root=tmp_path)
 raw=asyncio.run(service.get(15,27953,12670));a=np.array(Image.open(io.BytesIO(raw)))
 assert (a[:,:,3]==0).any() and (a[:,:,3]==255).any()
 assert raw==m.query_png(path,15,27953,12670)
 monkeypatch.setattr(m,'query_png',lambda *a:(_ for _ in ()).throw(AssertionError('cache missed')))
 assert asyncio.run(service.get(15,27953,12670))==raw
 path.touch()
 with pytest.raises(m.ImageryUnavailable):asyncio.run(service.get(15,27953,12670))


def test_missing_partial_escape_sha_and_changed_pointer_rejected(tmp_path):
 service=m.RoadImagery(data_root=tmp_path)
 with pytest.raises(m.ImageryUnavailable):asyncio.run(service.get(15,1,1))
 path,latest,pointer=fixture(tmp_path)
 for changes in ({'complete':False},{'sourceCount':1},{'rows':20000},{'file':'../roads.sqlite'},{'version':'../escape'},{'sha256':'0'*64}):
  latest.write_text(json.dumps({**pointer,**changes}))
  with pytest.raises(m.ImageryUnavailable):asyncio.run(m.RoadImagery(data_root=tmp_path).get(15,1,1))
 latest.write_text(json.dumps(pointer));service.select();latest.write_text(json.dumps(pointer,indent=2))
 with pytest.raises(m.ImageryUnavailable):service.select()


def test_row_budget_refuses_partial_png(tmp_path,monkeypatch):
 path,_,_=fixture(tmp_path);monkeypatch.setattr(m,'MAX_ROWS',0)
 with pytest.raises(m.ImageryUnavailable):m.query_png(path,15,27953,12670)


def test_cancel_coalesce_two_workers_and_pending_limit(tmp_path,monkeypatch):
 service=m.RoadImagery(data_root=tmp_path);release=threading.Event();lock=threading.Lock();state={'calls':0,'active':0,'max':0}
 def image(key):
  with lock:state['calls']+=1;state['active']+=1;state['max']=max(state['max'],state['active'])
  release.wait(3)
  with lock:state['active']-=1
  return b'png'
 monkeypatch.setattr(service,'image',image)
 async def run():
  first=asyncio.create_task(service.get(15,1,1));await asyncio.sleep(.03);second=asyncio.create_task(service.get(15,1,1));await asyncio.sleep(.01);first.cancel()
  with pytest.raises(asyncio.CancelledError):await first
  others=[asyncio.create_task(service.get(15,i,1)) for i in (2,3,4)];await asyncio.sleep(.03);assert state['max']==2
  release.set();assert await second==b'png';await asyncio.gather(*others);assert state['calls']==4
  service.pending={i:None for i in range(64)}
  with pytest.raises(m.ImageryUnavailable):await service.get(15,5,1)
  service.pending.clear()
 asyncio.run(run())


def test_route_absent_index_503_invalid422(tmp_path,monkeypatch):
 monkeypatch.setenv('DATA_ROOT',str(tmp_path));app=FastAPI();app.include_router(create_land_map_router());client=TestClient(app)
 assert client.get('/api/v1/land/road-imagery/12/1/1.png').status_code==422
 r=client.get('/api/v1/land/road-imagery/15/1/1.png');assert r.status_code==503 and r.json()=={'detail':'Road imagery unavailable'}


def test_versioned_route_rejects_a_different_style_instead_of_serving_changed_pixels(tmp_path,monkeypatch):
 monkeypatch.setenv('DATA_ROOT',str(tmp_path));app=FastAPI();app.include_router(create_land_map_router());client=TestClient(app)
 wrong='0'*64
 assert wrong!=m.STYLE_SHA
 assert client.get(f'/api/v1/land/road-imagery/{wrong}/15/1/1.png').status_code==404
 assert client.get(f'/api/v1/land/road-imagery/{m.STYLE_SHA}/15/1/1.png').status_code==503


def test_coverage_edges_holes_and_no_width_expansion(tmp_path):
 path,_,_=fixture(tmp_path)
 world=np.pi*6378137;span=2*world/2**15;pixel=span/256;w=-world+27953*span;n=world-12670*span
 def rect(l,t,r,b):return box(w+l*pixel,n-b*pixel,w+r*pixel,n-t*pixel)
 geometry=rect(10.25,10.25,30.75,30.75).difference(rect(16,16,24,24))
 db=sqlite3.connect(path);db.execute('UPDATE roads SET wkb=?',(zlib.compress(shapely.to_wkb(geometry)),));a,b,c,d=geometry.bounds;db.execute('UPDATE bounds SET minx=?,maxx=?,miny=?,maxy=?',(a,c,b,d));db.commit();db.close()
 rgba=np.asarray(Image.open(io.BytesIO(m.query_png(path,15,27953,12670))));alpha=rgba[:,:,3]
 assert alpha[12,12]==255 and alpha[20,20]==0
 assert 0<alpha[10,15]<255 and 0<alpha[15,30]<255
 assert not alpha[:10].any() and not alpha[31:].any() and not alpha[:,:10].any() and not alpha[:,31:].any()
 assert np.all(rgba[:,:,:3]==[206,205,199])
 assert abs(alpha.sum()/255-((20.5**2)-8**2))<1


def test_neighbour_tile_seam_matches_one_coverage_raster(tmp_path):
 from shapely.geometry import Polygon
 path,_,_=fixture(tmp_path)
 world=np.pi*6378137;span=2*world/2**15;pixel=span/256;w=-world+27953*span;n=world-12670*span
 g=Polygon([(w+240*pixel,n-90*pixel),(w+275*pixel,n-110*pixel),(w+275*pixel,n-114*pixel),(w+240*pixel,n-94*pixel)])
 db=sqlite3.connect(path);db.execute('UPDATE roads SET wkb=?',(zlib.compress(shapely.to_wkb(g)),));a,b,c,d=g.bounds;db.execute('UPDATE bounds SET minx=?,maxx=?,miny=?,maxy=?',(a,c,b,d));db.commit();db.close()
 pair=np.concatenate([np.asarray(Image.open(io.BytesIO(m.query_png(path,15,x,12670))))[:,:,3] for x in (27953,27954)],axis=1)
 high=m.rasterize([(g,255)],out_shape=(1024,2048),transform=m.from_bounds(w,n-span,w+2*span,n,2048,1024),dtype='uint8')
 reference=np.asarray(Image.fromarray(high).resize((512,256),Image.Resampling.BOX))
 assert np.array_equal(pair,reference)
 assert np.any((pair>0)&(pair<255))


def test_style_invalidates_old_binary_cache():
 assert m.STYLE_SHA!=hashlib.sha256(b'native-road-area-rgba206-205-199-alpha255-pixel-center-v1').hexdigest()


def test_straight_alpha_bilinear_boundary_has_no_dark_fringe(tmp_path):
 path,_,_=fixture(tmp_path)
 rgba=np.asarray(Image.open(io.BytesIO(m.query_png(path,15,27953,12670)))).astype(float)
 edges=np.argwhere((rgba[:,:-1,3]==0)&(rgba[:,1:,3]>0))
 assert len(edges)>0
 y,x=edges[len(edges)//2];texels=rgba[y:y+2,x:x+2]/255
 weights=np.array([[.375,.375],[.125,.125]])
 sampled=(texels*weights[:,:,None]).sum(axis=(0,1));color=np.array([206,205,199])/255;background=np.array([.95,.9,.85])
 expected=color*sampled[3]+background*(1-sampled[3])
 assert np.allclose(sampled[:3]*sampled[3]+background*(1-sampled[3]),expected)
 black=texels.copy();black[black[:,:,3]==0,:3]=0
 old=(black*weights[:,:,None]).sum(axis=(0,1))
 assert np.all(old[:3]*old[3]+background*(1-old[3])<expected)
 assert m.STYLE_SHA!=hashlib.sha256(b'native-road-area-rgba206-205-199-coverage4x-box-v2').hexdigest()

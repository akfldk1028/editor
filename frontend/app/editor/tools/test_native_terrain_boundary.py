import importlib.util
from pathlib import Path
import math
import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer


def module():
    path=Path(__file__).with_name('native_terrain_boundary.py')
    assert path.exists(), 'native boundary policy is not implemented'
    spec=importlib.util.spec_from_file_location('native_boundary',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def fixture(tmp_path,missing=False):
    x,y=Transformer.from_crs(4326,5186,always_xy=True).transform(127,37)
    transform=from_origin(x-100,y+100,5,5)
    data=np.random.default_rng(4).uniform(10,3500,(40,40)).astype('float32')
    if missing:data[:,20]=-9999
    path=tmp_path/'source.tif'
    with rasterio.open(path,'w',driver='GTiff',width=40,height=40,count=1,dtype='float32',crs=5186,transform=transform,nodata=-9999) as ds:ds.write(data,1)
    width=180/2**20
    key=(20,math.floor(307/width),math.floor(53/width))
    return path,key


def test_boundary_grid_matches_authoritative_scalar_sampler_at_every_vertex(tmp_path):
    m=module();path,key=fixture(tmp_path,missing=True)
    with rasterio.open(path) as ds:rows=list(m.native_tiles(ds,[key],validate=True))
    assert rows[0][3] is True
    grid=rows[0][4]
    spec=importlib.util.spec_from_file_location('authoritative',Path(__file__).with_name('sample-building-dem.py'))
    reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
    level,x,y=key;w=180/2**level
    points=[[-180+(x+c/32)*w,90-(y+r/32)*w] for r in range(33) for c in range(33)]
    expected=np.array([np.nan if z is None else z for z in reference.sample(path,points)['heights']],dtype='float32').reshape(33,33)
    assert np.array_equal(grid,expected,equal_nan=True)
    assert np.isnan(grid).any() and np.isfinite(grid).any()


def test_finite_interior_is_classified_for_byte_preservation(tmp_path):
    m=module();path,key=fixture(tmp_path)
    with rasterio.open(path) as ds:row=next(m.native_tiles(ds,[key],validate=True))
    assert row[3] is False and row[4] is None

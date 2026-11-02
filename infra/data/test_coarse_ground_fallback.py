import importlib.util
from pathlib import Path
import numpy as np


def implementation():
    path=Path(__file__).with_name('coarse_ground_fallback.py')
    assert path.exists(),'Guarded measured fallback helper is not implemented'
    spec=importlib.util.spec_from_file_location('fallback',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def sample(grid,x,y):
    c,r=int(np.floor(x-.5)),int(np.floor(y-.5))
    if c>=0 and r>=0 and c+1<grid.shape[1] and r+1<grid.shape[0] and np.isfinite(grid[r:r+2,c:c+2]).all():
        u,v=x-.5-c,y-.5-r
        return grid[r,c]*(1-u)*(1-v)+grid[r,c+1]*u*(1-v)+grid[r+1,c]*(1-u)*v+grid[r+1,c+1]*u*v
    return grid[int(y),int(x)]


def test_fallback_never_changes_valid_pixel_or_its_missing_neighbours():
    m=implementation();base=np.full((7,7),np.nan,dtype='float32');base[3,3]=12
    result=m.guarded_fallback(np.pad(base,1,constant_values=np.nan),np.full((7,7),55,dtype='float32'))
    assert np.isnan(result[2:5,2:5]).all()
    assert np.isfinite(result).sum()==40
    assert np.isfinite(result[0,0])


def test_halo_just_outside_output_window_blocks_boundary_fill():
    m=implementation();halo=np.full((5,5),np.nan,dtype='float32');halo[0,2]=0
    result=m.guarded_fallback(halo,np.full((3,3),77,dtype='float32'))
    assert np.isnan(result[0,:]).all()
    assert np.isfinite(result[1:,:]).all()


def test_every_previously_finite_native_sample_stays_exactly_identical():
    m=implementation();rng=np.random.default_rng(842)
    base=rng.uniform(0,900,(40,40)).astype('float32');base[rng.random(base.shape)<.85]=np.nan
    candidate=np.full(base.shape,135,dtype='float32')
    fallback=m.guarded_fallback(np.pad(base,1,constant_values=np.nan),candidate)
    result=np.where(np.isfinite(base),base,fallback)
    assert np.isfinite(fallback).any()
    for x,y in rng.uniform(0,40,(20000,2)):
        before=sample(base,x,y)
        if np.isfinite(before):assert sample(result,x,y)==before


def test_unknown_or_invalid_candidate_heights_remain_unsupported():
    m=implementation();candidate=np.array([[np.nan,0,-9999,9001]],dtype='float32')
    result=m.guarded_fallback(np.full((3,6),np.nan,dtype='float32'),candidate)
    assert np.isnan(result[0,[0,2,3]]).all() and result[0,1]==0

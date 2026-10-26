"""Authoritative native sampling at L20 vertices whose support touches NoData."""
import hashlib
import math
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
import pyproj
from rasterio.windows import Window

POLICY='native-boundary-l20-v1'


def base_signature():
    return hashlib.sha256(Path(__file__).with_name('terrain_archive.py').read_bytes()
                          +rasterio.__version__.encode()+rasterio.__gdal_version__.encode()
                          +b'height-range:-500:9000;explicit-nodata-v1').hexdigest()


def provenance():
    native=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    authoritative=hashlib.sha256(Path(__file__).with_name('sample-building-dem.py').read_bytes()).hexdigest()
    signature=hashlib.sha256((POLICY+base_signature()+native+authoritative+np.__version__+pyproj.__version__).encode()).hexdigest()
    return dict(policy=POLICY,level=20,baseSamplerSHA256=base_signature(),nativeSamplerSHA256=native,
                authoritativeSamplerSHA256=authoritative,samplerSHA256=signature,
                numpyVersion=np.__version__,pyprojVersion=pyproj.__version__,
                rule='At every L20 native 2x2 NoData-support boundary: bilinear if all four native cells are valid; otherwise the valid containing native cell; unsupported vertices remain NoData. Other tiles retain GDAL bilinear.')


def _reference(cols,rows,data,valid,r0,c0,source_width,source_height):
    result=[]
    for col,row in zip(cols.ravel(),rows.ravel()):
        col,row=float(col),float(row)
        if not (0<=col<source_width and 0<=row<source_height):result.append(np.nan);continue
        c,r=math.floor(col-.5),math.floor(row-.5);cc,rr=c-c0,r-r0
        if c>=0 and r>=0 and c+1<source_width and r+1<source_height and valid[rr:rr+2,cc:cc+2].all():
            u,v=col-.5-c,row-.5-r
            # Scalar NumPy operations deliberately mirror sample-building-dem.py.
            z=data[rr,cc]*(1-u)*(1-v)+data[rr,cc+1]*u*(1-v)+data[rr+1,cc]*(1-u)*v+data[rr+1,cc+1]*u*v
        else:
            cc,rr=math.floor(col)-c0,math.floor(row)-r0
            if not valid[rr,cc]:result.append(np.nan);continue
            z=data[rr,cc]
        result.append(round(float(z),3))
    return np.asarray(result,dtype='float32').reshape(cols.shape)


def native_tiles(source,keys,*,validate=True):
    """Yield (level,x,y,boundary,native_grid); read native pixels once per spatial batch."""
    groups={}
    for level,x,y in keys:
        if level!=20:raise ValueError('Native boundary policy applies only at L20')
        groups.setdefault((x//16,y//16),[]).append((level,x,y))
    to=Transformer.from_crs(4326,source.crs,always_xy=True);inverse=~source.transform
    width=180/2**20;fractions=np.arange(33,dtype='float64')/32
    for _,group in sorted(groups.items()):
        x0=min(k[1] for k in group);x1=max(k[1] for k in group)
        y0=min(k[2] for k in group);y1=max(k[2] for k in group)
        bounds=to.transform_bounds(-180+x0*width,90-(y1+1)*width,-180+(x1+1)*width,90-y0*width,densify_pts=21)
        window=source.window(*bounds)
        c0=math.floor(window.col_off)-2;r0=math.floor(window.row_off)-2
        c1=math.ceil(window.col_off+window.width)+2;r1=math.ceil(window.row_off+window.height)+2
        outside=c0<0 or r0<0 or c1>source.width or r1>source.height
        native=source.read(1,window=Window(c0,r0,c1-c0,r1-r0),boundless=outside,masked=True)
        data=np.asarray(native.data,dtype='float32')
        valid=~np.ma.getmaskarray(native)&np.isfinite(data)&(data>=-500)&(data<=9000)
        if valid.all():
            for level,x,y in group:yield level,x,y,False,None
            continue
        for level,x,y in group:
            lon,lat=np.meshgrid(-180+(x+fractions)*width,90-(y+fractions)*width)
            xx,yy=to.transform(lon,lat)
            cols=inverse.a*xx+inverse.b*yy+inverse.c;rows=inverse.d*xx+inverse.e*yy+inverse.f
            cc=np.floor(cols-.5).astype('int64');rr=np.floor(rows-.5).astype('int64')
            ci,ri=cc-c0,rr-r0
            if ci.min()<0 or ri.min()<0 or ci.max()+1>=data.shape[1] or ri.max()+1>=data.shape[0]:
                raise ValueError('Native batch does not enclose all interpolation support')
            four=valid[ri,ci]&valid[ri,ci+1]&valid[ri+1,ci]&valid[ri+1,ci+1]
            four&=(cc>=0)&(rr>=0)&(cc+1<source.width)&(rr+1<source.height)
            if four.all():yield level,x,y,False,None;continue
            u=cols-.5-cc;v=rows-.5-rr
            u32=u.astype('float32');v32=v.astype('float32');mu=(1-u).astype('float32');mv=(1-v).astype('float32')
            z=data[ri,ci]*mu*mv+data[ri,ci+1]*u32*mv+data[ri+1,ci]*mu*v32+data[ri+1,ci+1]*u32*v32
            nearest_c=np.floor(cols).astype('int64')-c0;nearest_r=np.floor(rows).astype('int64')-r0
            containing=valid[nearest_r,nearest_c]
            inside=(cols>=0)&(rows>=0)&(cols<source.width)&(rows<source.height)
            z=np.where(four,z,np.where(containing,data[nearest_r,nearest_c],np.nan))
            z=np.where(inside,z,np.nan)
            grid=np.round(z.astype('float64'),3).astype('float32')
            if validate:
                reference=_reference(cols,rows,data,valid,r0,c0,source.width,source.height)
                if not np.array_equal(grid,reference,equal_nan=True):
                    raise ValueError('Vectorized boundary grid differs from the authoritative scalar rule')
            yield level,x,y,True,grid

import struct
import numpy as np
from affine import Affine
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from rasterio.windows import Window

def encode_grid(grid):
    if grid.shape!=(33,33):raise ValueError('Expected 33x33 grid')
    if np.isinf(grid).any():raise ValueError('Infinite height')
    return b'HTM1'+struct.pack('<HH',33,0)+grid.astype('<f4').tobytes()

def grid_view(source,level):
    step=180/(2**level*32)
    return WarpedVRT(source,crs='EPSG:4326',transform=Affine(step,0,-180-step/2,0,-step,90+step/2),
                     width=2**(level+1)*32+1,height=2**level*32+1,resampling=Resampling.bilinear,
                     dtype='float32',nodata=float('nan'),warp_mem_limit=64)

def read_grid(view,x,y):
    return view.read(1,window=Window(x*32,y*32,33,33))

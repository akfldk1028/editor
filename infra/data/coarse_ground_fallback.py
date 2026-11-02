"""Measured coarse-source fallback that preserves all existing native samples.

Input elevation scale remains 1:25,000. A 5 m output lattice does not assert
5 m measurement accuracy. A one-cell unsupported collar is intentional.
"""
import numpy as np

POLICY='measured-25000-fallback-3x3-nodata-v1'


def valid_heights(grid):
    values=np.asarray(np.ma.getdata(grid))
    return ~np.ma.getmaskarray(grid)&np.isfinite(values)&(values>=-500)&(values<=9000)


def guarded_fallback(base_with_halo,candidate):
    """Allow measured values only where all nine base support cells are NoData.

    The base array must contain a one-pixel halo on each side of candidate.
    Reading the halo from the complete immutable composite is required at
    strip/tile boundaries; padding each strip independently is incorrect.
    """
    if base_with_halo.shape!=(candidate.shape[0]+2,candidate.shape[1]+2):
        raise ValueError('A full one-cell base halo is required')
    height,width=candidate.shape;valid=valid_heights(base_with_halo)
    blocked=np.zeros(candidate.shape,dtype=bool)
    for dy in range(3):
        for dx in range(3):blocked|=valid[dy:dy+height,dx:dx+width]
    return np.where(~blocked&valid_heights(candidate),np.ma.getdata(candidate),np.nan).astype('float32')

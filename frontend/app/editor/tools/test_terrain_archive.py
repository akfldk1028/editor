import unittest, numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from terrain_archive import encode_grid, grid_view, read_grid

class TerrainArchiveTests(unittest.TestCase):
    def test_binary_layout_preserves_nodata_and_zero(self):
        grid=np.zeros((33,33),dtype='float32');grid[0,0]=np.nan
        data=encode_grid(grid)
        self.assertEqual(data[:8],b'HTM1!\x00\x00\x00')
        self.assertTrue(np.isnan(np.frombuffer(data[8:],dtype='<f4')[0]))
        self.assertEqual(np.frombuffer(data[8:],dtype='<f4')[1],0)

    def test_adjacent_grids_share_identical_edge_samples(self):
        with MemoryFile() as memory:
            with memory.open(driver='GTiff',width=100,height=100,count=1,dtype='float32',crs='EPSG:4326',transform=from_origin(126,39,.02,.02),nodata=-9999) as source:
                rows,cols=np.indices((100,100));source.write((rows+cols*2).astype('float32'),1)
                with grid_view(source,12) as view:
                    a=read_grid(view,6988,1189);b=read_grid(view,6989,1189)
                    np.testing.assert_array_equal(a[:,-1],b[:,0])
                    self.assertTrue(np.isfinite(a).all())
                    lon=6988*180/4096-180;lat=90-1189*180/4096
                    expected=(39-lat)/.02-.5+2*((lon-126)/.02-.5)
                    self.assertAlmostEqual(float(a[0,0]),expected,places=3)

if __name__=='__main__':unittest.main()

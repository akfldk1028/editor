import json,tempfile,unittest
from pathlib import Path
import numpy as np,rasterio
from rasterio.transform import from_origin
from ground_vrt_layers import compose,prepare

class GroundVrtTests(unittest.TestCase):
    def test_known_incomplete_cached_dxf_cannot_enter_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'base.vrt';base.write_text('<VRTDataset/>')
            (root/'terrain-stage-status.json').write_text(json.dumps({'results':{'original.dxf':{'state':'staged'}}}))
            with self.assertRaisesRegex(ValueError,'current parser version'):
                prepare(base,root,root/'output')
    def test_precision_wins_and_nodata_keeps_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,values in [('base',[10,20,30,-9999]),('fine',[12,-9999,-9999,44])]:
                with rasterio.open(root/f'{name}.tif','w',driver='GTiff',width=2,height=2,count=1,dtype='float32',crs='EPSG:5186',transform=from_origin(0,10,5,5),nodata=-9999) as ds:ds.write(np.array(values,dtype='float32').reshape(2,2),1)
            compose(root/'base.tif',[root/'fine.tif'],root/'result.vrt')
            with rasterio.open(root/'result.vrt') as ds:self.assertEqual(ds.read(1).tolist(),[[12,20],[30,44]])
    def test_misaligned_precision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,x in [('base',0),('fine',1)]:
                with rasterio.open(root/f'{name}.tif','w',driver='GTiff',width=2,height=2,count=1,dtype='float32',crs='EPSG:5186',transform=from_origin(x,10,5,5),nodata=-9999) as ds:ds.write(np.ones((2,2),dtype='float32'),1)
            with self.assertRaises(ValueError):compose(root/'base.tif',[root/'fine.tif'],root/'result.vrt')

if __name__=='__main__':unittest.main()

from pathlib import Path
import tempfile
import unittest
import pyarrow as pa
import pyogrio
import shapely
from ngii_spatial_index import build_qix


class SpatialIndexTests(unittest.TestCase):
    def test_exact_geometry_attributes_duplicates_and_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder)/'stage';stage.mkdir()
            path=stage/'contours.shp'
            shapes=[shapely.LineString([(0,0),(2,2)]),shapely.LineString([(0,0),(2,2)]),shapely.LineString([(20,20),(22,22)])]
            table=pa.table({'CONT':[0.0,0.0,20.0],'geometry':shapely.to_wkb(shapes)})
            pyogrio.write_arrow(table,path,driver='ESRI Shapefile',geometry_name='geometry',geometry_type='LineString',crs='EPSG:5179')
            result=build_qix(path,stage,'CONT',[-1,-1,3,3])
            self.assertEqual(result['before']['rows'],2)
            self.assertEqual(result['before']['sha256'],result['after']['sha256'])
            self.assertEqual(build_qix(path,stage,'CONT',[-1,-1,3,3]),result)
            with self.assertRaises(ValueError):build_qix(path,Path(folder)/'originals','CONT',[-1,-1,3,3])


if __name__=='__main__':unittest.main()

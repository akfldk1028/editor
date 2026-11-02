import unittest
import ezdxf
import numpy as np
from ngii_dxf import parse_elevation, PARSER_VERSION, needs_reparse, raster_name


class DxfElevationTests(unittest.TestCase):
    def test_2d_polyline_uses_header_elevation_and_3d_preserves_vertex_heights(self):
        doc=ezdxf.new(); model=doc.modelspace()
        model.add_polyline2d([(10,20),(30,40)],dxfattribs={'layer':'F0017114','elevation':(0,0,25)})
        model.add_polyline3d([(10,20,30),(30,40,35)],dxfattribs={'layer':'F0017114'})
        chunks,contours,spots=parse_elevation(doc)
        self.assertEqual((contours,spots),(2,0))
        np.testing.assert_array_equal(chunks[0],[[10,20,25],[30,40,25]])
        np.testing.assert_array_equal(chunks[1],[[10,20,30],[30,40,35]])

    def test_polyline_ocs_is_transformed_and_meshes_are_excluded(self):
        doc=ezdxf.new();model=doc.modelspace()
        entity=model.add_polyline2d([(10,20),(30,40)],dxfattribs={'layer':'F0017114','elevation':(0,0,25),'extrusion':(0,0,-1)})
        model.add_polymesh((2,2),dxfattribs={'layer':'F0017114'})
        model.add_polyface(dxfattribs={'layer':'F0017114'}).append_face([(0,0,1),(10,0,2),(0,10,3)])
        model.add_polyline3d([(10,20,999),(30,40,999)],dxfattribs={'layer':'A0010000'})
        chunks,contours,spots=parse_elevation(doc)
        self.assertEqual((len(chunks),contours,spots),(1,1,0))
        np.testing.assert_array_equal(chunks[0],list(entity.points_in_wcs()))
        self.assertEqual(chunks[0][0,2],-25)

    def test_lwpolyline_and_spots_remain_supported_without_fabricating_missing_elevation(self):
        doc=ezdxf.new();model=doc.modelspace()
        model.add_lwpolyline([(1,2),(3,4)],dxfattribs={'layer':'F001','elevation':0})
        model.add_lwpolyline([(1,2),(3,4)],dxfattribs={'layer':'F001'})
        model.add_blockref('spot',(5,6,7),dxfattribs={'layer':'F002'})
        chunks,contours,spots=parse_elevation(doc)
        self.assertEqual((contours,spots),(1,1))
        self.assertEqual(chunks[0][0,2],0)
        np.testing.assert_array_equal(chunks[1],[[5,6,7]])

    def test_versioned_paths_never_reuse_legacy_raster_and_cached_dxf_is_invalidated(self):
        self.assertTrue(needs_reparse('a.dxf',{'state':'staged'}))
        self.assertFalse(needs_reparse('a.zip',{'state':'staged'}))
        self.assertFalse(needs_reparse('a.dxf',{'state':'staged','parserVersion':PARSER_VERSION}))
        self.assertNotEqual(raster_name('sheet','abcdef123456789','a.dxf'),'sheet-abcdef123456.tif')
        self.assertEqual(raster_name('sheet','abcdef123456789','a.zip'),'sheet-abcdef123456.tif')


if __name__=='__main__':unittest.main()

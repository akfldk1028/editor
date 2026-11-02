import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from pmtiles.reader import Reader, all_tiles

spec=importlib.util.spec_from_file_location('repack',Path(__file__).with_name('repack-ngii-road-pyramid.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class FakeMask:
    grid=dict(z=2,x0=0,y0=0,nx=2,ny=1)
    def __init__(self):
        self.blocks={(x,0):np.zeros((256,256),dtype=np.uint8) for x in range(2)}
    def read(self,key):return self.blocks[key]


class Tests(unittest.TestCase):
    def test_incomplete_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'receipt.json').write_text(json.dumps(dict(completeCoverage=False)))
            (p/'inputs.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Incomplete source'):m.pin_source(p)

    def test_area_line_width_and_child_edge(self):
        mask=FakeMask()
        for a in mask.blocks.values():a[100,:]=255
        alpha=m.coverage(mask,1,0,0,list(mask.blocks))
        self.assertEqual(np.count_nonzero(alpha),256)
        self.assertTrue(np.all(alpha[50]==128))
        # Half-pixel line remains half opacity, never the old full-opacity expansion.
        self.assertLessEqual(abs(alpha.sum()*4/255-512),256*4/(2*255))
        self.assertEqual(int(alpha[50,127]),int(alpha[50,128]))
        self.assertEqual(alpha[51].sum(),0)

    def test_native_png_exact_and_alpha_color(self):
        mask=FakeMask();mask.blocks[0,0][3:8,4:9]=255
        original=np.zeros((256,256,4),dtype=np.uint8);original[3:8,4:9]=[206,205,199,255]
        out=io.BytesIO();Image.fromarray(original).save(out,format='PNG',compress_level=6)
        self.assertEqual(m.png(m.coverage(mask,2,0,0,[(0,0)])),out.getvalue())
        a=np.zeros((256,256),dtype=np.uint8);a[0,0]=64
        rgba=np.asarray(Image.open(io.BytesIO(m.png(a))))
        self.assertEqual(rgba[0,0].tolist(),[206,205,199,64])
        self.assertEqual(rgba[0,1].tolist(),[0,0,0,0])

    def test_archive_every_tile_and_determinism(self):
        mask=FakeMask();mask.blocks[0,0][3:80,4:90]=255;mask.blocks[1,0][90:100,:]=255
        metadata=dict(bounds=[124,33,132,39],algorithm=m.REVISION)
        with tempfile.TemporaryDirectory() as directory,patch.object(m.common,'RESERVE',0):
            paths=[Path(directory)/name for name in ['a.pmtiles','b.pmtiles']]
            m.base.pack_owned=m.pack_owned
            for path in paths:m.base.pack(mask,path,metadata)
            self.assertEqual(paths[0].read_bytes(),paths[1].read_bytes())
            data=paths[0].read_bytes();get=lambda offset,length:data[offset:offset+length]
            self.assertEqual(Reader(get).header()['max_zoom'],2)
            count=0
            for (z,x,y),payload in all_tiles(get):
                children=[key for key in mask.blocks if key[0]//2**(2-z)==x and key[1]//2**(2-z)==y]
                expected=m.png(m.coverage(mask,z,x,y,children))
                self.assertEqual(hashlib.sha256(payload).digest(),hashlib.sha256(expected).digest());count+=1
            self.assertEqual(count,4)

    def test_readonly_mask_bounds_and_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mask';path.write_bytes(bytes(65536))
            grid=dict(z=12,x0=3,y0=4,nx=1,ny=1,width=256,height=256)
            before=path.stat();reader=m.ReadMask(path,grid)
            try:
                self.assertEqual(reader.read((3,4)).sum(),0)
                with self.assertRaises(ValueError):reader.read((4,4))
                with self.assertRaises(io.UnsupportedOperation):reader.file.write(b'x')
            finally:reader.file.close()
            self.assertEqual(before.st_mtime_ns,path.stat().st_mtime_ns)


if __name__=='__main__':unittest.main()

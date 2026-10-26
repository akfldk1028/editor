import tempfile
import unittest
from pathlib import Path
import zipfile
from ngii_split_zip import stage_members


class SplitExtractionTests(unittest.TestCase):
    def test_checked_stream_extract_and_missing_member(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'source.zip'
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('folder/a.shp',b'abcd'*100000)
                z.writestr('folder/a.prj',b'EPSG')
            stage_members([archive],root/'stage',['folder/a.shp','folder/a.prj'],0)
            self.assertEqual((root/'stage/folder/a.shp').read_bytes(),b'abcd'*100000)
            with self.assertRaisesRegex(ValueError,'absent'):
                stage_members([archive],root/'stage',['missing.shp'],0)

    def test_path_escape_and_disk_reserve(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'source.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('../escaped.shp',b'unsafe')
                z.writestr('safe.shp',b'safe')
            with self.assertRaisesRegex(ValueError,'Unsafe'):
                stage_members([archive],root/'stage',['../escaped.shp'],0)
            with self.assertRaisesRegex(RuntimeError,'reserve'):
                stage_members([archive],root/'stage',['safe.shp'],2**63)


if __name__=='__main__':unittest.main()

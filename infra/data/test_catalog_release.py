import json,tempfile,unittest
from pathlib import Path
from catalog_release import build

class CatalogTests(unittest.TestCase):
    def fixture(self,root):
        public=root/'public';folder=public/'world-buildings/r';folder.mkdir(parents=True)
        (folder/'mesh.b3dm').write_bytes(b'example');(folder/'unused.b3dm').write_bytes(b'old')
        (folder/'footprints.json').write_text('[]');(folder/'tileset.json').write_text(json.dumps({'root':{'content':{'uri':'mesh.b3dm'}}}))
        regions=[{'id':'r','z':14,'x':13976,'y':6310,'bounds':[127,37,128,38],'url':'/world-buildings/r/tileset.json','footprints':'/world-buildings/r/footprints.json','coverage':[],'partialCoverage':['16/55904/25240']}]
        catalog=public/'world-buildings/catalog.json';catalog.write_text(json.dumps({'source':'https://example/a.pmtiles','regions':regions}))
        return public,catalog,regions

    def test_snapshot_shards_preserve_records_and_exclude_unreferenced_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);public,catalog,regions=self.fixture(root);out=root/'output';r=build(catalog,public,out,publish=True)
            index=json.loads((out/r['latest']['index']).read_text());shard=json.loads((out/index['shards'][0]['href']).read_text())
            self.assertEqual(shard['regions'],regions);self.assertEqual(r['assetFiles'],3)
            self.assertNotIn('r/unused.b3dm',[x['key'] for x in r['assets']]);self.assertTrue((out/'latest.json').exists())

    def test_missing_dependency_never_advances_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);public,catalog,_=self.fixture(root);(public/'world-buildings/r/mesh.b3dm').unlink()
            with self.assertRaises(FileNotFoundError):build(catalog,public,root/'output',publish=True)
            self.assertFalse((root/'output/latest.json').exists())

if __name__=='__main__':unittest.main()

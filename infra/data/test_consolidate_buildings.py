import json,tempfile,unittest
from pathlib import Path
from consolidate_buildings import consolidate

class ConsolidationTests(unittest.TestCase):
    def test_verified_copy_preserves_source_and_excludes_mutable_root_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';(source/'region').mkdir(parents=True)
            (source/'region/mesh.b3dm').write_bytes(b'mesh');(source/'catalog.json').write_text('{}')
            receipt=root/'receipts.jsonl';target=root/'external'
            result=consolidate(source,target,receipt)
            self.assertEqual(result,{'files':1,'bytes':4,'originalsDeleted':0})
            self.assertEqual((source/'region/mesh.b3dm').read_bytes(),(target/'region/mesh.b3dm').read_bytes())
            self.assertFalse((target/'catalog.json').exists())
            self.assertEqual(len(json.loads(receipt.read_text())['sha256']),64)

    def test_conflicting_immutable_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'external'
            for base in [source,target]:(base/'region').mkdir(parents=True)
            (source/'region/mesh.b3dm').write_bytes(b'new');(target/'region/mesh.b3dm').write_bytes(b'old')
            with self.assertRaisesRegex(ValueError,'Conflicting'):consolidate(source,target,root/'receipts.jsonl')
            self.assertEqual((target/'region/mesh.b3dm').read_bytes(),b'old')

if __name__=='__main__':unittest.main()

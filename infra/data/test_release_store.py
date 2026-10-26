import json,tempfile,unittest
from pathlib import Path
from release_store import atomic_json,locked,seal,activate,read_json,verify

class ReleaseTests(unittest.TestCase):
    def test_v2_requires_bound_browser_pass_including_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=self.fixture(root);activate(root,first['releaseId'])
            file=root/'world-terrain/new.pmtiles';file.write_bytes(b'new')
            second=seal(root,{'schema':'ace-map-release-v2','runtimeValidationRequired':True},[file])
            proof={'schema':'ngii-national-browser-validation-v1','status':'PASS','releaseId':second['releaseId'],
                   'filesReceiptSHA256':second['filesReceiptSHA256'],'renderer':'national','isolatedCandidate':True,
                   'buildingSourceCount':1,'legacyBuildingRequests':0,'terrainRequests':3,'errors':0,
                   'distances':{'near':'PASS','mid':'PASS','far':'PASS'}}
            path=root/'browser.json'
            for reason in ('activate','rollback'):
                with self.assertRaisesRegex(ValueError,'requires runtime'):
                    activate(root,second['releaseId'],reason=reason)
                for changes in ({'releaseId':first['releaseId']},{'filesReceiptSHA256':'0'*64},
                                {'status':'FAIL'},{'errors':1},{'terrainRequests':0},{'buildingSourceCount':2},
                                {'legacyBuildingRequests':1},{'isolatedCandidate':False},
                                {'distances':{'near':'PASS','mid':'PASS'}},{'terrainRequests':True}):
                    atomic_json(path,{**proof,**changes})
                    with self.assertRaisesRegex(ValueError,'Runtime validation'):
                        activate(root,second['releaseId'],reason=reason,runtime_validation_path=path)
                    self.assertEqual(read_json(root/'releases/current.json'),first)
            atomic_json(path,proof)
            activate(root,second['releaseId'],runtime_validation_path=path)
            events=[read_json(p) for p in (root/'management/history').glob('*.json')]
            self.assertEqual([e['runtimeValidation']['evidence'] for e in events if 'runtimeValidation' in e],[proof])
            activate(root,first['releaseId'],reason='rollback')
            activate(root,second['releaseId'],reason='rollback',runtime_validation_path=path)

    def test_v2_false_flag_cannot_bypass_guard_and_changed_files_still_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'asset';file.write_bytes(b'old')
            second=seal(root,{'schema':'ace-map-release-v2','runtimeValidationRequired':False},[file])
            with self.assertRaisesRegex(ValueError,'requires runtime'):
                activate(root,second['releaseId'])
            file.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Release file'):
                activate(root,second['releaseId'])
            self.assertFalse((root/'releases/current.json').exists())

    def test_expected_current_guards_activation_and_conditional_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=self.fixture(root);activate(root,first['releaseId'])
            other=root/'world-terrain/other.pmtiles';other.write_bytes(b'other')
            second=seal(root,{'schema':'ace-map-release-v1'},[other])
            with self.assertRaisesRegex(ValueError,'expected current'):
                activate(root,second['releaseId'],expected_current='f'*64)
            self.assertEqual(read_json(root/'releases/current.json')['releaseId'],first['releaseId'])
            activate(root,second['releaseId'],expected_current=first['releaseId'])
            with self.assertRaisesRegex(ValueError,'expected current'):
                activate(root,first['releaseId'],reason='rollback',expected_current=first['releaseId'])
            self.assertEqual(read_json(root/'releases/current.json')['releaseId'],second['releaseId'])
            activate(root,first['releaseId'],reason='rollback',expected_current=second['releaseId'])
            self.assertEqual(read_json(root/'releases/current.json')['releaseId'],first['releaseId'])

    def test_stale_candidate_cannot_overwrite_newly_active_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=self.fixture(root);activate(root,first['releaseId'])
            other=root/'world-terrain/other.pmtiles';other.write_bytes(b'other')
            stale=seal(root,{'schema':'ace-map-release-v1','predecessorRelease':None},[other])
            with self.assertRaisesRegex(ValueError,'Active release changed'):activate(root,stale['releaseId'])
            self.assertEqual(read_json(root/'releases/current.json'),first)
    def fixture(self,root,content=b'first'):
        file=root/'world-terrain/sample.pmtiles';file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(content)
        return seal(root,{'schema':'ace-map-release-v1','buildings':{'version':'20261009-2f30a80f'},'terrain':{'url':'sample.pmtiles'}},[file])

    def test_activation_and_rollback_restore_whole_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=self.fixture(root)
            activate(root,first['releaseId'])
            other=root/'world-terrain/other.pmtiles';other.write_bytes(b'other')
            second=seal(root,{'schema':'ace-map-release-v1','buildings':{'version':'20261010-aaaaaaaa'},'terrain':{'url':'other.pmtiles'}},[other])
            activate(root,second['releaseId']);activate(root,first['releaseId'],reason='rollback')
            self.assertEqual(read_json(root/'releases/current.json'),first)
            self.assertEqual(len(list((root/'management/history').glob('*.json'))),3)

    def test_changed_file_refuses_activation_and_preserves_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=self.fixture(root);activate(root,first['releaseId'])
            (root/'world-terrain/sample.pmtiles').write_bytes(b'changed')
            with self.assertRaises(ValueError):activate(root,first['releaseId'])
            self.assertEqual(read_json(root/'releases/current.json'),first)

    def test_missing_file_and_second_writer_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(FileNotFoundError):seal(root,{},[root/'missing'])
            with locked(root):
                with self.assertRaises(OSError):
                    with locked(root):pass

    def test_receipts_cannot_reference_files_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);outside=root/'outside';outside.write_bytes(b'secret')
            with self.assertRaises(ValueError):seal(root/'data',{},[outside])

if __name__=='__main__':unittest.main()

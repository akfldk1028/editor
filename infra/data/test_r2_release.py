import io
import gzip
import hashlib
import json
import posixpath
import tempfile
import unittest
import contextlib
from pathlib import Path
from unittest.mock import patch
from r2_release import public_asset, national_asset, transport_manifest, publish, promote, export_plan, Failure, IMMUTABLE, main
from release_store import digest, encoded, seal, verify


class FakeS3:
    def __init__(self): self.objects = {}; self.writes = []; self.corrupt = 0; self.before_put = None
    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            error = Exception('secret endpoint must not escape')
            error.response = {'Error': {'Code': '404'}}
            raise error
        data, args = self.objects[Key]
        return {'ContentLength': len(data), 'Metadata': args.get('Metadata', {}), 'ETag': hashlib.md5(data).hexdigest(), **({'ContentEncoding': args['ContentEncoding']} if 'ContentEncoding' in args else {})}
    def get_object(self, Bucket, Key):
        data, _ = self.objects[Key]
        if self.corrupt:
            self.corrupt -= 1; data = b'corrupted'
        return {'Body': io.BytesIO(data)}
    def upload_file(self, Filename, Bucket, Key, ExtraArgs, **kwargs):
        self.objects[Key] = (Path(Filename).read_bytes(), ExtraArgs); self.writes.append(Key)
    def put_object(self, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None, **kwargs):
        if self.before_put: hook, self.before_put = self.before_put, None; hook()
        current = self.objects.get(Key)
        if (IfNoneMatch == '*' and current is not None) or (IfMatch is not None and (current is None or hashlib.md5(current[0]).hexdigest() != IfMatch)):
            error = Exception('precondition'); error.response = {'Error': {'Code': 'PreconditionFailed'}}; raise error
        self.objects[Key] = (Body, kwargs); self.writes.append(Key)


class R2Tests(unittest.TestCase):
    def test_dry_run_needs_no_settings_or_sdk_and_errors_are_redacted(self):
        argv=['r2_release.py','--data-root','unused','--release-id','a'*64,'--dry-run']
        output=io.StringIO()
        with patch('sys.argv',argv), patch('r2_release.export_plan',return_value=(self.manifest(),[])), patch('r2_release.load_settings',side_effect=AssertionError('must not read settings')), contextlib.redirect_stdout(output):
            self.assertEqual(main(),0)
        self.assertFalse(json.loads(output.getvalue())['networkWrites'])
        output=io.StringIO()
        with patch('sys.argv',argv), patch('r2_release.export_plan',side_effect=Exception('secret-account-url')), contextlib.redirect_stdout(output):
            self.assertEqual(main(),1)
        self.assertNotIn('secret-account',output.getvalue())

    def fixture(self, root):
        key = 'tiles/buildings/20261009-2f30a80f/buildings.pmtiles'
        p = root/key; p.parent.mkdir(parents=True); p.write_bytes(b'tiles')
        m=p.with_name('manifest.json'); m.write_text(json.dumps({'version':'20261009-2f30a80f','layer':'buildings'}))
        self.scene={'key':m.relative_to(root).as_posix(),'bytes':m.stat().st_size,'sha256':digest(m)}
        return {'key': key, 'bytes': 5, 'sha256': digest(p)}
    def manifest(self):
        return {'schema':'ace-map-release-v1','releaseId':'a'*64,
            'buildings':{'version':'20261009-2f30a80f','href':'/api/map-data/buildings/20261009-2f30a80f/buildings.pmtiles'},
            'buildingCatalog':{'index':'catalogs/x/index.json'}, 'terrain':{'url':'/api/map-data/world-terrain/a.pmtiles'}}
    def test_allowlist_and_transport_do_not_mutate_local_manifest(self):
        for key in ['management/key.json','.env','raw/source.zip','world-buildings/../secret.json','world-buildings/state.json','world-buildings/a/keys.json']:
            self.assertFalse(public_asset(key))
        self.assertTrue(public_asset('world-buildings/region/tileset.json'))
        original = self.manifest(); remote = transport_manifest(original, 'https://assets.example')
        self.assertNotIn('assetBases', original)
        self.assertEqual(remote['sourceReleaseId'], original['releaseId'])
        self.assertNotEqual(remote['releaseId'], original['releaseId'])
        self.assertEqual(remote['assetBases']['buildings'],'https://assets.example/tiles/buildings')
        rid=remote.pop('releaseId')
        self.assertEqual(rid,hashlib.sha256(encoded(remote)).hexdigest())
        with self.assertRaises(Failure):transport_manifest({'schema':'ace-map-release-v3','releaseId':'a'*64},'https://assets.example')
        with self.assertRaises(Failure):transport_manifest({'schema':'ace-map-release-v2','releaseId':'a'*64},'https://assets.example')

    def test_failed_owned_write_resumes_and_logs_failure_without_secret(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);row=self.fixture(root);client=FakeS3()
            kwargs=dict(client=client,bucket='fixture',root=root,manifest=self.manifest(),rows=[row,self.scene],base='https://assets.example',work=root/'private',workers=1,retries=1)
            original=client.upload_file
            def broken(*a,**k):
                original(*a,**k)
                key=a[2];_,extra=client.objects[key];client.objects[key]=(b'wrong',extra)
            with patch.object(client,'upload_file',side_effect=broken):
                with self.assertRaises(Failure):publish(**kwargs)
            self.assertFalse(json.loads((root/'private/objects.jsonl').read_text().splitlines()[0])['verified'])
            publish(**kwargs)
            self.assertEqual(client.objects[row['key']][0],b'tiles')
            self.assertNotIn('secret endpoint',(root/'private/objects.jsonl').read_text())

    def test_missing_sealed_scene_manifest_prevents_all_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);row=self.fixture(root);client=FakeS3()
            with self.assertRaises(Failure):publish(client=client,bucket='fixture',root=root,manifest=self.manifest(),rows=[row],base='https://assets.example',work=root/'private')
            self.assertEqual(client.writes,[])
    def test_verified_assets_precede_pointers_and_resume_rechecks_get(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); row=self.fixture(root); client=FakeS3(); kwargs=dict(client=client,bucket='fixture',root=root,manifest=self.manifest(),rows=[row,self.scene],base='https://assets.example',work=root/'private',workers=2,retries=1)
            publish(**kwargs)
            self.assertEqual(client.writes[-1], 'releases/current.json')
            self.assertGreater(client.writes.index('tiles/buildings/latest.json'),client.writes.index(row['key']))
            self.assertEqual(client.objects[row['key']][1]['CacheControl'],IMMUTABLE)
            count=client.writes.count(row['key']); publish(**kwargs)
            self.assertEqual(client.writes.count(row['key']),count)
    def test_corrupt_created_object_retries_but_foreign_collision_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); row=self.fixture(root); client=FakeS3(); client.corrupt=1
            kwargs=dict(client=client,bucket='fixture',root=root,manifest=self.manifest(),rows=[row,self.scene],base='https://assets.example',work=root/'private',workers=1,retries=1)
            publish(**kwargs); self.assertEqual(client.writes.count(row['key']),2)
            client.objects[row['key']]=(b'foreign',{'Metadata':{'sha256':'wrong'}})
            before=len(client.writes)
            with self.assertRaises(Failure):publish(**kwargs)
            self.assertEqual(len(client.writes),before)
    def test_failure_keeps_all_latest_pointers_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); row=self.fixture(root); client=FakeS3(); client.corrupt=50
            with self.assertRaises(Failure):publish(client=client,bucket='fixture',root=root,manifest=self.manifest(),rows=[row,self.scene],base='https://assets.example',work=root/'private',workers=1,retries=1)
            self.assertNotIn('releases/current.json',client.objects)
            self.assertNotIn('tiles/buildings/latest.json',client.objects)


HLOD='world-buildings/national/'+'b'*64
REGION='world-buildings/national-regions-gzip-v2/14-1-2-'+'c'*16
TERRAIN='world-terrain/terrain-5c2f8cf2f24e1540fac1.pmtiles'


class NationalTests(unittest.TestCase):
    def sealed(self, root):
        files={TERRAIN:b'pmtiles',
            HLOD+'/tileset.json':json.dumps({'root':{'content':{'uri':'nodes/5-1-1.json'}}}).encode(),
            HLOD+'/nodes/5-1-1.json':json.dumps({'root':{'content':{'uri':'5-1-1.b3dm.gz'},'children':[
                {'content':{'uri':'/api/map-data/'+REGION+'/tileset.json'}}]}},separators=(',',':')).encode(),
            HLOD+'/nodes/5-1-1.b3dm.gz':gzip.compress(b'b3dm-node'),
            HLOD+'/summaries/5-1-1.json':b'[]', HLOD+'/candidate-inputs.json':b'{}', HLOD+'/candidate-receipt.json':b'{}',
            REGION+'/tileset.json':json.dumps({'root':{'content':{'uri':'14-1-2.b3dm.gz'}}}).encode(),
            REGION+'/14-1-2.b3dm.gz':gzip.compress(b'b3dm-region'),
            REGION+'/footprints.json.gz':gzip.compress(b'[]'), REGION+'/ground-source.json.gz':gzip.compress(b'{}'),
            REGION+'/candidate-receipt.json':b'{}', 'management/ngii-national-publications/x/coverage.json':b'{}'}
        for key,data in files.items(): (root/key).parent.mkdir(parents=True,exist_ok=True); (root/key).write_bytes(data)
        payload={'schema':'ace-map-release-v2','sourceFamily':'NGII-B021','runtimeValidationRequired':True,
            'terrain':{'url':'/api/map-data/'+TERRAIN,'sha256':digest(root/TERRAIN),'vrt_sha256':'d'*64,'heightContract':'resolved-ancestor-grid-v1'},
            'nationalBuildings':{'schema':'world-buildings/national-v1','url':'/api/map-data/'+HLOD+'/tileset.json'}}
        return seal(root,payload,[root/k for k in files])
    def proof(self, root, manifest):
        path=root/'proof.json'
        path.write_text(json.dumps({'schema':'ngii-national-browser-validation-v1','releaseId':manifest['releaseId'],
            'filesReceiptSHA256':manifest['filesReceiptSHA256'],'status':'PASS','isolatedCandidate':True,'renderer':'national',
            'buildingSourceCount':1,'legacyBuildingRequests':0,'errors':0,'terrainRequests':3,'distances':{'near':'PASS','mid':'PASS','far':'PASS'}}))
        return path

    def test_allowlist_serves_only_what_cesium_fetches(self):
        for key in [TERRAIN,HLOD+'/tileset.json',HLOD+'/nodes/5-1-1.json',HLOD+'/nodes/5-1-1.b3dm.gz',REGION+'/tileset.json',REGION+'/14-1-2.b3dm.gz']:
            self.assertTrue(national_asset(key),key)
        for key in [HLOD+'/summaries/5-1-1.json',HLOD+'/candidate-inputs.json',HLOD+'/candidate-receipt.json',REGION+'/footprints.json.gz',
                    REGION+'/ground-source.json.gz',REGION+'/candidate-receipt.json','world-terrain/archive.json','management/x/tileset.json']:
            self.assertFalse(national_asset(key),key)

    def test_plan_streams_and_rewrites_absolute_links_without_touching_sealed_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); manifest=self.sealed(root); node=root/HLOD/'nodes/5-1-1.json'; before=node.read_bytes()
            _,rows=export_plan(root,manifest['releaseId'])
            self.assertNotIsInstance(rows,list); first=list(rows); self.assertEqual(first,list(rows))
            self.assertEqual({r['key'] for r in first},{TERRAIN,HLOD+'/tileset.json',HLOD+'/nodes/5-1-1.json',HLOD+'/nodes/5-1-1.b3dm.gz',REGION+'/tileset.json',REGION+'/14-1-2.b3dm.gz'})
            rewritten=[r for r in first if 'sourceSHA256' in r]
            self.assertEqual([r['key'] for r in rewritten],[HLOD+'/nodes/5-1-1.json'])
            self.assertEqual(rewritten[0]['sourceSHA256'],digest(node)); self.assertEqual(node.read_bytes(),before)
            verify(root,manifest['releaseId'],deep=True)

    def test_upload_requires_browser_proof_before_any_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); manifest=self.sealed(root); _,rows=export_plan(root,manifest['releaseId']); client=FakeS3()
            kwargs=dict(client=client,bucket='fixture',root=root,manifest=manifest,rows=rows,base='https://assets.example',work=root/'management/r2/x',workers=2,retries=1)
            with self.assertRaises(Failure):publish(**kwargs)
            bad=root/'bad.json'; bad.write_text(json.dumps({'schema':'ngii-national-browser-validation-v1','status':'FAIL'}))
            with self.assertRaises(Failure):publish(**kwargs,validation=bad)
            self.assertEqual(client.writes,[])

    def test_upload_serves_like_local_route_and_links_resolve_on_r2(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); manifest=self.sealed(root); _,rows=export_plan(root,manifest['releaseId']); client=FakeS3()
            kwargs=dict(client=client,bucket='fixture',root=root,manifest=manifest,rows=rows,base='https://assets.example/',
                work=root/'management/r2/x',workers=2,retries=1,validation=self.proof(root,manifest))
            result=publish(**kwargs)
            self.assertTrue(client.writes[-1].startswith('releases/') and client.writes[-1].endswith('/manifest.json'))
            self.assertNotIn('releases/current.json',client.objects); self.assertNotIn('tiles/buildings/latest.json',client.objects)
            self.assertEqual(result['state'],'uploaded-unpromoted')
            for key in [HLOD+'/nodes/5-1-1.b3dm.gz',REGION+'/14-1-2.b3dm.gz']:
                data,args=client.objects[key]
                self.assertEqual((args['ContentEncoding'],args['ContentType'],args['CacheControl']),('gzip','application/octet-stream',IMMUTABLE))
                self.assertEqual(data,(root/key).read_bytes())
            data,args=client.objects[HLOD+'/nodes/5-1-1.json']
            self.assertNotIn(b'/api/map-data',data); self.assertEqual(args['Metadata']['sha256'],hashlib.sha256(data).hexdigest())
            uri=json.loads(data)['root']['children'][0]['content']['uri']
            self.assertEqual(posixpath.normpath(posixpath.join(HLOD+'/nodes',uri)),REGION+'/tileset.json')
            self.assertFalse([k for k in client.objects if k.endswith(('receipt.json','inputs.json','footprints.json.gz','ground-source.json.gz')) or '/summaries/' in k or k.startswith('management')])
            remote=json.loads(client.objects[client.writes[-1]][0])
            self.assertEqual(remote['assetBases'],{'world-buildings':'https://assets.example/world-buildings','terrain':'https://assets.example/world-terrain'})
            self.assertEqual((remote['terrain'],remote['nationalBuildings']),(manifest['terrain'],manifest['nationalBuildings']))
            self.assertEqual((remote['sourceReleaseId'],result['fileCount']),(manifest['releaseId'],6))
            self.assertIn('runtimeValidationSHA256',result)
            count=len(client.writes); publish(**kwargs)
            self.assertEqual([k for k in client.writes[count:] if not k.startswith('releases/')],[])

    def test_promote_needs_r2_browser_pass_and_compares_current_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); manifest=self.sealed(root); _,rows=export_plan(root,manifest['releaseId']); client=FakeS3()
            result=publish(client=client,bucket='fixture',root=root,manifest=manifest,rows=rows,base='https://assets.example/',
                work=root/'management/r2/x',workers=2,retries=1,validation=self.proof(root,manifest))
            rid=result['remoteReleaseId']
            local=json.loads(self.proof(root,manifest).read_text())
            proof=root/'r2-proof.json'
            # A local-route PASS is not evidence for the relinked R2 objects.
            proof.write_text(json.dumps(local))
            with self.assertRaises(Failure): promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id=rid,validation=proof,expected_current='none')
            proof.write_text(json.dumps({**local,'remoteReleaseId':rid,'baseUrl':'https://assets.example'}))
            with self.assertRaises(Failure): promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id=rid,validation=proof,expected_current='b'*64)
            self.assertNotIn('releases/current.json',client.objects)
            self.assertEqual(promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id=rid,validation=proof,expected_current='none')['state'],'promoted')
            self.assertEqual(json.loads(client.objects['releases/current.json'][0])['releaseId'],rid)
            # Rerunning the same promotion is idempotent and writes nothing.
            count=len(client.writes)
            self.assertEqual(promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id=rid,validation=proof,expected_current='none')['state'],'already-current')
            self.assertEqual(len(client.writes),count)
            # A stale run for another release that still expects the old (empty) pointer cannot move it.
            client.objects['releases/'+'d'*64+'/manifest.json']=(json.dumps({**json.loads(client.objects['releases/current.json'][0]),'releaseId':'d'*64}).encode(),{})
            other=root/'other-proof.json'; other.write_text(json.dumps({**local,'remoteReleaseId':'d'*64,'baseUrl':'https://assets.example'}))
            with self.assertRaises(Failure) as caught: promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id='d'*64,validation=other,expected_current='none')
            self.assertEqual(str(caught.exception),'CURRENT_POINTER_CHANGED')
            # A writer that slips in between our read and write loses to the conditional put, not to us.
            client.objects.pop('releases/current.json')
            client.before_put=lambda: client.objects.__setitem__('releases/current.json',(b'{"releaseId":"other"}',{}))
            with self.assertRaises(Failure) as caught: promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id=rid,validation=proof,expected_current='none')
            self.assertEqual(str(caught.exception),'CURRENT_POINTER_CHANGED')
            self.assertEqual(client.objects['releases/current.json'][0],b'{"releaseId":"other"}')
            # The proof must belong to the sealed source release.
            with self.assertRaises(Failure): promote(client=client,bucket='fixture',base='https://assets.example/',remote_release_id=rid,validation=proof,expected_current='none',source={'releaseId':'c'*64})

    def test_foreign_gzip_without_encoding_and_changed_local_link_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); manifest=self.sealed(root); _,rows=export_plan(root,manifest['releaseId']); proof=self.proof(root,manifest)
            kwargs=dict(bucket='fixture',root=root,manifest=manifest,rows=rows,base='https://assets.example',work=root/'management/r2/x',workers=1,retries=0,validation=proof)
            key=REGION+'/14-1-2.b3dm.gz'; row=next(r for r in rows if r['key']==key); client=FakeS3()
            client.objects[key]=((root/key).read_bytes(),{'Metadata':{'sha256':row['sha256']}})
            with self.assertRaises(Failure):publish(client=client,**kwargs)
            self.assertEqual(client.objects[key][1],{'Metadata':{'sha256':row['sha256']}}); self.assertNotIn('releases/current.json',client.objects)
            node=root/HLOD/'nodes/5-1-1.json'; node.write_bytes(node.read_bytes().replace(b'5-1-1.b3dm',b'5-1-2.b3dm'))
            with self.assertRaises(Failure):list(rows)

    def test_dry_run_counts_v2_without_network_or_settings(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); manifest=self.sealed(root); output=io.StringIO()
            argv=['r2_release.py','--data-root',str(root),'--release-id',manifest['releaseId'],'--dry-run']
            with patch('sys.argv',argv), patch('r2_release.load_settings',side_effect=AssertionError('must not read settings')), contextlib.redirect_stdout(output):
                self.assertEqual(main(),0)
            report=json.loads(output.getvalue())
            self.assertEqual((report['schema'],report['publicFiles'],report['rewrittenLinkFiles'],report['networkWrites']),('ace-map-release-v2',6,1,False))


if __name__=='__main__':unittest.main()

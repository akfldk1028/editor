import hashlib
import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingest_ngii_buildings import open_db, packed
from prepare_ngii_national_release import prepare, PROVINCES, MESH, PACKING, CONTRACT, HLOD, public_url
from release_store import atomic_json, digest, encoded, read_json, verify


class NationalPreparationTests(unittest.TestCase):
    def test_completed_snapshot_matches_database_and_incomplete_rejected(self):
        from ngii_canonical_snapshot import initialize, identity
        snap=initialize(self.plan,self.root/'canonical.sqlite',self.root/'delta')
        snap['complete']=True;snap['delta'].update(identity(snap['delta']['path']))
        path=self.root/'delta/canonical-snapshot.json';atomic_json(path,snap)
        args=(self.root,self.root/'canonical.sqlite',self.root/'plan.json',self.root/'regions.json',
              self.root/'hlod-input.json',self.hlod,self.root/'terrain.json',self.work)
        expected=prepare(*args)
        result=prepare(args[0],path,*args[2:],snapshot=True)
        self.assertEqual(result['releaseId'],expected['releaseId'])
        wal=Path(snap['delta']['path']+'-wal');wal.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'delta changed'):prepare(args[0],path,*args[2:],snapshot=True)
        wal.unlink()
        snap['complete']=False;atomic_json(path,snap)
        with self.assertRaisesRegex(ValueError,'incomplete'):prepare(args[0],path,*args[2:],snapshot=True)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        # These payload tests use one synthetic tile rather than a national map.
        lon=1.5/16384*360-180
        lat=math.degrees(math.atan(math.sinh(math.pi*(1-2*1.5/16384))))
        probes=patch.dict('prepare_ngii_national_release.GEOGRAPHIC_PROBES',{'fixture':(lon,lat)},clear=True)
        probes.start();self.addCleanup(probes.stop)
        self.root=Path(self.tmp.name).resolve();r=self.root
        source=r/'source.zip';source.write_bytes(b'official fixture')
        atomic_json(r/'source.zip.receipt.json',{'bytes':source.stat().st_size,'sha256':digest(source)})
        manifest={'family':'NGII-B021','productCode':'B021','productKind':'continuous-topographic','edition':'2024'}
        self.plan={'schema':'ngii-canonical-plan-v1','storageSchema':'canonical-sqlite-v2','expectedRows':17,
                   'sources':[{'id':'source','expectedRows':17,'manifest':manifest,'bindings':[{'path':str(source),
                   'bytes':source.stat().st_size,'mtimeNs':source.stat().st_mtime_ns,'sha256':digest(source),
                   'receiptSHA256':digest(r/'source.zip.receipt.json')}]}]}
        self.plan['planSHA256']=hashlib.sha256(packed(self.plan).encode()).hexdigest();(r/'plan.json').write_text(packed(self.plan),encoding='utf-8')
        db=open_db(r/'canonical.sqlite',self.plan)
        keys=['ngii:'+hashlib.sha256(p.encode()).hexdigest() for p in sorted(PROVINCES)]
        with db:
            db.execute("UPDATE sources SET next_row=17,status='complete'")
            for i,p in enumerate(sorted(PROVINCES)):
                db.execute('INSERT INTO buildings VALUES(?,?,?,?,?,?,?,?)',(keys[i],'14/1/1','16/4/4',None,p+'00000000',3.4,'{}',b''))
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?)',('source',i,keys[i],p+'00000000','inserted'))
        db.close()
        atomic_json(r/'regions.json',{'schema':'ngii-canonical-regions-v1','planSHA256':self.plan['planSHA256'],
            'sourceComplete':True,'sourceRows':17,'buildingCount':17,'regionCount':1,'regions':[{'region14':'14/1/1','buildings':17,'components':17}]})
        terrain=r/'world-terrain/terrain.pmtiles';terrain.parent.mkdir();terrain.write_bytes(b'terrain');self.terrain_sha=digest(terrain)
        pointer={'url':public_url(r,terrain,'world-terrain'),'sha256':self.terrain_sha,'vrt_sha256':'a'*64,'heightContract':CONTRACT};atomic_json(r/'terrain.json',pointer)
        self.region=r/'world-buildings/regions/region';self.region.mkdir(parents=True);self.hlod=r/'world-buildings/national/hlod';self.hlod.mkdir(parents=True)
        ground={'archiveSha256':self.terrain_sha,'contract':CONTRACT,'buildings':[{'id':k,'provenance':{**manifest,'row':i},'ground':{'archiveSha256':self.terrain_sha,
            'contract':CONTRACT,'height':0 if i==0 else 10,'sourceLevels':[-1] if i==0 else [14],'ellipsoidZero':i==0}} for i,k in enumerate(keys)]}
        self.regional={'schema':'ngii-region-candidate-v1','completeRegion':True,'owner':'14/1/1','buildings':17,'components':17,
             'supportedGroundBuildings':16,'unresolvedGroundBuildings':1,'sourcePlanSHA256':self.plan['planSHA256'],
             'sourcePlanFileSHA256':digest(r/'plan.json'),'terrainSHA256':self.terrain_sha,'meshRevision':MESH,'assetPacking':PACKING,'terrainContract':CONTRACT,
             'files':self.files(self.region,{'tileset.json':{'root':{'content':{'uri':'tile.b3dm.gz'}}},'tile.b3dm.gz':b'fixture-mesh',
                 'footprints.json.gz':[{'key':k+'/0','z':0 if i==0 else 10} for i,k in enumerate(keys)],'ground-source.json.gz':ground})}
        atomic_json(self.region/'candidate-receipt.json',self.regional)
        inputs={'sourcePlanSHA256':self.plan['planSHA256'],'terrainSHA256':self.terrain_sha,
                'regions':[{'owner':'14/1/1','folder':str(self.region),'uri':public_url(r,self.region/'tileset.json')}]}
        atomic_json(r/'hlod-input.json',inputs)
        pins=[{'owner':'14/1/1','receiptSHA256':digest(self.region/'candidate-receipt.json'),'uri':inputs['regions'][0]['uri']}]
        self.revision=hashlib.sha256(encoded(pins)).hexdigest()
        atomic_json(self.hlod/'candidate-receipt.json',{'revision':HLOD,'mesh':MESH,'assetPacking':PACKING,'sourcePlanSHA256':self.plan['planSHA256'],
            'terrainSHA256':self.terrain_sha,'sampleOnly':False,'completeRegion':True,'publishable':False,'pins':pins,
            'regions':1,'buildings':17,'components':17,'files':self.files(self.hlod,{'tileset.json':{'root':{'content':{'uri':pins[0]['uri']}}}})})
        self.work=r/'work'
        atomic_json(self.work/'archive-receipt.json',{'sha256':self.terrain_sha,'metadata':{'sourceFilesSHA256':'b'*64}})
        atomic_json(self.work/'publication-verification.json',{'sha256':self.terrain_sha,'httpStatus':206})
        atomic_json(self.work/'height-verification.json',{'terrainArchiveSHA256':self.terrain_sha,'sourceVrtSHA256':'a'*64,
            'complete':True,'sampleOnly':False,'passed':True,'nativeFinite':16,'nativeNoData':1,'nativeEvidence':'recorded',
            'buildingCatalogSHA256':self.revision,'sourceFilesSHA256':'b'*64,'missing':0,'absoluteErrorMetres':{'maximum':.1},
            'nativeDisagreement':{'gate':'record-only','thresholdMetres':.5,'maxMetres':.1,'regionsOver':0,'buildingsOver':0},
            'publishedBuildingDatumCheck':{'expected':17,'compared':17,'maximumAbsoluteErrorMetres':0},
            'regions':[{'owner':'14/1/1','buildings':17,'components':17,'passed':True,'nativeMaximumMetres':.1,'nativeOver':0}]})

    def files(self,folder,values):
        rows=[]
        for name,value in values.items():
            p=folder/name
            extra={}
            if name.endswith('.gz'):
                if not isinstance(value,bytes):value=encoded(value)
                extra={'contentEncoding':'gzip','decodedBytes':len(value),'decodedSHA256':hashlib.sha256(value).hexdigest()}
                p.write_bytes(gzip.compress(value,compresslevel=6,mtime=0))
            elif isinstance(value,bytes):p.write_bytes(value)
            else:atomic_json(p,value)
            rows.append({'path':name,'bytes':p.stat().st_size,'sha256':digest(p),**extra})
        return rows

    def run_prepare(self):
        r=self.root
        return prepare(r,r/'canonical.sqlite',r/'plan.json',r/'regions.json',r/'hlod-input.json',self.hlod,r/'terrain.json',self.work)

    def test_seals_v2_without_activation_or_legacy_fields_and_retains_nodata(self):
        result=self.run_prepare()
        self.assertEqual(result['schema'],'ace-map-release-v2')
        self.assertNotIn('buildings',result);self.assertNotIn('buildingCatalog',result)
        self.assertEqual(result['coverage']['supportedGroundBuildings'],16)
        self.assertEqual(result['coverage']['unresolvedGroundBuildings'],1)
        self.assertTrue(result['runtimeValidationRequired'])
        self.assertFalse((self.root/'releases/current.json').exists())
        self.assertEqual(verify(self.root,result['releaseId'],deep=True),result)

    def test_seal_reuses_payload_hashes_from_verification_without_rereading(self):
        import release_store
        from prepare_ngii_national_release import payload_files
        known={};payload_files(self.root,self.region,self.regional,known)
        self.assertEqual({p.name:v[2] for p,v in known.items()},{f['path']:f['sha256'] for f in self.regional['files']})
        reread=[];real=release_store.digest
        def counted(path):
            if path.resolve().is_relative_to(self.region) or path.resolve().is_relative_to(self.hlod):reread.append(path.resolve())
            return real(path)
        with patch('release_store.digest',side_effect=counted):result=self.run_prepare()
        self.assertEqual(reread,[(self.hlod/'candidate-receipt.json').resolve()])  # one small HLOD receipt only
        self.assertEqual(verify(self.root,result['releaseId'],deep=True),result)

    def test_old_asset_packing_cannot_enter_new_national_release(self):
        self.regional.pop('assetPacking')
        atomic_json(self.region/'candidate-receipt.json',self.regional)
        with self.assertRaises(ValueError):self.run_prepare()

    def test_encoded_and_decoded_mesh_hashes_are_both_verified(self):
        from prepare_ngii_national_release import payload_files
        mesh=next(f for f in self.regional['files'] if f['path'].endswith('.b3dm.gz'))
        payload_files(self.root,self.region,self.regional)
        mesh['decodedSHA256']='f'*64
        with self.assertRaisesRegex(ValueError,'Decoded'):payload_files(self.root,self.region,self.regional)
        path=self.region/mesh['path'];path.write_bytes(b'not gzip')
        mesh['bytes']=path.stat().st_size;mesh['sha256']=digest(path)
        with self.assertRaisesRegex(ValueError,'gzip'):payload_files(self.root,self.region,self.regional)

    def test_compressed_metadata_requires_decoded_hash_and_rejects_invalid_json(self):
        from prepare_ngii_national_release import payload_files
        for name in ('footprints.json.gz','ground-source.json.gz'):
            row=next(f for f in self.regional['files'] if f['path']==name)
            expected=row['decodedSHA256'];row['decodedSHA256']='f'*64
            with self.assertRaisesRegex(ValueError,'Decoded'):payload_files(self.root,self.region,self.regional)
            row['decodedSHA256']=expected
        decoded=b'not-json';path=self.region/'ground-source.json.gz';path.write_bytes(gzip.compress(decoded,mtime=0))
        row=next(f for f in self.regional['files'] if f['path']==path.name)
        row.update(bytes=path.stat().st_size,sha256=digest(path),decodedBytes=len(decoded),decodedSHA256=hashlib.sha256(decoded).hexdigest())
        atomic_json(self.region/'candidate-receipt.json',self.regional)
        with self.assertRaises(ValueError):self.run_prepare()

    def test_mesh_namespace_cannot_publish_private_candidate_paths(self):
        with self.assertRaisesRegex(ValueError,'namespace'):public_url(self.root,self.root/'ngii-mesh-candidates/private/tileset.json')
        self.assertTrue(public_url(self.root,self.region/'tileset.json').startswith('/api/map-data/world-buildings/'))

    def test_missing_province_is_reported_without_dropping_or_relabeling_building(self):
        db=open_db(self.root/'canonical.sqlite',self.plan)
        with db:
            db.execute("UPDATE buildings SET bjcd='-' WHERE id=(SELECT id FROM buildings LIMIT 1)")
            db.execute("INSERT INTO observations VALUES('missing-original',0,'existing','-','duplicate')")
        db.close()
        result=self.run_prepare()
        self.assertEqual(result['coverage']['unclassifiedProvinceBuildings'],1)
        self.assertEqual(result['coverage']['buildings'],17)
        self.assertEqual(result['coverage']['provinces'],sorted(PROVINCES))
        db=open_db(self.root/'canonical.sqlite',self.plan)
        with db:db.execute("UPDATE observations SET bjcd='99' WHERE source_id='missing-original'")
        db.close()
        with self.assertRaisesRegex(ValueError,'province'):self.run_prepare()

    def test_incomplete_source_rejected(self):
        db=open_db(self.root/'canonical.sqlite',self.plan)
        with db:db.execute("UPDATE sources SET next_row=16,status='partial'")
        db.close()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.run_prepare()

    def test_missing_region_rejected(self):
        path=self.root/'hlod-input.json';v=read_json(path);v['regions']=[];atomic_json(path,v)
        with self.assertRaisesRegex(ValueError,'region set'):self.run_prepare()

    def test_partial_and_ground_overclaim_rejected(self):
        self.regional['completeRegion']=False;atomic_json(self.region/'candidate-receipt.json',self.regional)
        with self.assertRaisesRegex(ValueError,'coverage'):self.run_prepare()
        self.regional['completeRegion']=True;self.regional['supportedGroundBuildings']=17
        atomic_json(self.region/'candidate-receipt.json',self.regional)
        with self.assertRaisesRegex(ValueError,'recovered'):self.run_prepare()

    def test_payload_tampering_and_path_escape_rejected(self):
        (self.region/'tileset.json').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'hash'):self.run_prepare()
        self.regional['files'][0]['path']='../outside';atomic_json(self.region/'candidate-receipt.json',self.regional)
        with self.assertRaisesRegex(ValueError,'path'):self.run_prepare()

    def test_terrain_binding_rejected(self):
        p=self.work/'height-verification.json';v=read_json(p);v['terrainArchiveSHA256']='c'*64;atomic_json(p,v)
        with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()

    def test_sample_or_insufficient_native_evidence_cannot_publish(self):
        path=self.work/'height-verification.json';original=read_json(path)
        for key,value in [('complete',False),('sampleOnly',True),('passed',False),
                          ('nativeFinite',0),('nativeFinite',True),('nativeEvidence','insufficient')]:
            atomic_json(path,{**original,key:value})
            with self.subTest(key=key,value=value):
                with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()

    def test_wholesale_terrain_offset_beyond_sanity_cap_cannot_publish(self):
        path=self.work/'height-verification.json';v=read_json(path)
        v['absoluteErrorMetres']={'maximum':25.0};v['nativeDisagreement'].update(maxMetres=25.0,regionsOver=1,buildingsOver=1)
        v['regions']=[{**v['regions'][0],'nativeMaximumMetres':25.0,'nativeOver':1}]
        atomic_json(path,v)
        with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()
        atomic_json(path,{**v,'regions':[]})
        with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()

    def test_single_outlier_region_beyond_cap_is_recorded_not_blocking(self):
        path=self.work/'height-verification.json';v=read_json(path)
        v['absoluteErrorMetres']={'maximum':31.0};v['nativeDisagreement'].update(maxMetres=31.0,regionsOver=1,buildingsOver=1)
        v['regions']=[{**v['regions'][0],'nativeMaximumMetres':31.0,'nativeOver':1}]+[{**v['regions'][0],'owner':f'14/2/{i}','nativeMaximumMetres':.2} for i in range(2)]
        atomic_json(path,v)
        self.assertEqual(self.run_prepare()['nativeDisagreement']['maxMetres'],31.0)

    def test_native_dem_disagreement_is_recorded_not_a_gate(self):
        path=self.work/'height-verification.json';v=read_json(path)
        v['absoluteErrorMetres']={'maximum':2.37};v['nativeDisagreement'].update(maxMetres=2.37,regionsOver=1,buildingsOver=3)
        atomic_json(path,v)
        result=self.run_prepare()
        self.assertEqual(result['nativeDisagreement'],{'maxMetres':2.37,'regionsOver':1,'buildingsOver':3,'thresholdMetres':.5,'gate':'record-only'})
        for broken in [{},{**v['nativeDisagreement'],'gate':'blocking'},{**v['nativeDisagreement'],'maxMetres':1.0},
                       {**v['nativeDisagreement'],'regionsOver':2},{**v['nativeDisagreement'],'regionsOver':True},
                       {**v['nativeDisagreement'],'buildingsOver':0},{**v['nativeDisagreement'],'buildingsOver':None}]:
            atomic_json(path,{**v,'nativeDisagreement':broken})
            with self.subTest(broken=broken):
                with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()
        atomic_json(path,{**v,'nativeEvidence':'verified'})
        with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()

    def test_datum_gate_still_blocks_publication(self):
        path=self.work/'height-verification.json';v=read_json(path)
        atomic_json(path,{**v,'publishedBuildingDatumCheck':{**v['publishedBuildingDatumCheck'],'maximumAbsoluteErrorMetres':.011}})
        with self.assertRaisesRegex(ValueError,'alignment'):self.run_prepare()

    def test_known_island_source_gaps_are_recorded_but_other_empty_probes_fail(self):
        from prepare_ngii_national_release import GEOGRAPHIC_PROBES
        probes=dict(GEOGRAPHIC_PROBES,Baengnyeong=(124.65,37.95),Goseong=(128.36,38.51))
        with patch.dict('prepare_ngii_national_release.GEOGRAPHIC_PROBES',probes,clear=True):
            result=self.run_prepare()
        self.assertEqual(result['coverage']['sourceCoverageGaps'],['Baengnyeong','Goseong'])
        with patch.dict('prepare_ngii_national_release.GEOGRAPHIC_PROBES',dict(probes,Seoul=(126.98,37.57)),clear=True):
            with self.assertRaisesRegex(ValueError,'Missing geographic source coverage: Seoul'):self.run_prepare()

    def test_terrain_requires_same_sampling_contract(self):
        path=self.root/'terrain.json';pointer=read_json(path);pointer.pop('heightContract');atomic_json(path,pointer)
        with self.assertRaisesRegex(ValueError,'height contract'):self.run_prepare()

    def test_missing_referenced_mesh_rejected(self):
        self.regional['files']=[f for f in self.regional['files'] if f['path']!='tile.b3dm.gz']
        atomic_json(self.region/'candidate-receipt.json',self.regional)
        with self.assertRaisesRegex(ValueError,'tileset content'):self.run_prepare()

    def test_unresolved_issue_and_missing_province_rejected(self):
        db=open_db(self.root/'canonical.sqlite',self.plan)
        with db:db.execute('INSERT INTO issues VALUES(?,?,?,?)',('source',0,'conflict','{}'))
        db.close()
        with self.assertRaisesRegex(ValueError,'issues'):self.run_prepare()
        db=open_db(self.root/'canonical.sqlite',self.plan)
        with db:
            db.execute('DELETE FROM issues');db.execute("UPDATE observations SET bjcd='1100000000'")
        db.close()
        with self.assertRaisesRegex(ValueError,'province'):self.run_prepare()

    def test_hlod_receipt_must_bind_exact_regional_pins(self):
        p=self.hlod/'candidate-receipt.json';v=read_json(p);v['pins'][0]['receiptSHA256']='d'*64;atomic_json(p,v)
        with self.assertRaisesRegex(ValueError,'national HLOD'):self.run_prepare()


if __name__=='__main__':unittest.main()

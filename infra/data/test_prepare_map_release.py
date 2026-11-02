import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from release_store import atomic_json,digest,read_json,verify
from prepare_map_release import prepare

class PreparationTests(unittest.TestCase):
    def fixture(self,root):
        catalog=root/'world-buildings/catalog.json'
        atomic_json(catalog,{'source':'http://localhost/scene/tiles/buildings/20261009-2f30a80f/buildings.pmtiles','regions':[{'z':14,'x':1,'y':1,'coverage':['16/4/4']}]})
        revision=digest(catalog)
        latest={'schema':'world-buildings/latest-v1','revision':revision,'source':read_json(catalog)['source'],'index':f'catalogs/{revision}/index.json'}
        atomic_json(root/'world-buildings/latest.json',latest);atomic_json(root/'world-buildings'/latest['index'],{'shards':[]})
        atomic_json(root/'management/catalog-plans'/f'{revision}.json',{'latest':latest,'assets':[]})
        archive=root/'tiles/buildings/20261009-2f30a80f/buildings.pmtiles';archive.parent.mkdir(parents=True);archive.write_bytes(b'buildings')
        atomic_json(archive.parent/'manifest.json',{})
        terrain=root/'world-terrain/terrain.pmtiles';terrain.parent.mkdir();terrain.write_bytes(b'terrain')
        pointer={'url':'/api/map-data/world-terrain/terrain.pmtiles','sha256':digest(terrain),'vrt_sha256':'a'*64}
        atomic_json(terrain.parent/'archive.json',pointer)
        work=root/'work';atomic_json(work/'archive-receipt.json',{**pointer,'metadata':{'version':1,'sourceFilesSHA256':'e'*64}})
        atomic_json(work/'publication-verification.json',{'sha256':pointer['sha256']})
        atomic_json(work/'height-verification.json',{'sourceFilesSHA256':'e'*64,'absoluteErrorMetres':{'maximum':.1},'sourceVrtSHA256':'a'*64,'terrainArchiveSHA256':pointer['sha256'],'buildingCatalogSHA256':revision,'missing':0,'publishedBuildingDatumCheck':{'expected':1,'compared':1,'maximumAbsoluteErrorMetres':0}})
        return work

    @patch('prepare_map_release.audit',return_value={'sourceZ14Tiles':1,'preparedRegions':1,'sourceWithoutPreparedRegion':[]})
    def test_new_evidence_never_mutates_previous_release(self,audit):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=self.fixture(root);first=prepare(root,work)
            receipt=read_json(work/'archive-receipt.json');receipt['metadata']['version']=2;atomic_json(work/'archive-receipt.json',receipt)
            second=prepare(root,work)
            self.assertNotEqual(first['releaseId'],second['releaseId'])
            self.assertEqual(verify(root,first['releaseId'],deep=True),first)
            self.assertEqual(second['coverage']['partialCoordinates'],1)
            ledger=read_json(root/'management/gaps/current.json')
            self.assertTrue((root/ledger['issues'][0]['evidence']).is_file())

    def test_stale_height_validation_blocks_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=self.fixture(root);report=read_json(work/'height-verification.json');report['buildingCatalogSHA256']='b'*64
            atomic_json(work/'height-verification.json',report)
            with self.assertRaisesRegex(ValueError,'another dataset'):prepare(root,work)
            self.assertFalse((root/'releases/current.json').exists())

    @patch('prepare_map_release.audit',return_value={'sourceZ14Tiles':2,'preparedRegions':2,'sourceWithoutPreparedRegion':[]})
    def test_candidate_inputs_prepare_without_replacing_active_writer_pointers(self,audit):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=self.fixture(root)
            first=prepare(root,work);audit.reset_mock()
            active=root/'releases/current.json';atomic_json(active,first)
            originals={p:p.read_bytes() for p in [active,root/'world-buildings/catalog.json',root/'world-buildings/latest.json',root/'world-terrain/archive.json']}
            candidate=root/'candidate';catalog=candidate/'catalog.json'
            document=read_json(root/'world-buildings/catalog.json')
            document['regions'].append({'z':14,'x':1,'y':2,'coverage':['16/4/8']})
            atomic_json(catalog,document);revision=digest(catalog)
            latest={**read_json(root/'world-buildings/latest.json'),'revision':revision,'index':f'catalogs/{revision}/index.json'}
            latest_path=candidate/'latest.json';atomic_json(latest_path,latest)
            atomic_json(root/'world-buildings'/latest['index'],{'shards':[]})
            atomic_json(root/'management/catalog-plans'/f'{revision}.json',{'latest':latest,'assets':[]})
            terrain=root/'world-terrain/new-terrain.pmtiles';terrain.write_bytes(b'new terrain')
            pointer={**read_json(root/'world-terrain/archive.json'),'url':'/api/map-data/world-terrain/new-terrain.pmtiles','sha256':digest(terrain)}
            pointer_path=candidate/'terrain.json';atomic_json(pointer_path,pointer)
            receipt=read_json(work/'archive-receipt.json');receipt.update(pointer);atomic_json(work/'archive-receipt.json',receipt)
            atomic_json(work/'publication-verification.json',{'sha256':pointer['sha256']})
            heights=read_json(work/'height-verification.json');heights.update(buildingCatalogSHA256=revision,terrainArchiveSHA256=pointer['sha256'])
            atomic_json(work/'height-verification.json',heights)
            release=prepare(root,work,catalog_path=catalog,catalog_pointer_path=latest_path,terrain_pointer_path=pointer_path)
            self.assertEqual(release['buildingCatalog']['revision'],revision)
            self.assertEqual(release['terrain'],pointer)
            self.assertEqual(release['predecessorRelease'],first['releaseId'])
            self.assertEqual(verify(root,release['releaseId'],deep=True),release)
            audit.assert_called_once_with(root/'tiles/buildings/20261009-2f30a80f/buildings.pmtiles',catalog,rows=document['regions'])
            for path,raw in originals.items():self.assertEqual(path.read_bytes(),raw)

if __name__=='__main__':unittest.main()

import unittest
import json,tempfile
from pathlib import Path
from unittest.mock import patch
from bake_ground_candidate import compare_ground,reconcile_catalog,affected,include_duplicate_regions,require_unique_regions

class GroundProgressTests(unittest.TestCase):
    def test_duplicate_coordinates_are_scheduled_and_final_catalog_must_be_unique(self):
        first={'id':'old','z':14,'x':5,'y':6};second=dict(first,id='new')
        catalog={'regions':[first,{'id':'other','z':14,'x':7,'y':8},second]}
        self.assertEqual(include_duplicate_regions(['14/1/2'],catalog),['14/1/2','14/5/6'])
        with self.assertRaisesRegex(ValueError,'Duplicate building region coordinates'):
            require_unique_regions(catalog)
        require_unique_regions({'regions':[second,catalog['regions'][1]]})
        with self.assertRaisesRegex(ValueError,'Invalid building region coordinates'):
            include_duplicate_regions([],{'regions':[dict(first,x=-1)]})

    def test_reconciliation_skips_nonowner_assets_but_requires_relevant_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'owner').mkdir();asset=root/'owner/footprints.json'
            asset.write_text(json.dumps([{'key':'16/4/8/1','z':20}]))
            catalog={'regions':[{'id':'unreadable','z':14,'x':9,'y':9},{'id':'owner','z':14,'x':1,'y':2}]}
            result,cache=reconcile_catalog(catalog,root,{'16/4/8/1'})
            self.assertEqual(result['newlyFilled'],1)
            self.assertEqual(set(cache['regions']),{'owner'})
            catalog['regions'][0]['z']=None
            with self.assertRaises(FileNotFoundError):reconcile_catalog(catalog,root,{'16/4/8/1'},cache)
            catalog['regions'][0]['z']=14
            with self.assertRaises(FileNotFoundError):reconcile_catalog(catalog,root,{'unparseable'},cache)
            asset.unlink()
            with self.assertRaises(FileNotFoundError):reconcile_catalog(catalog,root,{'16/4/8/1'},cache)

    def test_reordered_common_precision_invalidates_union_but_new_insertion_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            import numpy as np,rasterio
            from rasterio.transform import from_origin
            root=Path(temp)
            def source(name,x):
                path=root/(name+'.tif')
                with rasterio.open(path,'w',driver='GTiff',width=2,height=2,count=1,dtype='float32',crs='EPSG:5186',transform=from_origin(x,450000,5,5),nodata=-9999) as ds:ds.write(np.ones((2,2),dtype='float32'),1)
                return {'path':str(path),'sha256':name}
            a=source('a',200000);b=source('b',300000);c=source('c',250000)
            old={'base':a['path'],'sources':[a,b]}
            reordered={'base':a['path'],'sources':[b,a]}
            self.assertEqual(affected(reordered,old),affected(reordered))
            inserted={'base':a['path'],'sources':[a,c,b]}
            self.assertEqual(affected(inserted,old),affected({'base':a['path'],'sources':[c]}))
            with self.assertRaisesRegex(ValueError,'Base DEM signature changed'):
                affected({'base':b['path'],'sources':[a,b]},old)

    def test_reports_only_previously_missing_keys_as_filled(self):
        before=[{'key':'existing','z':10}]
        after=[{'key':'existing','z':12},{'key':'gap','z':20},{'key':'gap','z':20},{'key':'other','z':30}]
        result=compare_ground(before,after,{'gap','still-missing'})
        self.assertEqual(result['newlyFilledKeys'],['gap'])
        self.assertEqual(result['existingHeightChanged'],1)
        self.assertEqual(result['remaining'],1)
    def test_missing_or_invalid_values_do_not_count_as_repaired(self):
        result=compare_ground([], [{'key':'a','z':None},{'key':'b','z':float('nan')}], {'a','b'})
        self.assertEqual(result['newlyFilled'],0)

    def test_cumulative_recovery_includes_earlier_batches_and_rechecks_changed_regions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def write(region,features):
                folder=root/region;folder.mkdir(exist_ok=True)
                (folder/'footprints.json').write_text(json.dumps(features))
            write('a',[{'key':'gap-a','z':10}]);write('b',[{'key':'old','z':20}])
            catalog={'regions':[{'id':'a'},{'id':'b'}]};missing={'gap-a','gap-b','gap-c'}
            first,cache=reconcile_catalog(catalog,root,missing)
            self.assertEqual(first['newlyFilled'],1)
            write('b-new',[{'key':'gap-b','z':30}]);catalog['regions'][1]={'id':'b-new'}
            from bake_ground_candidate import read_json
            with patch('bake_ground_candidate.read_json',wraps=read_json) as reader:
                second,cache=reconcile_catalog(catalog,root,missing,cache)
                self.assertEqual(reader.call_count,1)
            self.assertEqual(second['newlyFilledKeys'],['gap-a','gap-b'])
            self.assertEqual(second['remaining'],1)
            write('a',[{'key':'gap-a','z':None}])
            third,cache=reconcile_catalog(catalog,root,missing,cache)
            self.assertEqual(third['newlyFilledKeys'],['gap-b'])
            self.assertEqual(third['remaining'],2)
            other,_=reconcile_catalog(catalog,root,{'old'},cache)
            self.assertEqual(other['newlyFilled'],0)

if __name__=='__main__':unittest.main()

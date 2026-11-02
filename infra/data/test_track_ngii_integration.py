import importlib.util
import pathlib
import sqlite3
import tempfile
import unittest
import json
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('monitor', pathlib.Path(__file__).with_name('track_ngii_integration.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MonitorTests(unittest.TestCase):
    def test_refinement_progress_requires_matching_script_and_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder).resolve()
            (root/'progress.json').write_text(json.dumps({'state':'refining','verifiedRegions':42}))
            (root/'refinement.lock').write_text('123')
            with patch.object(m.psutil, 'Process') as process:
                process.return_value.cmdline.return_value=['bun','refine-ngii-national-terrain.ts','--work',str(root)]
                process.return_value.cwd.return_value=str(root)
                result=m.progress_status(root,'refine-ngii-national-terrain.ts','refinement.lock')
                self.assertTrue(result['workerMatchesCandidate'])
                self.assertEqual(result['verifiedRegions'],42)
                process.return_value.cmdline.return_value=['python','unrelated.py','--work',str(root)]
                self.assertFalse(m.progress_status(root,'refine-ngii-national-terrain.ts','refinement.lock')['workerMatchesCandidate'])

    def test_v2_delivery_probes_national_root_without_legacy_catalog(self):
        url='/api/map-data/world-buildings/national/version/tileset.json'
        with patch.object(m, 'read', side_effect=AssertionError('Legacy catalog must not be read')):
            self.assertEqual(m.release_building_url(pathlib.Path('unused'),
                {'schema':'ace-map-release-v2','nationalBuildings':{'url':url}}),url)
        with self.assertRaisesRegex(ValueError,'national building URL'):
            m.release_building_url(pathlib.Path('unused'),
                {'schema':'ace-map-release-v2','nationalBuildings':{'url':'https://untrusted.invalid/a'}})

    def test_quality_failure_is_preserved_as_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'height-verification.json'
            report={'state':'quality_failed','complete':False,'passed':False,'pendingRegions':25937,
                    'nativeFinite':14,'absoluteErrorMetres':{'maximum':2.3704846379762756}}
            path.write_text(json.dumps(report))
            result=m.height_verification_status(path)
            self.assertEqual(result['state'],'quality_failed')
            self.assertFalse(result['passed'])
            self.assertEqual(result['absoluteErrorMetres'],report['absoluteErrorMetres'])

    def test_national_completed_receipts_cached_and_staging_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder); regions=root/'regions.json'
            inventory={'schema':'ngii-canonical-regions-v1','sourceComplete':True,'planSHA256':'plan',
                       'regionCount':2,'buildingCount':5,'regions':[{'region14':'14/1/1','buildings':2},{'region14':'14/1/2','buildings':3}]}
            regions.write_text(json.dumps(inventory))
            digest=m.hashlib.sha256(regions.read_bytes()).hexdigest()
            binding={'sourcePlan':'plan','expectedTerrain':'terrain','inventorySHA256':digest,'assetPacking':'gzip'}
            (root/'candidate-inputs.json').write_text(json.dumps(binding))
            part=root/'14-1-1-a';part.mkdir()
            value={'schema':'ngii-region-candidate-v1','completeRegion':True,'owner':'14/1/1',
                   'sourcePlanSHA256':'plan','terrainSHA256':'terrain','inventorySHA256':digest,'assetPacking':'gzip',
                   'buildings':2,'supportedGroundBuildings':1,'unresolvedGroundBuildings':1,'files':[{'bytes':123}]}
            receipt=part/'candidate-receipt.json';receipt.write_text(json.dumps(value))
            (root/'.staging'/'14-1-2-a').mkdir(parents=True)
            (root/'.staging'/'14-1-2-a'/'candidate-receipt.json').write_text(json.dumps(value))
            (root/'14-1-2-partial').mkdir()
            monitor=m.NationalBakeMonitor()
            first=monitor.status(root,regions)
            self.assertEqual((first['completedRegions'],first['buildings'],first['payloadBytes']), (1,2,123))
            self.assertEqual((first['stagingCount'],first['partialFolders']), (1,1))
            self.assertIn('national_bake_work_remaining_worker_missing',first['alerts'])
            with patch.object(pathlib.Path,'read_bytes',side_effect=AssertionError('unchanged document reread')):
                self.assertEqual(monitor.status(root,regions)['buildings'],2)
            (root/'queue-status.json').write_text(json.dumps({'state':'baking','pid':42,'childPID':43}))
            with patch.object(m.psutil,'Process') as process:
                process.return_value.cwd.return_value=folder
                process.return_value.cmdline.return_value=['python','queue_ngii_national_bake.py','--output',str(root)]
                running=monitor.status(root,regions)
                self.assertTrue(running['processes'][0]['matchesCandidate'])
                self.assertFalse(running['processes'][1]['matchesCandidate'])
                self.assertNotIn('national_bake_work_remaining_worker_missing',running['alerts'])
                process.return_value.cmdline.return_value=['python','queue_ngii_national_bake.py','--output',str(root/'other')]
                self.assertIn('national_bake_work_remaining_worker_missing',monitor.status(root,regions)['alerts'])
            (root/'queue-status.json').unlink()
            value['terrainSHA256']='wrong';receipt.write_text(json.dumps(value))
            result=monitor.status(root,regions)
            self.assertEqual(result['completedRegions'],0)
            self.assertIn('national_bake_receipt_mismatch',result['alerts'])

    def test_national_inventory_rejects_unbound_or_incomplete_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);regions=root/'regions.json'
            regions.write_text(json.dumps({'regions':[],'sourceComplete':False}))
            (root/'candidate-inputs.json').write_text('{}')
            with self.assertRaises(ValueError):m.NationalBakeMonitor().status(root,regions)

    def test_frozen_base_uses_cumulative_delta_cursors_without_double_count(self):
        from ngii_canonical_snapshot import initialize
        from ingest_ngii_buildings import open_db
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);base=root/'buildings.sqlite'
            plan={'planSHA256':'test','sources':[{'id':'a','expectedRows':100,'manifest':{}}]}
            db=open_db(base,plan)
            with db:db.execute("UPDATE sources SET next_row=40,status='partial'")
            db.close();initialize(plan,base,root/'delta')
            db=open_db(root/'delta/buildings.sqlite',plan)
            with db:db.execute("UPDATE sources SET next_row=70")
            db.close()
            result=m.database_status(base)
            self.assertEqual(result['processedRows'],70)
            self.assertFalse(result['snapshotComplete'])
            self.assertTrue(m.worker_matches(['python','ngii_canonical_snapshot.py','run','--output',str(root/'delta')],root/'delta/buildings.sqlite',root))
            self.assertFalse(m.worker_matches(['python','ngii_canonical_snapshot.py','run','--output',str(root/'other')],root/'delta/buildings.sqlite',root))

    def test_obsolete_candidate_does_not_raise_worker_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            old, active = pathlib.Path(folder) / 'old', pathlib.Path(folder) / 'active'
            for path in [old, active]:
                path.mkdir()
                (path / 'queue-progress.json').write_text(json.dumps({'pid': 42, 'state': 'batch-complete', 'jobsCompleted': 32, 'jobsTotal': 1931, 'results': {}, 'cohortSHA256': 'a'}))
            with patch.object(m.psutil, 'Process') as process, patch.object(m, 'terrain_worker_matches', side_effect=[False, True]):
                process.return_value.cwd.return_value = folder
                result = m.terrain_status([old, active], active)
            self.assertEqual(result['alerts'], [])
            self.assertFalse(result['candidates'][0]['healthPrimary'])
            self.assertTrue(result['candidates'][1]['healthPrimary'])

    def test_terrain_worker_must_match_plan_and_script(self):
        candidate = pathlib.Path('C:/Data/candidate-v2')
        args = ['python', 'loop_ngii_terrain_targets.py', '--plan', str(candidate / 'plan.json')]
        self.assertTrue(m.terrain_worker_matches(args, candidate, pathlib.Path.cwd()))
        self.assertFalse(m.terrain_worker_matches(args, pathlib.Path('C:/Data/old'), pathlib.Path.cwd()))
        self.assertFalse(m.terrain_worker_matches(['python', 'unrelated.py'] + args[2:], candidate, pathlib.Path.cwd()))

    def test_incomplete_batch_missing_worker_is_alert(self):
        state = {'state': 'batch-complete', 'jobsCompleted': 32, 'jobsTotal': 1931, 'workerAlive': False}
        self.assertIn('terrain_work_remaining_worker_missing', m.terrain_alerts(state))
        state['workerAlive'] = True
        self.assertEqual(m.terrain_alerts(state), [])

    def test_failed_or_storage_state_alert_even_with_live_worker(self):
        for state in ['failed', 'needs_storage']:
            self.assertIn('terrain_' + state, m.terrain_alerts({'state': state, 'workerAlive': True}))

    def test_static_url_preserves_catalog_root(self):
        self.assertEqual(m.building_url('/world-buildings/14-1-1-ab/tileset.json'), '/api/map-data/world-buildings/14-1-1-ab/tileset.json')

    def test_union_rejects_other_cohort_and_deduplicates(self):
        result = m.filled_union([{'cohortSHA256': 'a', 'filledKeys': ['1', '2']}, {'cohortSHA256': 'a', 'filledKeys': ['2', '3']}, {'cohortSHA256': 'b', 'filledKeys': ['4']}], 'a')
        self.assertEqual(result, {'filledKeysUnion': 3, 'rejectedCohortResults': 1})

    def test_database_uses_committed_source_cursors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'buildings.sqlite'
            with sqlite3.connect(path) as db:
                db.executescript("CREATE TABLE sources(expected_rows,next_row,status); INSERT INTO sources VALUES(100,100,'complete'),(200,37,'partial'); CREATE TABLE issues(kind); INSERT INTO issues VALUES('bad');")
            db.close()
            result = m.database_status(path)
            self.assertEqual(result['processedRows'], 137)
            self.assertEqual(result['expectedRows'], 300)
            self.assertEqual(result['completeSources'], 1)
            self.assertEqual(result['issues'], 1)

    def test_worker_requires_same_output_database(self):
        db = pathlib.Path('C:/Data/canonical/buildings.sqlite')
        self.assertTrue(m.worker_matches(['python', 'ingest_ngii_buildings.py', 'run', '--output', 'C:/Data/canonical'], db, pathlib.Path.cwd()))
        self.assertFalse(m.worker_matches(['python', 'ingest_ngii_buildings.py', 'run', '--output', 'C:/Data/other'], db, pathlib.Path.cwd()))


if __name__ == '__main__':
    unittest.main()

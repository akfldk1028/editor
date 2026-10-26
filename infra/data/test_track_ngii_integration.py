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

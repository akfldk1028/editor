import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from loop_ngii_terrain_targets import main


class QueueTests(unittest.TestCase):
    def test_resume_uses_verified_result_receipts_without_repeating_completed_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'plan.json').write_text(json.dumps({'candidateId':'candidate'}))
            (root/'priority.json').write_text(json.dumps({'sha256':'cohort','count':1,'jobs':[{'cell':[1,2],'targetKeys':['a'],'targetCount':1}]}))
            (root/'supported.json').write_text(json.dumps([{'key':'a'}]))
            def work(*_):
                target=root/'target-patches/1-2';target.mkdir(parents=True,exist_ok=True)
                (target/'result.json').write_text(json.dumps({'cohortSHA256':'cohort','candidateId':'candidate','targetCount':1,'filledKeys':['a'],'unfilledKeys':[]}))
            args=['loop','--plan',str(root/'plan.json'),'--priority',str(root/'priority.json'),'--supported-keys',str(root/'supported.json'),'--limit','1']
            with patch('sys.argv',args),patch('loop_ngii_terrain_targets.reserve',side_effect=RuntimeError('20 GiB storage reserve before extraction')):
                with self.assertRaises(RuntimeError):main()
                self.assertEqual(json.loads((root/'queue-progress.json').read_text())['state'],'needs_storage')
            with patch('sys.argv',args),patch('loop_ngii_terrain_targets.reserve'),patch('loop_ngii_terrain_targets.run',side_effect=work) as run,patch('loop_ngii_terrain_targets.faulthandler.dump_traceback_later') as timer:
                main();main()
                self.assertEqual(run.call_count,1)
                timer.assert_not_called()
                state=json.loads((root/'queue-progress.json').read_text())
                self.assertEqual((state['state'],state['filledKeys'],state['targetKeysChecked']),('complete',1,1))


if __name__=='__main__':unittest.main()

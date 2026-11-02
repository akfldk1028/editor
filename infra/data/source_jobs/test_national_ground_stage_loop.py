import json,tempfile,unittest
from pathlib import Path
from national_ground_stage_loop import signature,stage_counts

class StageWatchTests(unittest.TestCase):
    def test_source_failures_and_exclusions_are_explicit_after_successful_process_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'terrain-stage-status.json').write_text(json.dumps({'results':{'a':{'state':'staged'},'b':{'state':'failed'},'c':{'state':'ambiguous_crs_rejected'}}}))
            self.assertEqual(stage_counts(root),{'stagedSources':1,'failedSources':1,'excludedSources':1})
    def test_receipt_or_catalogue_arrival_reopens_completed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'files').mkdir();initial=signature(root)
            (root/'files/a.dxf').write_bytes(b'not verified')
            self.assertEqual(signature(root),initial)
            (root/'files/a.dxf.receipt.json').write_text('{}')
            receipt=signature(root);self.assertNotEqual(receipt,initial)
            (root/'17-catalogue.json').write_text('[]')
            self.assertNotEqual(signature(root),receipt)

if __name__=='__main__':unittest.main()

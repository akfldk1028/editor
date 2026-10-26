import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from queue_ngii_national_bake import coordinate, writer_lock, RESERVE, RETRY_GROWTH


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.args=SimpleNamespace(output=str(self.root/'out'),snapshot=str(self.root/'snapshot.json'),plan=str(self.root/'plan.json'),
            terrain=str(self.root/'terrain.pmtiles'),terrain_sha='a'*64,regions=str(self.root/'regions.json'),
            bun='bun',python='python',editor_root=str(self.root/'editor'),watch=False,limit=16)
        Path(self.args.plan).write_text('{}');Path(self.args.terrain).write_bytes(b'archive')
        self.complete(False);self.commands=[]
    def complete(self,flag):Path(self.args.snapshot).write_text(json.dumps({'schema':'ngii-canonical-snapshot-v1','complete':flag}))
    def runner(self,cmd,cwd,log,started):
        self.commands.append(cmd);started(123);log.write_text('ok')
        if 'regions' in cmd:Path(cmd[cmd.index('--output')+1]).write_text('{"sourceComplete":true}')
        return 0
    def run_queue(self,**kw):return coordinate(self.args,runner=kw.pop('runner',self.runner),free=kw.pop('free',lambda _:RESERVE+1024**3),**kw)
    def test_incomplete_never_launches_bake_or_source_writer(self):
        self.assertEqual(self.run_queue()['state'],'waiting-source');self.assertEqual(self.commands,[])
    def test_watch_transitions_then_bounded_bake_and_resume_without_inventory_repeat(self):
        self.args.watch=True;sleeps=[]
        def sleep(seconds):sleeps.append(seconds);self.complete(True)
        result=self.run_queue(sleep=sleep)
        self.assertEqual(sleeps,[60]);self.assertEqual(result['state'],'bounded-complete')
        self.assertEqual(len(self.commands),3);self.assertEqual(self.commands[-1][-2:],['--limit','16'])
        self.assertFalse(result['activeNationalComplete']);self.assertNotIn('activate',str(self.commands))
        self.commands=[];self.assertEqual(self.run_queue()['state'],'bounded-complete')
        self.assertEqual(len(self.commands),2);self.assertFalse(any('regions' in c for c in self.commands))
    def test_receipt_gate_failure_stops_before_inventory_or_bake(self):
        self.complete(True)
        def fail(cmd,cwd,log,started):self.commands.append(cmd);started(9);log.write_text('source mismatch');return 2
        result=self.run_queue(runner=fail)
        self.assertEqual(result['state'],'failed');self.assertEqual(result['exitCode'],2);self.assertEqual(len(self.commands),1)
    def test_needs_storage_waits_for_measurable_growth_not_poll_retry(self):
        self.complete(True);self.args.watch=True;capacity=[RESERVE+1024**3];bakes=[0];sleeps=[0]
        def runner(cmd,cwd,log,started):
            self.runner(cmd,cwd,log,started)
            if cmd[0]=='bun':
                bakes[0]+=1
                if bakes[0]==1:capacity[0]=RESERVE-1;log.write_text('20GiB free-space reserve');return 1
            return 0
        def sleep(seconds):
            sleeps[0]+=1
            self.assertEqual(bakes[0],1)
            if sleeps[0]==2:capacity[0]=RESERVE+RETRY_GROWTH*2
        result=self.run_queue(runner=runner,free=lambda _:capacity[0],sleep=sleep)
        self.assertEqual(result['state'],'bounded-complete');self.assertEqual(bakes[0],2);self.assertEqual(sleeps[0],2)
    def test_stop_and_failed_inputs_do_not_activate(self):
        self.complete(True);self.run_queue();Path(self.args.plan).write_text('{"changed":true}')
        self.commands=[];result=self.run_queue();self.assertEqual(result['state'],'failed');self.assertIn('inputs changed',result['error']);self.assertEqual(self.commands,[])
        (Path(self.args.output)/'STOP').write_text('stop');self.assertEqual(self.run_queue()['state'],'stopped')
    def test_verified_inventory_reuse_across_new_candidate_output_without_rescan(self):
        self.complete(True)
        Path(self.args.plan).write_text(json.dumps({'planSHA256':'plan','expectedRows':1}))
        def runner(cmd,cwd,log,started):
            self.runner(cmd,cwd,log,started)
            if 'regions' in cmd:Path(self.args.regions).write_text(json.dumps({'schema':'ngii-canonical-regions-v1',
                'sourceComplete':True,'planSHA256':'plan','sourceRows':1,'regionCount':1,'buildingCount':1,
                'regions':[{'region14':'14/1/1','buildings':1,'components':1}]}))
            return 0
        self.assertEqual(self.run_queue(runner=runner)['state'],'bounded-complete')
        self.args.reuse_regions_pin=str(Path(self.args.output)/'queue-inputs.json')
        self.args.output=str(self.root/'public-new-output');self.commands=[]
        self.assertEqual(self.run_queue(runner=runner)['state'],'bounded-complete')
        self.assertEqual(len(self.commands),2);self.assertFalse(any('regions' in cmd for cmd in self.commands))
        self.args.output=str(self.root/'another-output');Path(self.args.regions).write_text('{}')
        self.commands=[];result=self.run_queue(runner=runner)
        self.assertEqual(result['state'],'failed');self.assertIn('SHA256',result['error'])
        self.assertEqual(len(self.commands),1)

    def test_second_owner_cannot_overwrite_live_status(self):
        folder=Path(self.args.output);folder.mkdir();status=folder/'queue-status.json';status.write_text('{"pid":99}')
        with writer_lock(folder):
            with self.assertRaises(OSError):self.run_queue()
        self.assertEqual(status.read_text(),'{"pid":99}')
    def test_low_disk_without_watch_records_no_child(self):
        result=self.run_queue(free=lambda _:RESERVE-1)
        self.assertEqual(result['state'],'needs_storage');self.assertIsNone(result['childPID']);self.assertEqual(self.commands,[])


if __name__=='__main__':unittest.main()

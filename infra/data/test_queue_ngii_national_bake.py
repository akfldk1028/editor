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
        self.assertEqual(len(self.commands),3);self.assertEqual(self.commands[-1][-4:],['--limit','16','--reserve-gib','20.0'])
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
    def test_reserve_flag_lowers_threshold_and_is_forwarded_to_baker(self):
        self.complete(True);self.args.reserve_gib=5
        result=self.run_queue(free=lambda _:6*1024**3)
        self.assertEqual(result['state'],'bounded-complete');self.assertEqual(self.commands[-1][-2:],['--reserve-gib','5.0'])
        self.commands=[];self.assertEqual(self.run_queue(free=lambda _:4*1024**3)['state'],'needs_storage')
        self.assertEqual(self.commands,[])
        self.args.reserve_gib=.5
        with self.assertRaisesRegex(ValueError,'reserve-gib'):self.run_queue()
    def test_lowered_reserve_restart_is_not_held_by_previous_block(self):
        self.complete(True);self.args.reserve_gib=20
        self.assertEqual(self.run_queue(free=lambda _:RESERVE-1024**2)['state'],'needs_storage')
        self.args.reserve_gib=5;self.commands=[]
        self.assertEqual(self.run_queue(free=lambda _:RESERVE-1024**2)['state'],'bounded-complete')
        self.assertEqual(self.commands[-1][-2:],['--reserve-gib','5.0'])


if __name__=='__main__':unittest.main()

class ParallelTests(unittest.TestCase):
    def test_failure_stops_sibling_at_boundary_and_tracks_pids(self):
        from queue_ngii_national_bake import execute_parallel
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder);tick=[0];children=[];states=[]
            class Child:
                def __init__(self,pid):self.pid=pid
                def poll(self):
                    if self.pid==10:return 2 if tick[0]>=1 else None
                    return 0 if (output/'STOP').exists() and tick[0]>=3 else None
                def wait(self):return self.poll()
            def popen(*args,**kw):
                child=Child(10+len(children));children.append(child);return child
            result=execute_parallel([['bun','a'],['bun','b']],folder,output,lambda p,r:states.append((p,r)),python='python',free=lambda _:RESERVE+1024**3,sleep=lambda _:tick.__setitem__(0,tick[0]+1),popen=popen)
            self.assertEqual(result['reason'],'failed');self.assertEqual(result['exitCodes'],{'10':2,'11':0});self.assertEqual(tick[0],3)
            self.assertTrue((output/'STOP').exists());self.assertTrue(any(p==[10,11] for p,_ in states))

    def test_parallel_storage_guard_launches_no_children(self):
        from queue_ngii_national_bake import execute_parallel
        with tempfile.TemporaryDirectory() as folder:
            result=execute_parallel([['bun'],['bun']],folder,Path(folder),lambda *a:None,python='python',free=lambda _:RESERVE+RETRY_GROWTH,popen=lambda *a,**k:self.fail('must not launch'))
            self.assertEqual(result['reason'],'needs_storage')

    def test_parallel_storage_guard_uses_configured_reserve(self):
        from queue_ngii_national_bake import execute_parallel
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder);launched=[]
            class Child:
                pid=30
                def poll(self):return 0
                def wait(self):return 0
            def popen(*a,**k):launched.append(1);return Child()
            result=execute_parallel([['bun']],folder,output,lambda *a:None,python='python',free=lambda _:5*1024**3+RETRY_GROWTH,sleep=lambda _:None,popen=popen,reserve=5*1024**3)
            self.assertEqual(result['reason'],'complete');self.assertEqual(launched,[1])

    def test_parallel_storage_drop_requests_graceful_stop(self):
        from queue_ngii_national_bake import execute_parallel
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder);reads=[0];children=[]
            class Child:
                def __init__(self,pid):self.pid=pid
                def poll(self):return 0 if (output/'STOP').exists() else None
                def wait(self):return self.poll()
            def free(_):reads[0]+=1;return RESERVE+1024**3 if reads[0]==1 else RESERVE
            def popen(*a,**k):child=Child(20+len(children));children.append(child);return child
            result=execute_parallel([['bun'],['bun']],folder,output,lambda *a:None,python='python',free=free,sleep=lambda _:None,popen=popen)
            self.assertEqual(result['reason'],'needs_storage');self.assertEqual(result['exitCodes'],{'20':0,'21':0})

    def test_coordinator_initializes_before_launching_disjoint_workers(self):
        helper=QueueTests();helper.setUp()
        try:
            helper.complete(True);helper.args.workers=2;calls=[]
            def parallel(commands,cwd,output,status,**kwargs):
                self.assertIn('--initialize-only',helper.commands[-1]);self.assertTrue((output/'queue-inputs.json').exists())
                self.assertEqual([c[c.index('--shard-index')+1] for c in commands],['0','1']);calls.extend(commands)
                return {'reason':'complete','childPIDs':[1,2],'exitCodes':{'1':0,'2':0}}
            result=helper.run_queue(parallel_runner=parallel)
            self.assertEqual(result['state'],'bounded-complete');self.assertEqual(len(calls),2)
        finally:helper.doCleanups()

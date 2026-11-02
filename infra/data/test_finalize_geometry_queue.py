import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from finalize_geometry_queue import finalize
from queue_building_geometry import REVISION
from release_store import atomic_json, read_json, digest


class FinalizationTests(unittest.TestCase):
    def fixture(self, root):
        work=root/'queue';terrain=root/'terrain-work';dem=root/'fixed.vrt';points=root/'points.json'
        dem.write_bytes(b'fixed dem');points.write_text('[]')
        previous={'releaseId':'a'*64,'terrain':{'sha256':'d'*64,'vrt_sha256':digest(dem)}}
        atomic_json(root/'releases/current.json',previous)
        catalog={'source':'fixed','regions':[{'z':14,'x':1,'y':2,'meshRevision':REVISION}]}
        atomic_json(root/'world-buildings/catalog.json',catalog)
        revision=digest(root/'world-buildings/catalog.json')
        atomic_json(work/'plan.json',{'source':'fixed','allCoordinates':['14/1/2'],'targets':['14/1/2']})
        atomic_json(work/'status.json',{'state':'completed','remaining':0,'catalogSHA256':revision})
        atomic_json(terrain/'archive-receipt.json',{'sha256':'d'*64})
        atomic_json(terrain/'height-verification.json',{'missing':0,'absoluteErrorMetres':{'maximum':.1},'buildingCatalogSHA256':revision,
                    'publishedBuildingDatumCheck':{'expected':1,'compared':1,'maximumAbsoluteErrorMetres':0}})
        args=SimpleNamespace(data_root=root,queue_work=work,dem_root=root,editor_root=root,terrain_work=terrain,dem=dem,points=points,
                             expected_release='a'*64,base_url='http://127.0.0.1:3003')
        pins={'demSHA256':digest(dem),'pointsSHA256':digest(points)}
        candidate={'releaseId':'b'*64,'predecessorRelease':'a'*64,'buildingCatalog':{'revision':revision}}
        return args,pins,candidate

    def test_failed_queue_or_changed_release_never_activates(self):
        for changed in ['queue','release']:
            with tempfile.TemporaryDirectory() as directory:
                args,pins,candidate=self.fixture(Path(directory))
                if changed=='queue':atomic_json(args.queue_work/'status.json',{'state':'failed','remaining':1})
                else:atomic_json(args.data_root/'releases/current.json',{'releaseId':'c'*64})
                with patch('finalize_geometry_queue.activate') as activation, self.assertRaises(ValueError):finalize(args,pins)
                activation.assert_not_called()

    def test_height_gate_failure_never_publishes_catalog_or_activates(self):
        with tempfile.TemporaryDirectory() as directory:
            args,pins,candidate=self.fixture(Path(directory))
            report=read_json(args.terrain_work/'height-verification.json');report['missing']=1
            atomic_json(args.terrain_work/'height-verification.json',report)
            with patch('finalize_geometry_queue.health',return_value={}),patch('finalize_geometry_queue.run_command'),patch('finalize_geometry_queue.build') as build,patch('finalize_geometry_queue.activate') as activation:
                with self.assertRaisesRegex(ValueError,'accuracy gate'):finalize(args,pins)
                build.assert_not_called();activation.assert_not_called()

    def test_activation_is_pinned_and_post_health_failure_requests_only_conditional_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            args,pins,candidate=self.fixture(Path(directory))
            with patch('finalize_geometry_queue.health',side_effect=[{},ValueError('HTTP failed')]),patch('finalize_geometry_queue.run_command'),patch('finalize_geometry_queue.build'),patch('finalize_geometry_queue.prepare',return_value=candidate),patch('finalize_geometry_queue.activate',side_effect=[candidate,{'releaseId':'a'*64}]) as activation:
                with self.assertRaisesRegex(ValueError,'HTTP failed'):finalize(args,pins)
                self.assertEqual(activation.call_args_list[0].kwargs['expected_current'],'a'*64)
                self.assertEqual(activation.call_args_list[1].kwargs,{'reason':'rollback','expected_current':'b'*64})
                state=read_json(args.queue_work/'finalization-status.json')
                self.assertEqual(state['state'],'activated_health_failed')
                self.assertEqual(state['rollback']['state'],'restored_checkpoint')

    def test_changed_pinned_dem_aborts_before_http_or_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            args,pins,candidate=self.fixture(Path(directory));args.dem.write_bytes(b'changed')
            with patch('finalize_geometry_queue.health') as health,patch('finalize_geometry_queue.activate') as activation:
                with self.assertRaisesRegex(ValueError,'Pinned DEM'):finalize(args,pins)
                health.assert_not_called();activation.assert_not_called()


if __name__=='__main__':unittest.main()

"""An explicit surface design target is independent of a resolved legal count."""
import unittest
from unittest.mock import patch
from shapely.geometry import Polygon, box, mapping
from backend.app.modules.design.generation.maas.masterplan.planner import _plan_site_fixed


class DesignTargetTests(unittest.TestCase):
    def request(self, target=50):
        return {'pnu':'test', 'site':mapping(box(0,0,40,40)),
            'footprint':mapping(box(10,10,20,20)),
            'law':{'status':'needs_evidence','required_spaces':None},
            'rules':{'stall_width_m':2.5,'stall_length_m':5,
                'accessible_width_m':3.3,'accessible_length_m':5,'aisle_width_m':6},
            'options':{'parking_strategy':'ground_surface','max_basement_levels':0,
                **({'target_parking_stalls':target} if target is not None else {})}}

    def test_design_target_reaches_surface_packer_without_legal_approval(self):
        parked={'stalls':[], 'drive':Polygon(), 'provided':0,'accessible':0,'search_count':1}
        with patch('backend.app.modules.design.generation.maas.masterplan.planner.pack_level',return_value=parked) as pack:
            result=_plan_site_fixed(self.request())
        pack.assert_called_once()
        self.assertEqual(pack.call_args.args[3],50)
        self.assertFalse(result['handoff']['hard_pass'])
        self.assertIn('law parking requirement is missing',result['blocking'])
        self.assertIsNone(result['provenance']['law']['required_spaces'])

    def test_no_target_and_no_legal_count_does_not_generate(self):
        with patch('backend.app.modules.design.generation.maas.masterplan.planner.pack_level') as pack:
            _plan_site_fixed(self.request(None))
        pack.assert_not_called()

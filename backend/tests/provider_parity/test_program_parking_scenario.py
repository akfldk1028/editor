"""Explicit planning hypotheses must never become legal parking minima."""
from copy import deepcopy
import unittest
from backend.app.modules.law.reference.program_parking import review_parking


def request():
    return {'project_id':'own','program_id':'civic','program_revision':2,'input_hash':'snapshot',
        'assessment_date':'2026-10-01','site':{'input':'4115011300106840001'},
        'use_units':[{'use_unit_id':'u','space_refs':['a','b']}],
        'spaces':[{'space_id':'a','quantity':1,'area':{'value':2000,'basis':'gross','unit':'m2'}},
                  {'space_id':'b','quantity':1,'area':{'value':601.936409089,'basis':'gross','unit':'m2'}}],
        'requirements':{'parking_planning_scenario':{
            'use_unit_id':'u','space_refs':['a','b'], 'aggregation_scope':'single_use_facility',
            'classification':{'canonical_use':'공공업무시설','status':'proposed',
                'source_ref':'building_decree_annex_1/14가'},
            'area':{'value':2601.936409089,'unit':'m2','basis':'gross','source_ref':'own-Program'},
            'assumption':'gross_reservations_equal_parking_facility_area_for_scenario_only'}}}


class PlanningScenarioTests(unittest.TestCase):
    def test_explicit_gross_hypothesis_gets_owner_count_but_not_legal_minimum(self):
        result=review_parking(request())
        self.assertIsNone(result['required_spaces'])
        scenario=result['planning_scenario']
        self.assertEqual(scenario['status'],'conditional')
        self.assertEqual(scenario['proposed_spaces'],26)
        self.assertEqual(scenario['calculation']['selected_rule_id'],'uijeongbu_parking_appendix3_row_02')
        self.assertFalse(scenario['client_approved'])
        self.assertEqual(scenario['measurement_request']['space_refs'],['a','b'])
        self.assertIn('parking_facility_floor_area_excluded_m2',scenario['measurement_request']['required_facts'])
        self.assertEqual(scenario['measurement_request']['program_identity']['input_hash'],'snapshot')

    def test_never_infers_scenario_from_gross_or_target(self):
        value=request(); value['requirements']={'target_parking_stalls':50}
        result=review_parking(value)
        self.assertNotIn('planning_scenario',result)
        self.assertIsNone(result['required_spaces'])

    def test_wrong_coverage_area_or_assumption_refuses(self):
        for field,bad in [('space_refs',['a']),('area',{'value':50,'unit':'m2','basis':'gross','source_ref':'x'}),
                          ('assumption','approved'),('classification',{'canonical_use':'공공업무시설','status':'classified','source_ref':'x'})]:
            value=request(); value['requirements']['parking_planning_scenario'][field]=bad
            with self.subTest(field=field), self.assertRaises(ValueError): review_parking(value)

    def test_invalid_numbers_are_controlled_refusals(self):
        for amount in (True,float('nan'),float('inf'),10**400):
            value=request(); value['requirements']['parking_planning_scenario']['area']['value']=amount
            with self.subTest(amount=str(amount)[:15]), self.assertRaises(ValueError): review_parking(value)

    def test_no_input_mutation_and_no_shared_output_provenance(self):
        value=request(); before=deepcopy(value); result=review_parking(value)
        self.assertEqual(value,before)
        result['planning_scenario']['input_evidence']['space_refs'].append('x')
        self.assertEqual(value,before)


if __name__=='__main__': unittest.main()

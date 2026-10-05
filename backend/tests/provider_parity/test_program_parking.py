"""Program parking dispatch never borrows a planning target or an unqualified gross area."""
import unittest
from unittest.mock import patch

from backend.app.modules.law.reference.program_review import review_program, fingerprint


def handoff(qualified=True):
    value={'contract_version':'program-law/2','project_id':'fixture','program_id':'a','program_revision':1,
        'input_hash':'fixture-input','assessment_date':'2026-09-30','input_versions':{},
        'site':{'input':'4115011300106840001','input_type':'pnu'},'use_units':[{'use_unit_id':'u'}],
        'requested_checks':['parking'],'requirements':{'parking_assessment':{
            'use_unit_id':'u','aggregation_scope':'single_use_facility',
            'classification':{'canonical_use':'공공업무시설','status':'classified' if qualified else 'declared','source_ref':'source-use'},
            'facility_area':{'value':3200,'unit':'m2','basis':'parking_facility_area','source_ref':'source-area',
                'qualification_status':'qualified' if qualified else 'needs_evidence'},
        }}}
    value['request_hash']=fingerprint(value)
    return value


class ProgramParkingTests(unittest.TestCase):
    def test_missing_use_identity_cannot_bind_single_use_aggregation(self):
        value = handoff()
        value['use_units'] = [{}]
        value['requirements']['parking_assessment'].pop('use_unit_id')
        value['request_hash'] = fingerprint({k:v for k,v in value.items() if k!='request_hash'})
        with patch('backend.app.modules.law.reference.program_parking._resolve', return_value={'status':'needs_evidence'}) as resolver:
            result = review_program(value)['parking']
        resolver.assert_not_called()
        self.assertIn('single_use_facility_aggregation', result['missing_inputs'])

    def test_invalid_numeric_owner_counts_cannot_be_published(self):
        for count in (True, -1, 1.5, '32'):
            with self.subTest(count=count), patch('backend.app.modules.law.reference.program_parking._resolve', return_value={
                    'status':'computed','required_spaces':count,
                    'source':{'effective_date':'2026-01-09','source_sha256':'source'}}):
                result = review_program(handoff())['parking']
                self.assertIsNone(result['required_spaces'])
                self.assertIn('supported_parking_rule_calculation', result['missing_inputs'])

    def test_existing_uijeongbu_numeric_owner_keeps_source_and_rounding(self):
        result=review_program(handoff())['parking']
        self.assertEqual(result['required_spaces'],32)
        self.assertEqual(result['calculation']['selected_rule_id'],'uijeongbu_parking_appendix3_row_02')
        self.assertTrue(result['calculation']['source']['source_sha256'])
        self.assertEqual(result['calculation']['rounding_rule'],'appendix_note_6_half_up_total_under_one_zero')

    def test_program_dispatches_qualified_count_without_recalculation(self):
        with patch('backend.app.modules.law.reference.program_parking._resolve',return_value={'status':'computed','required_spaces':32,
                'source':{'effective_date':'2026-01-09','source_sha256':'source'},'rounding_rule':'owner-rounding'}) as resolver:
            result=review_program(handoff())
        self.assertEqual(result['parking']['required_spaces'],32)
        self.assertEqual(resolver.call_args.kwargs['facility_area_m2'],3200)
        self.assertFalse(result['permit_ready'])

    def test_unqualified_inputs_only_produce_conditional_scenario(self):
        with patch('backend.app.modules.law.reference.program_parking._resolve',return_value={'status':'computed','required_spaces':32,
                'source':{'effective_date':'2026-01-09','source_sha256':'source'}}):
            result=review_program(handoff(False))['parking']
        self.assertIsNone(result['required_spaces'])
        self.assertEqual(result['scenario_calculation']['required_spaces'],32)
        self.assertEqual(result['status'],'needs_evidence')

    def test_missing_area_does_not_fall_back_to_target_or_ledger(self):
        value=handoff(); value['requirements']['parking_assessment'].pop('facility_area')
        value['requirements']['target_parking_stalls']=50
        value['area_ledger']={'totals':{'gross_area_m2':9999}}
        value['request_hash']=fingerprint({k:v for k,v in value.items() if k!='request_hash'})
        with patch('backend.app.modules.law.reference.program_parking._resolve') as resolver:
            result=review_program(value)['parking']
        resolver.assert_not_called()
        self.assertIsNone(result['required_spaces'])
        self.assertIn('parking_facility_area',result['missing_inputs'])

    def test_mixed_scope_and_future_rule_cannot_publish_minimum(self):
        value=handoff(); value['use_units'].append({'use_unit_id':'other'})
        value['request_hash']=fingerprint({k:v for k,v in value.items() if k!='request_hash'})
        with patch('backend.app.modules.law.reference.program_parking._resolve') as resolver:
            self.assertIsNone(review_program(value)['parking']['required_spaces'])
        resolver.assert_not_called()
        with patch('backend.app.modules.law.reference.program_parking._resolve',return_value={'status':'computed','required_spaces':32,
                'source':{'effective_date':'2027-01-01','source_sha256':'source'}}):
            self.assertIsNone(review_program(handoff())['parking']['required_spaces'])


if __name__=='__main__': unittest.main()

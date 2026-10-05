"""Synthetic rule fixtures test arithmetic, not statutory requirements."""
import copy
import json
import unittest

from backend.app.modules.law.reference.facility_area_engine import evaluate_facility_areas


class FacilityAreaEngineTests(unittest.TestCase):
    def setUp(self):
        self.rule = {
            'rule_id': 'synthetic', 'facility_types': ['test_facility'],
            'quantity_fact': 'occupants', 'area_fact': 'room',
            'area_basis': 'net_room', 'coefficient_m2_per_unit': 2,
            'fixed_minimum_m2': 5, 'effective_from': '2025-01-01',
            'effective_to': '2025-12-31', 'required_conditions': {'new_build': True},
            'source': {'url': 'https://example.invalid/test', 'edition': 'synthetic',
                       'locator': 'fixture only'},
        }
        self.facts = {
            'facility_type': 'test_facility', 'quantities': {'occupants': 3},
            'areas': {'room': {'value': 6, 'unit': 'm2', 'basis': 'net_room',
                               'source_ref': 'drawing-1'}},
            'conditions': {'new_build': True},
            'condition_evidence': {'new_build': {'source_ref': 'project-brief'}},
            'source_edition_confirmed': {'synthetic': True},
        }

    def check_result(self, date='2025-06-01'):
        return evaluate_facility_areas(self.facts, [self.rule], date)['checks'][0]

    def test_equal_threshold_and_immutability(self):
        before = copy.deepcopy((self.facts, self.rule))
        result = self.check_result()
        self.assertEqual(result['status'], 'meets_area_minimum')
        self.assertEqual(result['required_area_m2'], 6)
        self.assertEqual(result['source'], self.rule['source'])
        self.assertEqual((self.facts, self.rule), before)

    def test_zero_area_is_below_not_missing(self):
        self.facts['areas']['room']['value'] = 0
        self.assertEqual(self.check_result()['status'], 'below_area_minimum')

    def test_date_boundaries_and_unconfirmed_edition(self):
        for date in ['2025-01-01', '2025-12-31']:
            self.assertEqual(self.check_result(date)['status'], 'meets_area_minimum')
        for date in ['2024-12-31', '2026-01-01']:
            result = self.check_result(date)
            self.assertEqual(result['status'], 'needs_evidence')
            self.assertEqual(result['conditional_area_comparison'], 'meets_area_minimum')
        self.facts['source_edition_confirmed'] = {}
        self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_conditions_unknown_and_mismatched(self):
        self.facts['conditions'] = {}
        self.assertEqual(self.check_result()['status'], 'needs_input')
        self.facts['conditions'] = {'new_build': False}
        self.assertEqual(self.check_result()['status'], 'not_applicable')

    def test_count_validation_zero_and_optional_minimum(self):
        for value in [True, -1, 1.5, float('nan'), float('inf'), '3', None]:
            self.facts['quantities']['occupants'] = value
            self.assertEqual(self.check_result()['status'], 'needs_input')
        self.facts['quantities']['occupants'] = 0
        self.assertEqual(self.check_result()['required_area_m2'], 5)
        self.rule['minimum_quantity'] = 1
        self.assertEqual(self.check_result()['status'], 'needs_input')

    def test_area_basis_units_and_missing_measurement(self):
        for field, value in [('basis', 'gross_building'), ('unit', 'pyeong'),
                             ('value', None), ('value', -1), ('value', True)]:
            original = self.facts['areas']['room'].copy()
            self.facts['areas']['room'][field] = value
            self.assertEqual(self.check_result()['status'], 'needs_input')
            self.facts['areas']['room'] = original
        self.facts['areas']['room'].update(value=100, unit='ft2')
        self.assertAlmostEqual(self.check_result()['provided_area_m2'], 9.290304)
        self.facts['areas'] = {}
        self.assertEqual(self.check_result()['status'], 'needs_input')

    def test_invalid_rule_and_missing_source_never_pass(self):
        for value in [-1, float('nan'), float('inf'), True, '2']:
            self.rule['coefficient_m2_per_unit'] = value
            self.assertEqual(self.check_result()['status'], 'needs_evidence')
        self.rule['coefficient_m2_per_unit'] = 2
        self.rule['source'] = {}
        self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_coverage_gap_and_no_global_compliance(self):
        for rules in [[], [dict(self.rule, facility_types=['other'])]]:
            result = evaluate_facility_areas(self.facts, rules, '2025-06-01')
            self.assertTrue(result['coverage_gaps'])
            self.assertNotIn('compliant', result)
            self.assertNotIn('permit', result)

    def test_invalid_assessment_date_and_rule_interval(self):
        self.assertEqual(self.check_result('not-a-date')['status'], 'needs_input')
        self.rule['effective_to'] = '2024-01-01'
        self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_open_ended_interval_still_requires_edition_confirmation(self):
        del self.rule['effective_to']
        self.assertEqual(self.check_result('2026-01-01')['status'], 'meets_area_minimum')
        self.facts['source_edition_confirmed']['synthetic'] = 'true'
        self.assertEqual(self.check_result('2026-01-01')['status'], 'needs_evidence')

    def test_known_exception_takes_precedence_over_an_unknown_condition(self):
        self.rule['required_conditions'] = {'unknown': True, 'new_build': True}
        self.facts['conditions']['new_build'] = False
        self.assertEqual(self.check_result()['status'], 'not_applicable')

    def test_measurement_evidence_and_output_copies(self):
        result = self.check_result()
        result['source']['edition'] = 'changed'
        result['provided_area']['value'] = 999
        self.assertEqual(self.rule['source']['edition'], 'synthetic')
        self.assertEqual(self.facts['areas']['room']['value'], 6)
        del self.facts['areas']['room']['source_ref']
        result = self.check_result()
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertIn('missing_measurement_source', result['reason_codes'])

    def test_arithmetic_overflow_does_not_pass(self):
        self.facts['quantities']['occupants'] = 1e300
        self.rule['coefficient_m2_per_unit'] = 1e300
        self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_piecewise_affine_boundaries(self):
        rules = [dict(self.rule, quantity_range={'minimum': low, 'maximum': high},
                      coefficient_m2_per_unit=coefficient, additive_constant_m2=constant)
                 for low, high, coefficient, constant in
                 [(0, 40, 2, 10), (41, 240, 3, 20), (241, None, 4, 30)]]
        for count, expected_index, expected_area in [(40, 0, 90), (41, 1, 143),
                                                       (240, 1, 740), (241, 2, 994)]:
            self.facts['quantities']['occupants'] = count
            checks = evaluate_facility_areas(self.facts, rules, '2025-06-01')['checks']
            self.assertEqual(checks[expected_index]['required_area_m2'], expected_area)
            self.assertEqual(checks[expected_index]['status'], 'below_area_minimum')
            for index, result in enumerate(checks):
                if index != expected_index:
                    self.assertEqual(result['status'], 'not_applicable')

    def test_mixed_quantities_sum_and_primary_scope(self):
        self.rule['area_terms'] = [
            {'quantity_fact': 'group_a', 'coefficient': 2},
            {'quantity_fact': 'group_b', 'coefficient': 4},
        ]
        del self.rule['coefficient_m2_per_unit']
        self.rule['additive_constant_m2'] = 1
        self.facts['quantities'].update(group_a=1, group_b=2)
        self.assertEqual(self.check_result()['required_area_m2'], 11)
        self.rule['quantity_range'] = {'minimum': 4}
        self.assertEqual(self.check_result()['status'], 'not_applicable')
        del self.rule['quantity_range']
        self.facts['quantities']['group_b'] = 1.5
        self.assertEqual(self.check_result()['status'], 'needs_input')
        self.facts['quantities']['group_b'] = 0
        self.rule['area_terms'][0]['coefficient'] = 0
        self.assertEqual(self.check_result()['required_area_m2'], 5)

    def test_malformed_terms_ranges_and_constants(self):
        for terms in [None, [], {}, [None], [{'quantity_fact': 'x'}],
                      [{'quantity_fact': 'x', 'coefficient': -1}],
                      [{'quantity_fact': [], 'coefficient': 1}]]:
            self.rule['area_terms'] = terms
            self.assertEqual(self.check_result()['status'], 'needs_evidence')
        del self.rule['area_terms']
        for bounds in [None, [], {}, {'minimum': -1}, {'minimum': 1.5},
                       {'maximum': True}, {'minimum': 10, 'maximum': 5},
                       {'minimum': 0, 'maximum': float('inf')}, {'maximun': 5}]:
            self.rule['quantity_range'] = bounds
            self.assertEqual(self.check_result()['status'], 'needs_evidence')
        del self.rule['quantity_range']
        for constant in [-1, True, float('nan'), '3']:
            self.rule['additive_constant_m2'] = constant
            self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_edition_evidence_metadata_copied_without_confirming(self):
        evidence = {'checked_url': 'https://example.invalid/edition', 'note': 'synthetic'}
        self.facts['source_edition_evidence'] = {'synthetic': evidence}
        result = self.check_result()
        self.assertEqual(result['source_edition_evidence'], evidence)
        result['source_edition_evidence']['note'] = 'modified'
        self.assertEqual(evidence['note'], 'synthetic')
        self.facts['source_edition_confirmed'] = {'synthetic': 1}
        self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_mixed_integer_and_float_overflow_does_not_raise(self):
        self.rule['area_terms'] = [
            {'quantity_fact': 'large', 'coefficient': 10 ** 300},
            {'quantity_fact': 'small', 'coefficient': 1.5}]
        self.facts['quantities'].update(large=10 ** 300, small=1)
        self.assertEqual(self.check_result()['status'], 'needs_evidence')

    def test_decimal_threshold_equality_and_immediately_below(self):
        for quantity, coefficient, exact_area in [(20, 2.64, 52.8), (12, 23.6, 283.2)]:
            self.facts['quantities']['occupants'] = quantity
            self.rule['coefficient_m2_per_unit'] = coefficient
            self.facts['areas']['room']['value'] = exact_area
            self.assertEqual(self.check_result()['status'], 'meets_area_minimum')
            self.assertEqual(self.check_result()['required_area_m2'], exact_area)
            json.dumps(self.check_result(), allow_nan=False)
            self.facts['areas']['room']['value'] = exact_area - 0.00000001
            self.assertEqual(self.check_result()['status'], 'below_area_minimum')

    def test_decimal_sum_affine_and_exact_unit_conversion(self):
        self.rule['area_terms'] = [
            {'quantity_fact': 'a', 'coefficient': 0.1},
            {'quantity_fact': 'b', 'coefficient': 0.2}]
        self.facts['quantities'].update(a=1, b=1)
        self.rule.update(additive_constant_m2=0.4, fixed_minimum_m2=0)
        self.facts['areas']['room']['value'] = 0.7
        self.assertEqual(self.check_result()['status'], 'meets_area_minimum')
        del self.rule['area_terms']
        self.rule.update(coefficient_m2_per_unit=0.09290304, additive_constant_m2=0)
        self.facts['quantities']['occupants'] = 100
        self.facts['areas']['room'].update(value=100, unit='ft2')
        self.assertEqual(self.check_result()['status'], 'meets_area_minimum')
        self.assertEqual(self.check_result()['required_area_m2'], 9.290304)

    def test_matching_conditions_require_documented_evidence(self):
        for evidence in [None, {}, {'new_build': True}, {'new_build': {}},
                         {'new_build': {'source_ref': ' '}}]:
            self.facts['condition_evidence'] = evidence
            result = self.check_result()
            self.assertEqual(result['status'], 'needs_evidence')
            self.assertEqual(result['conditional_area_comparison'], 'meets_area_minimum')
            self.assertIn('missing_condition_evidence:new_build', result['reason_codes'])


if __name__ == '__main__':
    unittest.main()

"""Synthetic rule fixtures test mechanics, not Korean statutory permission."""
from copy import deepcopy
import unittest

from backend.app.modules.regulations.extended import calculate_extended


class ZoningUseEvidenceTests(unittest.TestCase):
    def rule(self, **updates):
        row = {'id': 'synthetic-area-rule', 'zone_name': '준공업지역',
               'canonical_use': '아파트', 'effect': 'allow',
               'conditions_complete': True,
               'source': {'url': 'https://example.org/synthetic-rule',
                          'article': 'synthetic fixture', 'excerpt': 'Synthetic test only.',
                          'effective_from': '2026-01-01'},
               'conditions': [{'fact': 'floor_area_m2', 'operator': 'lte', 'value': 123}]}
        row.update(updates)
        return row

    def evaluate(self, rules=None, area=100, facts=None, assessment='2026-09-13', uses=None):
        return calculate_extended(['준공업지역'],
            {'zoning_use_evidence': {'rules': rules if rules is not None else [self.rule()],
                                     'facts': facts or {}}},
            program_uses=uses or [{'id': 'housing', 'building_type': '아파트', 'floor_area_m2': area}],
            assessment_date=assessment)['building_use_restriction']

    def test_matching_rule_is_partial_evaluation_never_permission(self):
        result = self.evaluate()
        row = result['per_use'][0]
        self.assertTrue(row['evidence_evaluated'])
        self.assertEqual(row['scoped_rule_result'], 'allow')
        self.assertEqual(row['rule_evaluations'][0]['status'], 'met')
        self.assertIsNone(row['permitted'])
        self.assertFalse(row['evaluated'])
        self.assertIsNone(result['permitted'])
        self.assertIn('municipal_ordinance', row['missing_evidence'])
        self.assertIn('district_plan', row['missing_evidence'])

    def test_failed_allow_condition_is_not_prohibition(self):
        row = self.evaluate(area=124)['per_use'][0]
        self.assertEqual(row['rule_evaluations'][0]['status'], 'not_met')
        self.assertEqual(row['scoped_rule_result'], 'unknown')

    def test_missing_and_invalid_area_do_not_become_numbers(self):
        for area in [None, True, '100', float('nan'), float('inf'), -1]:
            with self.subTest(area=area):
                row = self.evaluate(area=area)['per_use'][0]
                self.assertEqual(row['scoped_rule_result'], 'unknown')
                self.assertFalse(row['evidence_evaluated'])

    def test_incomplete_source_conditions_or_date_stay_unknown(self):
        for rule in [self.rule(source={}), self.rule(conditions_complete=False),
                     self.rule(conditions=None), self.rule(effect='maybe'),
                     self.rule(conditions=[{'fact': 'floor_area_m2', 'operator': 'eval', 'value': 1}])]:
            with self.subTest(rule=rule):
                self.assertEqual(self.evaluate([rule])['per_use'][0]['scoped_rule_result'], 'unknown')
        for assessment in [None, 'invalid', '2025-01-01']:
            self.assertEqual(self.evaluate(assessment=assessment)['per_use'][0]['scoped_rule_result'], 'unknown')
        rule = self.rule()
        rule['source']['effective_to'] = '2026-09-12'
        self.assertEqual(self.evaluate([rule])['per_use'][0]['scoped_rule_result'], 'unknown')

    def test_exact_use_and_zone_required(self):
        for rule in [self.rule(canonical_use='공동주택'), self.rule(zone_name='일반상업지역')]:
            self.assertEqual(self.evaluate([rule])['per_use'][0]['scoped_rule_result'], 'unknown')

    def test_conflicting_evidence_is_visible(self):
        row = self.evaluate([self.rule(), self.rule(id='prohibition', effect='prohibit')])['per_use'][0]
        self.assertEqual(row['scoped_rule_result'], 'conflict')
        self.assertIsNone(row['permitted'])

    def test_facts_are_typed_source_bound_and_use_specific(self):
        rule = self.rule(conditions=[{'fact': 'special_condition', 'operator': 'eq', 'value': True}])
        fact = {'value': True, 'source': {'url': 'https://example.org/site-evidence', 'excerpt': 'Fixture'}}
        for facts in [{}, {'housing': {'special_condition': True}},
                      {'other': {'special_condition': fact}},
                      {'housing': {'special_condition': {'value': True, 'source': {}}}}]:
            self.assertEqual(self.evaluate([rule], facts=facts)['per_use'][0]['scoped_rule_result'], 'unknown')
        row = self.evaluate([rule], facts={'housing': {'special_condition': fact}})['per_use'][0]
        self.assertEqual(row['scoped_rule_result'], 'allow')
        fact['value'] = 1
        self.assertEqual(self.evaluate([rule], facts={'housing': {'special_condition': fact}})['per_use'][0]['scoped_rule_result'], 'unknown')

    def test_rule_input_not_mutated_and_area_cannot_be_overridden(self):
        rule = self.rule()
        before = deepcopy(rule)
        row = self.evaluate([rule], area=124, facts={'housing': {'floor_area_m2': {'value': 1}}})['per_use'][0]
        self.assertEqual(rule, before)
        self.assertEqual(row['scoped_rule_result'], 'unknown')

    def test_no_evidence_preserves_unknown(self):
        row = self.evaluate([])['per_use'][0]
        self.assertFalse(row['evidence_evaluated'])
        self.assertEqual(row['rule_evaluations'], [])

    def test_threshold_boundary_and_prohibition_are_scoped(self):
        row = self.evaluate(area=123)['per_use'][0]
        self.assertEqual(row['scoped_rule_result'], 'allow')
        row = self.evaluate([self.rule(effect='prohibit')])['per_use'][0]
        self.assertEqual(row['scoped_rule_result'], 'prohibit')
        self.assertIsNone(row['permitted'])

    def test_unknown_condition_prevents_completed_conjunction(self):
        rule = self.rule(conditions=[{'fact': 'floor_area_m2', 'operator': 'lt', 'value': 1},
                                    {'fact': 'unprovided', 'operator': 'eq', 'value': True}])
        row = self.evaluate([rule])['per_use'][0]
        self.assertFalse(row['evidence_evaluated'])
        self.assertEqual(row['rule_evaluations'][0]['status'], 'unknown')

    def test_unconditional_rule_requires_explicit_completeness(self):
        rule = self.rule(conditions=[])
        self.assertEqual(self.evaluate([rule])['per_use'][0]['scoped_rule_result'], 'allow')
        del rule['conditions_complete']
        self.assertEqual(self.evaluate([rule])['per_use'][0]['scoped_rule_result'], 'unknown')

    def test_invalid_sources_and_dates_are_not_accepted(self):
        for field, value in [('url', 'javascript:alert(1)'), ('url', 'https://['),
                             ('excerpt', ''), ('article', None), ('effective_from', '2026-1-1'),
                             ('effective_to', None), ('effective_to', '2025-01-01')]:
            with self.subTest(field=field, value=value):
                rule = self.rule()
                rule['source'][field] = value
                self.assertFalse(self.evaluate([rule])['per_use'][0]['evidence_evaluated'])

    def test_edition_end_is_inclusive(self):
        rule = self.rule()
        rule['source']['effective_to'] = '2026-09-13'
        self.assertEqual(self.evaluate([rule])['per_use'][0]['scoped_rule_result'], 'allow')

    def test_other_program_uses_do_not_inherit_rule_or_fact(self):
        rows = self.evaluate(uses=[{'id': 'housing', 'building_type': '아파트', 'floor_area_m2': 100},
                                   {'id': 'office', 'building_type': '오피스텔', 'floor_area_m2': 100},
                                   {'id': 'unknown', 'building_type': 'unclassified', 'floor_area_m2': 100}])['per_use']
        self.assertEqual([row['scoped_rule_result'] for row in rows], ['allow', 'unknown', 'unknown'])

    def test_bad_envelopes_do_not_crash(self):
        for evidence in [True, [], {'rules': True}, {'rules': [None, [], 'bad']}]:
            row = calculate_extended(['준공업지역'], {'zoning_use_evidence': evidence},
                                     building_type='아파트')['building_use_restriction']['per_use'][0]
            self.assertFalse(row['evidence_evaluated'])


if __name__ == '__main__':
    unittest.main()

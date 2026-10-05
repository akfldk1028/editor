"""Source, statutory measurement and independent trigger boundary checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.modules.law.reference import fire_requirements as fire


def facts():
    paths = ['governing_edition', 'specific_fire_object', 'classification_basis', 'fire_subtype',
             'nuclear_reactor_related_facility', 'mixed_use_scope_reviewed',
             'substation_remote_sprinkler_or_water_spray_control', 'kitchen_has_hood', 'kitchen_has_duct',
             'general_restaurant_in_statutory_large_store', 'collective_food_service_under_food_act',
             'has_rooftop_garage_or_parking']
    paths += ['exception_review.' + key for key, *_ in fire.RULES]
    paths += ['qualifying_floor.' + key for key in ('floor_id', 'is_basement', 'is_windowless', 'floor_number', 'is_barn')]
    return {'governing_edition': '287375', 'specific_fire_object': True,
            'classification_basis': 'fire_decree_annex_2', 'fire_subtype': 'other_confirmed',
            'nuclear_reactor_related_facility': False, 'mixed_use_scope_reviewed': True,
            'exception_review': {key: 'none' for key, *_ in fire.RULES},
            'fact_evidence': {path: {'source_ref': 'project:review-document#' + path,
                                     'assessment_date': '2026-09-13'} for path in paths}}


def area(value, basis):
    return {'value': value, 'unit': 'm2', 'basis': basis, 'source_ref': 'project:certified-area-schedule#' + basis,
            'assessment_date': '2026-09-13'}


def finding(data, key, day='2026-09-13'):
    return next(f for f in fire.evaluate_fire_requirements(data, day)['findings'] if f['rule_id'] == key)


class FireRequirementTests(unittest.TestCase):
    def test_verified_edition_exact_text_and_six_rule_scope(self):
        source = fire._source()
        self.assertEqual(source['selected_effective_date'], '20260701')
        self.assertEqual(source['annex_revision_date'], '2025-11-25')
        result = fire.evaluate_fire_requirements({}, '2026-09-13')
        self.assertEqual(len(result['findings']), 6)
        self.assertTrue(all(f['status'] == 'needs_input' for f in result['findings']))
        for f in result['findings']:
            self.assertTrue(f['evidence_text'])
            self.assertIn(f['evidence_text'], source['annex_text'])
        self.assertFalse(result['coverage']['all_fire_requirements_covered'])
        self.assertEqual(result['global_compliance'], 'not_evaluated')

    def test_extinguisher_independent_area_boundaries(self):
        for value, status in [(32.999, 'not_required_by_this_rule'), (33, 'required'), (33.001, 'required')]:
            f = facts(); f['gross_floor_area'] = area(value, fire.GROSS_BASIS)
            self.assertEqual(finding(f, 'extinguisher_area')['status'], status)

    def test_hydrant_gross_area_and_explicit_exclusions(self):
        for value, status in [(2999.99, 'not_required_by_this_rule'), (3000, 'required')]:
            f = facts(); f['gross_floor_area'] = area(value, fire.GROSS_BASIS)
            self.assertEqual(finding(f, 'hydrant_gross_area')['status'], status)
        for subtype in ['gas_facility', 'underground_utility', 'tunnel']:
            f = facts(); f['fire_subtype'] = subtype; f['gross_floor_area'] = area(9000, fire.GROSS_BASIS)
            self.assertEqual(finding(f, 'hydrant_gross_area')['status'], 'not_required_by_this_rule')
        f['fire_subtype'] = 'unmanned_substation'
        self.assertEqual(finding(f, 'hydrant_gross_area')['status'], 'needs_input')
        f['substation_remote_sprinkler_or_water_spray_control'] = True
        self.assertEqual(finding(f, 'hydrant_gross_area')['status'], 'not_required_by_this_rule')
        f['substation_remote_sprinkler_or_water_spray_control'] = False
        self.assertEqual(finding(f, 'hydrant_gross_area')['status'], 'required')

    def test_rooftop_parking_boundaries_and_its_distinct_area_basis(self):
        f = facts(); f['has_rooftop_garage_or_parking'] = True
        for value, status in [(199.99, 'not_required_by_this_rule'), (200, 'required')]:
            f['rooftop_parking_used_area'] = area(value, fire.ROOF_BASIS)
            self.assertEqual(finding(f, 'hydrant_rooftop_parking')['status'], status)
        f['rooftop_parking_used_area']['basis'] = fire.GROSS_BASIS
        self.assertEqual(finding(f, 'hydrant_rooftop_parking')['status'], 'needs_input')

    def test_kitchens_require_hood_and_duct_and_statutory_use(self):
        f = facts(); f.update(fire_subtype='apartment_etc', kitchen_has_hood=True, kitchen_has_duct=True)
        self.assertEqual(finding(f, 'residential_kitchen')['status'], 'required')
        f['kitchen_has_duct'] = False
        self.assertEqual(finding(f, 'residential_kitchen')['status'], 'not_required_by_this_rule')
        del f['kitchen_has_duct']
        self.assertEqual(finding(f, 'residential_kitchen')['status'], 'needs_input')
        f.update(kitchen_has_duct=True, fire_subtype='other_confirmed',
                 general_restaurant_in_statutory_large_store=True,
                 collective_food_service_under_food_act=False)
        self.assertEqual(finding(f, 'commercial_kitchen')['status'], 'required')
        f.update(general_restaurant_in_statutory_large_store=False,
                 collective_food_service_under_food_act=True)
        self.assertEqual(finding(f, 'commercial_kitchen')['status'], 'required')
        f['collective_food_service_under_food_act'] = False
        self.assertEqual(finding(f, 'commercial_kitchen')['status'], 'not_required_by_this_rule')

    def test_floor_thresholds_windowless_basement_fourth_floor_and_barn(self):
        f = facts()
        floor = {'floor_id': 'L4', 'floor_area': area(600, fire.FLOOR_BASIS),
                 'is_basement': False, 'is_windowless': False, 'floor_number': 4, 'is_barn': False}
        f['qualifying_floor'] = floor
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'required')
        floor['floor_area']['value'] = 599.99
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'not_required_by_this_rule')
        floor['floor_area']['value'] = 600; floor['floor_number'] = 3
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'not_required_by_this_rule')
        floor['is_windowless'] = True
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'required')
        floor['is_barn'] = True
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'not_required_by_this_rule')
        floor.update(is_windowless=False, is_basement=True, floor_number=4)
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'not_required_by_this_rule')
        floor['is_barn'] = False
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'required')
        del floor['is_windowless']
        self.assertEqual(finding(f, 'hydrant_floor_area')['status'], 'needs_input')

    def test_absent_invalid_and_unreviewed_facts_do_not_become_passes(self):
        f = facts(); f['gross_floor_area'] = area(100, fire.GROSS_BASIS)
        for key in ['governing_edition', 'specific_fire_object', 'classification_basis', 'fire_subtype',
                    'nuclear_reactor_related_facility', 'mixed_use_scope_reviewed', 'exception_review']:
            broken = copy.deepcopy(f); del broken[key]
            self.assertEqual(finding(broken, 'extinguisher_area')['status'], 'needs_input', key)
        for bad in [True, None, -1, 'NaN', 'Infinity']:
            f['gross_floor_area']['value'] = bad
            self.assertEqual(finding(f, 'extinguisher_area')['status'], 'needs_input')
        f['gross_floor_area'] = area(100, fire.GROSS_BASIS); f['gross_floor_area']['unit'] = 'ft2'
        self.assertEqual(finding(f, 'extinguisher_area')['status'], 'needs_input')

    def test_reactor_routing_old_or_future_edition_and_tampered_evidence(self):
        f = facts(); f['nuclear_reactor_related_facility'] = True
        self.assertTrue(all(x['status'] == 'needs_evidence' for x in fire.evaluate_fire_requirements(f, '2026-09-13')['findings']))
        for day in ['2026-06-30', '2026-09-14']:
            self.assertEqual(finding(facts(), 'extinguisher_area', day)['status'], 'needs_evidence')
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'source.json'
            d = fire._source(); d['annex_text'] = d['annex_text'].replace('33', '34', 1)
            p.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
            with patch.object(fire, 'SOURCE_PATH', p):
                self.assertEqual(finding(facts(), 'extinguisher_area')['status'], 'needs_evidence')

    def test_unproven_measurement_and_assertion_keep_only_conditional_result(self):
        f = facts(); f['gross_floor_area'] = area(33, fire.GROSS_BASIS)
        del f['gross_floor_area']['source_ref']
        result = finding(f, 'extinguisher_area')
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertEqual(result['conditional_predicate_result'], 'required')
        self.assertIn('gross_floor_area.source_ref', result['missing_evidence'])
        f['gross_floor_area'] = area(32, fire.GROSS_BASIS)
        for key in ['governing_edition', 'classification_basis', 'fire_subtype', 'mixed_use_scope_reviewed',
                    'nuclear_reactor_related_facility', 'exception_review.extinguisher_area']:
            broken = copy.deepcopy(f); del broken['fact_evidence'][key]
            result = finding(broken, 'extinguisher_area')
            self.assertEqual(result['status'], 'needs_evidence')
            self.assertEqual(result['conditional_predicate_result'], 'not_required_by_this_rule')

    def test_exempt_assertion_and_kitchen_booleans_need_project_evidence(self):
        f = facts(); f['exception_review']['extinguisher_area'] = 'exempt'
        del f['fact_evidence']['exception_review.extinguisher_area']
        result = finding(f, 'extinguisher_area')
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertEqual(result['conditional_predicate_result'], 'not_required_by_this_rule')
        f = facts(); f.update(fire_subtype='apartment_etc', kitchen_has_hood=True, kitchen_has_duct=True)
        f['fact_evidence']['kitchen_has_duct'] = {'source_ref': ' '}
        result = finding(f, 'residential_kitchen')
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertEqual(result['conditional_predicate_result'], 'required')

    def test_early_exclusions_do_not_bypass_evidence(self):
        for subtype in ['gas_facility', 'underground_utility', 'unmanned_substation']:
            f = facts(); f['fire_subtype'] = subtype
            f['substation_remote_sprinkler_or_water_spray_control'] = True
            del f['fact_evidence']['fire_subtype']
            self.assertEqual(finding(f, 'hydrant_gross_area')['status'], 'needs_evidence')
        f = facts(); f.update(fire_subtype='unmanned_substation', substation_remote_sprinkler_or_water_spray_control=True)
        del f['fact_evidence']['substation_remote_sprinkler_or_water_spray_control']
        self.assertEqual(finding(f, 'hydrant_gross_area')['status'], 'needs_evidence')

    def test_review_dates_and_input_hash_track_consumed_measurements(self):
        f = facts(); f['gross_floor_area'] = area(33, fire.GROSS_BASIS)
        original = finding(f, 'extinguisher_area')
        f['gross_floor_area']['value'] = 34
        changed = finding(f, 'extinguisher_area')
        self.assertNotEqual(original['input_sha256'], changed['input_sha256'])
        self.assertEqual(changed['consumed_evidence_records']['gross_floor_area']['value'], 34)
        f['gross_floor_area']['assessment_date'] = '2026-09-12'
        self.assertEqual(finding(f, 'extinguisher_area')['status'], 'needs_evidence')
        f['gross_floor_area']['assessment_date'] = '2026-09-13'
        del f['fact_evidence']['governing_edition']['assessment_date']
        self.assertEqual(finding(f, 'extinguisher_area')['status'], 'needs_evidence')

    def test_blanket_exemption_is_not_a_kitchen_exemption(self):
        f = facts(); key = 'residential_kitchen'; f['exception_review'][key] = 'exempt'
        proof = f['fact_evidence']['exception_review.' + key]
        proof.update(rule_id=key, legal_basis='Annex 5 automatic-device substitution',
                     exemption_basis_type='rule_specific_statutory_exemption')
        result = finding(f, key)
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertTrue(any('generic Annex 5' in item for item in result['missing_evidence']))
        key = 'extinguisher_area'; f['exception_review'][key] = 'exempt'
        self.assertEqual(finding(f, key)['status'], 'needs_evidence')
        f['fact_evidence']['exception_review.' + key].update(
            rule_id=key, legal_basis='project-specific approval document section 2',
            exemption_basis_type='specific_authority_approval')
        self.assertEqual(finding(f, key)['status'], 'not_required_by_this_rule')


if __name__ == '__main__':
    unittest.main()

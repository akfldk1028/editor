from unittest import TestCase as SimpleTestCase
from unittest.mock import patch
from copy import deepcopy
from backend.app.modules.regulations import calculator as calc
from backend.app.modules.regulations.legal_use import classify_building_use

class CalculatorSafetyTests(SimpleTestCase):
    def test_school_label_maps_to_education_category(self):
        result = classify_building_use('학교시설')
        self.assertEqual(result['category'], '교육연구시설')
        self.assertEqual(result['subtype'], '학교')

    def calculate(self, **kwargs):
        kwargs.setdefault("assessment_date", "2026-10-04")
        return calc.calculate_all(['제3종일반주거지역'], use_llm_extraction=False, **kwargs)

    def test_example_ordinance_is_quarantined(self):
        self.assertIsNone(calc._load_ordinance('11680'))

    def test_missing_city_does_not_return_binding_national_ceiling(self):
        result = self.calculate(sigungu_code='26110')
        self.assertIsNone(result['bcr_pct'])
        self.assertIsNone(result['far_pct'])
        self.assertEqual(result['municipal_coverage']['status'], 'needs_evidence')
        self.assertIsNotNone(result['national_bcr_ceiling_pct'])

    def test_officetel_does_not_match_ordinary_office(self):
        result = self.calculate(sigungu_code='11680', building_type='업무시설(오피스텔)', floor_area_m2=2000)
        self.assertIsNone(result['parking_ratio_m2_per_car'])
        self.assertIsNone(result['parking_required'])
        self.assertIn('주택', result['parking_ratio_rule'])

    def test_specific_data_centre_wins_and_alias_matches(self):
        for label in ['방송통신시설 중 데이터센터', '데이터센터', 'data centre']:
            with self.subTest(label=label):
                result = self.calculate(building_type=label, floor_area_m2=2100)
                self.assertEqual(result['parking_ratio_m2_per_car'], 400)
                self.assertEqual(result['parking_calculated_intermediate'], 5.25)
                self.assertIsNone(result['parking_required'])

    def test_unknown_use_is_not_miscellaneous(self):
        result = self.calculate(building_type='알수없는용도', floor_area_m2=2000)
        self.assertIsNone(result['parking_ratio_m2_per_car'])
        self.assertIsNone(result['parking_required'])

    def test_excluded_and_ambiguous_uses_do_not_match_broad_rows(self):
        for label in ['업무시설(외국공관)', '의료시설(요양병원)', '방송통신시설', '제1종 근린생활시설', '공장(아파트형 공장)']:
            with self.subTest(label=label):
                result = self.calculate(building_type=label, floor_area_m2=2000)
                self.assertIsNone(result['parking_ratio_m2_per_car'])

    def test_single_use_final_count_rounds_half_up_on_the_ordinance(self):
        # 별표 1 비고 6: 소수점 이하 0.5 이상은 1로 본다. 의정부 조례 업무시설 100㎡/대.
        result = self.calculate(sigungu_code='41150', building_type='업무시설', floor_area_m2=2000)
        self.assertEqual(result['parking_basis'], 'municipal_snapshot')
        self.assertEqual(result['parking_ratio_m2_per_car'], 100)
        self.assertEqual(result['parking_required'], 20)
        self.assertEqual(result['parking_status'], 'calculated')
        self.assertEqual(result['parking_calculation']['rounding_policy'], 'exact_quotient')
        self.assertFalse(result['parking_calculation']['mixed_use'])

    def test_total_below_one_car_is_zero_not_one(self):
        # 별표 1 비고 6 단서. 95/100 = 0.95 -> 0대. 비고 4's first-decimal step is for
        # 복합용도 only, so it must not lift a single use to 1.0 here.
        result = self.calculate(sigungu_code='41150', building_type='업무시설', floor_area_m2=95)
        self.assertEqual(result['parking_required'], 0)
        self.assertEqual(result['parking_status'], 'calculated')

    def test_half_exactly_rounds_up_and_just_under_rounds_down(self):
        for area, expected in ((250, 3), (240, 2)):   # 2.5 -> 3, 2.4 -> 2
            with self.subTest(area=area):
                result = self.calculate(sigungu_code='41150', building_type='업무시설', floor_area_m2=area)
                self.assertEqual(result['parking_required'], expected)

    def test_detached_house_tiers_follow_the_ordinance_thresholds(self):
        # 별표 1 제4호 (의정부 별표 3: 50㎡ 초과 134㎡ 이하 1대, 초과분 85㎡당 1대; 50㎡ 이하는
        # 비고 1 -> 85㎡로 나눈 대수) then 비고 6. 300 -> 1 + 166/85 = 2.95 -> 3; 40 -> 0.47 -> 0.
        for area, expected in ((120, 1), (300, 3), (40, 0)):
            with self.subTest(area=area):
                result = self.calculate(sigungu_code='41150', building_type='단독주택', floor_area_m2=area)
                self.assertEqual(result['parking_required'], expected)
                self.assertEqual(result['parking_status'], 'calculated')
        # 서울 별표 2 keeps the 시행령 thresholds (150/100): 200 -> 1.5 -> 2.
        seoul = self.calculate(sigungu_code='11680', building_type='단독주택', floor_area_m2=200)
        self.assertEqual(seoul['parking_required'], 2)
        # 다가구주택 is carved out of the row and follows 주택건설기준 §27 (manual rule only).
        multi = self.calculate(sigungu_code='41150', building_type='다가구주택', floor_area_m2=300)
        self.assertIsNone(multi['parking_required'])

    def test_accessible_stalls_follow_ratio_threshold_and_ceiling(self):
        # 주차장법 시행령 별표1 비고10 -> 의정부 별표3 비고2 (3 %) -> 장애인등편의법 시행령 별표2 제2호(2)(가):
        # 10대 미만 제외, 끝수는 1대 (올림). 20 x 3 % = 0.6 -> 1; 3대 -> none; 100 x 3 % = 3 exactly.
        office = self.calculate(sigungu_code='41150', building_type='업무시설', floor_area_m2=2000)
        self.assertEqual(office['parking_required_accessible'], 1)
        self.assertEqual(office['parking_accessible']['status'], 'calculated')
        self.assertEqual(office['parking_accessible']['applicability']['status'], 'applies')
        small = self.calculate(sigungu_code='41150', building_type='업무시설', floor_area_m2=300)
        self.assertEqual(small['parking_required_accessible'], 0)
        self.assertEqual(small['parking_accessible']['status'], 'not_required')
        seoul = self.calculate(sigungu_code='11680', building_type='업무시설', floor_area_m2=10000)
        self.assertEqual(seoul['parking_required'], 100)
        self.assertEqual(seoul['parking_required_accessible'], 3)

    def test_accessible_stalls_need_a_target_facility_and_a_binding_count(self):
        # 창고시설 is not in 장애인등편의법 시행령 별표1 -> 0; 근생 depends on 세부용도 -> needs_evidence;
        # no ordinance -> no binding count -> nothing.
        warehouse = self.calculate(sigungu_code='41150', building_type='창고시설', floor_area_m2=3500)
        self.assertEqual(warehouse['parking_required'], 10)
        self.assertEqual(warehouse['parking_accessible']['status'], 'not_applicable')
        self.assertEqual(warehouse['parking_required_accessible'], 0)
        retail = self.calculate(sigungu_code='41150', building_type='제2종 근린생활시설', floor_area_m2=2000)
        self.assertIsNone(retail['parking_required_accessible'])
        self.assertIn('accessibility_act_target_facility', retail['parking_accessible']['missing_evidence'])
        national = self.calculate(building_type='업무시설', floor_area_m2=2000)
        self.assertIsNone(national['parking_required_accessible'])
        self.assertIn('binding_parking_count', national['parking_accessible']['missing_evidence'])

    def test_mixed_use_sums_first_decimals_then_rounds(self):
        # 별표 1 비고 4 -> 비고 6. 업무 1200/100 = 12.0, 근생 260/134 = 1.94 -> 1.9; 13.9 -> 14.
        uses = [{'id': 'office', 'building_type': '업무시설', 'floor_area_m2': 1200},
                {'id': 'retail', 'building_type': '제2종 근린생활시설', 'floor_area_m2': 260}]
        result = self.calculate(sigungu_code='41150', program_uses=uses)
        calculation = result['parking_calculation']
        self.assertTrue(calculation['mixed_use'])
        self.assertEqual(calculation['rounding_policy'], 'first_decimal_round_half_up')
        self.assertEqual([u['cars_first_decimal'] for u in calculation['uses']], [12.0, 1.9])
        self.assertEqual(calculation['subtotal_first_decimal'], 13.9)
        self.assertEqual(result['parking_required'], 14)

    def test_restricted_district_candidate_withholds_the_final_count(self):
        # 별표 3 is a 최고한도 lower than the requirement; without the boundary the
        # uncapped number would overstate parking, so nothing is emitted.
        result = calc.calculate_all(['일반상업지역'], use_llm_extraction=False, sigungu_code='11680',
                                    building_type='업무시설', floor_area_m2=2000)
        self.assertIsNotNone(result['parking_restricted_candidate'])
        self.assertIsNone(result['parking_required'])
        self.assertEqual(result['parking_status'], 'needs_evidence')
        self.assertIn('restricted_district_parcel_boundary', result['parking_missing_evidence'])

    def test_national_table_alone_is_a_floor_not_the_binding_count(self):
        result = self.calculate(building_type='업무시설', floor_area_m2=2000)
        self.assertEqual(result['parking_basis'], 'national_reference')
        self.assertIsNone(result['parking_required'])
        self.assertIn('applicable_municipal_ordinance', result['parking_missing_evidence'])
        self.assertEqual(result['parking_calculation']['national_floor_cars'], 13)

    def test_umbrella_office_resolves_but_its_carve_outs_never_inherit(self):
        office = self.calculate(sigungu_code='41150', building_type='업무시설', floor_area_m2=2000)
        self.assertEqual(office['parking_program_uses'][0]['use_precision'], 'exact')
        for label in ('업무시설(외국공관)', '외국공관'):
            with self.subTest(label=label):
                result = self.calculate(sigungu_code='41150', building_type=label, floor_area_m2=2000)
                self.assertIsNone(result['parking_ratio_m2_per_car'])
                self.assertIsNone(result['parking_required'])

    def test_future_edition_does_not_apply_to_past_date(self):
        result = self.calculate(sigungu_code='11680', assessment_date='2020-01-01')
        self.assertIsNone(result['bcr_pct'])
        self.assertIsNone(result['parking_ordinance_rows'])

    def test_missing_zone_still_reports_evidence_contract(self):
        result = calc.calculate_all(['unknown'], use_llm_extraction=False)
        self.assertEqual(result['municipal_coverage']['status'], 'needs_evidence')
        self.assertIsNone(result['national_bcr_ceiling_pct'])

    def test_unknown_zone_cannot_be_silently_discarded(self):
        # An unknown 용도지역 (a 국토계획법 제36조 family name the catalog lacks) withholds the caps.
        result = calc.calculate_all(['일반상업지역', '미확인주거지역'],
                                    sigungu_code='11680', use_llm_extraction=False)
        self.assertIsNone(result['bcr_pct'])
        self.assertIn('unresolved_zoning:미확인주거지역', result['municipal_coverage']['missing_evidence'])
        # A designation outside those families is reported, never silently dropped, and the caps stand.
        other = calc.calculate_all(['일반상업지역', '엉뚱한보존지역'],
                                   sigungu_code='11680', use_llm_extraction=False)
        self.assertIsNotNone(other['bcr_pct'])
        self.assertIn('unlisted_designation:엉뚱한보존지역', other['municipal_coverage']['missing_evidence'])

    def test_recognized_overlay_is_not_unresolved_zoning(self):
        result = calc.calculate_all(['일반상업지역', '지구단위계획구역'],
                                    sigungu_code='11680', use_llm_extraction=False)
        self.assertNotIn('unresolved_zoning:지구단위계획구역', result['municipal_coverage']['missing_evidence'])

    def test_ordinance_id_is_not_fabricated_as_an_edition_url(self):
        doc = deepcopy(calc._load_ordinance('11'))
        for key in ('mst', 'ordinSeq', 'edition_id', 'url'):
            doc['ordinance'].pop(key, None)
        doc.pop('source_url', None)
        with patch.dict(calc._ordinance_cache, {'11': doc}):
            result = self.calculate(sigungu_code='11680')
        source = result['municipal_coverage']['sources'][0]
        self.assertEqual(source['ordinance_id'], '2000719')
        self.assertIsNone(source['edition_id'])
        self.assertIsNone(source['url'])
        self.assertIsNone(result['bcr_pct'])
        self.assertEqual(result['municipal_bcr_snapshot_pct'], 50)

    def test_source_metadata_is_rechecked_even_in_cache(self):
        source = calc._load_ordinance('11')
        for key in ['ordinance', 'fetched_at', '__comment']:
            with self.subTest(key=key):
                invalid = deepcopy(source)
                invalid.pop(key)
                if key == '__comment':
                    invalid['ordinance'].pop('url', None)
                    invalid.pop('source_url', None)
                with patch.dict(calc._ordinance_cache, {'11': invalid}):
                    self.assertIsNone(calc._load_ordinance('11'))

    def test_source_jurisdiction_and_expiry_are_enforced(self):
        source = deepcopy(calc._load_ordinance('11'))
        source['ordinance']['valid_until'] = '2026-09-01'
        with patch.dict(calc._ordinance_cache, {'11': source}):
            self.assertIsNone(calc._load_ordinance('11', '2026-09-13'))
        source['ordinance'].pop('valid_until')
        source['sigungu_code'] = '26'
        with patch.dict(calc._ordinance_cache, {'11': source}):
            self.assertIsNone(calc._load_ordinance('11'))

    def test_partial_city_coverage_does_not_label_national_caps_municipal(self):
        source = deepcopy(calc._load_ordinance('11'))
        source['overrides'].pop('제3종일반주거지역')
        with patch.dict(calc._ordinance_cache, {'11': source}):
            result = self.calculate(sigungu_code='11680')
        self.assertIsNone(result['bcr_pct'])
        self.assertIsNone(result['municipal_bcr_snapshot_pct'])

    def test_housing_alias_keeps_manual_housing_parking_rule(self):
        for label in ['아파트', '공동주택(아파트)', '연립주택', '다세대주택', 'officetel']:
            with self.subTest(label=label):
                result = self.calculate(building_type=label, floor_area_m2=2000)
                self.assertIn('주택', result['parking_ratio_rule'])
                self.assertIsNone(result['parking_required'])

    def test_program_sums_complete_intermediates_only(self):
        uses = [{'id':'storage','building_type':'창고시설','floor_area_m2':400}, {'id':'data','building_type':'데이터센터','floor_area_m2':600}]
        result = self.calculate(program_uses=uses)
        self.assertEqual(result['parking_calculated_intermediate'], 2.5)
        self.assertIsNone(result['parking_required'])
        uses[1]['building_type'] = 'unknown'
        result = self.calculate(program_uses=uses)
        self.assertIsNone(result['parking_calculated_intermediate'])
        self.assertEqual(result['parking_status'], 'needs_evidence')


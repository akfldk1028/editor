"""Ensure the source catalog cannot silently lose annex clauses or qualifiers."""

from backend.app.modules.design.generation import paths as _design_paths
import copy
import hashlib
import json
from pathlib import Path
import unittest

from backend.app.modules.law.reference.building_use_catalog import get_building_use_catalog, parse_building_use_source


SOURCE = _design_paths.package_root('law') / 'data/facility_sources/building_decree_annex_1.json'


class BuildingUseCatalogTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(SOURCE.read_text(encoding='utf-8'))

    def test_all_families_and_source_can_be_reconstructed_without_loss(self):
        result = get_building_use_catalog()
        expected_ids = [str(n) for n in range(1, 24)] + ['23의2'] + [str(n) for n in range(24, 30)]
        self.assertEqual([f['family_id'] for f in result['families']], expected_ids)
        self.assertEqual(result['family_count'], 30)
        self.assertEqual(result['matched_family_count'], 30)
        reconstructed = result['preamble_text'] + ''.join(f['text'] for f in result['families']) + result['notes_text']
        self.assertEqual(reconstructed, self.source['annex_text'])
        self.assertIn('고시할 수 있다.', result['notes_text'])
        self.assertEqual(result['source']['annex_text_sha256'], hashlib.sha256(reconstructed.encode('utf-8')).hexdigest())
        self.assertEqual(result['source']['selected_mst'], self.source['selected_mst'])

    def test_wrapped_sentence_is_not_a_new_clause_and_nested_requirements_survive(self):
        family = next(f for f in get_building_use_catalog()['families'] if f['family_id'] == '4')
        clauses = {c['clause_id']: c['text'] for c in family['clauses']}
        self.assertEqual(len(clauses), 20)
        self.assertIn('다. 이하 같다)', clauses['4거'])
        self.assertIn('500제곱미터 미만인 것', clauses['4거'])
        self.assertIn('1)', clauses['4너'])
        self.assertIn('2)', clauses['4너'])
        self.assertIn('전량 위탁처리하는 것', clauses['4너'])
        self.assertEqual(family['intro_text'] + ''.join(clauses.values()), family['text'])

    def test_unlettered_family_retains_qualifier(self):
        result = get_building_use_catalog('발전시설')
        self.assertEqual(result['matched_family_count'], 1)
        family = result['families'][0]
        self.assertEqual(family['family_id'], '25')
        self.assertEqual(family['clauses'][0]['text'], family['text'])
        self.assertIn('해당하지 아니하는 것', family['text'])

    def test_query_finds_data_center_and_preserves_family_context(self):
        result = get_building_use_catalog(' 데이터 센터 ')
        self.assertEqual(result['family_count'], 30)
        self.assertEqual(result['matched_family_count'], 1)
        family = result['families'][0]
        self.assertEqual(family['name'], '방송통신시설')
        self.assertEqual(family['matched_clause_ids'], ['24마'])
        self.assertEqual(len(family['clauses']), 6)
        self.assertIn('제1종 근린생활시설에 해당하는 것은 제외한다', family['intro_text'])
        self.assertEqual(get_building_use_catalog('없는용도검색어')['families'], [])

    def test_changed_source_hash_is_rejected(self):
        self.source['annex_text'] += 'changed'
        with self.assertRaisesRegex(ValueError, 'hash'):
            parse_building_use_source(self.source)

    def test_missing_family_is_rejected_even_with_valid_hash(self):
        source = copy.deepcopy(self.source)
        start = source['annex_text'].index('  23의2.')
        end = source['annex_text'].index('  24.')
        source['annex_text'] = source['annex_text'][:start] + source['annex_text'][end:]
        source['annex_text_sha256'] = hashlib.sha256(source['annex_text'].encode('utf-8')).hexdigest()
        with self.assertRaisesRegex(ValueError, 'coverage'):
            parse_building_use_source(source)


if __name__ == '__main__':
    unittest.main()

from copy import deepcopy
from datetime import date
import importlib

import pytest


def normalize(body):
    return importlib.import_module('backend.app.modules.land.analysis_request').normalize_program_request(body)


def response():
    return importlib.import_module('backend.app.modules.land.analysis_response')


def test_program_normalizes_schedule_without_changing_input():
    body = {'building_type': ' office ', 'floor_area_m2': '12.5', 'assessment_date': '2026-10-04',
            'program_uses': [{'building_type': ' school ', 'floor_area_m2': '200'},
                             {'id': 'second', 'building_type': 'housing'}]}
    original = deepcopy(body)
    assert normalize(body) == {'building_type': 'office', 'floor_area_m2': 12.5,
                              'assessment_date': '2026-10-04', 'program_uses': [
                                  {'id': 'use-1', 'building_type': 'school', 'floor_area_m2': 200.0},
                                  {'id': 'second', 'building_type': 'housing', 'floor_area_m2': None}]}
    assert body == original


def test_empty_program_uses_current_date_and_unknown_area():
    assert normalize({}) == {'building_type': '', 'floor_area_m2': None,
                             'assessment_date': date.today().isoformat(), 'program_uses': None}


@pytest.mark.parametrize('area', [True, False, 0, -1, float('nan'), float('inf'), 'bad', []])
def test_invalid_program_area_is_rejected(area):
    with pytest.raises(ValueError, match='finite positive area'):
        normalize({'floor_area_m2': area})


@pytest.mark.parametrize('body', [[], {'assessment_date': '20261004'}, {'assessment_date': '2026-02-30'},
                                 {'assessment_date': 20261004}, {'program_uses': []},
                                 {'program_uses': [None]}, {'program_uses': [{'building_type': ' '}]},
                                 {'program_uses': [{'id': 'a', 'building_type': 'x'}, {'id': 'a', 'building_type': 'y'}]}])
def test_invalid_program_contract_is_rejected(body):
    with pytest.raises(ValueError):
        normalize(body)


def test_formatting_preserves_uncertainty_and_parking_evidence():
    coverage = {'status': 'needs_evidence', 'missing_evidence': ['edition']}
    reg = {'bcr_pct': None, 'national_bcr_ceiling_pct': 60, 'municipal_coverage': coverage,
           'parking_required': None, 'parking_calculated_intermediate': 2.5,
           'parking_status': 'needs_evidence', 'parking_missing_evidence': ['municipal'],
           'parking_accessible': {'status': 'needs_evidence'}}
    extended = {'building_use_restriction': {'permitted': None, 'evaluated': False}}
    result = response().format_regulations(reg, extended)
    assert len(result) == 11
    assert result['bcr']['limit_pct'] is None
    assert result['bcr']['national_ceiling_pct'] == 60
    assert result['bcr']['coverage'] == coverage
    assert result['parking']['required_cars'] is None
    assert result['parking']['calculated_intermediate'] == 2.5
    assert result['parking']['missing_evidence'] == ['municipal']
    assert result['extended'] == extended


def test_restrictions_do_not_report_recognized_overlay_as_unknown():
    result = response().build_restrictions(
        {'bcr_pct': 60, 'far_pct': None, 'unmatched_zones': ['overlay', 'unknown']},
        ['residential', 'overlay'], overlay_all_matched={'overlay'})
    assert any('60%' in text for text in result)
    assert any('unknown' in text for text in result)
    assert not any('overlay' in text for text in result)


def test_law_flattening_deduplicates_identified_nested_articles_and_preserves_errors():
    article = {'hang_id': 'one', 'content': 'text'}
    unidentified = {'content': 'unidentified'}
    flat = {'hang_id': 'flat'}
    result = response().flatten_law_articles({'articles': [
        {'query': 'a', 'results': [article, unidentified]},
        {'query': 'b', 'results': [article, unidentified]}, flat], 'errors': ['partial']})
    assert result == {'articles': [article, unidentified, unidentified, flat],
                      'total_count': 4, 'errors': ['partial']}

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.modules.regulations import calculator, extended, overlays
from backend.app.modules.regulations.zoning_catalog import CatalogUnavailable


FIXTURE = Path(__file__).with_name('fixtures') / 'regulations_parity.json'


def response_digest(value):
    # The source constructs this article string from a set, so its order varies
    # with process hash randomization. All other fields compare exactly.
    value['core']['landscaping_article'] = '; '.join(sorted(
        value['core'].get('landscaping_article', '').split('; ')))
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize('case', json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'],
                         ids=lambda case: case['name'])
def test_fixed_date_original_source_parity(case):
    args = case['input']
    result = {
        'core': calculator.calculate_all(**args, use_llm_extraction=False),
        'extended': extended.calculate_extended(args['zone_names'], args.get('land_info'),
            building_type=args.get('building_type', ''), program_uses=args.get('program_uses'),
            assessment_date=args['assessment_date']),
        'overlays': overlays.resolve_overlays(args['zone_names']),
        'recognized_overlays': sorted(overlays.get_all_matched_zones(args['zone_names'])),
    }
    assert response_digest(result) == case['response_sha256']


def test_data_files_are_the_preserved_source_bytes():
    directory = Path(calculator.__file__).parent.with_name('data')
    for name, expected in json.loads(FIXTURE.read_text(encoding='utf-8'))['data_sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected


def test_advisory_requires_explicit_opt_in_and_cannot_replace_numeric_rules():
    calls = []
    def extractor(zones, kind):
        calls.append(kind)
        return {'adjacent_setback_m': 0, 'sunlight_rules': [{'setback_m': 0}],
                'building_designation_setback_m': 0}
    args = {'zone_names': ['제3종일반주거지역', '지구단위계획구역'], 'assessment_date': '2026-10-04'}
    baseline = calculator.calculate_all(**args, extractor=extractor)
    assert calls == []
    with pytest.raises(ValueError, match='explicit extractor'):
        calculator.calculate_all(**args, use_llm_extraction=True)
    advised = calculator.calculate_all(**args, use_llm_extraction=True, extractor=extractor)
    assert calls == ['sunlight', 'adjacent_setback', 'building_designation']
    for key in ('adjacent_setback_m', 'sunlight_rules', 'building_designation_setback_m'):
        assert advised[key] == baseline[key]
    assert advised['sunlight_proposal']['status'] == 'unverified_proposal'


def test_advisory_failure_leaves_reference_calculation_available():
    def fail(*args):
        raise RuntimeError('fixture provider failure')
    args = {'zone_names': ['제3종일반주거지역'], 'assessment_date': '2026-10-04'}
    assert calculator.calculate_all(**args, use_llm_extraction=True, extractor=fail) == calculator.calculate_all(**args)


def test_response_mutation_does_not_poison_next_calculation():
    args = {'zone_names': ['제3종일반주거지역'], 'sigungu_code': '41150',
            'building_type': '업무시설', 'floor_area_m2': 2000, 'assessment_date': '2026-10-04'}
    first = calculator.calculate_all(**args)
    expected = first['parking_required']
    first['parking_national_rows'][0]['m2_per_car'] = -999
    first['parking_ordinance_rows'].clear()
    first['parking_accessible']['national_band_pct'].clear()
    next_result = calculator.calculate_all(**args)
    assert next_result['parking_required'] == expected
    assert next_result['parking_ordinance_rows']
    assert next_result['parking_accessible']['national_band_pct'] == [2, 4]
    assert next_result['parking_national_rows'][0].get('m2_per_car') != -999


def test_calculator_does_not_import_legacy_django_or_network_adapters():
    import ast
    directory = Path(calculator.__file__).parent.parent
    for name in ('calculator/__init__', 'calculator/rules', 'calculator/parking',
                 'extended', 'legal_use', 'ordinance_evidence', 'zoning_use_evidence', 'overlays'):
        tree = ast.parse((directory / (name + '.py')).read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('land', 'django', 'httpx', 'requests', 'openai'))
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith(('land', 'django', 'httpx', 'requests', 'openai')) for alias in node.names)


@pytest.mark.parametrize('resource', ['parking_national', 'accessible_parking_applicability',
                                    'zoning_limits_extended', 'overlay_zones'])
@pytest.mark.parametrize('content', [None, '{', '{}', '[]'])
def test_required_resource_failure_is_explicit(tmp_path, monkeypatch, resource, content):
    path = tmp_path / (resource + '.json')
    if content is not None:
        path.write_text(content, encoding='utf-8')
    if resource == 'parking_national':
        monkeypatch.setattr(calculator, 'ORDINANCE_DIR', tmp_path / 'ordinance_overrides')
        monkeypatch.setattr(calculator, '_parking_national_cache', None)
        load = calculator._parking_national
    elif resource == 'accessible_parking_applicability':
        monkeypatch.setattr(calculator, 'ORDINANCE_DIR', tmp_path / 'ordinance_overrides')
        monkeypatch.setattr(calculator, '_accessible_applicability_cache', None)
        load = calculator._accessible_applicability
    elif resource == 'zoning_limits_extended':
        monkeypatch.setattr(extended, '_DATA_DIR', str(tmp_path))
        load = extended._load_extended_data
    else:
        monkeypatch.setattr(overlays, '_DATA_PATH', path)
        monkeypatch.setattr(overlays, '_OVERLAY_DATA', None)
        load = overlays._load_data
    with pytest.raises(CatalogUnavailable):
        load()

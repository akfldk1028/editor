import hashlib
import json
from pathlib import Path
import shutil

from backend.app.modules.design.generation.maas import parking_requirements as parking

ROOT = Path(__file__).resolve().parents[1] / 'app/modules/law/reference'
DATA = ROOT / 'data/structured'


def test_packaged_parking_rules_preserve_source_bytes_and_load_offline(monkeypatch):
    monkeypatch.setenv('MAAS_DISABLE_PARKING_NEO4J', '1')
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', 'missing-user-data')
    manifest_path = ROOT / 'parking-source-manifest.json'
    assert manifest_path.exists(), 'Parking rule sources were not absorbed'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for entry in manifest['files']:
        assert hashlib.sha256((DATA / entry['name']).read_bytes()).hexdigest() == entry['source_sha256']
    result = parking.load_parking_requirement_rules()
    assert result['status'] == 'loaded'
    assert result['source'] == 'local_structured_seed'
    assert len(result['rules']['national']) == 11
    assert len(result['rules']['local']) == 17


def test_missing_other_jurisdiction_keeps_national_and_seoul_rules(tmp_path, monkeypatch):
    assert DATA.is_dir(), 'Missing packaged parking rules'
    target = tmp_path / 'data/structured'
    target.mkdir(parents=True)
    for filename in ('parking_appendix_rules.json', 'seoul_parking_ordinance_rules.json'):
        shutil.copyfile(DATA / filename, target / filename)
    monkeypatch.setattr(parking._design_paths, 'package_root', lambda owner: tmp_path)
    rules = parking._load_structured_seed_rules()
    assert rules is not None
    assert len(rules['national']) == 11
    assert len(rules['local']) == 14
    assert all(row['pnu_prefix'] == '11' for row in rules['local'])


def test_packaged_seoul_counts_use_declared_facility_and_preserve_provenance(monkeypatch):
    monkeypatch.setenv('MAAS_DISABLE_PARKING_NEO4J', '1')
    for area, expected in [(100, 1), (101, 2), (150, 2)]:
        result = parking.resolve_candidate_parking_requirement(pnu='1168011800104170004', building_type='entertainment', facility_area_m2=area, options={'parking_rule_id': 'parking_appendix1_row_01'})
        assert result['status'] == 'computed'
        assert result['required_spaces'] == expected
        assert result['selected_rule_id'] == 'seoul_parking_appendix2_row_01'
        assert result['source']['source_url'].startswith('https://www.law.go.kr/')
        assert result['source']['effective_date'] == '2026-03-30'
        assert result['rule_repository_source'] == 'local_structured_seed'


def test_housing_does_not_invent_a_unit_schedule(monkeypatch):
    monkeypatch.setenv('MAAS_DISABLE_PARKING_NEO4J', '1')
    kwargs = dict(pnu='1168010100106770000', building_type='housing', facility_area_m2=1000, options={'parking_rule_id': 'parking_appendix1_row_05'})
    result = parking.resolve_candidate_parking_requirement(**kwargs)
    assert result['status'] == 'needs_external_rule'
    assert result['required_spaces'] is None
    kwargs['options']['housing_unit_schedule'] = [{'exclusive_area_m2': 60, 'count': 10}]
    result = parking.resolve_candidate_parking_requirement(**kwargs)
    assert result['status'] == 'computed'
    assert result['required_spaces'] == 8

import json
import hashlib
from pathlib import Path

import pytest

from backend.app.modules.regulations import zoning_limits
from backend.app.modules.regulations.zoning_catalog import CatalogUnavailable


FIXTURES = Path(__file__).with_name('fixtures') / 'zoning_limits_parity.json'


@pytest.mark.parametrize('case', json.loads(FIXTURES.read_text(encoding='utf-8'))['cases'],
                         ids=lambda case: case['name'])
def test_preserved_source_behavior(case):
    if case['operation'] == 'resolve':
        result = zoning_limits.resolve_limits(case['zone_names'], case.get('areas'))
    else:
        zones = [zoning_limits.lookup(name) for name in case['zone_names']]
        for zone, changes in zip(zones, case.get('overrides', [])):
            zone.update(changes)
        result = zoning_limits.combine_limits(zones, case.get('areas'), unmatched=case.get('unmatched'))
    projected = {**result, 'zones': [zone['zone_name'] for zone in result['zones']]}
    assert projected == case['expected']


def test_results_do_not_share_mutable_catalog_state():
    name = '제2종일반주거지역'
    first = zoning_limits.lookup(name)
    original = first['bcr_default']
    first['bcr_default'] = 999
    assert zoning_limits.resolve_limits([name])['bcr_limit'] == original


def test_reference_data_matches_parity_fixture_provenance():
    fixture = json.loads(FIXTURES.read_text(encoding='utf-8'))
    directory = Path(zoning_limits.__file__).with_name('data')
    for name, expected in fixture['data_sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('contents', [None, '{', '{}', '{"small_part_threshold": []}'])
def test_missing_or_broken_overlap_rules_are_not_silent_defaults(tmp_path, monkeypatch, contents):
    path = tmp_path / 'rules.json'
    if contents is not None:
        path.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(zoning_limits, 'OVERLAP_PATH', path)
    with pytest.raises(CatalogUnavailable):
        zoning_limits.resolve_limits(['제2종일반주거지역', '자연녹지지역'],
                                     {'제2종일반주거지역': 1000, '자연녹지지역': 200})

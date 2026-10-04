import json
from pathlib import Path

import pytest

from backend.app.modules.land import frontage


FIXTURE = Path(__file__).with_name('fixtures') / 'frontage_parity.json'


@pytest.mark.parametrize('case', json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'],
                         ids=lambda case: case['name'])
def test_frontage_matches_original_metric_calculation(case):
    assert frontage.neighbor_roads(case['parcel'], case['features']) == case['roads']
    assert frontage.neighbor_parcels(case['parcel'], case['features']) == case['neighbors']


def test_invalid_subject_does_not_invent_frontage():
    assert frontage.neighbor_roads({}, [])['success'] is False
    assert frontage.neighbor_parcels({}, [])['success'] is False


def test_invalid_features_do_not_discard_valid_neighbor():
    case = json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'][0]
    mixed = [None, {'properties': []}, {'properties': {'lndcgrCode': '07'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[float('nan'), 0]]]}}] + case['features']
    assert frontage.neighbor_roads(case['parcel'], mixed) == case['roads']
    assert frontage.neighbor_parcels(case['parcel'], mixed) == case['neighbors']

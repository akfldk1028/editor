import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from backend.app.modules.land.vworld.geometry import GeometryProviderUnavailable
from backend.app.modules.land.analysis import analyze_land


FIXTURE = Path(__file__).with_name('fixtures') / 'land_parcel_parity.json'


def comparable(result):
    value = deepcopy(result)
    value.pop('storage', None)
    # Provider errors are deliberately sanitized by the new adapter; no-zone
    # wording no longer refers to a future data.go.kr integration.
    if 'errors' in value:
        value['errors'] = bool(value['errors'])
    if 'warning' in value:
        value['warning'] = bool(value['warning'])
    return value


def digest(result):
    return hashlib.sha256(json.dumps(comparable(result), ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize('case', json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'],
                         ids=lambda case: case['name'])
def test_full_parcel_response_matches_original_calculation(case):
    class Addresses:
        async def fetch_parcel_geometry(self, pnu):
            return {'success': True, 'geometry': deepcopy(case['geometry'])}

    class Attributes:
        async def get(self, pnu):
            return deepcopy(case['land_info'])

    class Geometry:
        async def zone_features(self, parcel):
            if case.get('geometry_failure'):
                raise GeometryProviderUnavailable('fixture unavailable')
            return deepcopy(case['zone_features'])

        async def cadastral_features(self, parcel):
            if case.get('geometry_failure'):
                raise GeometryProviderUnavailable('fixture unavailable')
            return deepcopy(case['cadastral_features'])

    value = asyncio.run(analyze_land(case['body'], Addresses(), Attributes(), Geometry()))
    # `review` (2026-10-09) is additive: the per-lot provision list, tested in test_land_review.py.
    review = value.pop('review', None)
    assert review is None or {item['group'] for item in review['items']} <= {'use', 'bcr_far', 'height_sunlight', 'road_setback', 'parking_landscape', 'district'}
    assert digest(value) == case['response_sha256']
    assert bool(value.get('setback_lines')) == case['has_setbacks']
    assert value['storage']['saved'] is False

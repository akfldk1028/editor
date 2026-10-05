"""Parity against the preserved selector immediately before geometry caching."""
from pathlib import Path
import json
import time

import pytest
from shapely.geometry import box, LineString, shape

from backend.app.modules.design.generation.maas import parking_layout as parking


def reference_selector():
    namespace = dict(vars(parking))
    source = Path(__file__).with_name('fixtures').joinpath('parking_selector_before_cache.py').read_text(encoding='utf-8')
    exec(compile(source, 'parking_selector_before_cache.py', 'exec'), namespace)
    return namespace['_select_compact_grid_candidates']


def candidates():
    result = []
    for row in range(3):
        for index in range(8):
            x, y = index * 1.25, row * 11
            width = 3.3 if index == 0 else 2.5
            result.append(dict(type='accessible' if index == 0 else 'standard',
                width_m=width, length_m=5, row=row, orientation='x',
                start_u=x, start_v=y, stall_polygon=box(x,y,x+width,y+5),
                drive_polygon=box(x,y+5,x+width,y+11)))
    return result


@pytest.mark.parametrize('required,accessible', [(1,0),(3,1),(6,0),(9,1),(18,1)])
def test_cached_selector_preserves_exact_order_and_partial_capacity(required, accessible, monkeypatch):
    items = candidates()
    kwargs = dict(required_spaces=required, accessible_spaces=accessible,
                  access_edges=[LineString([(0,5),(12,5)])])
    original = parking._stall_polygons_overlap
    counts = {'calls':0}
    def counted(*args):
        counts['calls'] += 1
        return original(*args)
    monkeypatch.setattr(parking, '_stall_polygons_overlap', counted)
    started = time.monotonic()
    expected = reference_selector()(items, **kwargs)
    original_calls = counts['calls']
    original_seconds = time.monotonic()-started
    counts['calls'] = 0
    started = time.monotonic()
    actual = parking._select_compact_grid_candidates(items, **kwargs)
    print(f'required={required} original={original_seconds:.3f}s cached={time.monotonic()-started:.3f}s overlap_calls={original_calls}->{counts["calls"]}')
    assert [id(item) for item in actual] == [id(item) for item in expected]
    if required >= 6:
        assert counts['calls'] < original_calls


@pytest.mark.parametrize('required', [8, 16, 32])
def test_captured_capacity_anchor_geometry_matches_reference(required):
    data = json.loads(Path(__file__).with_name('fixtures').joinpath('parking_anchor_candidates.json').read_text())
    # Every tenth entry spans the real 452-candidate layout, orientations,
    # standard/accessibility types and all parking rows. Keep scalar reference
    # parity bounded instead of adding its multi-minute full search to pytest.
    items = [{key: shape(value) if key.endswith('_polygon') else value
              for key,value in item.items()} for item in data['candidates'][::10]]
    kwargs = dict(required_spaces=required, accessible_spaces=data['accessible_spaces'],
                  access_edges=[shape(item) for item in data['access_edges']])
    expected = reference_selector()(items, **kwargs)
    actual = parking._select_compact_grid_candidates(items, **kwargs)
    assert [id(item) for item in actual] == [id(item) for item in expected]


def test_duplicate_and_tiny_stall_dict_membership_matches_reference():
    items = candidates()
    items.extend([items[0], dict(items[0])])
    tiny = dict(items[3], stall_polygon=box(100,100,100.0001,100.0001))
    items.extend([tiny, dict(tiny)])
    kwargs = dict(required_spaces=18, accessible_spaces=1)
    expected = reference_selector()(items, **kwargs)
    actual = parking._select_compact_grid_candidates(items, **kwargs)
    assert [id(item) for item in actual] == [id(item) for item in expected]

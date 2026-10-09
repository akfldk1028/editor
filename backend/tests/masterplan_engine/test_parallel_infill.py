import pytest
from shapely.geometry import box, mapping
from shapely.affinity import rotate

from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves


def test_ai_can_request_strict_ring_and_mixed_parking_without_moving_site():
    request = {'site': mapping(box(0, 0, 40, 40)), 'rules': {}, 'options': {}}
    result = apply_placement_moves(request, {'circulation': 'ring', 'parking_mix': 'parallel_infill'})['request']
    assert result['site'] == request['site']
    assert result['options']['basement_parking_field'] == 'ring'
    assert result['options']['parking_mix'] == 'parallel_infill'
    assert result['rules'] == request['rules']
    assert request['options'] == {} and request['rules'] == {}


@pytest.mark.parametrize('circulation', ['auto', 'comb', 'ring'])
def test_circulation_is_an_alternative_choice(circulation):
    request = {'site': mapping(box(0, 0, 40, 40)), 'options': {}, 'rules': {}}
    result = apply_placement_moves(request, {'circulation': circulation, 'parking_mix': 'perpendicular'})['request']
    assert result['options']['basement_parking_field'] == circulation
    assert result['options']['parking_mix'] == 'perpendicular'


@pytest.mark.parametrize('angle', [0, 31])
def test_parallel_infill_uses_shallow_strip_without_narrowing_drive(angle):
    from backend.app.modules.design.generation.maas.masterplan.parallel_parking import infill
    rot = lambda g: rotate(g, angle, origin=(0, 0))
    host, drive = rot(box(0, 0, 18, 8)), rot(box(0, 2, 18, 8))
    result = infill(host, drive, [], 3, aisle_width=6)
    assert len(result) == 3
    for stall in result:
        assert stall['type'] == 'standard_parallel'
        assert stall['polygon'].area == pytest.approx(12)
        assert host.buffer(1e-6).covers(stall['polygon'])
        assert stall['polygon'].intersection(drive).area < 1e-6
        assert drive.buffer(1e-6).covers(stall['front'])


def test_parallel_infill_does_not_bridge_obstacles_or_clip_stalls():
    from backend.app.modules.design.generation.maas.masterplan.parallel_parking import infill
    drive = box(0, 2, 18, 8)
    host = box(0, 0, 18, 8).difference(box(5, 0, 13, 2))
    assert infill(host, drive, [], 3, aisle_width=6) == []


def test_validator_uses_parallel_dimensions_and_full_long_side_access():
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    from backend.app.modules.design.generation.maas.masterplan.geometry import feature
    request = {'site': mapping(box(0, 0, 20, 20)), 'rules': {'stall_width_m': 2.5, 'stall_length_m': 5}, 'law': {}}
    bay = feature('parking_stall', box(0, 0, 6, 2), 0, type='standard_parallel', stall_id='P')
    for drive, expected in [(box(0, 2, 6, 8), 'passed'), (box(6, 0, 12, 2), 'failed')]:
        result = validate_plan(request, {'features': [bay, feature('parking_aisle', drive, 0)]})
        checks = {c['id']: c['status'] for c in result['checks']}
        assert checks['stall_dimensions:P'] == 'passed'
        assert checks['stall_aisle_frontage:P'] == expected

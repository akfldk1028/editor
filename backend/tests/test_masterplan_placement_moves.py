import copy

import pytest
from shapely.geometry import LineString, box, mapping, shape

from backend.app.modules.design.generation.maas.masterplan_operations import invoke


def request():
    return {'site': mapping(box(0, 0, 100, 100)),
            'buildable': mapping(box(0, 0, 100, 100)),
            'front_frontage': mapping(LineString([(0, 0), (100, 0)])),
            'law': {'required_spaces': 40, 'status': 'needs_evidence'},
            'rules': {'stall_length_m': 5, 'aisle_width_m': 6},
            'evidence': {'source': ['authored']},
            'options': {'planning_stage': 'placement', 'target_footprint_m2': 1600,
                        'target_parking_stalls': 50, 'max_surface_stalls': 30}}


def call(req, moves):
    return invoke({'operation': 'apply_placement_moves',
                   'arguments': {'request': req, 'moves': moves}})


def test_moves_are_cloned_and_preserve_evidence_counts_and_area():
    req = request()
    before = copy.deepcopy(req)
    response = call(req, {'building_side': 'SE', 'surface_share': 'half', 'ramp': 'curved'})
    assert response['status'] == 'succeeded', response
    result = response['result']
    moved = result['request']
    assert req == before
    for key in ('site', 'buildable', 'front_frontage', 'law', 'rules', 'evidence'):
        assert moved[key] == before[key]
    assert moved['options']['target_parking_stalls'] == 50
    assert moved['options']['target_surface_stalls'] == 25
    assert moved['options']['max_surface_stalls'] == 30
    assert moved['options']['ramp_shape'] == 'curved'
    assert moved['options']['target_footprint_m2'] == 1600
    fp = shape(moved['footprint'])
    assert fp.area == pytest.approx(1600)
    assert fp.centroid.x > 50 and fp.centroid.y < 50
    assert result['applied']['building_side'] == 'SE'
    moved['evidence']['source'].append('changed')
    assert req == before


@pytest.mark.parametrize('moves', [{'bad': 'keep'}, {'building_side': 'east'},
    {'piloti': True}, {'surface_share': 0.5}, {'ramp': 'curved_beside'}, {'ramp': []}])
def test_invalid_move_enum_is_refused(moves):
    response = call(request(), moves)
    assert response['status'] == 'failed'
    assert 'move' in response['reason']


@pytest.mark.parametrize('key,value', [('footprint', mapping(box(0, 0, 40, 40))),
    ('ground_footprint', mapping(box(0, 0, 10, 10))),
    ('core', mapping(box(5, 5, 10, 10))), ('columns', [mapping(box(2, 2, 3, 3))])])
@pytest.mark.parametrize('moves', [{'building_side': 'N'}, {'piloti': 'piloti'}])
def test_authored_geometry_is_protected(key, value, moves):
    req = request()
    req[key] = value
    response = call(req, moves)
    assert response['status'] == 'failed'
    assert 'authored' in response['reason']
    kept = call(req, {'ramp': 'any'})
    assert kept['status'] == 'succeeded'
    assert kept['result']['request'][key] == value


def test_unavailable_direction_is_refused_without_fallback():
    req = request()
    req['buildable'] = mapping(box(0, 0, 40, 40))
    response = call(req, {'building_side': 'NE'})
    assert response['status'] == 'failed'
    assert 'candidate' in response['reason']


def test_missing_count_is_not_guessed():
    req = request()
    req['options'].pop('target_parking_stalls')
    req['law'].pop('required_spaces')
    response = call(req, {'surface_share': 'half'})
    assert response['status'] == 'failed'
    assert 'count' in response['reason']


def test_surface_promises_and_caps_are_preserved():
    req = request()
    assert call(req, {'surface_share': 'all_surface'})['status'] == 'failed'
    req['options']['target_surface_stalls'] = 26
    assert call(req, {'surface_share': 'half'})['status'] == 'failed'
    req['options'].pop('target_parking_stalls')
    assert call(req, {'surface_share': 'mostly_surface'})['status'] == 'failed'
    req['options'].pop('target_surface_stalls')
    response = call(req, {'surface_share': 'half'})
    assert response['status'] == 'succeeded', response
    assert response['result']['request']['options']['target_surface_stalls'] == 20


def test_piloti_retains_footprint_and_reports_unverified_clear_height():
    response = call(request(), {'building_side': 'SE', 'piloti': 'piloti'})
    assert response['status'] == 'succeeded', response
    result = response['result']
    fp = shape(result['request']['footprint'])
    ground = shape(result['request']['ground_footprint'])
    assert fp.area == pytest.approx(1600)
    assert 0 < ground.area < fp.area
    assert fp.covers(ground)
    assert any('clear' in note and 'unverified' in note for note in result['unresolved'])


def test_keep_does_not_add_geometry_or_change_options():
    req = request()
    response = call(req, dict.fromkeys(('building_side', 'piloti', 'surface_share', 'ramp'), 'keep'))
    assert response['status'] == 'succeeded', response
    assert response['result'] == {'request': req, 'applied': {}, 'unresolved': []}


def test_center_selects_a_central_candidate_without_shrinking():
    response = call(request(), {'building_side': 'center'})
    assert response['status'] == 'succeeded', response
    fp = shape(response['result']['request']['footprint'])
    assert fp.area == pytest.approx(1600)
    assert fp.centroid.distance(box(0, 0, 100, 100).centroid) < 5


def test_explicit_zero_count_is_not_replaced_by_law_count():
    req = request()
    req['options']['target_parking_stalls'] = 0
    response = call(req, {'surface_share': 'all_surface'})
    assert response['status'] == 'succeeded', response
    assert response['result']['request']['options']['target_surface_stalls'] == 0


def test_piloti_refuses_to_erase_the_entire_ground():
    req = request()
    req['site'] = req['buildable'] = mapping(box(0, 0, 10, 10))
    req['options']['target_footprint_m2'] = 100
    response = call(req, {'piloti': 'piloti'})
    assert response['status'] == 'failed'
    assert 'candidate' in response['reason']


def test_equal_area_proportions_offer_distinct_central_envelopes():
    geometries = {}
    for proportion in ('compact', 'along_axis', 'cross_axis'):
        response = call(request(), {'building_side': 'center', 'building_proportion': proportion})
        assert response['status'] == 'succeeded', response
        fp = shape(response['result']['request']['footprint'])
        assert fp.area == pytest.approx(1600)
        assert fp.centroid.distance(box(0, 0, 100, 100).centroid) < 5
        geometries[proportion] = fp
    def ratio(p):
        x0,y0,x1,y1 = p.bounds
        return (x1-x0)/(y1-y0)
    assert ratio(geometries['compact']) == pytest.approx(1)
    assert ratio(geometries['along_axis']) > 1.5
    assert ratio(geometries['cross_axis']) < 1/1.5


def test_proportion_cannot_replace_authored_mass():
    req = request()
    req['footprint'] = mapping(box(0, 0, 40, 40))
    assert call(req, {'building_proportion': 'compact'})['status'] == 'failed'


def test_perpendicular_move_does_not_report_parallel_assumption():
    result = call(request(), {'parking_mix': 'perpendicular'})['result']
    assert not any('parallel infill' in note for note in result['unresolved'])


def test_proportions_follow_explicit_layout_axis_not_frontage_label():
    from shapely.affinity import rotate
    from backend.app.modules.design.generation.maas.masterplan.joint import footprint_candidates
    candidates = footprint_candidates(box(0, 0, 100, 100), 1600,
        LineString([(0, 0), (100, 0)]), 16, angle_deg=90, aspect_ratio=2)
    assert candidates
    fp = rotate(candidates[0], -90, origin=(0, 0))
    x0,y0,x1,y1 = fp.bounds
    assert (x1-x0)/(y1-y0) == pytest.approx(2)

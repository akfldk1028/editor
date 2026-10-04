import json

import pytest

from backend.app.modules.planm_execution import service


def test_empty_core_search_survives_stage_artifact_without_acceptance(tmp_path):
    # Local-metre floor plate from the preserved candidate PK18183.
    polygon = [
        [-2.2375841134344228, 3.9780892599374056],
        [-1.2548159269499592, 4.349717108067125],
        [3.462703894765582, -2.4808537191711366],
        [0.6123992934008129, -3.558679168112576],
        [-0.2594101603026502, -1.253182951360941],
        [-1.3325002964702435, -1.6589654949493706],
        [-2.6339152613072656, 0.17007826315239072],
        [-2.972352935525123, 1.0650751837529242],
        [-1.365774660895113, 1.6725930427201092],
    ]
    payload = {'project_id': 'archived-small-floor', 'floors': 2, 'footprint_polygon': polygon,
               'floor_footprints': [{'floor_index': i, 'footprint_polygon': polygon} for i in (1, 2)],
               'use_mix': {'office': 1}, 'site_edges': [], 'access_candidates': [],
               'building_code_context': {'floor_to_floor_height_m': 3.5}}
    input_path = tmp_path / 'mass.json'
    input_path.write_text(json.dumps(payload), encoding='utf-8')
    before = input_path.read_bytes()
    output = tmp_path / 'artifacts'
    state = output / 'state.json'
    assert service.normalize(input_path, state, output)['status'] == 'success'
    assert service.analyze(input_path, state, output)['status'] == 'success'
    result = service.alternatives(input_path, state, output)
    assert result['status'] == 'blocked'
    assert result['violations'][0]['code'] == 'insufficient_accepted_alternatives'
    summary = json.loads((output / 'alternatives.json').read_text(encoding='utf-8'))
    assert summary['accepted_count'] == 0 and summary['alternatives'] == []
    assert summary['rejected_families']
    diagnostic = summary['rejected_families'][0]['diagnostics'][0]
    assert diagnostic['code'] == 'no_core_candidates'
    assert diagnostic['shared_intersection_area_m2'] == pytest.approx(21.263416997821526)
    assert [(a['minimum_width_m'], a['minimum_depth_m'], a['candidate_count'])
            for a in diagnostic['attempts']] == [(7.6, 5.2, 0), (7.6, 5.2, 0), (6.8, 6.8, 0)]
    assert input_path.read_bytes() == before
    assert 'jurisdiction' in json.loads(state.read_text(encoding='utf-8'))['unresolved_facts']

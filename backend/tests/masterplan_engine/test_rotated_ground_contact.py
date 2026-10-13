import json
from pathlib import Path

import pytest
from shapely.geometry import shape, mapping
from shapely.affinity import translate

from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan


@pytest.mark.parametrize('intrusion', [False, True])
def test_coincident_rotated_boundary_does_not_flip_collision_area(intrusion):
    fixture = json.loads((Path(__file__).parent/'fixtures/kmass_rotated_ground_contact.json').read_text())
    ground = fixture['ground']
    drive = shape(fixture['drive'])
    if intrusion:
        drive = translate(drive, xoff=-0.1)
    request = {'site': fixture['site'], 'footprint': ground, 'ground_footprint': ground,
               'law': {}, 'rules': {}, 'options': {}}
    features = [{'type': 'Feature', 'properties': {'layer': layer, 'level': 0}, 'geometry': geometry}
                for layer, geometry in [('building_footprint', ground), ('building_ground_footprint', ground),
                                         ('parking_aisle', mapping(drive))]]
    checks = {c['id']: c for c in validate_plan(request, {'features': features})['checks']}
    expected = 'failed' if intrusion else 'passed'
    assert checks['drive_ground_footprint_collision:0']['status'] == expected
    assert checks['drive_obstructions:0']['status'] == expected
    if not intrusion:
        assert checks['drive_obstructions:0']['overlap_m2'] == 0

from copy import deepcopy
import pytest
from shapely.geometry import box, mapping, shape
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan


def feature(layer, geom, level=0):
    return {'type': 'Feature', 'properties': {'layer': layer, 'level': level}, 'geometry': mapping(geom)}


def request():
    return {'site': mapping(box(0, 0, 60, 60)), 'buildable': mapping(box(0, 0, 60, 60)),
            'footprint': mapping(box(10, 10, 50, 50)), 'ground_footprint': mapping(box(10, 10, 50, 50)),
            'core': mapping(box(15, 15, 18, 22)), 'columns': [], 'law': {},
            'rules': {'aisle_width_m': 6}, 'options': {'core_vehicle_clearance_m': 1.5}}


def test_carved_aisle_touching_core_fails_declared_clearance():
    r = request()
    core = shape(r['core'])
    f = [feature('building_core', core, -1), feature('parking_aisle', box(18, 10, 24, 40), -1)]
    result = validate_plan(r, {'features': f})
    check = next((c for c in result['checks'] if c['id'] == 'core_vehicle_clearance:-1'), None)
    assert check is not None, 'zero polygon overlap must not hide zero usable clearance'
    assert check['status'] == 'failed'
    assert check['distance_m'] == 0


def test_core_candidates_are_authorized_and_preserve_area_and_count():
    from backend.app.modules.design.generation.maas.masterplan import core_repair
    r = request()
    baseline = deepcopy(r)
    f = [feature('building_core', shape(r['core']), -1),
         feature('parking_aisle', box(18, 10, 24, 40), -1)]
    assert core_repair.propose_core_repairs(r, {'features': f})['candidates'] == []
    r['options']['allow_core_repair'] = True
    got = core_repair.propose_core_repairs(r, {'features': f}, limit=3)
    assert got['candidates']
    for c in got['candidates']:
        proposed = c['request']
        core = shape(proposed['core'])
        assert core.area == pytest.approx(shape(r['core']).area)
        assert shape(r['ground_footprint']).covers(core)
        for k in ('site', 'footprint', 'ground_footprint', 'law'):
            assert proposed[k] == baseline[k]
        assert not core.equals(shape(r['core']))


def test_invalid_core_clearance_is_rejected():
    r = request()
    r['options']['core_vehicle_clearance_m'] = -1
    with pytest.raises(ValueError, match='core vehicle clearance'):
        validate_plan(r, {'features': []})


def test_pinched_connected_drive_does_not_count_as_full_width():
    from backend.app.modules.design.generation.maas.masterplan.circulation import full_width_stall_access
    # Two wide bays are joined by a 2m neck; topological connectivity is true.
    drive = box(0, 0, 12, 6).union(box(12, 2, 16, 4)).union(box(16, 0, 28, 6))
    stalls = [box(20, 6, 22.5, 11)]
    assert drive.geom_type == 'Polygon'
    assert full_width_stall_access(drive, stalls, [box(0, 0, 6, 6)], 6) is False
    assert full_width_stall_access(box(0, 0, 28, 6), stalls, [box(0, 0, 6, 6)], 6) is True

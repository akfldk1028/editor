from shapely.geometry import box, LineString
import pytest
from shapely.affinity import rotate, translate, scale
from backend.app.modules.design.generation.maas.masterplan.aisle_ramps import reserve_ramp


def row():
    return {'drive': box(0, 0, 40, 6), 'stalls': [
        {'polygon': box(x, 6, x+2.5, 11), 'front': box(x, 0, x+2.5, 6), 'type': 'standard_90deg'}
        for x in range(0, 40, 5)], 'angle_deg': 0}


def test_reserving_internal_ramp_removes_real_blocked_stalls():
    original = row()
    ramp = {'polygon': box(10, 6, 16, 36), 'upper_landing': box(10, 6, 16, 12)}
    result = reserve_ramp(original, ramp, LineString([(0, 0), (0, 6)]), 6.)
    assert result is not None
    assert result['provided'] == 6
    assert len(original['stalls']) == 8
    assert all(s['polygon'].intersection(ramp['polygon']).area < 1e-7 for s in result['stalls'])
    assert result['drive'].intersection(ramp['polygon'].difference(ramp['upper_landing'])).area < 1e-7


def test_ramp_cutting_the_only_road_approach_is_rejected():
    ramp = {'polygon': box(1, -10, 7, 20), 'upper_landing': box(1, 14, 7, 20)}
    assert reserve_ramp(row(), ramp, LineString([(0, 0), (0, 6)]), 6.) is None


def test_ramp_reservation_discards_unreachable_empty_drive_fragments():
    original = row()
    original['drive'] = original['drive'].union(box(12, 12, 15, 15))
    ramp = {'polygon': box(20, 6, 26, 36), 'upper_landing': box(20, 6, 26, 12)}
    result = reserve_ramp(original, ramp, LineString([(0, 0), (0, 6)]), 6.)
    assert result is not None
    assert result['drive'].intersection(box(12, 12, 15, 15)).area == 0


def test_rotated_exact_width_road_contact_tolerates_roundoff_only():
    from shapely.affinity import rotate, translate
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
    drive = rotate(box(0, 0, 40, 6).union(box(35, 0, 45, 12)), 150.215, origin=(0, 0))
    road = translate(rotate(LineString([(0, 0), (0, 6)]), 150.215, origin=(0, 0)), xoff=1e-10)
    front = rotate(box(20, 0, 22.5, 6), 150.215, origin=(0, 0))
    assert _width_connected({'drive': drive, 'stalls': [{'front': front}]}, [road], 6.)


def test_rotating_a_pure_exact_width_aisle_does_not_destroy_connectivity():
    from shapely.affinity import rotate
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
    drive = rotate(box(0, 0, 40, 6), 37., origin=(0, 0))
    road = rotate(LineString([(0, 0), (0, 6)]), 37., origin=(0, 0))
    front = rotate(box(20, 0, 22.5, 6), 37., origin=(0, 0))
    assert _width_connected({'drive': drive, 'stalls': [{'front': front}]}, [road], 6.)


@pytest.mark.parametrize('angle,offset,mirror', [(0, 0, False), (37, 0, False),
                                               (150.22, 10000, False), (29, -10000, True)])
def test_ramp_reservation_is_independent_of_site_frame(angle, offset, mirror):
    def transform(g):
        return translate(rotate(scale(g, xfact=-1 if mirror else 1, yfact=1, origin=(0, 0)),
                                angle, origin=(0, 0)), xoff=offset, yoff=-offset)
    source = row()
    transformed = {**source, 'drive': transform(source['drive']), 'stalls': [
        {**s, 'polygon': transform(s['polygon']), 'front': transform(s['front'])} for s in source['stalls']]}
    ramp = {'polygon': transform(box(10, 6, 16, 36)), 'upper_landing': transform(box(10, 6, 16, 12))}
    result = reserve_ramp(transformed, ramp, transform(LineString([(0, 0), (0, 6)])), 6.)
    assert result is not None
    assert result['provided'] == 6
    assert result['removed_for_ramp'] == 2


@pytest.mark.parametrize('angle,mirror', [(0, False), (37, False), (150.22, True)])
def test_nonconvex_narrow_neck_never_becomes_drivable_after_transform(angle, mirror):
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
    def transform(g):
        return translate(rotate(scale(g, xfact=-1 if mirror else 1, yfact=1, origin=(0, 0)),
                                angle, origin=(0, 0)), xoff=1000, yoff=-1000)
    drive = unary_union([box(0, 0, 6, 8), box(2.9, 8, 3.1, 20), box(0, 20, 30, 26)])
    candidate = {'drive': transform(drive), 'stalls': [{'front': transform(box(20, 20, 22.5, 26))}]}
    assert not _width_connected(candidate, [transform(LineString([(0, 0), (6, 0)]))], 6.)


@pytest.mark.parametrize('angle,mirror', [(0, False), (37, False), (150.22, True)])
def test_internal_ramp_generation_preserves_geometry_on_generic_transformed_site(angle, mirror):
    from shapely.geometry import Polygon
    from backend.app.modules.design.generation.maas.masterplan.aisle_ramps import aisle_ramp_candidates
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
    def transform(g):
        return translate(rotate(scale(g, xfact=-1 if mirror else 1, yfact=1, origin=(0, 0)),
                                angle, origin=(0, 0)), xoff=500, yoff=-200)
    source = row()
    transformed = {**source, 'provided': 8, 'angle_deg': angle, 'drive': transform(source['drive']),
                   'stalls': [{**s, 'polygon': transform(s['polygon']), 'front': transform(s['front'])}
                              for s in source['stalls']]}
    site, road = transform(box(0, -10, 70, 65)), transform(LineString([(0, 0), (0, 6)]))
    rules = {'ramp_width_m': 6., 'ramp_max_slope': .17, 'curved_ramp_width_m': 6.5,
             'curved_ramp_max_slope': .14, 'curve_min_inner_radius_m': 5.,
             'transition_length_m': 3., 'transition_slope': .07, 'aisle_width_m': 6.}
    proposals = aisle_ramp_candidates(site, [transformed], Polygon(), road, rules, 3.3, limit=4)
    assert 0 < len(proposals) <= 4
    for proposal in proposals:
        assert proposal['provided'] == len(proposal['stalls']) <= 8
        assert site.buffer(1e-6).covers(proposal['ramp']['polygon'])
        assert _width_connected(proposal, [road], 6.)
        assert all(s['polygon'].intersection(proposal['ramp']['polygon']).area < 1e-6
                   for s in proposal['stalls'])

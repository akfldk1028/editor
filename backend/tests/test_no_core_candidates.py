from dataclasses import replace

import pytest
from shapely.geometry import Polygon

from backend.app.core.serialization import to_jsonable
from backend.app.modules.alternative_composer.service import compose_structural_alternatives
from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.schemas.mass import MassInput, FloorFootprint, BuildingCodeContext
from backend.app.schemas.result import CoreSearchAttempt


SAVED_FOOTPRINT = [
    (-2.2375841134344228, 3.9780892599374056),
    (-1.2548159269499592, 4.349717108067125),
    (3.462703894765582, -2.4808537191711366),
    (0.6123992934008129, -3.558679168112576),
    (-0.2594101603026502, -1.253182951360941),
    (-1.3325002964702435, -1.6589654949493706),
    (-2.6339152613072656, 0.17007826315239072),
    (-2.972352935525123, 1.0650751837529242),
    (-1.365774660895113, 1.6725930427201092),
]


def saved_mass():
    return MassInput(
        project_id='saved-shape-regression', floors=2,
        footprint_polygon=SAVED_FOOTPRINT,
        floor_footprints=tuple(FloorFootprint(i, tuple(SAVED_FOOTPRINT)) for i in (1, 2)),
        use_mix={'office': 1}, site_edges=[], access_candidates=[],
        building_code_context=BuildingCodeContext(floor_to_floor_height_m=3.5),
    )


def test_saved_small_shape_preserves_empty_search_evidence_without_acceptance():
    mass = saved_mass()
    result = run_building_alternatives(mass)
    assert result.accepted_count == 0 and result.alternatives == ()
    assert len(result.rejected_families) == 1
    diagnostic = to_jsonable(result.rejected_families)[0]['diagnostics'][0]
    assert diagnostic['code'] == 'no_core_candidates'
    assert diagnostic['shared_intersection_area_m2'] == pytest.approx(21.263416997821526)
    assert diagnostic['shared_intersection_bounds_m'] == list(Polygon(SAVED_FOOTPRINT).bounds)
    assert diagnostic['requested_core_area_m2'] == pytest.approx(2.976878379695014)
    assert diagnostic['attempts'] == [
        dict(minimum_width_m=7.6, minimum_depth_m=5.2, widen=False, candidate_count=0),
        dict(minimum_width_m=7.6, minimum_depth_m=5.2, widen=True, candidate_count=0),
        dict(minimum_width_m=6.8, minimum_depth_m=6.8, widen=True, candidate_count=0),
    ]
    assert mass.site_edges == [] and mass.access_candidates == []


def test_nonoverlapping_floors_report_zero_intersection_without_nan():
    mass = saved_mass()
    shifted = replace(mass.floor_footprints[1], footprint_polygon=tuple((x+100,y) for x,y in SAVED_FOOTPRINT))
    mass = replace(mass, footprint_polygon=[(-10,-10),(110,-10),(110,10),(-10,10)], floor_footprints=(mass.floor_footprints[0], shifted))
    composition = compose_structural_alternatives(mass)
    assert not composition.alternatives
    evidence = to_jsonable(composition.rejections)[0]['diagnostic']
    assert evidence['shared_intersection_area_m2'] == 0
    assert evidence['shared_intersection_bounds_m'] is None


@pytest.mark.parametrize('changes', [
    {'shared_intersection_area_m2': float('nan')},
    {'shared_intersection_bounds_m': (0, 0, float('inf'), 2)},
    {'attempts': ()},
    {'attempts': (CoreSearchAttempt(7.6, 5.2, False, 1),)},
])
def test_empty_search_diagnostic_rejects_invalid_or_nonempty_evidence(changes):
    diagnostic = compose_structural_alternatives(saved_mass()).rejections[0].diagnostic
    with pytest.raises(ValueError):
        replace(diagnostic, **changes)

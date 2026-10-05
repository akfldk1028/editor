from collections import Counter

import pytest
from shapely.affinity import rotate
from shapely.geometry import box


from backend.app.modules.design.generation.maas.masterplan.program import (
    plant_zone_candidates,
    split_plant_zone_candidates,
)


ROOMS = [
    {"name": "plant", "area_m2": 90, "kind": "plant"},
    {"name": "store", "area_m2": 50, "kind": "storage"},
    {"name": "fan", "area_m2": 40, "kind": "plant"},
]


@pytest.mark.parametrize("angle", [0, 31])
def test_two_edge_bands_fit_whole_rooms_around_central_core(angle):
    host = rotate(box(0, 0, 20, 20), angle, origin=(0, 0))
    core = rotate(box(8, 8, 12, 12), angle, origin=(0, 0))
    assert not plant_zone_candidates(host, ROOMS, keep_clear=core, angle_deg=angle)
    candidates = split_plant_zone_candidates(host, ROOMS, keep_clear=core, angle_deg=angle)
    assert 2 <= len(candidates) <= 8
    assert len({c["side"] for c in candidates}) >= 2
    for candidate in candidates:
        assert Counter(r["name"] for r in candidate["rooms"]) == Counter(r["name"] for r in ROOMS)
        assert candidate["zone"].intersection(core).area < 1e-7
        assert host.buffer(1e-7).covers(candidate["zone"])
        assert candidate["zone"].area == pytest.approx(180, abs=1e-6)
        for i, room in enumerate(candidate["rooms"]):
            polygon = room["polygon"]
            assert polygon.geom_type == "Polygon" and not polygon.interiors
            assert polygon.is_valid
            assert polygon.area + 1e-7 >= room["area_m2"]
            for other in candidate["rooms"][i + 1:]:
                assert polygon.intersection(other["polygon"]).area < 1e-7


def test_does_not_split_single_room_or_force_impossible_programme():
    host = box(0, 0, 20, 20)
    assert split_plant_zone_candidates(host, ROOMS[:1]) == []
    assert split_plant_zone_candidates(host, ROOMS, keep_clear=host) == []


def test_budget_and_determinism():
    host, core = box(0, 0, 20, 20), box(8, 8, 12, 12)
    first = split_plant_zone_candidates(host, ROOMS, keep_clear=core, limit=2)
    second = split_plant_zone_candidates(host, ROOMS, keep_clear=core, limit=2)
    assert len(first) == 2
    assert [c["zone"].wkb_hex for c in first] == [c["zone"].wkb_hex for c in second]
    with pytest.raises(ValueError):
        split_plant_zone_candidates(host, ROOMS, limit=9)


@pytest.mark.parametrize('angle', [0, 37])
def test_adjacent_edges_share_corner_without_overlapping_or_losing_rooms(angle):
    # West 7.5x20 and the remaining south 12.5x8 fit exactly. Using
    # full-host strips for both makes their common corner overlap and rejects
    # this valid programme; the second band must use the remaining host.
    host=rotate(box(0,0,20,20),angle,origin=(0,0))
    core=rotate(box(12,8,20,20),angle,origin=(0,0))
    programme=[{'name':'mechanical','kind':'plant','area_m2':150},
               {'name':'storage','kind':'plant','area_m2':100}]
    candidates=split_plant_zone_candidates(host,programme,keep_clear=core,angle_deg=angle)
    assert candidates
    for candidate in candidates:
        assert candidate['zone'].area == pytest.approx(250,abs=1e-6)
        assert host.buffer(1e-7).covers(candidate['zone'])
        assert candidate['zone'].intersection(core).area < 1e-7
        assert len(candidate['rooms'])==2
        assert candidate['rooms'][0]['polygon'].intersection(candidate['rooms'][1]['polygon']).area < 1e-7

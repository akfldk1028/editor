"""Programme edge alternatives remain whole rooms and respect occupied space."""

from shapely.geometry import Polygon, box
from backend.app.modules.design.generation.maas.masterplan.program import plant_zone, plant_zone_candidates, _slice_rooms


def rooms(*areas):
    return [{"name": f"room-{i}", "kind": "plant", "area_m2": area} for i, area in enumerate(areas)]


def test_returns_all_edges_and_wrapper_uses_stable_ranked_first():
    basement = box(0, 0, 30, 20)
    programme = rooms(100.123, 79)
    candidates = plant_zone_candidates(basement, programme)
    assert {c["side"] for c in candidates} == {"west", "east", "north", "south"}
    assert candidates[0]["side"] == "west"
    assert plant_zone(basement, programme)["side"] == candidates[0]["side"]
    assert len(plant_zone_candidates(basement, programme, limit=2)) == 2
    for c in candidates:
        assert len(c["rooms"]) == len(programme)
        for room in c["rooms"]:
            assert room["polygon"].geom_type == "Polygon"
            assert room["polygon"].area + 1e-8 >= room["area_m2"]
            assert room["placed_area_m2"] + 1e-8 >= room["area_m2"]


def test_all_alternatives_respect_combined_keep_clear():
    basement = box(0, 0, 30, 20)
    reserved = box(14, 0, 16, 20)
    candidates = plant_zone_candidates(basement, rooms(180), keep_clear=reserved)
    assert {c["side"] for c in candidates} == {"west", "east"}
    assert all(c["zone"].intersection(reserved).area == 0 for c in candidates)
    assert all(r["polygon"].intersection(reserved).area == 0 for c in candidates for r in c["rooms"])


def test_disconnected_room_slice_rejects_entire_allocation():
    zone = Polygon([(0,0),(10,0),(10,2),(2,2),(2,8),(10,8),(10,10),(0,10)])
    assert _slice_rooms(zone, rooms(26, 26), True, 0, (0,0)) == []


def test_small_declared_programme_has_no_invented_minimum_room_depth():
    assert plant_zone_candidates(box(0,0,30,20), rooms(20))


def test_missing_area_or_disconnected_zone_never_yields_partial_programme():
    assert _slice_rooms(box(0,0,2,2), rooms(5), True, 0, (0,0)) == []
    zone = box(0,0,2,2).union(box(4,0,6,2))
    assert _slice_rooms(zone, rooms(8), True, 0, (0,0)) == []


def test_rotated_bands_preserve_room_area_and_declared_obstacles():
    from shapely.affinity import rotate
    basement = rotate(box(0,0,30,20), 23, origin=(0,0))
    clear = rotate(box(14,0,16,20), 23, origin=(0,0))
    candidates = plant_zone_candidates(basement, rooms(100,80), keep_clear=clear, angle_deg=23)
    assert candidates
    for candidate in candidates:
        assert basement.buffer(1e-8).covers(candidate["zone"])
        assert candidate["zone"].intersection(clear).area < 1e-8
        assert all(room["polygon"].area+1e-8 >= room["area_m2"] for room in candidate["rooms"])


def test_incompatible_obstacles_report_no_alternative_without_cutting_rooms():
    basement = box(0,0,30,20)
    clear = box(0,9,30,11).union(box(14,0,16,20))
    assert plant_zone_candidates(basement, rooms(180), keep_clear=clear) == []
    assert plant_zone(basement, rooms(180), keep_clear=clear) is None


def test_rotated_difference_remainder_with_zero_area_spikes_is_normalized():
    import json
    from pathlib import Path
    from shapely.geometry import shape
    data=json.loads((Path(__file__).parent/'fixtures/programme-rotated-remainder.json').read_text(encoding='utf8'))
    host=shape(data['host'])
    assert not host.is_valid
    candidates=plant_zone_candidates(host, rooms(data['target']))
    assert candidates
    for candidate in candidates:
        assert candidate['zone'].is_valid
        assert host.buffer(0).buffer(1e-7).covers(candidate['zone'])
        assert candidate['zone'].area+1e-7 >= data['target']


def test_every_emitted_room_is_valid_after_returning_to_world_frame():
    import json
    from pathlib import Path
    from shapely.geometry import shape
    data=json.loads((Path(__file__).parent/'fixtures/programme-room-rotation.json').read_text(encoding='utf8'))
    result=_slice_rooms(shape(data['zone']),data['rooms'],data['along_x'],data['angle_deg'],data['origin'])
    assert len(result)==len(data['rooms'])
    for room in result:
        assert room['polygon'].is_valid
        assert room['polygon'].geom_type=='Polygon' and not room['polygon'].interiors
        assert room['polygon'].area+1e-7 >= room['area_m2']

import pytest
from shapely.geometry import box
from shapely.affinity import rotate
from backend.app.modules.design.generation.maas.masterplan import program


@pytest.mark.parametrize('angle',[0,37])
def test_corner_room_block_fits_when_full_edge_bands_do_not(angle):
    turn=lambda g:rotate(g,angle,origin=(0,0))
    host=turn(box(0,0,20,20))
    obstacles=turn(box(0,15,20,16).union(box(15,0,16,20)))
    rooms=[{'name':'plant','area_m2':60,'kind':'plant'},
           {'name':'storage','area_m2':40,'kind':'plant'}]
    assert not program.plant_zone_candidates(host,rooms,keep_clear=obstacles,angle_deg=angle)
    choices=program.block_plant_zone_candidates(host,rooms,keep_clear=obstacles,angle_deg=angle)
    assert choices
    for choice in choices:
        assert host.buffer(1e-8).covers(choice['zone'])
        assert choice['zone'].intersection(obstacles).area<1e-8
        assert len(choice['rooms'])==2
        for room in choice['rooms']:
            assert room['polygon'].is_valid
            assert room['polygon'].area==pytest.approx(room['area_m2'])


def test_room_block_does_not_clip_rooms_to_fit():
    rooms=[{'name':'plant','area_m2':100,'kind':'plant'}]
    assert not program.block_plant_zone_candidates(box(0,0,9,9),rooms)

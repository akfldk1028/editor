from shapely.geometry import Polygon
from backend.app.modules.design.generation.maas.masterplan.program import _slice_rooms


def test_irregular_band_allocates_measured_room_areas_not_bbox_lengths():
    zone=Polygon([(0,0),(20,0),(20,10),(10,10)])
    rooms=[{'name':'plant','area_m2':90,'kind':'plant'},
           {'name':'store','area_m2':40,'kind':'storage'},
           {'name':'fan','area_m2':20,'kind':'plant'}]
    result=_slice_rooms(zone,rooms,True,0,(0,0))
    assert len(result)==3
    for r in result:
        assert r['polygon'].area+1e-6 >= r['area_m2']
        assert zone.buffer(1e-7).covers(r['polygon'])
    for i,a in enumerate(result):
        for b in result[i+1:]:
            assert a['polygon'].intersection(b['polygon']).area < 1e-7

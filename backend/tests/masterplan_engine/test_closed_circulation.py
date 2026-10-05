from shapely.geometry import box
from shapely.affinity import rotate
import pytest
from backend.app.modules.design.generation.maas.masterplan.circulation import closed_aisle_loop


@pytest.mark.parametrize('angle',[0,37])
def test_closed_loop_requires_full_width_return_leg(angle):
    ring=box(0,0,40,30).difference(box(6,6,34,24))
    transform=lambda g:rotate(g,angle,origin=(0,0))
    loop=closed_aisle_loop(transform(ring),6)
    assert loop is not None and loop.is_ring
    assert transform(ring).buffer(1e-6).covers(loop.buffer(3,join_style=2))
    opened=ring.difference(box(34,10,40,20))
    assert closed_aisle_loop(transform(opened),6) is None
    narrow=ring.difference(box(38,10,40,20))
    assert closed_aisle_loop(transform(narrow),6) is None


def test_validator_rejects_connected_but_open_aisle_despite_ring_label():
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    from backend.app.modules.design.generation.maas.masterplan.geometry import feature
    host=box(0,0,40,30)
    ring=host.difference(box(6,6,34,24))
    request={'site':mapping(host),'basement_boundary':mapping(host),
             'law':{'required_spaces':0},'rules':{'aisle_width_m':6},
             'options':{'basement_parking_field':'ring'}}
    for drive,expected in [(ring,'passed'),(ring.difference(box(34,10,40,20)),'failed')]:
        result=validate_plan(request,{'features':[
            feature('basement_boundary',host,-1),
            feature('parking_aisle',drive,-1,cross_aisles=2,dead_end_stalls=0)]})
        check=next(c for c in result['checks'] if c['id']=='closed_aisle_loop:-1')
        assert check['status']==expected


def test_ring_can_use_edge_aisles_without_imaginary_outer_parking_rows():
    from shapely.geometry import Polygon
    from backend.app.modules.design.generation.maas.masterplan.rows import _tile_bands
    result=_tile_bands(box(0,0,40,22),Polygon(),0,6,2.5,5,3.3,5,
                       0,40,0,None,0,None,0,ring=True,required=20,repair_ring=True)
    assert result is not None
    assert len(result['stalls'])>=20
    assert closed_aisle_loop(result['drive'],6) is not None
    assert all(box(0,0,40,22).covers(s['polygon']) for s in result['stalls'])


def test_return_aisle_moves_inward_to_clear_core_without_counting_blocked_bays():
    from backend.app.modules.design.generation.maas.masterplan.rows import _tile_bands
    core=box(0,7,3,15)
    host=box(0,0,40,22)
    result=_tile_bands(host.difference(core),core,0,6,2.5,5,3.3,5,
                       0,40,0,None,0,None,0,ring=True,required=20,repair_ring=True)
    assert result is not None
    assert len(result['stalls'])>=20
    assert result['drive'].intersection(core).area<1e-8
    loop=closed_aisle_loop(result['drive'],6)
    assert loop is not None
    assert loop.buffer(3,join_style=2).intersection(core).area<1e-8


def test_validator_subtracts_core_before_certifying_loop():
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    from backend.app.modules.design.generation.maas.masterplan.geometry import feature
    host=box(0,0,40,30)
    core=box(35,10,40,20)
    ring=host.difference(box(6,6,34,24))
    request={'site':mapping(host),'basement_boundary':mapping(host),'core':mapping(core),
             'law':{'required_spaces':0},'rules':{'aisle_width_m':6},
             'options':{'basement_parking_field':'ring'}}
    result=validate_plan(request,{'features':[feature('basement_boundary',host,-1),
             feature('building_core',core,-1),feature('parking_aisle',ring,-1)]})
    checks={c['id']:c['status'] for c in result['checks']}
    assert checks['drive_obstructions:-1']=='failed'
    assert checks['closed_aisle_loop:-1']=='failed'


def test_required_ring_never_falls_back_to_unconstrained_packer(monkeypatch):
    from shapely.geometry import Polygon
    from backend.app.modules.design.generation.maas.masterplan import basement_layout
    monkeypatch.setattr(basement_layout,'row_candidates',lambda *a,**k:[])
    def forbidden(*a,**k):
        raise AssertionError('non-loop fallback')
    monkeypatch.setattr(basement_layout,'pack_level',forbidden)
    result=basement_layout.solve_basement_level(box(0,0,40,30),
        {'polygon':box(0,0,6,10),'lower_landing':box(0,0,6,6)},Polygon(),[],
        {'aisle_width_m':6},20,0,field='ring')
    assert result is None

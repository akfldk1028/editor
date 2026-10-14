from shapely.geometry import box, mapping, Polygon
from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
from backend.app.modules.design.generation.maas.masterplan.basement_layout import solve_basement_level
from test_parking_modules import RULES
import pytest


def test_module_moves_preserve_rule_evidence():
    request={'site':mapping(box(0,0,40,40)),'rules':RULES,'evidence':{'source':'law'}}
    moved=apply_placement_moves(request,{'basement_module':'module27','module_axis':'cross_axis'})['request']
    assert moved['rules']==request['rules'] and moved['evidence']==request['evidence']
    assert moved['options']['basement_module']=='module27'
    assert 'options' not in request


def test_basement_uses_modules_and_never_generic_fallback(monkeypatch):
    import backend.app.modules.design.generation.maas.masterplan.basement_layout as module
    def forbidden(*a,**k):
        raise AssertionError('legacy fallback called')
    monkeypatch.setattr(module,'pack_level',forbidden)
    monkeypatch.setattr(module,'row_candidates',forbidden)
    ramp={'polygon':box(-6,5,0,11),'lower_landing':box(0,5,6,11)}
    result=solve_basement_level(box(0,0,36,32),ramp,Polygon(),[],RULES,100,0,
        module_family='module32',module_axis='along_axis',field='comb')
    assert result['parking']['generation']['selected_engine']=='parking_modules'
    assert result['parking']['generation']['module_layout']['family']=='module32'
    assert solve_basement_level(box(0,0,36,15),ramp,Polygon(),[],RULES,20,0,
        module_family='module32',module_axis='along_axis',field='comb') is None


@pytest.mark.parametrize('axis', ['along_axis', 'cross_axis'])
@pytest.mark.parametrize('access_branch', ['direct', 'rows'])
def test_module_axis_uses_site_frame_for_every_access_branch(monkeypatch, axis, access_branch):
    from backend.app.modules.design.generation.maas.masterplan import planner
    from shapely.geometry import shape
    from test_masterplan_engine import request
    data=request(20, 'basement')
    data['options'].update(planning_stage='placement', max_basement_levels=1,
        max_basement_solves=3, basement_module='module16', module_axis=axis,
        layout_axis={'frame':'site_local','vector':[1,0],'source':'fixture'})
    ramps=planner.ramp_candidates(shape(data['site']),shape(data['frontage']),
        shape(data['core']),data['rules'],3.3)
    assert ramps
    ramp=ramps[0]
    monkeypatch.setattr(planner, 'ramp_candidates', lambda *a, **k: [ramp] if access_branch=='direct' else [])
    monkeypatch.setattr(planner, 'curved_ramp_candidates', lambda *a, **k: [])
    row={'ramp':ramp,'basement':shape(data['site']),'angle_deg':90,
         'provided':0,'accessible':0,'stalls':[],'drive':Polygon(),'entrance':Polygon(),
         'score':0,'terms':{},'search_count':1}
    monkeypatch.setattr(planner, 'row_candidates', lambda *a, **k: [row] if access_branch=='rows' else [])
    angles=[]
    from backend.app.modules.design.generation.maas.masterplan import parking_modules
    def capture(*args, **kwargs):
        angles.extend(kwargs['angles'])
        return []
    monkeypatch.setattr(parking_modules, 'module_candidates', capture)
    planner.plan_site(data)
    assert angles, 'The selected access branch must reach module generation'
    assert {round(a % 180, 6) for a in angles} == {0 if axis=='along_axis' else 90}

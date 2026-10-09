from shapely.geometry import box, mapping, Polygon
from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
from backend.app.modules.design.generation.maas.masterplan.basement_layout import solve_basement_level
from test_parking_modules import RULES


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

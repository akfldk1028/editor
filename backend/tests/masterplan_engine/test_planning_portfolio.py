import pytest
from shapely.geometry import box, mapping
from backend.app.modules.design.generation.maas.masterplan import planning_portfolio as p


def layout(x, count=50, valid=True):
    return {'features':[{'properties':{'layer':'building_footprint'},'geometry':mapping(box(x,0,x+10,10))}],
            'validation':{'geometry_status':'passed' if valid else 'failed'},
            'metrics':{'provided_parking_stalls':count},'status':'needs_evidence',
            'blocking':[],'handoff':{}}


def test_reference_count_does_not_discard_a_different_building_arrangement():
    a,b=layout(0),layout(20,45)
    result=p.retain([a,b],a,limit=3)
    assert [v['layout']['metrics']['provided_parking_stalls'] for v in result['candidates']]==[50,45]
    assert a.get('planning_candidates') is None


def test_invalid_duplicate_and_budget_exclusions_are_explicit():
    a,b,c=layout(0),layout(20),layout(40)
    result=p.retain([a,a,b,c,layout(60,valid=False)],a,limit=2)
    assert len(result['candidates'])==2
    assert {v['reason'] for v in result['excluded']}=={'same_geometry','candidate_budget','geometry_failure'}


@pytest.mark.parametrize('limit',[True,0,9,1.5])
def test_invalid_budget(limit):
    with pytest.raises(ValueError):p.retain([layout(0)],layout(0),limit=limit)


def test_real_owner_candidates_have_revisable_individual_geometry(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from shapely.geometry import shape
    from backend.app.modules.design.generation.maas.masterplan_operations import dispatch
    from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request
    monkeypatch.setenv('EDITOR_PLACEMENT_SNAPSHOT_ROOT',str(tmp_path))
    request=json.loads((Path(__file__).parent/'fixtures/real_668_default_placement.json').read_text(encoding='utf8'))
    result=dispatch('plan_site',{'request':request})
    assert len(result['planning_candidates'])>=2
    for candidate in result['planning_candidates']:
        alternative=candidate['layout']
        resolved=resolve_request({**request,'placement_state':alternative['placement_snapshot']['ref']})
        drawn=next(f['geometry'] for f in alternative['features'] if f['properties']['layer']=='building_footprint')
        assert shape(resolved['footprint']).equals(shape(drawn))
    request['options']['selection_policy']='legacy_parking_v1'
    assert 'planning_candidates' not in dispatch('plan_site',{'request':request})

import pytest
from shapely.geometry import Polygon, shape

from backend.app.modules.design.generation.maas.masterplan import planner
from test_masterplan_engine import request


@pytest.mark.parametrize('row_state', ['absent', 'usable', 'missing_slab'])
@pytest.mark.parametrize('limit', [1, 2, 3])
@pytest.mark.parametrize('field', ['auto', 'ring', 'stacked'])
def test_basement_budget_reserves_only_for_usable_row_candidates(monkeypatch, row_state, limit, field):
    data=request(20, 'basement')
    data['options'].update(planning_stage='placement', max_basement_levels=2 if field=='stacked' else 1,
        max_basement_solves=limit, basement_module='module16', parking_field='auto' if field=='stacked' else field)
    ramps=planner.ramp_candidates(shape(data['site']),shape(data['frontage']),
        shape(data['core']),data['rules'],3.3)
    distinct=[]
    for ramp in ramps:
        if not any(ramp['polygon'].symmetric_difference(old['polygon']).area < 10 for old in distinct):
            distinct.append(ramp)
    assert len(distinct)>=3
    generic=distinct[:3]
    row_ramp={**generic[0], 'budget_family':'rows'}
    monkeypatch.setattr(planner, 'ramp_candidates', lambda *a, **k: generic)
    monkeypatch.setattr(planner, 'curved_ramp_candidates', lambda *a, **k: [])
    row={'ramp':row_ramp,'basement':shape(data['site']),'angle_deg':90,
         'provided':0,'accessible':0,'stalls':[],'drive':Polygon(),'entrance':Polygon(),
         'score':0,'terms':{},'search_count':1}
    if row_state=='missing_slab':
        row['basement']=None
    monkeypatch.setattr(planner, 'row_candidates', lambda *a, **k: [] if row_state=='absent' else [row])
    calls=[]
    def solve(slab, ramp, *args, **kwargs):
        calls.append(ramp.get('budget_family', 'generic'))
        if field=='stacked' and len(calls)==1:
            return {'zone':None, 'parking':{'stalls':[], 'drive':ramp['lower_landing'],
                'provided':1, 'accessible':0, 'search_count':1}}
        return None
    monkeypatch.setattr(planner, 'solve_basement_level', solve)
    result=planner.plan_site(data)
    expected=(['generic']*(limit-1)+['rows'] if row_state=='usable' and limit>=2 else ['generic']*limit)
    assert calls == expected
    assert result['search_budget']['invoked'] == limit

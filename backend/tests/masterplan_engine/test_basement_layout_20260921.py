from shapely.geometry import box
from backend.app.modules.design.generation.maas.masterplan.basement_layout import solve_basement_level


def test_basement_reserves_core_rooms_and_real_arrival_before_counting():
    slab=box(0,0,60,40)
    core=box(25,20,30,25)
    ramp={'polygon':box(0,0,4,30),'lower_landing':box(0,26,4,30)}
    rooms=[{'name':'plant','kind':'plant','area_m2':200}]
    rules={'stall_width_m':2.5,'stall_length_m':5.,'accessible_width_m':3.3,
           'accessible_length_m':5.,'aisle_width_m':6.}
    result=solve_basement_level(slab,ramp,core,rooms,rules,20,1,angle=0)
    assert result is not None
    zone,plan=result['zone'],result['parking']
    assert zone['zone'].intersection(core).area < 1e-6
    assert zone['zone'].intersection(ramp['polygon']).area < 1e-6
    assert plan['provided'] >= 20 and plan['accessible'] >= 1
    assert plan['drive'].distance(ramp['lower_landing']) < 1e-6
    assert all(st['polygon'].intersection(core.union(zone['zone']).union(ramp['polygon'])).area<1e-6
               for st in plan['stalls'])


def test_expanded_shortfall_still_tries_other_packer(monkeypatch):
    import backend.app.modules.design.generation.maas.masterplan.basement_layout as module
    def plan(kind):
        return {'stalls':[{'polygon':box(10,10,15,15),'type':kind}],
                'drive':box(4,15,20,21),'provided':1,'accessible':0}
    monkeypatch.setattr(module,'row_candidates',lambda *a,**k:[plan('general')])
    calls=[]
    def generic(*a,**k):
        calls.append(True)
        return plan('expanded')
    monkeypatch.setattr(module,'pack_level',generic)
    result=solve_basement_level(box(0,0,40,40),
        {'polygon':box(0,0,4,20),'lower_landing':box(0,15,4,20)},box(30,30,35,35),[],
        {'aisle_width_m':6},1,0,expanded_needed=1)
    assert calls and result['parking']['stalls'][0]['type']=='expanded'


def test_programme_choice_minimizes_actual_combined_construction_extent(monkeypatch):
    import backend.app.modules.design.generation.maas.masterplan.basement_layout as module
    far={'zone':box(50,30,55,35),'rooms':[]}
    near={'zone':box(5,25,10,30),'rooms':[]}
    monkeypatch.setattr(module,'plant_zone_candidates',lambda *a,**k:[far,near])
    plan={'stalls':[{'polygon':box(10,10,15,15),'type':'general'}],
          'drive':box(4,15,20,21),'provided':1,'accessible':0}
    monkeypatch.setattr(module,'row_candidates',lambda *a,**k:[plan])
    result=solve_basement_level(box(0,0,60,40),
        {'polygon':box(0,0,4,30),'lower_landing':box(0,26,4,30)},box(25,20,30,25),
        [{'area_m2':25}],{'aisle_width_m':6},1,0)
    assert result['zone'] is near

from copy import deepcopy
import pytest
from shapely.geometry import box, LineString, mapping
from shapely.affinity import rotate
from backend.app.modules.design.generation.maas.masterplan.geometry import digest, feature
from backend.app.modules.law.reference.road_aisle import evaluate


def case(angle=0, centreline=False):
    def geom(g):
        return mapping(rotate(g, angle, origin=(0, 0)))
    facts = {k: {'value': v, 'source_refs': ['synthetic:survey']} for k, v in
             dict(road_width_m=6, has_sidewalk_separation=False, centreline_presence=centreline,
                  unobstructed_connection=True, legal_road_frontage=True).items()}
    source = dict(pnu='1'*19, crs='EPSG:32652', facts=facts, source_refs=['synthetic:survey'],
                  road_polygon=geom(box(0,-6,12,0)), included_road_polygon=geom(box(0,-6,12,0)),
                  frontage=geom(LineString([(0,0),(12,0)])), parking_angle='perpendicular')
    if centreline:
        source['painted_centreline'] = geom(LineString([(0,-3),(12,-3)]))
        source['included_road_polygon'] = geom(box(0,-3,12,0))
    context = dict(deepcopy(source), source_context=deepcopy(source), source_context_hash=digest(source),
                   source_coordinate_crs=source['crs'])
    receipt = evaluate(source['pnu'], 2, 'surface', 'perpendicular', facts)
    receipt.update(via='lawagent_a2a', law_task_id='synthetic-task', source_context_hash=digest(source))
    request = dict(pnu=source['pnu'], crs='EPSG:32652', origin_utm=[0,0],
                   site=geom(box(0,0,12,10)), frontage=source['frontage'],
                   footprint=geom(box(0,6,12,10)), road_aisle_context=context,
                   evidence={'road_aisle_law':receipt},
                   rules=dict(stall_width_m=2.5,stall_length_m=5,aisle_width_m=6),
                   law=dict(required_spaces=2,required_accessible_spaces=0), options={})
    features = [feature('building_footprint', rotate(box(0,6,12,10),angle,origin=(0,0))),
                feature('external_road_aisle',rotate(box(0,-6,5,0),angle,origin=(0,0)))]
    features += [feature('parking_stall',rotate(box(x,0,x+2.5,5),angle,origin=(0,0)),
                         stall_id=f'R{i}',type='standard_90deg',access_kind='road_aisle')
                 for i,x in enumerate((0,2.5))]
    return request, features


@pytest.mark.parametrize('angle',[0,37,90])
def test_external_aisle_independent_certificate_preserves_site_containment(angle):
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import scope, certify
    request, features = case(angle)
    assert scope(request)['status']=='ready'
    result = certify(request, features)
    assert result['stall_ids']=={'R0','R1'}
    assert all(c['status']=='passed' for c in result['checks'])
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    report = validate_plan(request, {'features':features})
    assert report['geometry_status']=='passed', [c for c in report['checks'] if c['status']=='failed']
    assert report['external_road_aisle']['area_m2']==pytest.approx(30)
    assert 'road_aisle_vehicle_maneuver_review' in report['pending_reviews']


@pytest.mark.parametrize('change',['receipt','derived_polygon','count','missing_source','wrong_side','false_label'])
def test_road_relief_cannot_be_claimed_with_stale_or_out_of_scope_geometry(change):
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import certify
    request, features = case(centreline=(change=='wrong_side'))
    if change=='receipt':
        request['evidence']['road_aisle_law']['required_combined_aisle_width_m']=1
    elif change=='derived_polygon':
        request['road_aisle_context']['included_road_polygon']=mapping(box(0,-20,12,0))
    elif change=='count':
        features += [feature('parking_stall',box(0,0,2.5,5),stall_id=f'extra{i}') for i in range(8)]
    elif change=='missing_source':
        del request['road_aisle_context']['source_context']
    elif change=='false_label':
        features[-1]['geometry']=mapping(box(0,1,2.5,6))
    result=certify(request,features)
    assert any(c['status']=='failed' for c in result['checks'])


def test_missing_road_evidence_never_invents_extent():
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import scope
    request,_=case()
    del request['road_aisle_context']['included_road_polygon']
    assert scope(request)['status']!='ready'


def test_stall_outside_parcel_still_fails_even_when_road_is_allowed():
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request,features=case()
    features[-1]['geometry']=mapping(box(5,-1,7.5,4))
    report=validate_plan(request,{'features':features})
    assert any(c['id']=='stall_containment:R1' and c['status']=='failed' for c in report['checks'])


def test_independent_validation_rejects_prohibited_road_crossing():
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request,features=case()
    request['vehicle_prohibited']=request['frontage']
    for f in features:
        f['properties'].pop('access_kind',None)
    report=validate_plan(request,{'features':features})
    assert report['geometry_status']=='failed'


def test_partial_prohibited_untagged_stall_cannot_borrow_other_stalls_road_certificate():
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request,features=case()
    request['vehicle_prohibited']=mapping(LineString([(0,0),(2.4,0)]))
    for f in features:
        f['properties'].pop('access_kind',None)
    assert validate_plan(request,{'features':features})['geometry_status']=='failed'


def test_shared_aisle_remainder_inside_site_is_measured_together():
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request,features=case(centreline=True)
    request.pop('footprint')
    features=features[1:]
    features[0]['geometry']=mapping(box(0,-3,5,0))
    features.append(feature('parking_aisle',box(0,0,5,3)))
    features[1]['geometry']=mapping(box(0,3,2.5,8))
    features[2]['geometry']=mapping(box(2.5,3,5,8))
    report=validate_plan(request,{'features':features})
    assert report['geometry_status']=='passed', [c for c in report['checks'] if c['status']=='failed']


def test_centreline_on_disconnected_road_does_not_authorize_frontage_road():
    from shapely.geometry import MultiPolygon
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import scope
    request,_=case(centreline=True)
    context=request['road_aisle_context']
    for obj in (context,context['source_context']):
        obj['road_polygon']=mapping(MultiPolygon([box(0,-6,12,0),box(20,-6,24,0)]))
        obj['included_road_polygon']=mapping(box(0,-6,12,0))
        obj['painted_centreline']=mapping(LineString([(20,-3),(24,-3)]))
    context['source_context_hash']=digest(context['source_context'])
    request['evidence']['road_aisle_law']['source_context_hash']=context['source_context_hash']
    assert scope(request)['status']!='ready'


def test_centreline_on_connected_remote_spur_does_not_bound_frontage_aisle():
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import scope
    request,_=case(centreline=True)
    context=request['road_aisle_context']
    road=unary_union([box(0,-6,12,0),box(12,-6,20,-5),box(20,-6,24,0)])
    for obj in (context,context['source_context']):
        obj['road_polygon']=mapping(road)
        obj['included_road_polygon']=mapping(box(0,-6,12,0))
        obj['painted_centreline']=mapping(LineString([(20,-3),(24,-3)]))
    context['source_context_hash']=digest(context['source_context'])
    request['evidence']['road_aisle_law']['source_context_hash']=context['source_context_hash']
    assert scope(request)['status']!='ready'


def test_law_assessment_date_must_match_source_request():
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import scope
    request,_=case()
    context=request['road_aisle_context']
    # the receipt was evaluated today; a different source date must not bind to it on any day
    context['source_context']['assessment_date']='2030-01-01'
    context['source_context_hash']=digest(context['source_context'])
    request['evidence']['road_aisle_law']['source_context_hash']=context['source_context_hash']
    assert scope(request)['status']!='ready'


def test_parallel_law_response_cannot_certify_perpendicular_dimension_tags():
    from backend.app.modules.design.generation.maas.masterplan.road_aisle import certify
    request,features=case()
    context=request['road_aisle_context']
    context['parking_angle']=context['source_context']['parking_angle']='parallel'
    context['source_context_hash']=digest(context['source_context'])
    receipt=evaluate(request['pnu'],2,'surface','parallel',context['facts'])
    receipt.update(via='lawagent_a2a',law_task_id='synthetic-task',source_context_hash=context['source_context_hash'])
    request['evidence']['road_aisle_law']=receipt
    features[1]['geometry']=mapping(box(0,-4,10,0))
    features[2]['geometry']=mapping(box(0,0,5,2.5))
    features[3]['geometry']=mapping(box(5,0,10,2.5))
    result=certify(request,features)
    assert not result['stall_ids']
    assert any(c['status']=='failed' for c in result['checks'])

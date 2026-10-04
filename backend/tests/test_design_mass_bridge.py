from copy import deepcopy
import pytest
from shapely.geometry import Polygon

from backend.app.schemas.mass_io import mass_input_from_payload
from backend.app.modules.mass_analyzer.service import analyze_mass

SOURCE={'source_id':'arr-main','job_id':'job-1','result_pk':1,'row_sha256':'a'*64}


def candidate():
    return {'type':'Feature','geometry':{'type':'Polygon','coordinates':[
        [[127,37],[127.0002,37],[127.0002,37.0002],[127,37.0002],[127,37]]]},
        'properties':{'num_floors':3,'floor_height':3.2,'height':9.6,'building_type':'source label'}}


def test_projection_roundtrip_area_units_and_provenance():
    from backend.app.modules.design.mass_bridge import convert_saved_mass
    from backend.app.modules.land.projection import wgs84_to_utm,utm_to_wgs84
    original=candidate();before=deepcopy(original)
    payload=convert_saved_mass(original,project_id='project-1',source=SOURCE)
    mass=mass_input_from_payload(payload);analysis=analyze_mass(mass)
    projected=wgs84_to_utm(Polygon(original['geometry']['coordinates'][0]))
    assert analysis.area==pytest.approx(projected.area)
    assert analysis.floor_area==pytest.approx(projected.area*3)
    assert mass.floors==3 and mass.building_code_context.floor_to_floor_height_m==3.2
    provenance=payload['source_provenance']
    assert provenance['source']==SOURCE and provenance['units']=='m'
    assert provenance['source_crs']=='EPSG:4326' and provenance['projected_crs']=='EPSG:32652'
    ox,oy=provenance['origin_projected']
    roundtrip=utm_to_wgs84(Polygon([(x+ox,y+oy) for x,y in mass.footprint_polygon]))
    assert roundtrip.equals_exact(Polygon(original['geometry']['coordinates'][0]),1e-9)
    assert original==before


def test_stepback_preserves_explicit_floor_shapes():
    from backend.app.modules.design.mass_bridge import convert_saved_mass
    data=candidate();data['properties'].update(step_floor=1,upper_geometry={
        'type':'Polygon','coordinates':[[[127.00005,37.00005],[127.00015,37.00005],[127.00015,37.00015],[127.00005,37.00015],[127.00005,37.00005]]]})
    payload=convert_saved_mass(data,project_id='p',source=SOURCE)
    mass=mass_input_from_payload(payload);analysis=analyze_mass(mass)
    assert len(mass.floor_footprints)==3
    assert analysis.area_for_floor(2)<analysis.area_for_floor(1)
    assert analysis.area_for_floor(2)==analysis.area_for_floor(3)


def test_step_at_final_floor_does_not_invent_an_upper_floor():
    from backend.app.modules.design.mass_bridge import convert_saved_mass
    data=candidate();data['properties'].update(step_floor=3,upper_geometry=deepcopy(data['geometry']))
    payload=convert_saved_mass(data,project_id='p',source=SOURCE)
    assert len(payload['floor_footprints'])==3
    assert all(p['footprint_polygon']==payload['footprint_polygon'] for p in payload['floor_footprints'])


@pytest.mark.parametrize('mutation,code',[
    (lambda d:d['properties'].pop('num_floors'),'invalid_floor_count'),
    (lambda d:d['properties'].update(num_floors=True),'invalid_floor_count'),
    (lambda d:d['geometry'].update(type='MultiPolygon'),'unsupported_geometry'),
    (lambda d:d.update(crs={'type':'name','properties':{'name':'EPSG:3857'}}),'unsupported_crs'),
    (lambda d:d['properties'].update(mass_volumes=[{'geometry':{}}]),'unsupported_mass_representation'),
    (lambda d:d['properties'].update(height=20),'inconsistent_height'),
    (lambda d:d['geometry']['coordinates'][0][0].__setitem__(0,float('nan')),'invalid_json'),
])
def test_unsupported_mass_is_rejected_without_mutating_archive(mutation,code):
    from backend.app.modules.design.mass_bridge import convert_saved_mass,MassBridgeError
    data=candidate();mutation(data)
    with pytest.raises(MassBridgeError) as error:convert_saved_mass(data,project_id='p',source=SOURCE)
    assert error.value.code==code


def test_holes_are_not_silently_filled():
    from backend.app.modules.design.mass_bridge import convert_saved_mass,MassBridgeError
    data=candidate();data['geometry']['coordinates'].append([
        [127.00005,37.00005],[127.0001,37.00005],[127.0001,37.0001],[127.00005,37.0001],[127.00005,37.00005]])
    with pytest.raises(MassBridgeError,match='unsupported_geometry'):
        convert_saved_mass(data,project_id='p',source=SOURCE)


def test_explicit_floor_plates_require_complete_uniform_height_evidence():
    from backend.app.modules.design.mass_bridge import convert_saved_mass,MassBridgeError
    data=candidate();data['properties']['floor_plates']=[{'floor':i,'top_height':i*3.2,
        'geometry':deepcopy(data['geometry'])} for i in range(1,4)]
    payload=convert_saved_mass(data,project_id='p',source=SOURCE)
    assert payload['source_provenance']['representation']=='explicit_floor_plates'
    data['properties']['floor_plates'][1]['top_height']=7
    with pytest.raises(MassBridgeError,match='unsupported_floor_heights'):
        convert_saved_mass(data,project_id='p',source=SOURCE)


@pytest.mark.parametrize('geometry', [{'type':'Polygon','coordinates':None},{'type':'Polygon','coordinates':[None]}])
def test_malformed_geometry_is_an_explicit_bridge_rejection(geometry):
    from backend.app.modules.design.mass_bridge import convert_saved_mass,MassBridgeError
    data=candidate();data['geometry']=geometry
    with pytest.raises(MassBridgeError):convert_saved_mass(data,project_id='p',source=SOURCE)


@pytest.mark.parametrize('lower_height',[6.4,True,0,-3.2,None])
def test_stepback_rejects_conflicting_or_invalid_lower_height(lower_height):
    from backend.app.modules.design.mass_bridge import convert_saved_mass,MassBridgeError
    data=candidate();data['properties'].update(step_floor=1,lower_height=lower_height,
        upper_geometry=deepcopy(data['geometry']))
    with pytest.raises(MassBridgeError,match='inconsistent_height'):
        convert_saved_mass(data,project_id='p',source=SOURCE)


def test_explicit_floor_bottom_elevation_must_match_uniform_floor_model():
    from backend.app.modules.design.mass_bridge import convert_saved_mass,MassBridgeError
    data=candidate();data['properties']['floor_plates']=[{'floor':i,'top_height':i*3.2,
        'bottom_height':(i-1)*3.2,'geometry':deepcopy(data['geometry'])} for i in range(1,4)]
    convert_saved_mass(data,project_id='p',source=SOURCE)
    data['properties']['floor_plates'][1]['bottom_height']=4
    with pytest.raises(MassBridgeError,match='unsupported_floor_heights'):
        convert_saved_mass(data,project_id='p',source=SOURCE)

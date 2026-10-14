from shapely.geometry import box, mapping
from backend.app.modules.design.generation.maas.masterplan.siting_relations import measure_siting


def features(stalls=2, moved=False, cross=False):
    result=[]
    for layer, level, geom in [('building_footprint',0,box(12 if moved else 0,0,22 if moved else 10,10)),
                               ('parking_aisle',-1,box(0,10,30,16) if cross else box(10,0,16,30))]:
        result.append({'geometry':mapping(geom),'properties':{'layer':layer,'level':level}})
    for i in range(stalls):
        result.append({'geometry':mapping(box(0,i*3,5,i*3+2.5)),
                       'properties':{'layer':'parking_stall','level':-1}})
    return result


def signature(fs):
    return measure_siting({'site':mapping(box(0,0,40,40))},fs,box(0,0,10,10))['configuration_signature']


def test_capacity_changes_are_not_new_building_or_basement_configurations():
    assert signature(features(2))['key']==signature(features(5))['key']


def test_actual_building_and_basement_changes_are_separately_visible():
    a,b,c=signature(features()),signature(features(moved=True)),signature(features(cross=True))
    assert a['building_key']!=b['building_key'] and a['basement_key']==b['basement_key']
    assert a['building_key']==c['building_key'] and a['basement_key']!=c['basement_key']


def test_feature_order_and_names_do_not_change_configuration():
    fs=features(); changed=list(reversed(fs))
    for f in changed: f['properties']['label']='Different marketing label'
    assert signature(fs)['key']==signature(changed)['key']


def test_equivalent_polygon_decomposition_has_same_signature():
    fs=features()
    split=features()[1:]
    for geom in (box(0,0,5,10),box(5,0,10,10)):
        split.append({'geometry':mapping(geom),'properties':{'layer':'building_footprint','level':0}})
    assert signature(fs)['key']==signature(split)['key']


def test_invalid_basement_geometry_is_unknown_not_exception():
    for geometry in (None, {'type':'Point','coordinates':[0,0]}):
        fs=features()
        fs.append({'geometry':geometry,'properties':{'layer':'parking_stall','level':-1}})
        assert signature(fs)['status']=='unknown'


def test_numeric_level_serialization_does_not_change_identity():
    fs=features()
    floating=features()
    for f in floating:
        f['properties']['level']=float(f['properties']['level'])
    assert signature(fs)['key']==signature(floating)['key']

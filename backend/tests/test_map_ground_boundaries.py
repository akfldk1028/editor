import importlib
module=importlib.import_module("backend.app.modules.land.map_ground.compose")
from shapely.geometry import box, mapping, shape
from backend.app.modules.land.map_ground.compose import normalize, compose


def test_clipping_does_not_invent_parcel_edges(monkeypatch):
    monkeypatch.setattr(module, 'bbox', lambda *args: (127,37,127.002,37.002))
    original=box(126.999,36.999,127.001,37.003)
    source={'rows':[{'geometry':mapping(original),'properties':{'pnu':'p','jibun':'1 대'}}]}
    features=normalize(source,'cadastre',37.001,127.001,1000)
    boundary=shape(features[0]['properties']['parcel_boundary'])
    assert boundary.equals(original.boundary.intersection(box(127,37,127.002,37.002)))
    assert boundary.length < shape(features[0]['geometry']).boundary.length
    composed,_=compose(features,[],{'features':{'features':[]}})
    assert composed['features'][0]['properties']['parcel_boundary']==features[0]['properties']['parcel_boundary']


def test_true_boundary_coincident_with_clip_box_is_preserved(monkeypatch):
    bounds=(127,37,127.002,37.002)
    monkeypatch.setattr(module, 'bbox',lambda *args:bounds)
    original=box(*bounds)
    source={'rows':[{'geometry':mapping(original),'properties':{'pnu':'p','jibun':'1 대'}}]}
    feature=normalize(source,'cadastre',37.001,127.001,1000)[0]
    assert shape(feature['properties']['parcel_boundary']).equals(original.boundary)

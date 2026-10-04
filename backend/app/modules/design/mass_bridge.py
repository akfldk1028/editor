"""Loss-checked conversion of archived ARR WGS84 mass features into PLANM floor plates."""
from copy import deepcopy
import hashlib
import json
import math
import re

from shapely.geometry import Point, shape
from backend.app.modules.land.parcel_geometry import parcel_geometry
from backend.app.modules.land.projection import wgs84_to_utm,utm_to_wgs84
from backend.app.schemas.mass_io import mass_input_from_payload
from backend.app.modules.mass_analyzer.service import analyze_mass


class MassBridgeError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def _polygon(geometry):
    if not isinstance(geometry,dict) or geometry.get('type')!='Polygon':
        raise MassBridgeError('unsupported_geometry')
    if 'crs' in geometry:
        raise MassBridgeError('unsupported_crs')
    coordinates=geometry.get('coordinates')
    if not isinstance(coordinates,list) or len(coordinates)!=1 or not isinstance(coordinates[0],list):
        raise MassBridgeError('unsupported_geometry')
    if len(coordinates[0])>10000:
        raise MassBridgeError('geometry_budget_exceeded')
    try:
        parcel_geometry(geometry)
        projected=wgs84_to_utm(shape(geometry))
        if projected.is_empty or not projected.is_valid or not math.isfinite(projected.area) or projected.area<=0:
            raise ValueError('Invalid projected polygon')
        return projected
    except (ValueError,TypeError,KeyError,AttributeError):
        raise MassBridgeError('invalid_geometry') from None


def convert_saved_mass(mass_geojson,*,project_id,source):
    if not isinstance(project_id,str) or not project_id.strip():
        raise MassBridgeError('invalid_project')
    if (not isinstance(source,dict) or not isinstance(source.get('source_id'),str)
        or not source['source_id'] or not isinstance(source.get('job_id'),str) or not source['job_id']
        or type(source.get('result_pk')) is not int or source['result_pk']<=0
        or not isinstance(source.get('row_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',source['row_sha256'])):
        raise MassBridgeError('invalid_source_identity')
    try:
        encoded=json.dumps(mass_geojson,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        json.dumps(source,allow_nan=False)
    except (TypeError,ValueError):
        raise MassBridgeError('invalid_json') from None
    if not isinstance(mass_geojson,dict) or mass_geojson.get('type')!='Feature':
        raise MassBridgeError('unsupported_mass_representation')
    if 'crs' in mass_geojson:
        raise MassBridgeError('unsupported_crs')
    props=mass_geojson.get('properties')
    if not isinstance(props,dict):
        raise MassBridgeError('invalid_properties')
    floors=props.get('num_floors')
    if type(floors) is not int or not 1<=floors<=1000:
        raise MassBridgeError('invalid_floor_count')
    for key in ('mass_volumes','source_volumes','source_surfaces','section_source_surfaces','section_profile','typology_bands'):
        if props.get(key):
            raise MassBridgeError('unsupported_mass_representation')
    height=props.get('height');floor_height=props.get('floor_height')
    if not _positive(height):
        raise MassBridgeError('invalid_height')
    if floor_height is None:
        floor_height=height/floors
    if not _positive(floor_height) or not math.isclose(height,floors*floor_height,rel_tol=0,abs_tol=.011):
        raise MassBridgeError('inconsistent_height')
    if 'lower_height' in props:
        step=props.get('step_floor')
        if (type(step) is not int or not 1<=step<=floors or not _positive(props['lower_height'])
            or not math.isclose(props['lower_height'],step*floor_height,rel_tol=0,abs_tol=.011)):
            raise MassBridgeError('inconsistent_height')
    base=_polygon(mass_geojson.get('geometry'))
    origin=base.centroid
    geographic_origin=utm_to_wgs84(Point(origin.x,origin.y))
    def ring(polygon):
        return [[x-origin.x,y-origin.y] for x,y in list(polygon.exterior.coords)[:-1]]
    floor_shapes=[];representation='uniform_extrusion'
    explicit=props.get('floor_plates')
    if explicit:
        if not isinstance(explicit,list) or len(explicit)!=floors:
            raise MassBridgeError('incomplete_floor_plates')
        indexed={}
        for plate in explicit:
            if not isinstance(plate,dict) or type(plate.get('floor')) is not int or plate['floor'] in indexed:
                raise MassBridgeError('incomplete_floor_plates')
            index=plate['floor']
            if not _positive(plate.get('top_height')) or not math.isclose(plate['top_height'],index*floor_height,abs_tol=.011,rel_tol=0):
                raise MassBridgeError('unsupported_floor_heights')
            if 'bottom_height' in plate:
                bottom=plate['bottom_height']
                if (type(bottom) not in (int,float) or not math.isfinite(bottom) or bottom<0
                    or not math.isclose(bottom,(index-1)*floor_height,rel_tol=0,abs_tol=.011)):
                    raise MassBridgeError('unsupported_floor_heights')
            indexed[index]=_polygon(plate.get('geometry'))
        if set(indexed)!=set(range(1,floors+1)):
            raise MassBridgeError('incomplete_floor_plates')
        floor_shapes=[indexed[index] for index in range(1,floors+1)]
        representation='explicit_floor_plates'
    elif 'upper_geometry' in props or 'step_floor' in props:
        step=props.get('step_floor')
        if type(step) is not int or not 1<=step<=floors or not props.get('upper_geometry'):
            raise MassBridgeError('incomplete_stepback')
        upper=_polygon(props['upper_geometry'])
        floor_shapes=[base if index<=step else upper for index in range(1,floors+1)]
        representation='explicit_stepback'
    elif props.get('floor_groups') or props.get('maas_model'):
        raise MassBridgeError('unsupported_mass_representation')
    else:
        floor_shapes=[base]*floors
    if any(not base.covers(polygon) for polygon in floor_shapes):
        raise MassBridgeError('floor_outside_reference')
    payload={'project_id':project_id,'floors':floors,'footprint_polygon':ring(base),
        'floor_footprints':[{'floor_index':index,'footprint_polygon':ring(polygon)} for index,polygon in enumerate(floor_shapes,1)],
        'site_edges':[],'access_candidates':[],'use_mix':{},
        'building_code_context':{'floor_to_floor_height_m':floor_height},
        'source_provenance':{'source':deepcopy(source),'mass_sha256':hashlib.sha256(encoded.encode()).hexdigest(),
            'source_crs':'EPSG:4326','projected_crs':'EPSG:32652','units':'m',
            'origin_projected':[origin.x,origin.y],'origin_wgs84':[geographic_origin.x,geographic_origin.y],
            'height_m':height,'building_type':deepcopy(props.get('building_type')),'representation':representation}}
    try:
        analyze_mass(mass_input_from_payload(payload))
    except (ValueError,TypeError,KeyError):
        raise MassBridgeError('unsupported_planm_geometry') from None
    return payload

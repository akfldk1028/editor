"""The MasterPlan Agent's layout (`masterplan_layout_synthesize`) and the declared intent (`intent_declare`), read into
the contract's `masterplan` shape — what the site map's 3D view draws over the parcel.

The layout is the owner's GeoJSON (WGS84, `coordinate_crs`), one feature per drawn thing with `properties.layer`
(building_footprint, parking_stall, parking_aisle, vehicular_access, road_frontage, site_boundary, buildable_boundary)
and `properties.level`. MasterPlan draws the footprint and the parking, not the storeys: the height the 3D view
extrudes is an assumption named here — the requested floor area over the footprint, capped by Law's floor limit when
the run carried one, times STOREY_M — never the owner's measurement.
"""
import math

from backend.app.modules.platform.run_results.common import _dict, _num, _str

TOOL = 'masterplan_layout_synthesize'
INTENT_TOOL = 'intent_declare'
AGENT = 'masterplan'
STOREY_M = 3.5            # floor-to-floor assumed for the massing view until Mass gives the real section
LAYERS = ('building_footprint', 'parking_stall', 'parking_aisle', 'vehicular_access', 'road_frontage', 'site_boundary', 'buildable_boundary')
INTENT_FIELDS = ('parti', 'massing_strategy', 'material_attitude', 'exterior_relationship', 'interior_atmosphere', 'ordering_principles')


def _features(layout):
    out = []
    for feature in layout.get('features') or []:
        feature = _dict(feature)
        geometry, props = _dict(feature.get('geometry')), _dict(feature.get('properties'))
        if geometry.get('type') not in ('Polygon', 'MultiPolygon', 'LineString', 'MultiLineString') or not geometry.get('coordinates'):
            continue
        layer = _str(props.get('layer'))
        if layer not in LAYERS:
            continue
        out.append({'type': 'Feature', 'geometry': geometry,
                    'properties': {'layer': layer, 'level': props.get('level') if isinstance(props.get('level'), int) else 0,
                                   'area_m2': _num(props.get('area_m2'))}})
    return out


def _storeys(layout, max_floors):
    """ceil(requested floor area / footprint), capped by Law's floor limit; None when either number is missing."""
    brief = _dict(_dict(layout.get('provenance')).get('brief'))
    gfa = _num(_dict(brief.get('programme')).get('floor_area_m2'))
    footprint = _num(_dict(layout.get('metrics')).get('building_footprint_m2'))
    wanted = math.ceil(gfa / footprint) if gfa and footprint and footprint > 0 else None
    if wanted is None and isinstance(max_floors, int) and max_floors > 0:
        return max_floors, f'Law 층수 상한 {max_floors}층(연면적 미상)'
    if wanted is None:
        return None, '층수 미정(연면적·바닥면적 없음)'
    if isinstance(max_floors, int) and 0 < max_floors < wanted:
        return max_floors, f'연면적/바닥면적 {wanted}층을 Law 상한 {max_floors}층으로 제한'
    return wanted, f'연면적 {gfa:g}㎡ / 바닥면적 {footprint:g}㎡ = {wanted}층 (층고 {STOREY_M} m 가정)'


def parse_intent(response):
    """The declared intent as `intent_declare` wrote it (state_patch design_intent.*), the person's words kept."""
    patch = _dict(_dict(response).get('state_patch'))
    intent = {}
    for field in INTENT_FIELDS:
        value = patch.get(f'design_intent.{field}')
        if isinstance(value, str) and value.strip():
            intent[field] = value.strip()
        elif isinstance(value, (list, dict)) and value:
            intent[field] = value
    return intent or None


def parse(row, response, intent_response=None, *, max_floors=None):
    if row is None:
        return None
    response = _dict(response)
    layout = _dict(response.get('payload')) if isinstance(response.get('payload'), dict) and 'features' in response.get('payload') else response
    features = _features(layout)
    metrics = _dict(layout.get('metrics'))
    storeys, basis = _storeys(layout, max_floors)
    return {'status': _str(response.get('status')) or _str(layout.get('status')) or _str(row.get('state')) or 'unknown',
            'code': _str(response.get('code')), 'task_id': _str(row.get('task_id')), 'truncated': row.get('truncated') is True,
            'layout': {'crs': _str(layout.get('coordinate_crs')) or 'EPSG:4326', 'features': features,
                       'layers': sorted({f['properties']['layer'] for f in features}),
                       'footprint_m2': _num(metrics.get('building_footprint_m2')), 'site_area_m2': _num(metrics.get('site_area_m2')),
                       'coverage_pct': _num(metrics.get('coverage_ratio_pct')),
                       'storeys': storeys, 'storey_height_m': STOREY_M, 'height_m': storeys * STOREY_M if storeys else None,
                       'height_basis': basis} if features else None,
            'intent': parse_intent(intent_response) if intent_response else None}

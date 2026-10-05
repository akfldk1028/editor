import json

from shapely.geometry import mapping

from backend.app.modules.land.projection import utm_to_wgs84


def render_candidate(footprint, floors, floor_height, building_type, site_area, metrics,
                     *, upper=None, upper_scale=1.0, step_floor=None):
    properties = {'height':round(floors*floor_height,2), 'num_floors':floors,
                  'floor_height':floor_height, 'building_type':building_type, 'mass_shape':'additive',
                  'footprint_area':round(footprint.area,2), 'bcr':round(footprint.area/site_area*100,2),
                  'floor_area':metrics['floor_area'], 'far':metrics['far']}
    if upper is not None and floors > 1:
        properties.update(step_floor=step_floor, upper_scale=round(upper_scale,3),
                          lower_height=round(step_floor*floor_height,2),
                          upper_geometry=mapping(utm_to_wgs84(upper)))
    return json.loads(json.dumps({'type':'Feature','geometry':mapping(utm_to_wgs84(footprint)),
                                  'properties':properties}, allow_nan=False))

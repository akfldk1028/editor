"""Explicit geographic input and meter-based floor-plan display coordinates."""
from shapely.affinity import translate
from shapely.geometry import mapping, shape
from backend.app.modules.land.projection import wgs84_to_utm, utm_to_wgs84


def prepare_footprint(body, footprint):
    frame = body.get('coordinate_frame', 'local_meters')
    if frame not in ('local_meters', 'wgs84'):
        raise ValueError('coordinate_frame must be local_meters or wgs84')
    if frame == 'wgs84':
        west, south, east, north = footprint.bounds
        if not (-180 <= west <= east <= 180 and -80 <= south <= north <= 84):
            raise ValueError('wgs84 footprint is outside supported longitude/latitude bounds')
        footprint = wgs84_to_utm(footprint)
        if footprint.is_empty or not footprint.is_valid:
            raise ValueError('wgs84 footprint could not be projected to meters')
    origin = list(footprint.bounds[:2])
    descriptor = {'input': frame, 'output': frame, 'local_unit': 'meter',
                  'projected_crs': 'EPSG:32652' if frame == 'wgs84' else None,
                  'origin': origin}
    # Geographic generation runs near the origin to avoid numerical cancellation.
    if frame == 'wgs84':
        footprint = translate(footprint, xoff=-origin[0], yoff=-origin[1])
    return footprint, descriptor


def restore_coordinates(payload, descriptor):
    geographic = descriptor['input'] == 'wgs84'
    x, y = descriptor['origin']
    for design in payload.get('results', []):
        collection = design.get('floor_plan')
        if not collection:
            continue
        local_features, output_features = [], []
        for feature in collection.get('features', []):
            geometry = shape(feature['geometry'])
            local = geometry if geographic else translate(geometry, xoff=-x, yoff=-y)
            output = utm_to_wgs84(translate(geometry, xoff=x, yoff=y)) if geographic else geometry
            local_features.append({**feature, 'geometry': mapping(local)})
            output_features.append({**feature, 'geometry': mapping(output)})
        design['floor_plan_local'] = {**collection, 'features': local_features}
        design['floor_plan'] = {**collection, 'features': output_features}
    payload['coordinate_frame'] = descriptor

"""At-grade generation constraints; sloping ramp headroom is checked separately."""
from .geometry import EPS, number
from shapely.geometry import LineString, Point


def required_corner_clearance(options):
    value = options.get('corner_clearance_m')
    if value is None and options.get('entry_approach') in ('corner_clear', 'straight_6m', 'straight_10m'):
        value = 4.0
    return None if value is None else number(value, 'corner clearance')


def ramp_ground_clear(ramp, occupied):
    return all(geom is None or geom.is_empty or geom.intersection(occupied).area <= EPS
               for geom in (ramp.get('upper_landing'), ramp.get('ground_connector')))


def clears_frontage_ends(geometry, frontage, clearance):
    if clearance is None or geometry is None or geometry.is_empty:
        return True
    lines = [frontage] if isinstance(frontage, LineString) else list(getattr(frontage, 'geoms', ()))
    return all(geometry.distance(Point(line.coords[i])) >= clearance - EPS
               for line in lines for i in (0, -1))

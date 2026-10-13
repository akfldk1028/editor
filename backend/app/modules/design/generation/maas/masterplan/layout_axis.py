"""Explicit design module axis in the request's already established XY frame."""
import math


def layout_axis_angle(request):
    axis = (request.get('options') or {}).get('layout_axis')
    if axis is None:
        return None
    if not isinstance(axis, dict) or axis.get('frame') != 'site_local':
        raise ValueError('layout_axis requires the site_local metric frame')
    vector = axis.get('vector')
    if (not isinstance(vector, (list, tuple)) or len(vector) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)
            or math.hypot(*vector) == 0):
        raise ValueError('layout_axis requires a finite nonzero XY vector')
    if not isinstance(axis.get('source'), str) or not axis['source'].strip():
        raise ValueError('layout_axis requires source attribution')
    return math.degrees(math.atan2(vector[1], vector[0])) % 180


def planning_axis_angle(request):
    """One geometric module axis shared by coarse screening and detailed solving."""
    explicit = layout_axis_angle(request)
    if explicit is not None:
        return explicit
    from shapely.geometry import shape
    for key in ('front_frontage', 'frontage'):
        if not request.get(key):
            continue
        geometry = shape(request[key])
        lines = [geometry] if geometry.geom_type == 'LineString' else list(getattr(geometry, 'geoms', []))
        segments = [(math.hypot(b[0]-a[0], b[1]-a[1]), a, b)
                    for line in lines if line.geom_type == 'LineString'
                    for a, b in zip(line.coords, list(line.coords)[1:])]
        if segments:
            length, a, b = max(segments, key=lambda s:s[0])
            if length > 0:
                return math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) % 180
    return 0.0

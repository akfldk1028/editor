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

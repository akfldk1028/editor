"""Full-width longitudinal entry geometry in a row's rotated metric frame.

This is containment/contact geometry, not a vehicle swept-path or legal check.
No clipped obstacle bypass or lateral boundary contact is accepted.
"""
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, unary_union
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS


def straight_row_entrance(aisle, frontage, site, free, y, width, end):
    """Join an aisle end to an allowed boundary segment spanning its full width."""
    ax0, _, ax1, _ = aisle.bounds
    inner = min(ax1, ax0 + width) if end == 0 else max(ax0, ax1 - width)
    joined = unary_union([frontage])
    if joined.geom_type == 'MultiLineString':
        joined = linemerge(joined)
    # Merge only actually connected linework; simplify numeric-collinear nodes.
    # A prohibited gap remains disconnected and cannot create a wider portal.
    lines = [joined] if isinstance(joined, LineString) else getattr(joined, 'geoms', ())
    choices = []
    for line in lines:
        if not isinstance(line, LineString):
            continue
        line = line.simplify(EPS, preserve_topology=True)
        for a, b in zip(line.coords, list(line.coords)[1:]):
            dy = b[1] - a[1]
            # A side contact parallel to the aisle is not a transverse portal.
            if abs(dy) < width - EPS or min(a[1], b[1]) > y + EPS or max(a[1], b[1]) < y + width - EPS:
                continue
            xs = [a[0] + (height-a[1]) * (b[0]-a[0]) / dy for height in (y, y+width)]
            if (end == 0 and max(xs) > inner + EPS) or (end == 1 and min(xs) < inner - EPS):
                continue
            portal = LineString([(xs[0], y), (xs[1], y+width)])
            if portal.difference(site.boundary.buffer(EPS)).length > EPS:
                continue
            connector = Polygon([(xs[0], y), (inner, y), (inner, y+width), (xs[1], y+width)])
            if (connector.is_empty or not connector.is_valid or connector.area <= EPS
                    or not site.buffer(EPS).covers(connector) or not free.buffer(EPS).covers(connector)
                    or connector.intersection(aisle).area <= EPS):
                continue
            choices.append(connector)
    return min(choices, key=lambda shape: shape.area) if choices else None

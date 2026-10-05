"""Authoritative lift constructor parts shared by geometry and capacity semantics."""
import manifold3d as m3d


def lift_parts(base, p):
    minx, miny, minz, maxx, maxy, maxz = tuple(float(value) for value in base.bounding_box())
    height = max(maxz - minz, 1e-7)
    rise = height * max(0.08, min(0.45, float(p.get("rise_ratio", 0.22))))
    lifted = base.translate((0.0, 0.0, rise))
    support_ratio = max(0.06, min(0.22, float(p.get("support_ratio", 0.12))))
    access_side = str(p.get("access_side") or "closed").lower()
    support_height = rise + height * 0.08
    span_x, span_y = maxx - minx, maxy - miny
    if access_side in {"east", "west", "north", "south"}:
        # An occupiable back/service spine leaves a wide sheltered public
        # frontage under the lifted body. Four tiny corner columns read as
        # detached pieces and do not encode the access relation. The
        # placement is normalized to the live solid, never parcel coords.
        if access_side in {"east", "west"}:
            width = max(span_x * support_ratio, 1e-5)
            depth = max(span_y * 0.72, 1e-5)
            x = minx if access_side == "east" else maxx - width
            y = miny + (span_y - depth) / 2.0
        else:
            width = max(span_x * 0.72, 1e-5)
            depth = max(span_y * support_ratio, 1e-5)
            x = minx + (span_x - width) / 2.0
            y = miny if access_side == "north" else maxy - depth
        supports = [
            m3d.Manifold.cube((width, depth, support_height)).translate((x, y, minz))
        ]
        expansion = ["translate", "access_bound_service_spine", "union"]
    else:
        support_width = max(span_x * support_ratio, 1e-5)
        support_depth = max(span_y * support_ratio, 1e-5)
        inset_x = span_x * 0.16
        inset_y = span_y * 0.16
        supports = [
            m3d.Manifold.cube((support_width, support_depth, support_height)).translate((x, y, minz))
            for x in (minx + inset_x, maxx - inset_x - support_width)
            for y in (miny + inset_y, maxy - inset_y - support_depth)
        ]
        expansion = ["translate", "support_array", "union"]
    return lifted, supports, expansion, rise

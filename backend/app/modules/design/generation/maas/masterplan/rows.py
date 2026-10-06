"""Row-and-aisle parking candidates chosen by an objective, not by site rules.

Every candidate is one through aisle (a band) with a stall row on each side, an entrance
corridor from an allowed road edge to one end of the aisle, and - when a basement is wanted -
a straight ramp leaving the aisle at right angles. The engine enumerates aisle orientations
(every site and footprint edge direction), aisle positions (0.5 m steps across the free
ground), entrance ends and ramp positions, builds each exactly, and scores it:

    score = stalls_placed - w_aisle * aisle_length_m
            - w_access * mean distance of accessible stalls to the entrance
            + w_edge   * (aisle parallel to the longest allowed road edge)
            + w_beside * (ramp touches the plate but runs beside it - the basement stays under the plate)
            + w_far    * ramp at the aisle end away from the entrance (cars pass the rows first)
            + w_under  * share of the ramp under the plate (off by default)

The weights are parameters (defaults below); nothing here names a parcel. What practice plans
do - long straight aisle, rows both sides, ramp off the aisle beside/under the plate - is what
this objective rewards, so it emerges on any parcel where it fits. The planner validates every
candidate independently afterwards.
"""
from __future__ import annotations

import math

from shapely.affinity import rotate
from shapely import STRtree, from_wkb, prepare
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import substring, unary_union

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts
from backend.app.modules.design.generation.maas.masterplan.row_access import straight_row_entrance

# w_beside: the ramp runs beside the plate (touching, mostly outside it) so the basement floor under the
# plate stays whole and the ramp uses the yard - the practice arrangement (Alt1: ramp along the building's
# west face). w_far: the ramp leaves the aisle at the end away from the entrance, so entering cars pass the
# surface rows first. w_under kept for reference, off by default.
# THERE IS NO `w_loop`, ON PURPOSE. A loop's worth is not a constant: on a generous plate it costs
# nothing and on a tight one it costs a whole basement level, and which of those is true is a fact
# about the parcel, not a number to type here. Pricing it at four cars was wrong on both counts - it
# was invented, and on 고산 the measured price was twelve. The loop is therefore measured (`terms`
# carries `closed_aisle_loop` and `loop_length_m`) and decided by comparison: `basement_layout.rank`
# takes it when it costs no cars, and `planner.rank` takes it when it costs no level and no
# excavation. When it costs more, the plan says what it would have cost.
WEIGHTS = {"w_aisle": 0.08, "w_access": 0.05, "w_edge": 3.0, "w_under": 0.0, "w_beside": 4.0, "w_far": 3.0, "w_open": 0.0, "w_cluster": 0.02}


def _lines(geom):
    if geom is None:
        return []
    return [geom] if isinstance(geom, LineString) else list(getattr(geom, "geoms", ()))


def _segments(lines):
    for line in _lines(lines):
        for a, b in zip(line.coords, list(line.coords)[1:]):
            if math.dist(a[:2], b[:2]) > 0.5:
                yield LineString([a[:2], b[:2]])


def _angle(seg: LineString) -> float:
    (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180


def orientation_candidates(site, footprint, frontage, *, limit=8):
    """Aisle directions worth trying: every road edge, site edge and footprint edge direction (deduplicated to 1 deg)."""
    angles = []
    for seg in _segments(frontage):
        angles.append(_angle(seg))
    for poly in (site, footprint):
        if poly is None or poly.is_empty:
            continue
        # A generated mass footprint can come back in several pieces; reading `.exterior` off a
        # MultiPolygon raises, and it did - on the first run where the footprint was small enough to
        # split, which is exactly the practice-scale case this engine is meant to serve.
        for part in parts(poly):
            coords = list(part.exterior.coords)
            for a, b in zip(coords, coords[1:]):
                if math.dist(a, b) > 3.0:
                    angles.append(_angle(LineString([a, b])))
    out = []
    for ang in angles:
        if all(min(abs(ang - o), 180 - abs(ang - o)) > 1.0 for o in out):
            out.append(ang)
    # CAP THE FAN. Every edge over 3 m contributes a direction, so an irregular cadastral parcel
    # offers 20-40 of them and the whole y-sweep, ramp-sweep and tiling nest runs once per angle.
    # Practice lays bays parallel to the site's long dimension (CCDC), and the road edge decides the
    # entrance, so those are the directions worth spending on: the ones already listed that lie
    # closest to the frontage or to the minimum rotated rectangle's two axes come first, and the
    # tail is dropped. Order is preserved among the kept angles so existing results do not shuffle.
    if len(out) > limit:
        anchors = [_angle(max(_segments(frontage), key=lambda s: s.length))] if list(_segments(frontage)) else []
        if site is not None and not site.is_empty:
            box = site.minimum_rotated_rectangle
            coords = list(box.exterior.coords)
            anchors += [_angle(LineString([a, b])) for a, b in zip(coords, coords[1:])][:2]
        def near(ang):
            return min((min(abs(ang - a), 180 - abs(ang - a)) for a in anchors), default=0.0)
        keep = set(sorted(out, key=near)[:limit])
        out = [a for a in out if a in keep]
    return out


def _fill_row(host, drive, y0, y1, xs, xe, stall_w, stall_l, acc_w, acc_l, want_acc, blocked, side, *,
              expanded=None, want_expanded=0, n_expanded_start=0, expanded_from=None):
    """Stalls along x in [xs, xe) for a row that touches the aisle at y0 (side -1: row below y0; +1: row above y1).

    Accessible stalls are taken FIRST, at the row's start. 「장애인·노인·임산부 등의 편의증진 보장에 관한
    법률」 시행규칙 [별표 1] 4 asks for "건축물의 출입구 또는 장애인용 승강설비와 가장 가까운 장소", and the
    row's start is the CROSS AISLE end - the car gate - which on a through aisle is the end farthest
    from the building. So this ordering does not implement that rule, and MOVING it is not free: an
    accessible bay is 3.3 m against 2.5 m, so shifting it along the row changes how many stalls the
    row holds and flips the winning layout (measured 2026-09-27: 지상 24 -> 12, 굴착 891 -> 1,366 m2).
    Whether a given plan satisfies the rule is therefore measured and reported rather than forced
    here - masterplanagent.validation.accessible_placement raises accessible_stall_placement_review,
    which routes to Law, because the trade is 별표1's to price and 별표 content is not in the graph.

    `expanded_from` is the x beyond which a 확장형 (2.6 x 5.2, 시행규칙 제3조제1항제2호) is preferred - the
    closed end of the aisle, where the extra 100 mm is worth most.  임재문·오세경·김회경, 한국산학기술학회
    논문지 15(12):7403-7415 (2014) measured the end stall: at 2.5 m the car reversing out still intrudes
    0.22 m into its neighbour, 2.6 m is their optimum against land take, and 3.0 m is interference-free
    (which is also the 3000 mm Singapore's LTA code mandates for a dead-end end lot).  2.6 m is the one
    of those three that is already a Korean statutory stall size, so it costs nothing in compliance.
    """
    stalls = []
    x = xs
    n_acc = 0
    n_exp = n_expanded_start
    # both are fixed for the whole row; buffering them per stall attempt was the hottest call here
    host_b, drive_b = host.buffer(EPS), drive.buffer(EPS)
    # Fresh buffers, so preparing them in place touches nothing the caller holds; a prepared
    # covers() answers the same question without rebuilding the index on every stall.
    prepare(host_b)
    prepare(drive_b)
    blocked_live = blocked is not None and not blocked.is_empty
    if blocked_live:
        blocked_index = from_wkb(blocked.wkb)  # an exact copy, so preparing it leaves `blocked` untouched
        prepare(blocked_index)

    def clear(stall):
        return (not blocked_live or not blocked_index.intersects(stall)
                or stall.intersection(blocked).area <= EPS)

    while x + stall_w <= xe + EPS:
        acc = n_acc < want_acc
        exp = (not acc) and expanded is not None and n_exp < want_expanded \
            and (expanded_from is None or x + EPS >= expanded_from)
        # an 확장형 that does not fit here (row too shallow, end of row) falls back to a general stall
        attempts = [("accessible", acc_w, acc_l)] if acc else ([("expanded", *expanded)] if exp else []) + [("standard_90deg", stall_w, stall_l)]
        placed = False
        # The skip-ahead below needs the geometry we actually tried HERE. Reading `stall` from the
        # loop was wrong twice over: on the first x it is unbound (UnboundLocalError, which is how a
        # rotated site crashed the packer), and afterwards it silently holds the PREVIOUS position's
        # box, so the row skipped past an obstacle it had never tested at this x.
        attempted = None
        for kind, w, l in attempts:
            if x + w > xe + EPS:
                continue
            stall = box(x, y0 - l, x + w, y0) if side < 0 else box(x, y1, x + w, y1 + l)
            manoeuvre = box(x, y0, x + w, y1)
            attempted = stall
            if host_b.covers(stall) and drive_b.covers(manoeuvre) and clear(stall):
                stalls.append({"polygon": stall, "front": manoeuvre, "type": kind, "width_m": w, "length_m": l})
                if kind == "accessible":
                    n_acc += 1
                elif kind == "expanded":
                    n_exp += 1
                x += w
                placed = True
                break
        if not placed:
            inter = (attempted.intersection(blocked)
                     if attempted is not None and blocked is not None and not blocked.is_empty else None)
            if inter is not None and not inter.is_empty and inter.area > EPS:
                x = max(x + 0.25, inter.bounds[2])
            else:
                x += 0.5
    # Minimum bank size constraint (Thomas & Rambha, 2025):
    # Eliminate isolated stall fragments (< 2 stalls) split by cores or obstacles
    if stalls and len(stalls) > 1:
        runs = []
        curr_run = [stalls[0]]
        for s in stalls[1:]:
            prev_end = curr_run[-1]["polygon"].bounds[2]
            this_start = s["polygon"].bounds[0]
            if abs(this_start - prev_end) <= 0.05:
                curr_run.append(s)
            else:
                runs.append(curr_run)
                curr_run = [s]
        runs.append(curr_run)
        stalls = [s for r in runs if len(r) >= 2 for s in r]
    elif stalls and len(stalls) == 1 and blocked is not None and not blocked.is_empty:
        # Isolated single stall next to an obstacle is pruned
        stalls = []
    return stalls



def _tile_bands(*args, ring, repair_ring=False, **kwargs):
    """For a requested loop, move pinched cross aisles before counting bays."""
    from backend.app.modules.design.generation.maas.masterplan.circulation import closed_aisle_loop
    initial = _tile_bands_at(*args, ring=ring, edge_aisles=repair_ring, **kwargs)
    if not ring or not repair_ring:
        return initial
    aisle = args[3]
    if initial is not None and closed_aisle_loop(initial['drive'], aisle) is not None:
        return initial
    choices = []
    for near, far in ((aisle/2, 0), (0, aisle/2), (aisle/2, aisle/2),
                     (aisle, 0), (0, aisle), (aisle, aisle)):
        candidate = _tile_bands_at(*args, ring=True, edge_aisles=True, near_inset=near, far_inset=far, **kwargs)
        if candidate is None or closed_aisle_loop(candidate['drive'], aisle) is None:
            continue
        choices.append(candidate)
        if len(candidate['stalls']) >= (kwargs.get('required') or 0):
            break
    if not choices:
        # Last resort: put the loop inside the band we know is in the ground, rather than at the
        # bounding box. On an irregular parcel the box corner is outside the boundary, so every
        # attempt above lands its far cross aisle on nothing.
        candidate = _tile_bands_at(*args, ring=True, edge_aisles=True, clamp_to_band=True, **kwargs)
        if candidate is not None and closed_aisle_loop(candidate['drive'], aisle) is not None:
            choices.append(candidate)
    return max(choices, key=lambda c: (len(c['stalls']), -c['drive'].area)) if choices else None


def _tile_bands_at(g_ground, blocked, y, aisle, stall_w, stall_l, acc_w, acc_l, ax0, ax1, end,
                entrance, accessible, expanded_dims, want_expanded, *, ring, clamp_to_band=False, ground_stalls=True, required=None,
                near_inset=0, far_inset=0, edge_aisles=False):
    """Whole-module bands across the plate, joined by a cross aisle at the entrance end.

    The parking module - stall + aisle + stall - is the unit a plate is sized in, and geometry.py
    already quantises plate depth to a whole number of them.  Laying ONE band into a plate cut for
    three leaves two thirds of the excavation carrying nothing, which is the categorical penalty the
    functional-design canon describes (CCDC Parking Structure Design Guidelines: "overall width
    shall be a multiple of the bay width"; Jones/Nitterhouse measure a plate that loses its lower
    bay at +15 % area per stall).  Xu Han-zhe et al., J. BUPT 42(4):102-108 (2019) lay modules along
    the boundary first and decompose the interior; this is the rectangular case of that.

    The bands sit at y + k*module and are connected by ONE cross aisle at the entrance end (a comb)
    or TWO, one at each end (a ring).  IStructE 3.2.6/4.4 wants the aisle graph strongly connected so
    a driver who misses a space can come round again, which the ring gives and the comb does not;
    the ring costs a second cross aisle, so both are generated and the objective decides.

    Returns None when fewer than two bands fit, else
    {stalls, drive, bands, cross_aisles, dead_end_stalls}.
    """
    bay_depth = max(stall_l, acc_l if accessible else stall_l,
                    expanded_dims[1] if expanded_dims and want_expanded else stall_l)
    module = 2 * bay_depth + aisle
    minx, miny, maxx, maxy = g_ground.bounds
    minimum_depth = module + aisle if ring and edge_aisles else 2 * module
    if maxy - miny < minimum_depth - EPS:
        return None

    # The cross aisle takes one aisle width at the entrance end; stalls start beyond it.  The far
    # limit is the GROUND's extent, not the primary band's: on a parcel where the plate sits in the
    # middle, the primary band is a short piece of the ring around it, and clamping every other band
    # to that piece threw away runs several times longer.  Each band is filled over its own extent.
    # The outer cross aisle of a loop goes at the far end of the field. Taking that end from the
    # BOUNDING BOX puts it outside a parcel that is not a rectangle, the strip comes back empty and
    # the loop is abandoned - which is why `ring` returned nothing on every real parcel while it
    # worked on the rectangular fixtures. `clamp_to_band` falls back to the primary band's own
    # clipped extent, which is inside the ground by construction: a smaller loop, but a real one.
    if clamp_to_band:
        far, near = ax1, ax0
    else:
        far = ax1 if ax1 > maxx - 1 else maxx
        near = ax0 if ax0 < minx + 1 else minx
    if end == 0:
        far -= far_inset
        cx0, cx1 = ax0 + near_inset, ax0 + near_inset + aisle
        bxs0, bxs1 = cx1, (far - aisle) if ring else far
        dx0, dx1 = (far - aisle, far) if ring else (None, None)
    else:
        near += far_inset
        cx0, cx1 = ax1 - aisle - near_inset, ax1 - near_inset
        bxs0, bxs1 = (near + aisle) if ring else near, cx0
        dx0, dx1 = (near, near + aisle) if ring else (None, None)
    if bxs1 - bxs0 < 3 * stall_w:
        return None

    outer_bay = 0 if ring and edge_aisles else bay_depth
    kmin = math.ceil((miny + outer_bay - y - EPS) / module)
    kmax = math.floor((maxy - aisle - outer_bay - y + EPS) / module)
    nominal_capacity = max(1, 2 * int((bxs1 - bxs0) // stall_w))
    needed = math.ceil(max(0, required or 0) / nominal_capacity)
    budget = min(256, max(17, 2 * needed + 8))
    count = max(0, kmax - kmin + 1)
    if count <= budget:
        indices = list(range(kmin, kmax + 1))
    else:
        indices = [*range(kmin, kmin + 4), *range(kmax - 3, kmax + 1)]
        primary = min(kmax, max(kmin, 0))
        local_count = max(1, (budget - 8) // 2)
        indices += list(range(max(kmin, primary - local_count // 2), min(kmax + 1, primary + local_count // 2 + 1)))
        step = max(1, count // (budget - len(indices) + 1))
        indices += list(range(kmin, kmax + 1, step))
        indices = sorted(set(indices))
    offsets = []
    for k in indices:
        yk = y + k * module
        if yk - outer_bay < miny - EPS or yk + aisle + outer_bay > maxy + EPS:
            continue
        offsets.append(yk)
    if len(offsets) < 2:
        return None
    offsets.sort()

    # A ramp or a column bay splits a band into pieces.  Requiring every band to span the whole
    # plate threw those bands away and left the excavation empty, so each band keeps the piece that
    # reaches the cross aisle and is filled over ITS OWN run.
    aisles, kept, runs = [], [], []
    for yk in offsets:
        band = box(minx - 1, yk, maxx + 1, yk + aisle).intersection(g_ground)
        best_part = None
        for part in parts(band):
            px0, _, px1, _ = part.bounds
            if px1 - px0 < 3 * stall_w or part.area < 0.9 * (px1 - px0) * aisle:
                continue                      # not a straight run
            if px1 < cx0 - EPS or px0 > cx1 + EPS:
                continue                      # cannot reach the cross aisle, so it would be a stub
            if best_part is None or (px1 - px0) > (best_part.bounds[2] - best_part.bounds[0]):
                best_part = part
        if best_part is None:
            continue
        px0, _, px1, _ = best_part.bounds
        run0, run1 = max(bxs0, px0), min(bxs1, px1)
        if run1 - run0 < 3 * stall_w:
            continue
        piece = best_part.intersection(box(min(cx0, run0), yk, max(cx1, run1), yk + aisle))
        if piece.is_empty:
            continue
        aisles.append(piece)
        kept.append(yk)
        runs.append((run0, run1))
    if len(aisles) < 2:
        return None

    # the cross aisle(s) span every band it joins
    lo, hi = kept[0], kept[-1] + aisle
    cross = box(cx0, lo, cx1, hi).intersection(g_ground).difference(blocked)
    if cross.is_empty:
        return None
    crosses = [cross]
    if ring and dx0 is not None:
        second = box(dx0, lo, dx1, hi).intersection(g_ground).difference(blocked)
        if second.is_empty:
            return None
        crosses.append(second)

    drive = unary_union(aisles + crosses + ([entrance] if entrance is not None else [])).buffer(0)
    if drive.is_empty or len(parts(drive)) != 1:
        return None                       # the bands did not join up: not a layout, a set of stubs

    stalls = []
    for yk, (run0, run1) in zip(kept, runs):
        if not ground_stalls:
            break
        for side in (-1, 1):
            stalls += _fill_row(g_ground, drive, yk, yk + aisle, run0, run1, stall_w, stall_l,
                                acc_w, acc_l,
                                max(0, accessible - sum(s["type"] == "accessible" for s in stalls)),
                                blocked, side, expanded=expanded_dims, want_expanded=want_expanded,
                                n_expanded_start=sum(s["type"] == "expanded" for s in stalls),)
    # a stall the tiling put under another band's aisle or under the cross aisle is not a stall
    stalls = [st for st in stalls if st["polygon"].intersection(drive).area <= EPS]
    if not stalls:
        return None

    # IStructE 4.4.2 caps a dead-end aisle at six bins; with a ring there is no dead end.
    dead_end = 0 if ring else int(max(r1 - r0 for r0, r1 in runs) // stall_w)
    return {"stalls": stalls, "drive": drive, "bands": len(kept),
            "cross_aisles": len(crosses), "dead_end_stalls": dead_end,
            "aisle_span_m": round(sum(r1 - r0 for r0, r1 in runs), 2)}


def _inline_at_aisle_end(xs, y, aisle, xdir, spec, ax0, ax1):
    """The ramp CONTINUES the aisle instead of leaving it sideways.

    This is how the reference scheme reads as one roadway: you enter, drive the row, and the ramp is
    the far end of that same drive (고산 ALT1 배치도 - the 지하주차장 mouth is in line with the run,
    not hung off its side).  A ramp that leaves at right angles against the building face reads as an
    appendage and makes the ground and basement plans look unrelated.
    """
    w, length, landing = spec["width_m"], spec["length_m"], spec["landing_m"]
    if w > aisle + EPS:            # an in-line ramp cannot be wider than the aisle it continues
        return None
    y0 = y + (aisle - w) / 2       # centred on the aisle
    if xdir > 0:                   # continue past the high-x end
        x0 = ax1
        poly = box(x0, y0, x0 + length, y0 + w)
        upper = box(x0, y0, x0 + landing, y0 + w)
        lower = box(x0 + length - landing, y0, x0 + length, y0 + w)
        center = LineString([(x0 + p["distance_m"], y0 + w / 2, p["z_m"]) for p in spec["profile"]])
    else:
        x0 = ax0
        poly = box(x0 - length, y0, x0, y0 + w)
        upper = box(x0 - landing, y0, x0, y0 + w)
        lower = box(x0 - length, y0, x0 - length + landing, y0 + w)
        center = LineString([(x0 - p["distance_m"], y0 + w / 2, p["z_m"]) for p in spec["profile"]])
    return poly, upper, lower, center, spec, None


def _straight_off_aisle(xs, y, aisle, ydir, spec):
    """The ramp leaves the aisle at right angles and runs straight (the existing arrangement)."""
    w, length, landing = spec["width_m"], spec["length_m"], spec["landing_m"]
    if ydir > 0:
        poly = box(xs, y + aisle, xs + w, y + aisle + length)
        upper = box(xs, y + aisle, xs + w, y + aisle + landing)
        lower = box(xs, y + aisle + length - landing, xs + w, y + aisle + length)
        center = LineString([(xs + w / 2, y + aisle + p["distance_m"], p["z_m"]) for p in spec["profile"]])
    else:
        poly = box(xs, y - length, xs + w, y)
        upper = box(xs, y - landing, xs + w, y)
        lower = box(xs, y - length, xs + w, y - length + landing)
        center = LineString([(xs + w / 2, y - p["distance_m"], p["z_m"]) for p in spec["profile"]])
    return poly, upper, lower, center, spec, None


def _curved_at_aisle_end(y, aisle, xdir, hand, spec, min_radius, ax0, ax1, *, lead_fraction=0.5, turn_deg=90.0):
    """The ramp leaves IN LINE with the aisle and then turns - what practice actually draws.

    고산 ALT1/ALT2 both continue the surface drive past the last stall and turn the ramp down; a
    straight in-line run rarely fits a Korean parcel, which is why the reference scheme curves it.
    Heading starts along the aisle axis, so the drive reads as one roadway rather than an appendage.
    """
    start = (ax1 if xdir > 0 else ax0, y + aisle / 2)
    head = 0.0 if xdir > 0 else math.pi
    return _curved_ramp(start, head, hand, spec, min_radius, lead_fraction=lead_fraction, turn_deg=turn_deg)


def _curved_ramp(start, head, hand, spec, min_radius, *, lead_fraction=0.5, turn_deg=90.0, steps=32):
    """Lead straight, one arc on a fixed radius, tail straight; the centreline is exactly the ramp run.

    The arc is drawn as `steps` chords on the true circle, so every arc vertex sits at `radius` from
    the centre and the drawn turn is never tighter than the rule. Lead and tail absorb the run left
    after the CHORD length (not the ideal arc length): the centreline then measures exactly
    `spec["length_m"]`, and every grade station of `spec["profile"]` is a vertex carrying its own z.
    `lead_fraction` is the share of the slack straight placed before the turn (0 = turn right after
    the upper landing); `turn_deg` is the turn angle.
    """
    w, total, landing = spec["width_m"], spec["length_m"], spec["landing_m"]
    theta = math.radians(turn_deg)
    radius = (min_radius or 0.0) + w / 2
    if radius <= 0 or not 0 < theta <= math.pi or not 0.0 <= lead_fraction <= 1.0:
        return None
    arc_len = steps * 2 * radius * math.sin(theta / (2 * steps))
    slack = total - arc_len - 2 * landing
    if slack < -EPS:
        return None
    slack = max(slack, 0.0)
    lead = landing + slack * lead_fraction
    tail = total - arc_len - lead
    p0 = (start[0] + math.cos(head) * lead, start[1] + math.sin(head) * lead)
    centre = (p0[0] + math.cos(head + hand * math.pi / 2) * radius, p0[1] + math.sin(head + hand * math.pi / 2) * radius)
    a0 = math.atan2(p0[1] - centre[1], p0[0] - centre[0])
    arc = [(centre[0] + radius * math.cos(a0 + hand * theta * i / steps),
            centre[1] + radius * math.sin(a0 + hand * theta * i / steps)) for i in range(steps + 1)]
    end_head = head + hand * theta
    p1 = arc[-1]
    p2 = (p1[0] + math.cos(end_head) * tail, p1[1] + math.sin(end_head) * tail)
    spine = LineString([start, p0, *arc[1:], p2])
    poly = spine.buffer(w / 2, cap_style=2, join_style=1, quad_segs=32)
    # THE LANDING IS THE FLAT PART, NOT THE WHOLE STRAIGHT. `lead`/`tail` carry the landing plus a
    # share of the slack run, and that slack is already on grade in `spec["profile"]`. Handing the whole
    # straight out as a landing let the drive be drawn onto the slope, which is why every curved-ramp
    # scheme failed `drive_obstructions` at all three levels and no curved ramp ever reached a sheet.
    upper = substring(spine, 0, landing).buffer(w / 2, cap_style=2, join_style=1, quad_segs=32)
    lower = substring(spine, spine.length - landing, spine.length).buffer(
        w / 2, cap_style=2, join_style=1, quad_segs=32)
    return poly, upper, lower, _graded_centerline(spine, spec["profile"]), spec, radius


def _graded_centerline(spine, profile):
    """The 2-D spine with every grade station inserted as a vertex and z read by run distance."""
    pts = list(spine.coords)
    run = [0.0]
    for a, b in zip(pts, pts[1:]):
        run.append(run[-1] + math.dist(a, b))
    stations = sorted((float(p["distance_m"]), float(p["z_m"])) for p in profile)
    merged = list(zip(run, pts))
    for d, _ in stations:
        if any(abs(d - r) <= 1e-9 for r, _ in merged):
            continue
        for (r0, a), (r1, b) in zip(merged, merged[1:]):
            if r0 < d < r1:
                t = (d - r0) / (r1 - r0)
                merged.append((d, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)))
                break
        merged.sort(key=lambda item: item[0])

    def z_at(d):
        for (d0, z0), (d1, z1) in zip(stations, stations[1:]):
            if d <= d1 + 1e-9:
                return z0 if d1 - d0 <= EPS else z0 + (z1 - z0) * (d - d0) / (d1 - d0)
        return stations[-1][1]

    return LineString([(x, yy, z_at(d)) for d, (x, yy) in merged])


def _adjacent_pairs(polygons, tolerance):
    """Unordered pairs of stalls within `tolerance` of each other, through a spatial index.

    The same count as testing every pair, without the O(n^2) distance calls that took 84 % of a
    450-stall search.
    """
    if len(polygons) < 2:
        return 0
    left, right = STRtree(polygons).query(polygons, predicate="dwithin", distance=tolerance)
    return int((left < right).sum())


def _curved_off_aisle(xs, y, aisle, ydir, hand, spec, min_radius):
    """The ramp leaves the aisle, turns 90 degrees and runs back parallel to it.

    This is the arrangement the reference scheme draws where a straight run would cross the plate:
    a quarter turn on a fixed radius with straight lead and tail.  The radius is the rule's minimum
    inner radius plus half the band; the remaining run length is split between lead and tail.
    """
    start = (xs + spec["width_m"] / 2, y + aisle if ydir > 0 else y)
    head = math.pi / 2 if ydir > 0 else -math.pi / 2
    return _curved_ramp(start, head, hand, spec, min_radius)


LARGE_ENVELOPE_M2 = 10_000.0   # the line bounded_packing draws between the small and large search
BOUNDED_OFFSETS = 32           # band offsets per orientation on a large envelope (search effort, not design)
SEARCH_BUDGET = 384            # band offsets across all orientations on a large envelope


def _band_offsets(g_ground, aisle, stall_w, stall_l, step, *, straight_entry, limit=None):
    """Aisle-band offsets (y of the band's low edge) for one orientation.

    The full sweep steps `step` from the lowest position that leaves a row on both sides (or both
    edges, for a straight-entry study). A parcel too shallow for a double-loaded module still takes
    ONE loaded row, so its two edge positions are offered instead of nothing.

    `limit` bounds a large envelope: offsets whose band holds no straight two-bay run are dropped
    first (they cost a full evaluation and can yield nothing), then a sample is kept - every module
    pitch offset the tiling needs, thinned evenly, and the one-band positions spread evenly over the
    rest including both extremes.
    """
    minx, miny, maxx, maxy = g_ground.bounds
    y = miny if straight_entry else miny + stall_l
    far_margin = 0 if straight_entry else stall_l
    offsets = []
    while y + aisle + far_margin <= maxy + EPS:
        offsets.append(y)
        y += step
    if not offsets and not straight_entry and maxy - aisle >= miny - EPS:
        offsets = list(dict.fromkeys((miny, maxy - aisle)))
    if limit is None or len(offsets) <= limit:
        return offsets

    def usable(yy):
        band = box(minx - 1, yy, maxx + 1, yy + aisle).intersection(g_ground)
        return any(part.area >= aisle * 2 * stall_w
                   and part.area >= 0.9 * (part.bounds[2] - part.bounds[0]) * aisle for part in parts(band))

    offsets = [yy for yy in offsets if usable(yy)]
    if len(offsets) <= limit:
        return offsets

    def spread(values, count):
        if count <= 0 or not values:
            return []
        if len(values) <= count:
            return list(values)
        if count == 1:
            return [values[0]]
        return [values[round(i * (len(values) - 1) / (count - 1))] for i in range(count)]

    module = 2 * stall_l + aisle
    pitch = [yy for yy in offsets if yy - offsets[0] < module - EPS]
    tiling = spread(pitch, limit // 2)
    rest = [yy for yy in offsets if yy not in set(tiling)]
    return sorted(set(tiling) | set(spread(rest, limit - len(tiling))))


def row_candidates(site, ground, footprint, obstacles, frontage, front, rules, required, accessible, *,
                   ramp=None, curved=None, curve_min_radius=None, weights=None, step=0.5, limit=14,
                   expanded_needed=None, ground_stalls=True, turn_radius_m=None, turn_lane_m=None,
                   field="auto", occupied_footprint=None, accept_ramp=None, ramp_shape="any", allowed_angles=None,
                   preserve_banks=False, straight_entry=False, prohibited=None,
                   search_budget=SEARCH_BUDGET):  # noqa: E501
    """Scored row-and-aisle candidates in world coordinates.

    ramp: None (surface only) or {"width_m", "length_m", "landing_m", "profile"} from ramps.ramp_profile.
    ramp_shape: "any" builds both forms and lets the objective choose; "curved" builds ONLY turning
    ramps and "straight" only straight runs. Passing the curved SPEC alone was not enough - it set the
    band to the statutory curve width (6.5 m against a straight run's 6.0) while the straight builders
    went on running, and since the objective rewards a run beside the plate a straight 6.5 m ramp won
    every time. A scheme that asks for the practice form got a straight ramp at the curve's width.
    Returns a list of dicts: stalls, drive, entrance, aisle_length_m, ramp (polygon/landings/centerline or None),
    basement (Polygon or None), score, terms, angle_deg, entrance_end.
    """
    if ramp_shape not in ("any", "straight", "curved"):
        raise ValueError("ramp_shape must be any, straight or curved")
    want_straight, want_curved = ramp_shape in ("any", "straight"), ramp_shape in ("any", "curved")
    W = {**WEIGHTS, **(weights or {})}
    _drops = {}
    stall_w, stall_l = float(rules["stall_width_m"]), float(rules["stall_length_m"])
    acc_w, acc_l, aisle = float(rules["accessible_width_m"]), float(rules["accessible_length_m"]), float(rules["aisle_width_m"])
    road_segs = list(_segments(frontage))
    if not road_segs or ground.is_empty:
        return []
    longest_road = max(road_segs, key=lambda s: s.length)
    results = []
    search_count = 0
    angles = list(allowed_angles if allowed_angles is not None else orientation_candidates(site, footprint, frontage))
    # A large envelope is searched on a bounded sample of band offsets (the same 10,000 m2 line
    # bounded_packing draws); a practice-scale parcel keeps the full sweep, so its results do not move.
    bounded = ground.area >= LARGE_ENVELOPE_M2
    per_angle = max(1, min(BOUNDED_OFFSETS, int(search_budget) // max(1, len(angles))))
    for angle in angles:
        if angle % 360 == 0:
            rot = unrot = lambda g: g  # noqa: E731  (a zero rotation is the identity; it was 5 s of copies)
        else:
            rot = lambda g: rotate(g, -angle, origin=(0, 0))  # noqa: E731
            unrot = lambda g: rotate(g, angle, origin=(0, 0))  # noqa: E731
        g_site, g_ground, g_fp = rot(site), rot(ground), rot(footprint) if footprint is not None else Polygon()
        g_obst = rot(obstacles) if obstacles is not None and not obstacles.is_empty else Polygon()
        # An irregular cadastral parcel can rotate into a ring GEOS calls invalid, and the first
        # intersection then raises TopologyException and takes the whole plan with it. buffer(0)
        # normalises the ring without moving the boundary.
        g_site, g_ground, g_fp, g_obst = (g if g.is_valid else g.buffer(0)
                                          for g in (g_site, g_ground, g_fp, g_obst))
        if g_ground.is_empty or not g_ground.is_valid:
            continue
        g_roads = [rot(s) for s in road_segs]
        road_union = unary_union(g_roads)
        g_prohibited = rot(prohibited) if prohibited is not None and not prohibited.is_empty else None
        # fixed for this orientation: the inner loops used to rebuild these on every iteration
        g_site_b, g_ground_b = g_site.buffer(EPS), g_ground.buffer(EPS)
        road_reach = road_union.buffer(float(turn_radius_m) * 1.5) if turn_radius_m else None
        minx, miny, maxx, maxy = g_ground.bounds
        offsets = _band_offsets(g_ground, aisle, stall_w, stall_l, step, straight_entry=straight_entry,
                                limit=per_angle if bounded else None)
        search_count += len(offsets)
        for y in offsets:
            band = box(minx - 1, y, maxx + 1, y + aisle).intersection(g_ground)
            for aisle_poly in parts(band):
                # An aisle whose end sits on the road needs no separate entrance zone, so two bays
                # already make a field; one reached through a corridor still needs three.
                direct = aisle_poly.distance(road_union) <= 0.05
                if aisle_poly.area < aisle * (2 if direct else 3) * stall_w:
                    continue
                ax0, _, ax1, _ = aisle_poly.bounds
                # only keep a straight run: the band clipped must be close to its bounding box
                if aisle_poly.area < 0.9 * (ax1 - ax0) * aisle:
                    continue
                # 끝단 회전로 at the closed end of the aisle.  Korean law does not require one - 주차장법
                # 시행규칙 제6조/제11조 contain no 회차 clause at all - and 임재문·오세경·김회경, "막다른주차장내
                # 차량회전구간 설계기준 정립에 관한 연구", 한국산학기술학회논문지 15(12):7403-7415 (2014) says so
                # in terms: "끝단의 회전로는 설치하지 않아도 법적인 문제가 없으나 이를 설치할 경우에는 2.5m
                # 이상의 폭으로 설계하는 것이 일반적".  So it is an ENUMERATED option at the practice width,
                # not a mandate, and not the 2R a forward U-turn would need.
                bays = [0.0]
                if turn_lane_m:
                    bays.append(float(turn_lane_m))
                for end, bay in ((e, b) for e in (0, 1) for b in bays):
                    # entrance corridor from the aisle end down/up to the nearest road edge, or the aisle end itself on the road
                    xe0, xe1 = (ax0, ax0 + aisle) if end == 0 else (ax1 - aisle, ax1)
                    drive = aisle_poly
                    entrance = None
                    if straight_entry:
                        entrance = straight_row_entrance(aisle_poly, road_union, g_site, g_ground, y, aisle, end)
                    elif aisle_poly.distance(road_union) <= 0.05:
                        entrance = box(xe0, y, xe1, y + aisle).intersection(g_ground)  # the aisle end itself sits on the road
                        if entrance.is_empty or entrance.distance(road_union) > 0.05:
                            entrance = None
                        # ...over its full width: an aisle that grazes the road for a metre is not an entrance
                        # (the same contact bounded_packing._width_connected requires of the result).
                        elif (road_union.intersection(entrance.buffer(0.05)).length + 0.05
                              < min(aisle, road_union.length)):
                            entrance = None
                    elif not straight_entry:
                        sy0, sy1 = g_site.bounds[1], g_site.bounds[3]
                        for ydir in (-1, 1):
                            # The corridor runs to the site's own edge: a fixed 200 m stopped a field
                            # 450 m from its road short of the road it was meant to reach.
                            corridor = (box(xe0, sy0 - 1, xe1, y + aisle) if ydir < 0 else
                                        box(xe0, y, xe1, sy1 + 1)).intersection(g_site)
                            corridor = corridor.difference(g_fp).difference(g_obst)
                            piece = next((p for p in parts(corridor) if p.distance(aisle_poly) <= EPS), None)
                            if piece is None:
                                continue
                            # trim the corridor at the road: keep the part of the strip between the aisle and the road edge
                            road_hits = [p for p in parts(piece) if p.distance(road_union) <= 0.05]
                            if not road_hits:
                                continue
                            piece = road_hits[0]
                            if not g_ground_b.covers(piece.difference(aisle_poly)):
                                continue
                            entrance = piece
                            break
                    if entrance is None:
                        continue
                    # 제6조제1항제1호 (제11조제1항이 부설주차장에 준용): "출구와 입구에서 자동차의 회전을
                    # 쉽게 하기 위하여 ... 차로와 도로가 접하는 부분을 곡선형으로 하여야 한다."  The statute
                    # names no radius, so the flare is taken from the declared vehicle's turning radius;
                    # with none declared the junction stays square and the validator says so.
                    if turn_radius_m:
                        flare = entrance.buffer(float(turn_radius_m), join_style=1, quad_segs=16)
                        flare = flare.intersection(g_ground).intersection(
                            entrance.buffer(float(turn_radius_m)).difference(entrance).buffer(0))
                        near_road = flare.intersection(road_reach)
                        if not near_road.is_empty:
                            entrance = unary_union([entrance, near_road]).buffer(0)
                    # 차량출입불허구간: a vehicle entrance may not touch a prohibited interval. Ramp portals
                    # avoid it by construction from the permitted frontage; the surface connector is
                    # a parcel-edge strip and has to be checked outright.
                    if g_prohibited is not None and entrance.distance(g_prohibited) <= 0.05:
                        continue
                    drive = unary_union([aisle_poly, entrance])
                    turn_bay = None
                    # one entry per ramp the position can carry; a surface-only plan carries none and
                    # runs the tail once with no ramp, no plate and only the site's own obstacles
                    ramp_variants = [] if ramp is not None else [(None, None, g_obst)]
                    if ramp is not None:
                        best = {}
                        xs = ax0 + aisle if end == 0 else ax0
                        # The at-the-aisle-end ramps are a function of the aisle, not of xs: build
                        # them once instead of rebuilding the same arcs at every step of the sweep.
                        # in line with the aisle first: that is the arrangement practice draws
                        fixed_builds = ([_inline_at_aisle_end(xs, y, aisle, xdir, ramp, ax0, ax1) for xdir in (1, -1)]
                                        if want_straight else [])
                        if curved is not None and want_curved:
                            fixed_builds += [_curved_at_aisle_end(y, aisle, xdir, hand, curved, curve_min_radius, ax0, ax1)
                                             for xdir in (1, -1) for hand in (1, -1)]
                        fixed_builds = [b for b in fixed_builds if b is not None]
                        while xs + ramp["width_m"] <= ax1 + EPS:
                            # they are re-SCORED at every xs as before (the `far` term reads xs);
                            # only the construction is hoisted, so the winner cannot change
                            builds = list(fixed_builds)
                            for ydir in (1, -1):
                                if want_straight:
                                    builds.append(_straight_off_aisle(xs, y, aisle, ydir, ramp))
                                if curved is not None and want_curved:
                                    for hand in (1, -1):
                                        builds.append(_curved_off_aisle(xs, y, aisle, ydir, hand, curved, curve_min_radius))
                            for built in builds:
                                if built is None:
                                    _drops["not_built"] = _drops.get("not_built", 0) + 1
                                    continue
                                poly, upper, lower, center, spec, radius = built
                                open_part = poly.difference(g_fp)
                                if not g_site_b.covers(poly):
                                    _drops["outside_site"] = _drops.get("outside_site", 0) + 1
                                    continue
                                if poly.intersection(g_obst).area > EPS:
                                    _drops["hits_obstacle"] = _drops.get("hits_obstacle", 0) + 1
                                    continue
                                if not g_ground_b.covers(open_part):
                                    _drops["off_open_ground"] = _drops.get("off_open_ground", 0) + 1
                                    continue
                                if poly.intersection(entrance).area > EPS:
                                    _drops["hits_entrance"] = _drops.get("hits_entrance", 0) + 1
                                    continue
                                # The upper landing is flat drive AT GRADE - a car stands on it before it
                                # starts down - so it cannot lie under the building. The sloping body may
                                # (it is already below the slab), which is what `share_under_footprint`
                                # measures. Practice comes off the road, crosses the yard and goes down
                                # without threading the mass; a landing under the footprint is the drive
                                # that `drive_obstructions:0` then rejects.
                                if not g_fp.is_empty and upper.intersection(g_fp).area > EPS:
                                    _drops["landing_under_building"] = _drops.get("landing_under_building", 0) + 1
                                    continue
                                if accept_ramp is not None and not accept_ramp(unrot(poly)):
                                    _drops["rejected_by_caller"] = _drops.get("rejected_by_caller", 0) + 1
                                    continue
                                under = poly.intersection(g_fp).area / poly.area if not g_fp.is_empty else 0.0
                                beside = 1.0 if (poly.distance(g_fp) <= 1.0 and under < 0.2) else 0.0
                                far = abs(xs - (ax0 if end == 0 else ax1)) / max(ax1 - ax0, 1.0)  # 0 at the entrance end, 1 at the far end
                                key = W["w_beside"] * beside + W["w_under"] * under + W["w_far"] * far
                                # ONE WINNER PER SHAPE, not one winner. This key knows only where the
                                # ramp sits (beside the plate / under it / far from the entrance); it
                                # cannot see the excavation or the area per stall that follow from the
                                # choice. Collapsing to a single ramp here decided the shape before
                                # anything measured it, and on 고산 that is why `auto` returned a
                                # straight ramp while the same parcel's curved scheme dug 657 m2 less
                                # (1,843 vs 2,500) and carried its cars at 61.4/57.6 m2 instead of
                                # 64.1/108.7. Both shapes are now emitted as candidates and the
                                # planner's own ranking - which does measure the plate - decides.
                                shape_key = "curved" if radius else "straight"
                                if best.get(shape_key) is None or key > best[shape_key][0] + 1e-9:
                                    best[shape_key] = (key, poly, upper, lower, center, under, beside, far, spec, radius)
                            xs += stall_w
                        if not best:
                            continue
                        for ramp_key, poly, upper, lower, center, under, beside, far, used, radius in best.values():
                            ramp_geom = {"polygon": poly, "upper_landing": upper, "lower_landing": lower, "centerline": center,
                                         "profile": used["profile"], "width_m": used["width_m"], "length_m": used["length_m"],
                                         "share_under_footprint": round(under, 3), "beside_plate": bool(beside), "far_from_entrance": round(far, 2),
                                         "orientation": "off_aisle", "shape": "curved" if radius else "straight",
                                         "radius_m": radius, "inner_radius_m": (radius - used["width_m"] / 2) if radius else None}
                            hull = unary_union([g_fp, poly]).convex_hull if not g_fp.is_empty else poly.buffer(aisle)
                            ramp_variants.append((ramp_geom,
                                                  hull.intersection(g_site).buffer(0),  # the plate + ramp, clipped to the parcel
                                                  unary_union([g_obst, poly])))
                    for ramp_geom, basement, blocked in ramp_variants:
                        stalls = []
                        # The entrance end is kept clear of bays - except on a direct field shorter than
                        # two aisle widths, where that end IS the field: the car turns into the bay off
                        # the aisle it entered by, and holding it back left a two-bay lot with none.
                        short_direct = direct and (ax1 - ax0) < 2 * aisle - EPS
                        xs0, xs1 = (ax0 + aisle, ax1) if (not short_direct and end == 0 and entrance.intersection(box(ax0, y, ax0 + aisle, y + aisle)).area > EPS) else (ax0, ax1)
                        if not short_direct and end == 1 and entrance.intersection(box(ax1 - aisle, y, ax1, y + aisle)).area > EPS:
                            xs1 = ax1 - aisle
                        # A closed aisle end has to be turned in, not reversed out of.  Practice holds the
                        # rows back there (고산 ALT1 leaves its south row empty for 16.6 m at the closed end,
                        # which is what lets a 5.6 m circle fit): with the rows held back for `bay`, the
                        # drivable field is aisle + both row depths wide, so a disc of `turn_radius_m` fits
                        # when 2R <= that width and 2R <= bay.
                        if bay:
                            if end == 0:            # entrance at ax0, so the closed end is ax1
                                xs1 = max(xs0, xs1 - bay)
                            else:
                                xs0 = min(xs1, xs0 + bay)
                        expanded_dims = ((float(rules["expanded_width_m"]), float(rules["expanded_length_m"]))
                                         if rules.get("expanded_min_share") and rules.get("expanded_width_m") and rules.get("expanded_length_m") else None)
                        want_expanded = (int(expanded_needed) if expanded_needed is not None
                                         else int(math.ceil(float(rules["expanded_min_share"]) * required)) if expanded_dims and required else 0)
                        # the 확장형 belong at the closed end (see _fill_row); with the entrance at ax0 that is
                        # the high-x end, so reserve the last stalls there for them
                        exp_w = expanded_dims[0] if expanded_dims else stall_w
                        # one stall of slack: the greedy scan mixes 2.5 and 2.6 m widths, so a zone sized
                        # exactly to want_expanded * 2.6 loses a slot to alignment
                        exp_from = (xs1 - (want_expanded * exp_w + stall_w)) if (want_expanded and end == 0) else None
                        for side in ((-1, 1) if ground_stalls else ()):  # a basement-only plan keeps the ground clear
                            stalls += _fill_row(g_ground, drive, y, y + aisle, xs0, xs1, stall_w, stall_l, acc_w, acc_l,
                                                max(0, accessible - sum(s["type"] == "accessible" for s in stalls)), blocked, side,
                                                expanded=expanded_dims, want_expanded=want_expanded,
                                                n_expanded_start=sum(s["type"] == "expanded" for s in stalls),
                                                expanded_from=exp_from)
                        if bay:
                            # the held-back strip is drivable: it is where the turn happens
                            x0b, x1b = (xs1, ax1) if end == 0 else (ax0, xs0)
                            turn_bay = box(x0b, y - stall_l, x1b, y + aisle + stall_l).intersection(g_ground)
                            if ramp_geom is not None:
                                turn_bay = turn_bay.difference(ramp_geom["polygon"])
                            turn_bay = turn_bay.difference(g_obst).difference(g_fp)
                            if not turn_bay.is_empty:
                                drive = unary_union([drive, turn_bay])
                        if ramp_geom is not None:
                            stalls = [s for s in stalls if s["polygon"].intersection(ramp_geom["polygon"]).area <= EPS
                                      and s["polygon"].intersection(ramp_geom["upper_landing"]).area <= EPS]
                        # Trim the aisle to what it actually serves.  An aisle only earns its area where a
                        # stall faces it: practice runs 50.9 m of aisle for 30 stalls (0.59 per metre) and
                        # a run that carries stalls for only half its length is the difference between
                        # 21.5 and 28.2 m2 per stall.  Keep the entrance end so the drive still meets the road.
                        if stalls:
                            sx0 = min(st["polygon"].bounds[0] for st in stalls)
                            sx1 = max(st["polygon"].bounds[2] for st in stalls)
                            keep0 = ax0 if end == 0 else min(sx0, ax0 + aisle)
                            keep1 = ax1 if end == 1 else max(sx1, ax1 - aisle)
                            keep0, keep1 = min(keep0, sx0), max(keep1, sx1)
                            if keep1 - keep0 > aisle:
                                trimmed = aisle_poly.intersection(box(keep0, y - EPS, keep1, y + aisle + EPS))
                                if not trimmed.is_empty:
                                    drive = unary_union([trimmed, entrance] + ([turn_bay] if turn_bay is not None and not turn_bay.is_empty else []))
                                    if ramp_geom is not None:
                                        drive = unary_union([drive, ramp_geom["upper_landing"]])
                        ent_c = entrance.centroid
                        parallel = min(abs(angle - _angle(longest_road)), 180 - abs(angle - _angle(longest_road))) < 5.0

                        def emit(cand_stalls, cand_drive, bands, cross_aisles, dead_end, aisle_span):
                            # accessible stalls closest to the entrance first, then 확장형 (inside the quota), then by distance
                            cand_stalls = sorted(cand_stalls, key=lambda s: (s["type"] != "accessible", s["type"] != "expanded",
                                                                             s["polygon"].distance(ent_c)))
                            if required:
                                if preserve_banks:
                                    from backend.app.modules.design.generation.maas.masterplan.stall_banks import select_complete_banks
                                    cand_stalls=select_complete_banks(cand_stalls,required)
                                else:
                                    cand_stalls = cand_stalls[:required]
                            if not cand_stalls and (ground_stalls or ramp_geom is None):
                                return
                            # The objective keeps measuring the distance to the vehicle entrance,
                            # because its weight was calibrated against that quantity: re-pointing it
                            # at the building (which is what 편의증진법 제3조's 최단거리 is about) made
                            # the engine trade 13 surface stalls and 475 m2 of extra dig to pull two
                            # stalls 2 m closer. Where the accessible stalls sit within a row is now
                            # Where they end up relative to the BUILDING is reported instead, by
                            # masterplanagent.validation.accessible_placement, rather than priced
                            # here - see _fill_row's docstring for what re-pointing this cost.
                            acc_d = [s["polygon"].distance(ent_c) for s in cand_stalls if s["type"] == "accessible"]
                            adj_pairs = _adjacent_pairs([s["polygon"] for s in cand_stalls], 0.05)
                            # A loop needs two crossovers to close; with fewer, the offset test can
                            # only ever return None, and it is the most expensive thing in this
                            # innermost block. Skipping it there is exact, not an approximation.
                            loop = None
                            if cross_aisles >= 2:
                                from backend.app.modules.design.generation.maas.masterplan.circulation import closed_aisle_loop as _loop
                                loop = _loop(cand_drive, aisle)
                            # 진입점: where the car comes off the road, and how far it travels at grade
                            # before it starts down. Practice crosses the yard and descends; a long
                            # approach is pavement and a pedestrian conflict, so it is measured and
                            # reported whether or not it is scored.
                            approach = (ramp_geom["upper_landing"].distance(road_union)
                                        if ramp_geom is not None and not road_union.is_empty else None)
                            terms = {"stalls": len(cand_stalls), "aisle_length_m": round(aisle_span, 1),
                                     "closed_aisle_loop": loop is not None,
                                     "loop_length_m": round(loop.length, 1) if loop is not None else None,
                                     "ramp_approach_from_road_m": round(approach, 1) if approach is not None else None,
                                     "accessible_mean_distance_m": round(sum(acc_d) / len(acc_d), 1) if acc_d else 0.0,
                                     "parallel_to_longest_road_edge": parallel,
                                     "bands": bands, "cross_aisles": cross_aisles, "dead_end_stalls": dead_end,
                                     "adjacent_pairs": adj_pairs,
                                     "ramp_under_plate_share": ramp_geom["share_under_footprint"] if ramp_geom else None,
                                     "ramp_beside_plate": ramp_geom["beside_plate"] if ramp_geom else None,
                                     "ramp_far_from_entrance": ramp_geom["far_from_entrance"] if ramp_geom else None}
                            score = (len(cand_stalls) - W["w_aisle"] * aisle_span - W["w_access"] * terms["accessible_mean_distance_m"]
                                     + (W["w_edge"] if parallel else 0.0)
                                     + W.get("w_cluster", 0.02) * adj_pairs
                                     + (W.get("w_loop", 1.5) if terms["closed_aisle_loop"] else 0.0)
                                     - W.get("w_dead_end", 0.25) * max(0, dead_end - 6)
                                     + ((W["w_under"] * terms["ramp_under_plate_share"] + W["w_beside"] * (1.0 if terms["ramp_beside_plate"] else 0.0)
                                         + W["w_far"] * terms["ramp_far_from_entrance"]) if ramp_geom else 0.0))
                            results.append({"angle_deg": round(angle, 2), "entrance_end": end, "score": round(score, 3), "terms": terms,
                                            "stalls": [{**s, "polygon": unrot(s["polygon"]), "front": unrot(s["front"])} for s in cand_stalls],
                                            "drive": unrot(cand_drive), "entrance": unrot(entrance), "aisle_length_m": round(aisle_span, 2),
                                            # `dead_end_stalls` lived only inside `terms`, so every consumer that
                                            # reads the plan dict - `solve_basement_level.clean()` above all - dropped
                                            # it, `add_parking` left it off the aisle feature, and the validator
                                            # skipped `dead_end_run` for EVERY basement level: the exact levels
                                            # IStructE 4.4 is about had no dead-end measurement at all.
                                            "bands": bands, "cross_aisles": cross_aisles, "dead_end_stalls": dead_end,
                                            "provided": len(cand_stalls), "accessible": sum(s["type"] == "accessible" for s in cand_stalls),
                                            "ramp": ({**ramp_geom, "polygon": unrot(ramp_geom["polygon"]), "upper_landing": unrot(ramp_geom["upper_landing"]),
                                                      "lower_landing": unrot(ramp_geom["lower_landing"]), "centerline": unrot(ramp_geom["centerline"])}
                                                     if ramp_geom else None),
                                            "basement": unrot(basement) if basement is not None else None})

                        if field in ("auto", "single", "ring"):
                            # the one-band plan is the last resort under `ring` too; the sort demotes it
                            emit(stalls, drive, 1, 0, int((xs1 - xs0) // stall_w), ax1 - ax0)

                        # The same plate, tiled in whole modules.  A plate quantised to n modules that
                        # carries one band is the categorical loss the canon names; both the comb (one
                        # cross aisle) and the ring (two) are generated and the objective picks.
                        # `ring` means the loop is PREFERRED, not mandatory: the comb is still built so a
                        # plate that cannot take a loop yields a level instead of nothing, and the sort
                        # below puts any loop ahead of any comb. Making the loop compulsory emptied every
                        # slab too small to close one.
                        rings = {"auto": (False, True), "comb": (False,), "ring": (True, False),
                                 "single": ()}[field]
                        # The tiling puts bands at y + k*module for every k that fits, so an offset one
                        # whole module further along generates the SAME family of layouts.  Sweeping the
                        # full plate depth therefore re-derives each tiling once per module for nothing:
                        # one module pitch of offsets covers them all.
                        if y - (miny + stall_l) >= (2 * stall_l + aisle) - EPS:
                            rings = ()
                        for ring in rings:
                            tiled = _tile_bands(g_ground, blocked, y, aisle, stall_w, stall_l, acc_w, acc_l,
                                                ax0, ax1, end, entrance, int(accessible), expanded_dims,
                                                want_expanded, ring=ring,
                                                # the repair path exists but nothing switched it on:
                                                # a requested loop must be allowed to move its cross
                                                # aisles before it is given up on
                                                repair_ring=(field == "ring"), ground_stalls=ground_stalls)
                            if tiled is None:
                                continue
                            if ramp_geom is not None:
                                tiled["stalls"] = [st for st in tiled["stalls"]
                                                   if st["polygon"].intersection(ramp_geom["polygon"]).area <= EPS
                                                   and st["polygon"].intersection(ramp_geom["upper_landing"]).area <= EPS]
                                tiled["drive"] = unary_union([tiled["drive"], ramp_geom["upper_landing"]]).buffer(0)
                            emit(tiled["stalls"], tiled["drive"], tiled["bands"], tiled["cross_aisles"],
                                 tiled["dead_end_stalls"], tiled["aisle_span_m"])
    import os as _os
    if _os.environ.get("MASTERPLAN_EXPLAIN_RANK") and ramp is not None:
        import sys as _sys
        print("RAMP-BUILDS results=%d drops=%s" % (len(results), _drops), file=_sys.stderr)
    if field == "ring":
        results.sort(key=lambda r: (r["terms"].get("closed_aisle_loop", False), r["score"]), reverse=True)
    else:
        results.sort(key=lambda r: -r["score"])
    # keep the best per (angle, entrance_end, ramp, bands, cross aisles) so alternatives differ
    # in kind, not by 0.5 m - the band count is a kind, so a tiled plan is never crowded out
    # of the list by a one-band plan that scored better at some other offset
    seen, out = set(), []
    for r in results:
        # THE RAMP SHAPE IS A KIND. Without it in this key, the straight and curved variants of the
        # same position collapse into one and the sort - which rewards a run beside the plate - keeps
        # the straight one, so emitting both shapes above achieved nothing and the planner still never
        # saw a turning ramp. The shape changes the dig and the area per stall, which is exactly the
        # kind of difference this list exists to carry.
        key = (r["angle_deg"], r["entrance_end"], r["ramp"] is not None,
               (r["ramp"] or {}).get("shape"), r["bands"], r["cross_aisles"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    # A CLOSED AISLE GRAPH MUST SURVIVE TRUNCATION. The objective penalises aisle length, and a loop
    # always runs more aisle than the comb it beats, so the loop sorts last on score and `limit` cut
    # it out of the list entirely - the caller then chose between combs and never saw a loop. That,
    # not the ranking philosophy, is why the basement default laid dead-end combs while `ring`,
    # asked for by name, carried a whole level in one floor.
    #
    # Keeping it is not the same as preferring it: a loop spends its return leg on pavement and on a
    # dense plate a comb legitimately carries more cars. So the best loop is put IN FRONT of the
    # caller and the caller's own ranking decides. IStructE 3.2.6/4.4 is the reason it deserves a
    # reserved seat: a driver who misses a space should be able to come round again.
    # It must be the BIGGEST loop, and "a loop is already in the list" is not good enough: score
    # penalises aisle length, so the loops that survive on score are the SHORTEST ones - two-band
    # stubs carrying a handful of cars, which can never win on stalls and so change nothing. The
    # loop that matters is the one that carries the level.
    loop = max((r for r in results if r["terms"].get("closed_aisle_loop")),
               key=lambda r: (r["provided"], r["score"]), default=None)
    if loop is None:
        loop = max((r for r in results if r["cross_aisles"] >= 2),
                   key=lambda r: (r["provided"], r["score"]), default=None)
    if out and loop is not None and loop not in out:
        if len(out) >= limit:
            out[-1] = loop
        else:
            out.append(loop)
    for r in out:
        r["search_count"] = search_count
    return out


__all__ = ["WEIGHTS", "orientation_candidates", "row_candidates"]

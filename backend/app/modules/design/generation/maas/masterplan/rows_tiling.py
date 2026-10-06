"""Stall rows along an aisle and whole-module band tilings for `rows.row_candidates`."""
from __future__ import annotations

import math

from shapely import from_wkb, prepare
from shapely.geometry import box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts


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

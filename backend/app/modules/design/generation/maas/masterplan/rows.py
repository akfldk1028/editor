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
from shapely import STRtree, box, from_wkb, prepare
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring, unary_union

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts
from backend.app.modules.design.generation.maas.masterplan.row_access import straight_row_entrance
from backend.app.modules.design.generation.maas.masterplan.rows_orientation import _angle, _lines, _segments, orientation_candidates
from backend.app.modules.design.generation.maas.masterplan.rows_ramps import (
    _curved_at_aisle_end, _curved_off_aisle, _curved_ramp, _graded_centerline, _inline_at_aisle_end,
    _straight_off_aisle)
from backend.app.modules.design.generation.maas.masterplan.rows_search import _adjacent_pairs, _band_offsets
from backend.app.modules.design.generation.maas.masterplan.rows_tiling import _fill_row, _tile_bands, _tile_bands_at

# w_beside: the ramp runs beside the plate (touching, mostly outside it) so the basement floor under the
# plate stays whole and the ramp uses the yard - the practice arrangement (Alt1: ramp along the building's
# west face). w_far: the ramp leaves the aisle at the end away from the entrance, so entering cars pass the
# surface rows first. w_under kept for reference, off by default.
# Loop geometry is measured and retained as an alternative; only an explicit
# weight or requested ring family prefers it. No automatic topology bonus.
WEIGHTS = {"w_aisle": 0.08, "w_access": 0.05, "w_edge": 3.0, "w_under": 0.0, "w_beside": 4.0, "w_far": 3.0, "w_open": 0.0, "w_cluster": 0.02}


LARGE_ENVELOPE_M2 = 10_000.0   # the line bounded_packing draws between the small and large search
BOUNDED_OFFSETS = 32           # band offsets per orientation on a large envelope (search effort, not design)
SEARCH_BUDGET = 384            # band offsets across all orientations on a large envelope


def row_candidates(site, ground, footprint, obstacles, frontage, front, rules, required, accessible, *,
                   ramp=None, curved=None, curve_min_radius=None, weights=None, step=0.5, limit=14,
                   expanded_needed=None, ground_stalls=True, turn_radius_m=None, turn_lane_m=None,
                   field="auto", occupied_footprint=None, accept_ramp=None, ramp_shape="any", allowed_angles=None,
                   preserve_banks=False, straight_entry=False, prohibited=None, stall_exclusion=None,
                   demand_from_entrance=False, entry_clearance_m=None,
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
    if entry_clearance_m is not None:
        from .geometry import number
        entry_clearance_m = number(entry_clearance_m, 'entry clearance')
    source_lines = [frontage] if isinstance(frontage, LineString) else list(frontage.geoms)
    corners = [Point(line.coords[i]) for line in source_lines for i in (0, -1)]
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
        # The enclosed ground floor. Under a piloti (authored ground footprint smaller than the
        # footprint) the aisle, its road connector and an at-grade landing may pass beneath the
        # upper floors; only the enclosed part blocks them. Without one it is the footprint.
        g_occ = g_fp if occupied_footprint is None else rot(occupied_footprint)
        # Drivable but not for bays: a basement level's ramp landings. The level solver keeps them
        # in the free area so the aisle can reach them and dropped the bays laid on them afterwards;
        # with the kept set clustered at the landing (`emit`) that cost 고산 B1 its 20th bay.
        g_excl = (unary_union([g_obst, rot(stall_exclusion)]).buffer(0)
                  if stall_exclusion is not None and not stall_exclusion.is_empty else g_obst)
        if not g_occ.is_valid:
            g_occ = g_occ.buffer(0)
        if g_ground.is_empty or not g_ground.is_valid:
            continue
        g_roads = [rot(s) for s in road_segs]
        g_corners = [rot(p) for p in corners] if entry_clearance_m is not None else []
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
                            corridor = corridor.difference(g_occ).difference(g_obst)
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
                    if any(entrance.distance(p) < entry_clearance_m - EPS for p in g_corners):
                        continue
                    drive = unary_union([aisle_poly, entrance])
                    turn_bay = None
                    # one entry per ramp the position can carry; a surface-only plan carries none and
                    # runs the tail once with no ramp, no plate and only the site's own obstacles
                    ramp_variants = [] if ramp is not None else [(None, None, g_excl)]
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
                                open_part = poly.difference(g_occ)
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
                                if not g_occ.is_empty and upper.intersection(g_occ).area > EPS:
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
                                                  unary_union([g_excl, poly])))
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
                        # The rows carry the whole plate and the demand decides what is kept (`emit`), so
                        # the closed end of the 확장형 zone is the closed end of the DEMAND, not of the
                        # plate. Measured on 고산 B1 at 20 of 28: the zone sat at the far end of a 62 m
                        # aisle, the nearest standard bays were taken from the near end, and the kept set
                        # spanned the whole corridor - 14 bays on one side, 6 at the far end of the other.
                        # The per-row demand is an estimate; the fill still runs to the end of the plate.
                        demand_end = None
                        if required and ground_stalls and 2 * int((xs1 - xs0) // stall_w) > required:
                            per_row = math.ceil(required / 2)
                            need = (per_row * stall_w + min(want_expanded, per_row) * max(0.0, exp_w - stall_w)
                                    + min(int(accessible), per_row) * max(0.0, acc_w - stall_w) + stall_w)
                            if xs1 - xs0 > need:
                                demand_end = xs0 + need if end == 0 else xs1 - need
                        if want_expanded and end == 0:
                            exp_from = (demand_end if demand_end is not None else xs1) - (want_expanded * exp_w + stall_w)
                        elif want_expanded and demand_end is not None:
                            exp_from = demand_end
                        else:
                            exp_from = None
                        def fill(x_from):
                            out = []
                            for side in ((-1, 1) if ground_stalls else ()):  # a basement-only plan keeps the ground clear
                                out += _fill_row(g_ground, drive, y, y + aisle, x_from, xs1, stall_w, stall_l, acc_w, acc_l,
                                                 max(0, accessible - sum(s["type"] == "accessible" for s in out)), blocked, side,
                                                 expanded=expanded_dims, want_expanded=want_expanded,
                                                 n_expanded_start=sum(s["type"] == "expanded" for s in out),
                                                 expanded_from=exp_from)
                            return out
                        stalls = fill(xs0)
                        if demand_from_entrance and demand_end is not None and end == 1 and stalls:
                            # Accessible bays are seated at the row START (see _fill_row), which for an
                            # entrance at ax1 is the far closed end, so the kept set would span the whole
                            # plate whatever `emit` trims. Refill from the demand's closed end when the
                            # rows already hold the demand inside that span: nothing is lost, the bays move.
                            # Only the basement level asks for this: on the ground the rows' closed end is
                            # where the ramp attaches, and moving the bays away from it lost the attachment
                            # (고산 5 m piloti variant: 30 + 20 became 0 + 50).
                            if sum(s["polygon"].bounds[0] >= demand_end - EPS for s in stalls) >= required:
                                stalls = fill(demand_end)
                        if bay:
                            # the held-back strip is drivable: it is where the turn happens
                            x0b, x1b = (xs1, ax1) if end == 0 else (ax0, xs0)
                            turn_bay = box(x0b, y - stall_l, x1b, y + aisle + stall_l).intersection(g_ground)
                            if ramp_geom is not None:
                                turn_bay = turn_bay.difference(ramp_geom["polygon"])
                            turn_bay = turn_bay.difference(g_obst).difference(g_occ)
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
                            n_offered = len(cand_stalls)
                            if required:
                                if preserve_banks:
                                    from backend.app.modules.design.generation.maas.masterplan.stall_banks import select_complete_banks
                                    cand_stalls=select_complete_banks(cand_stalls,required)
                                else:
                                    cand_stalls = cand_stalls[:required]
                                if 0 < len(cand_stalls) < n_offered and ramp_geom is None:
                                    # The aisle follows the kept bays. The trim above saw every bay the plate
                                    # could hold, so a level that keeps 20 of 28 kept the 28-bay corridor.
                                    # Keep the entrance end and one aisle width past the last kept bay; a
                                    # cross-aisle plan the cut would sever keeps its drive.
                                    from backend.app.modules.design.generation.maas.masterplan.circulation import full_width_stall_access
                                    sx0 = min(s["polygon"].bounds[0] for s in cand_stalls)
                                    sx1 = max(s["polygon"].bounds[2] for s in cand_stalls)
                                    # the closed end keeps the larger of an aisle width and the turning
                                    # field the rows were held back for (`bay`, from turn_radius_m)
                                    room = max(aisle, bay or 0.0)
                                    k0 = ax0 if end == 0 else max(ax0, sx0 - room)
                                    k1 = ax1 if end == 1 else min(ax1, sx1 + room)
                                    if k1 - k0 < aisle_span - EPS:
                                        _, b1, _, b3 = cand_drive.bounds
                                        cut = unary_union([cand_drive.intersection(box(k0, b1 - EPS, k1, b3 + EPS)), entrance]).buffer(0)
                                        # the cut can leave a turn-bay fragment on the far side of the box
                                        # edge; only what still touches the entrance is the drive
                                        cut = unary_union([g for g in parts(cut) if g.intersects(entrance.buffer(EPS))])
                                        if full_width_stall_access(cut, [s["polygon"] for s in cand_stalls], [entrance], aisle):
                                            cand_drive, aisle_span = cut, k1 - k0
                                            dead_end = min(dead_end, int((k1 - k0) // stall_w))
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
                                     + (W.get("w_loop", 0.0) if terms["closed_aisle_loop"] else 0.0)
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
    # THE DEMAND COMES BEFORE THE SCORE, as in `parking_modules` and `planning_rank`. The score
    # prices a metre of aisle against a bay; once the aisle follows the kept bays (`emit`), a plan
    # that offers 19 of the 20 asked for can out-score the one that offers 20 by running a little
    # shorter, and the per-kind cut below would then hide the 20 from the planner for good.
    # Measured on 고산 B1 at 20: 19 standard bays on a 318 m2 drive beat 20.
    demand = lambda r: min(r["provided"], required) if required else r["provided"]
    if field == "ring":
        results.sort(key=lambda r: (r["terms"].get("closed_aisle_loop", False), demand(r), r["score"]), reverse=True)
    else:
        results.sort(key=lambda r: (-demand(r), -r["score"]))
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
    if rules.get('parking_mix') == 'parallel_infill' and ground_stalls:
        from .parallel_parking import infill
        for r in out:
            host = ground
            if obstacles is not None:
                host = host.difference(obstacles)
            if r.get('ramp'):
                host = host.difference(r['ramp']['polygon'])
            r['stalls'] = infill(host, r['drive'], r['stalls'], required or len(r['stalls']), aisle_width=aisle)
            r['provided'] = len(r['stalls'])
            r['terms']['stalls'] = r['provided']
            r['terms']['parallel_stalls'] = sum(s['type'] == 'standard_parallel' for s in r['stalls'])
    return out


__all__ = ["WEIGHTS", "orientation_candidates", "row_candidates"]

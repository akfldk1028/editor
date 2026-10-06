"""Tracked BOOK delivery helper extracted unchanged from the legacy owner tools.

No registry discovery, jury scheduling, or runtime CLI import belongs here.
"""
from pathlib import Path
from backend.app.modules.design.generation.maas.delivered.book_records import records_of
from backend.app.modules.design.generation.maas.delivered.book_floors import delivered_floor_evidence
from backend.app.modules.design.generation.maas.delivered.book_identity import shape_id, seat_certificate

BOOK_FAR_SHARE = 0.8
BOOK_GROUND_SHARE = 0.75


def _resolve_facing(facing, site, height_m, *, road_direction):
    """Execute road alignment; validate the nearest side of legal setback.

    north_side retains the sentence contract's sunlight-setback meaning.
    An oblique frontage does not require two exact cardinal alignments.
    Absent directional legal evidence is explicitly an unverified preference.
    """
    from math import atan2, cos, degrees, hypot, radians, sin
    sides = {'east': (1., 0.), 'north': (0., 1.),
             'west': (-1., 0.), 'south': (0., -1.)}
    if not isinstance(facing, dict) or facing.get('access_side') not in sides:
        raise ValueError('facing.access_side must name a program cardinal side')
    north = facing.get('north_side')
    if north is not None and north not in sides:
        raise ValueError('facing.north_side must name a program cardinal side')
    if not road_direction or hypot(*road_direction) < 1e-9:
        raise ValueError('authored facing requires site access direction evidence')
    local = sides[facing['access_side']]
    angle = degrees(atan2(road_direction[1], road_direction[0]) - atan2(local[1], local[0]))
    evidence = {'requested_angle_deg': angle, 'access_status': 'aligned',
                'north_side': north, 'north_status': 'not_requested'}
    if north is not None:
        evidence['north_status'] = 'unverified_preference_no_directional_setback'
        if site is not None and hasattr(site, 'plan_at') and height_m > 0:
            ground, top = site.plan_at(0.), site.plan_at(height_m)
            cut = ground.difference(top) if ground is not None and top is not None else None
            if cut is not None and not cut.is_empty and cut.area > 1.:
                dx, dy = cut.centroid.x - ground.centroid.x, cut.centroid.y - ground.centroid.y
                if hypot(dx, dy) > 1e-9:
                    c, t = cos(radians(angle)), sin(radians(angle))
                    # Invert the requested placement into the program frame.
                    lx, ly = c * dx + t * dy, -t * dx + c * dy
                    scores = {name: x * lx + y * ly for name, (x, y) in sides.items()}
                    if scores[north] < max(scores.values()) - 1e-8:
                        raise ValueError('facing.north_side contradicts access-aligned legal setback direction')
                    evidence.update(north_status='verified_nearest_side',
                                    setback_direction_world_xy=[dx, dy])
    return angle, evidence


def _to_parcel_size(footprint_m2: float, gross_m2: float, height_m: float,
                    site, *, storey_m=None) -> tuple[float, float]:
    """The book's figure at this parcel's size: (plan area, height).

    This proposes a similarity budget, not the executed placement. The bridge
    may fit XY independently; delivered_floor_evidence measures actual areas.
    """

    if site is None or footprint_m2 <= 1e-6 or gross_m2 <= 1e-6 or height_m <= 1e-6:
        return footprint_m2, height_m
    target = float(site.far_capacity_m2) * BOOK_FAR_SHARE
    scale = (target / gross_m2) ** 0.5
    ground_cap = float(site.ground_capacity_m2) * BOOK_GROUND_SHARE
    if footprint_m2 * scale * scale > ground_cap:
        scale = (ground_cap / footprint_m2) ** 0.5
    # A book taller than the parcel's own legal section is not this parcel's
    # building; the envelope would cut it to one anyway, and cutting is what
    # made these read as fragments in the first place.
    ceiling = float(site.floor_height_m) * max(
        1.0, float(site.far_capacity_m2) / max(float(site.ground_capacity_m2), 1.0)) * 2.0
    if height_m * scale > ceiling:
        scale = ceiling / height_m
    return footprint_m2 * scale * scale, height_m * scale


def scaled_book_metrics(gross_m2, storey_m, floor_count, scale):
    """Retain the floor schedule under uniform similarity, including downsizing."""
    return {'floor_area_m2': float(gross_m2) * float(scale) ** 2,
            'book_storey_height_m': float(storey_m) * scale if storey_m is not None else None,
            'book_floor_count': floor_count}


def _compile_record(rec: dict, buildable, site=None):
    """One book record -> SourceMass, the book's figure at this parcel's size.

    The single path the stage and the board's baker share, so a seated
    book mass is rebuilt exactly as it was judged. Returns (source, entry)
    or (None, reason); `entry` is what the registry records about it.
    """

    from dataclasses import replace  # noqa: E402
    from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram  # noqa: E402
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import compile_geometry_program_to_source_mass

    art = rec.get("geometry_artifact") or {}
    payload = art.get("authoredGeometryProgram") or art.get("geometryProgram")
    if not payload:
        return None, "no geometry program"
    metrics = ((art.get("hardGates") or {}).get("projectedMetrics") or {})
    storeys = art.get('storeyEvidence') or {}
    floor_count = storeys.get('storey_count') or metrics.get('floor_count')
    if floor_count is None and storeys.get('actual_floor_areas_m2'):
        floor_count = len(storeys['actual_floor_areas_m2'])
    storey_m = storeys.get('typical_storey_height_m') or metrics.get('floor_height_m')
    footprint_m2 = float(metrics.get("footprint_area_m2") or 0.0)
    book_gross_m2 = float(metrics.get("floor_area_m2") or 0.0)
    book_height_m = float(
        (art.get("projectedVisualCertificate") or {}).get("physical_height_m")
        or metrics.get("height_m") or 0.0)
    # The figure is the book's, the size is the parcel's.
    from backend.app.modules.design.generation.maas.book_development import exact_dimensions
    from math import isclose
    from backend.app.modules.design.generation.maas.dimensional_intent import program_intent, POLICY
    try:
        intent = program_intent(payload)
        exact = exact_dimensions(payload)
        if intent is not None and exact is not None:
            raise ValueError("dimensional intent cannot override exact development")
        if exact is not None:
            if str(getattr(site, 'pnu', '')) != exact['site_pnu']:
                raise ValueError('exact development parcel frame mismatch')
            if (floor_count != exact['storey_count']
                    or not isclose(float(storey_m or 0), exact['storey_height_m'], rel_tol=1e-8)
                    or not isclose(book_height_m, exact['height_m'], rel_tol=1e-8, abs_tol=1e-5)
                    or not isclose(book_gross_m2, exact['target_gfa_m2'], rel_tol=1e-5, abs_tol=1e-3)):
                raise ValueError('exact development inherited dimensions mismatch')
            # The legacy portfolio display bounds are rounded to six places.
            # Exact inheritance carries the verified full-precision ruler.
            book_height_m = float(exact['height_m'])
            scaled_height_m = book_height_m
        elif intent is not None:
            if (floor_count != intent['storey_count']
                    or not isclose(float(storey_m or 0), intent['storey_height_m'], rel_tol=1e-8)
                    or not isclose(book_height_m, floor_count * intent['storey_height_m'], rel_tol=1e-8, abs_tol=1e-5)
                    or not isclose(book_gross_m2, intent['target_gfa_m2'], rel_tol=1e-5, abs_tol=1e-3)):
                raise ValueError('authored dimensional intent disagrees with physical floor evidence')
            book_height_m = float(intent['storey_count'] * intent['storey_height_m'])
            scaled_height_m = book_height_m
        else:
            footprint_m2, scaled_height_m = _to_parcel_size(
                footprint_m2, book_gross_m2, book_height_m, site, storey_m=storey_m)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f'BOOK dimensional evidence: {exc}'
    try:
        program = GeometryProgram.from_dict(payload)
        # At the book's own plan size. Left to its default the shared
        # compile fits the plan to the legal host, and the book's 209 m2
        # footprint was staged at 705 m2 under the book's 35 m - a tower
        # 3.4x the certificate's, captioned 270% on a 250% parcel.
        # Exact inheritance and authored intent both carry physical dimensions.
        # A bridge's ground-floor area is not its full projected footprint;
        # fitting that projection to the ground area would silently shrink it.
        # The legal line cuts (`clip_to_host`): a footprint the author sized
        # to the parcel is placed at its own size and the boundary takes
        # what crosses it, the way the parcel cuts a massv2 seed. Fitted
        # inside instead, every intent above the host's inscribed copy came
        # back "cannot fit the legal host without resizing" - 24 of 24 when
        # the intents were sized to the FAR cap rather than the coverage cap.
        # The law floor by floor: each band's section is the legal plan at
        # the band's top (where 정북일조 is tightest), in the fit's normalized z.
        clip_sections = None
        if site is not None and floor_count and scaled_height_m and hasattr(site, 'plan_at'):
            count = int(floor_count)
            clip_sections = tuple(
                (index / count, (index + 1) / count,
                 site.plan_at(float(scaled_height_m) * (index + 1) / count))
                for index in range(count))
        facing_angle = None
        facing_evidence = {'access_status': 'not_requested', 'north_status': 'not_requested'}
        facing = (program.metadata or {}).get('facing') if isinstance(program.metadata, dict) else None
        if facing is not None:
            from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction
            facing_angle, facing_evidence = _resolve_facing(
                facing, site, float(scaled_height_m or 0.),
                road_direction=site_open_side_direction(site) if site is not None else None)
        # massv2's plot modes, ported - but the author declares them: the
        # sentence says `site_fit: impose` (fitted inside and trimmed) or
        # `inherit` (placed at its size and cut to the outline). A word list
        # deciding this here was the harness making a design call the LLM
        # was put in the loop to make. An exact child is never resized.
        meta = program.metadata if isinstance(program.metadata, dict) else {}
        impose = exact is None and str(meta.get('site_fit') or 'inherit') == 'impose'
        source = compile_geometry_program_to_source_mass(
            program, buildable, name=rec.get("trace_sequence_name"),
            target_plan_area=footprint_m2 or None,
            minimum_plan_area=footprint_m2 or None,
            placement_policy=POLICY if intent is not None or exact is not None else None,
            max_volume_bands=int(floor_count) if floor_count else 3,
            clip_to_host=True, clip_sections=clip_sections, facing_angle_deg=facing_angle,
            impose_fit=impose)
    except Exception as exc:  # a book record that no longer compiles is news, not a crash
        return None, f"{type(exc).__name__}: {exc}"
    if source is None:
        return None, ("exact development cannot fit the legal host without resizing"
                      if exact is not None else
                      "authored dimensional intent cannot fit the legal host without resizing"
                      if intent is not None else "compiled to None")
    # The height dialect. massv2's measure, gates and renderer read
    # `metadata["authored_height_m"]`; the book stamps its physical height
    # as a certificate on the artifact instead, and the shared compile
    # leaves the volumes as fractions of an unstated whole - so every book
    # mass measured 0.0 m and drew flat. Translated once, from the book's
    # own certificate, never from a guess.
    height_m, certificate = 0.0, ""
    for label, value in (
            ("projectedVisualCertificate.physical_height_m",
             (art.get("projectedVisualCertificate") or {}).get("physical_height_m")),
            ("hardGates.projectedMetrics.height_m", metrics.get("height_m")),
            ("capacityAlternative.candidate_requested_height_m",
             (art.get("capacityAlternative") or {}).get("candidate_requested_height_m"))):
        if value:
            height_m, certificate = float(value), label
            break
    if height_m <= 0.0:
        return None, "no physical height certificate"
    # Scaled with the plan, so the book's proportion survives.
    if scaled_height_m > 0.0:
        height_m = scaled_height_m
    scaled = scaled_book_metrics(book_gross_m2, storey_m, floor_count,
                                  height_m / book_height_m if book_height_m > 1e-6 else 1)
    source = replace(source, metadata={**dict(source.metadata),
                                       "authored_height_m": float(height_m),
                                       'book_floor_count': floor_count,
                                       'book_storey_height_m': scaled['book_storey_height_m'],
                                       'book_floor_area_m2': scaled['floor_area_m2'],
                                       'book_original_storey_evidence': storeys,
                                       "book_height_certificate": certificate})
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence
    storey_gate = storey_limit_evidence(source, site, storey_m=scaled['book_storey_height_m'],
                                        book_floor_count=floor_count, source_kind='book')
    if not storey_gate['satisfied']:
        return None, 'parcel storey gate: ' + ', '.join(storey_gate['reasons'])
    try:
        floors = delivered_floor_evidence(source, storeys, floor_count=floor_count,
                                          storey_m=storey_m)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f'BOOK delivered floor measurement: {exc}'
    if not floors['measurement_consistent']:
        return None, 'BOOK delivered floor measurement: ' + '; '.join(floors['measurement_issues'])
    if facing_angle is not None:
        from math import atan2, degrees
        matrix = floors['normalized_host_fit_matrix4']
        executed_angle = degrees(atan2(matrix[1][0], matrix[0][0]))
        difference = (executed_angle - facing_angle + 180.) % 360. - 180.
        if abs(difference) > 1e-6:
            return None, 'authored facing changed during delivery'
        facing_evidence['executed_angle_deg'] = executed_angle
    dimensional_evidence = None
    if intent is not None or exact is not None:
        matrix = floors['normalized_host_fit_matrix4']
        # A metric pose, or - for an imposing figure - one uniform plan scale
        # the fit chose and recorded, never a resize the pose invented.
        column_norms = [sum(matrix[i][j] ** 2 for i in range(2)) ** 0.5 for j in range(2)]
        impose_scale = float(((source.metadata.get('legal_host_clip') or {}).get('impose_scale')) or 1.0)
        metric_pose = (all(isclose(norm, impose_scale, rel_tol=1e-6, abs_tol=1e-8) for norm in column_norms)
            and isclose(sum(matrix[i][0] * matrix[i][1] for i in range(2)), 0.0, abs_tol=1e-8)
            and isclose(floors['z_scale'], 1.0, rel_tol=1e-8, abs_tol=1e-8)
            and (impose_scale == 1.0 or exact is None))
        # A cut delivery keeps the authored dimensions up to the legal line:
        # the pose stays metric (no resize), and the floor area delivered is
        # the authored area minus the law's recorded take. An exact
        # development inherits its parent's dimensions and is not cut.
        legal_take = sum(floors.get('legal_take_areas_m2') or ()) if floors.get('legal_clip') else 0.0
        if exact is not None and legal_take > 1e-3:
            return None, 'exact development cannot fit the legal host without resizing or clipping'
        expected_gfa = book_gross_m2 * impose_scale ** 2 - legal_take if legal_take > 0 else book_gross_m2 * impose_scale ** 2
        if not metric_pose or not isclose(floors['actual_gfa_m2'], expected_gfa, rel_tol=1e-5, abs_tol=1e-3):
            return None, ('exact development dimensions changed during delivery' if exact is not None
                          else 'authored dimensional intent changed during delivery')
    if intent is not None:
        dimensional_evidence = {'requested': intent,
            'effective': {'storey_count': floor_count, 'storey_height_m': storey_m,
                          'height_m': book_height_m, 'gfa_m2': book_gross_m2},
            'delivered': {'storey_count': floor_count, 'storey_height_m': float(storey_m) * floors['z_scale'],
                          'height_m': height_m, 'gfa_m2': floors['actual_gfa_m2'],
                          'shape_id': floors['source_shape_id']},
            'programme_status': 'unknown', 'authority': 'soft_authored_target; not project programme compliance'}
    # Replace the unexecuted similarity estimate with actual mesh sections.
    scaled['floor_area_m2'] = floors['actual_gfa_m2']
    scaled['book_storey_height_m'] = float(storey_m) * floors['z_scale']
    source = replace(source, metadata={**dict(source.metadata),
                      'book_floor_area_m2': scaled['floor_area_m2'],
                      'book_storey_height_m': scaled['book_storey_height_m'],
                      'book_delivered_floor_evidence': floors,
                      'book_facing_evidence': facing_evidence,
                      **({'dimensional_intent_evidence': dimensional_evidence} if dimensional_evidence is not None else {})})
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import area_limit_evidence
    area_gate = area_limit_evidence(source, site, scaled['floor_area_m2'])
    if not area_gate['satisfied']:
        return None, 'parcel area gate: ' + ', '.join(area_gate['reasons'])
    verbs = list(((payload.get("metadata") or {}).get("book_recursive_projection") or {})
                 .get("ordered_verbs") or [])
    entry = {
        'facing_evidence': facing_evidence,
        "trace": rec.get("trace_sequence_name"),
        # What the tile says about itself. The portfolio reader writes a
        # sentence ("courtyard - inscribe (11)"); the older artifact carries a
        # principle id. Either beats the literal words "book principle", which
        # is what every one of sixty tiles was captioned with.
        "thesis": str(rec.get("thesis")
                      or art.get("bookPrincipleId")
                      or art.get("bookScope") or "book principle"),
        "verbs": verbs,
        "height_m": round(height_m, 2),
        "footprint_m2": floors['mesh_projection_m2'],
        "requested_footprint_m2": footprint_m2,
        "floor_area_m2": scaled['floor_area_m2'],
        "delivered_floor_evidence": floors,
        **({"dimensional_intent_evidence": dimensional_evidence} if dimensional_evidence is not None else {}),
        "program": art.get("programType"),
        'book_floor_count': floor_count,
        'book_storey_height_m': scaled['book_storey_height_m'],
        'original_book_storey_height_m': storey_m,
        'original_storey_evidence': storeys,
        'storey_limit': storey_gate,
    }
    return source, entry


def book_rebuild(name: str, site, buildable, *, book_entry=None):
    """A seated book mass, rebuilt exactly as it was judged (for the baker)."""

    if not name.startswith('book:') or book_entry is None:
        raise ValueError('explicit BOOK entry required')
    entry = book_entry
    if entry is None:
        return None
    # `records_of` reads whichever shape the run wrote; the old artifact file
    # was being opened unconditionally beside it, so a seat imported from a
    # portfolio run could be judged and then not baked.
    artifacts = {"records": records_of(Path(entry["book_dir"]))}
    rec = next((r for r in artifacts.get("records") or []
                if r.get("trace_sequence_name") == entry["trace"]), None)
    if rec is None:
        return None
    source, _entry = _compile_record(rec, buildable, site)
    return source


def rebuild_seat(name, book, site, buildable, axis, base, *, book_entry=None):
    """BOOK-only exporter compatibility; presentation captions are not consumed."""
    return book_rebuild(name, site, buildable, book_entry=book_entry), None

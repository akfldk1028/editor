"""Bring BOOK-stack masses to the massv2 jury.

Two pipelines, one shared IR: book_language compiles its 70-principle
vocabulary into the same SourceMass that massv2's post-compile funnel
consumes. This tool replays a book run's exact geometry artifacts
(GeometryProgram AST -> SourceMass on this parcel's legal host) and
stages them as anonymous jury tiles - PROMPT.txt, tNN.png, key.json,
with three current board seats riding as anchors - exactly the stage
layout judge.sh/score.sh already speak. Book masses then face the same
blind eyes as every massv2 family, which is what "use the book" means.

    python tools/book_import.py <book-run-dir> <stage-name>
    # e.g. python tools/book_import.py ../c250-t3 book01
    # then: judge with skills/mass-judge (stage name book01)
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
from shapely.errors import GEOSException
from shapely.geometry import Polygon
import sys
from pathlib import Path

ROOT = _mass_paths.workspace_root()


BOOKS = ROOT / "runs" / "books"


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


def records_of(book_dir: Path) -> list[dict]:
    """Every BOOK record in a run directory, whichever era wrote it.

    The exploration command has two output shapes. The older run wrote one
    `maas-book-exact-geometry-artifacts.json` holding records with a
    `geometry_artifact`; the current one writes a portfolio plus one JSON per
    candidate, each with its `geometry_program` directly. Both are BOOK masses
    and the board judges both, so the reader takes either.
    """

    old = book_dir / "maas-book-exact-geometry-artifacts.json"
    if old.exists():
        return list(json.loads(old.read_text(encoding="utf-8")).get("records") or [])
    portfolio = book_dir / "maas-creative-portfolio.json"
    if not portfolio.exists():
        return []
    entries = json.loads(portfolio.read_text(encoding="utf-8")).get("candidates") or []
    records = []
    for entry in entries:
        path = book_dir / str(entry.get("candidate_json") or "")
        if not path.exists():
            continue
        candidate = json.loads(path.read_text(encoding="utf-8"))
        program = candidate.get("geometry_program")
        if not program:
            continue
        floors = (candidate.get("storey_evidence") or {}).get("actual_floor_areas_m2")
        if not floors:
            # Without the book's own plan size the shared compile fits the
            # plan to the legal host, which is how a 209 m2 book was once
            # staged at 705 m2. Skipped loudly rather than judged at a size
            # nobody authored.
            import sys as _sys
            print(f"  skip {entry.get('candidate_id')}: no floor areas",
                  file=_sys.stderr)
            continue
        # The portfolio's own words for what this candidate is: the family it
        # came from and the BOOK principle it was assigned. That is the thesis
        # a juror reads, and without it the tile carries a hash.
        assignment = (program.get("metadata") or {}).get(
            "creative_book_assignment") or {}
        principle = str(assignment.get("principle_id") or "")
        verbs = ", ".join(str(v) for v in (assignment.get("execution_verbs") or ()))
        family = str(candidate.get("family") or entry.get("family") or "")
        records.append({
            # The run id is part of the identity. Candidate ids restart at
            # creative-001 every exploration, so without it two runs mint the
            # same sixty keys and the registry - a flat merge of every
            # runs/books/*.json - hands the baker whichever sorted last.
            "trace_sequence_name":
                f"{book_dir.name}:{family}:{entry.get('candidate_id')}",
            "thesis": (
                f"{family.replace('_', ' ')} - "
                f"{verbs or 'base'}"
                + (f" ({principle.split(':')[-1]})" if principle else "")
            ),
            "geometry_artifact": {
                'storeyEvidence': dict(candidate.get('storey_evidence') or {}),
                "authoredGeometryProgram": program,
                # The portfolio states the physical height as the top of the
                # mesh bounds and the storeys it was cut into; the older
                # artifact carried a certificate instead. Both are the book's
                # own account of how tall it is, which is what the height
                # dialect below needs - without one every book mass measured
                # 0.0 m and drew flat.
                "projectedVisualCertificate": {
                    "physical_height_m": float(
                        ((candidate.get("mesh_evidence") or {}).get("bounds")
                         or [[0, 0, 0], [0, 0, 0]])[1][2] or 0.0),
                },
                "hardGates": {"projectedMetrics": {
                    "footprint_area_m2": float(
                        ((candidate.get("storey_evidence") or {}).get(
                            "actual_floor_areas_m2") or [0.0])[0] or 0.0),
                    # The book's own gross, summed over its own floors at its
                    # own storey height. Left unset, the caption fell back to
                    # measuring the delivered bands at the parcel's storey -
                    # the very reading the height dialect below exists to
                    # avoid - and all sixty tiles went to the jury with a
                    # 용적률 taken on the wrong ruler.
                    "floor_area_m2": float(sum(
                        (candidate.get("storey_evidence") or {}).get(
                            "actual_floor_areas_m2") or ())),
                }},
            },
        })
    return records


# What share of the parcel's 용적률 capacity a book mass is brought to. Not the
# whole of it: an authored scheme that fills the cap is making a claim about
# density, and a book figure makes no such claim - it states a proportion. Four
# fifths puts it in the same conversation as the schemes it is judged against
# without pretending it was designed for this brief.
BOOK_FAR_SHARE = 0.8

# And the ceiling on its footprint, as a share of the 건폐율 capacity. A book
# figure taken to the full coverage ceiling would be a different figure - the
# whole parcel wearing a cross - so it stops here and takes the rest in height.
BOOK_GROUND_SHARE = 0.75


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


def delivered_floor_evidence(source, storeys, *, floor_count, storey_m):
    """Measure the exported mesh at the executed authored floor centers.

    Host fitting controls XY independently of requested stature. Its exact
    affine map is the transport authority; a height ratio is not an area scale.
    The volume bands remain conservative occupancy proxies, not floor areas.
    """
    from math import isfinite
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid, solid_section_polygon, _mesh_plan_projection_area, section_export_area_resolution, _compile_geometry_program_cached, section_coplanar_skin_area
    bridge = source.metadata['geometry_program_bridge_evidence']
    matrix = bridge['host_fit_matrix4']
    if not bridge.get('host_fit_matrix4_exact') or any(
            matrix[i][j] != 0 for i, j in ((0, 2), (1, 2), (2, 0), (2, 1))):
        raise ValueError('BOOK floor schedule requires an exact horizontal affine placement')
    count = int(floor_count)
    original_centers = storeys.get('floor_center_elevations_m')
    center_basis = 'authored_floor_center_elevations_m'
    if original_centers is None:
        original_centers = [(i + .5) * float(storey_m) for i in range(count)]
        center_basis = 'authored_count_and_typical_storey_height'
    centers = [float(z) for z in original_centers]
    if len(centers) != count or any(not isfinite(z) for z in centers) or any(
            a >= b for a, b in zip(centers, centers[1:])):
        raise ValueError('invalid authored BOOK floor-center schedule')
    fractions = [matrix[2][2] * z + matrix[2][3] for z in centers]
    if any(not 0 < z < 1 for z in fractions):
        raise ValueError('authored BOOK floor center outside delivered solid height')
    vertices = tuple(p for s in source.surfaces for p in s.vertices_m)
    triangles = tuple((i, i+1, i+2) for i in range(0, len(vertices), 3))
    if not vertices or any(len(s.vertices_m) != 3 for s in source.surfaces):
        raise ValueError('BOOK requires a complete triangle mesh')
    # A horizontal skin exactly at a floor's centre plane makes the section
    # there a coin toss, and the rule below refused it. The book's joints sit
    # at half height, and half of 5 x 3.8 m is floor 3's centre, so comp23
    # refused every vertical sentence for it. The probe steps off the skin by
    # 2% of a storey to the side with the smaller section - the conservative
    # floor - and the offset is recorded.
    probe_offsets = [0.0] * len(fractions)
    if storey_m:
        step = abs(float(matrix[2][2])) * 0.02 * float(storey_m)
        probe = mesh_section_solid(vertices, triangles)
        for index, z in enumerate(list(fractions)):
            if section_coplanar_skin_area(vertices, triangles, z, matrix) <= 0.0:
                continue
            below, above = z - step, z + step
            if not (0 < below and above < 1):
                continue
            candidates = []
            for side in (below, above):
                polygon = solid_section_polygon(probe, side)
                candidates.append((float(polygon.area) if polygon is not None else 0.0, side))
            area, side = min(candidates)
            fractions[index] = side
            probe_offsets[index] = side - z
    solid = mesh_section_solid(vertices, triangles)
    sections = [solid_section_polygon(solid, z) for z in fractions]
    empty_floors = [index for index, p in enumerate(sections) if p is None or p.is_empty or p.area <= 0]
    if empty_floors and not source.metadata.get('legal_host_clip'):
        raise ValueError('authored BOOK floor has no delivered occupied section')
    # Under a cut, a floor with no section is either the law's whole take
    # of that floor (its legal section had no room where the authored floor
    # stood) or a pose that missed the parcel; the first is recorded below
    # and the second still refuses.
    removed_by_law: set[int] = set(empty_floors)
    from shapely.geometry import Polygon as _Empty
    sections = [p if index not in removed_by_law else _Empty() for index, p in enumerate(sections)]
    areas = [float(p.area) for p in sections]
    height = float(source.metadata['authored_height_m'])
    origin = source.footprint.centroid
    from shapely.affinity import translate
    proxy_areas, missing_areas = [], []
    for z, section in zip(fractions, sections):
        proxy = unary_union([v.footprint for v in source.volumes
                             if v.bottom_fraction <= z <= v.top_fraction])
        proxy_areas.append(float(proxy.area))
        missing_areas.append(float(translate(section, xoff=origin.x, yoff=origin.y).difference(proxy).area))
    from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
    original = _compile_geometry_program_cached(GeometryProgram.from_dict(source.metadata['geometry_program']))
    physical_matrix = [list(row) for row in matrix]
    physical_matrix[2] = [value * height for value in physical_matrix[2]]
    transformed = original._solid.transform(physical_matrix[:3])
    # Delivered through a cut: the reference is the authored floor inside
    # the host the bridge cut at, not the whole authored floor. The
    # difference is the law's take, recorded per floor.
    clip = source.metadata.get('legal_host_clip')
    clip_host = None
    clip_bands = []
    if isinstance(clip, dict) and clip.get('exterior'):
        clip_host = Polygon([tuple(pt) for pt in clip['exterior']],
                            [[tuple(pt) for pt in hole] for hole in clip.get('holes') or ()])
        clip_bands = [(float(b['lo']), float(b['hi']),
                       Polygon([tuple(pt) for pt in b['exterior']],
                               [[tuple(pt) for pt in hole] for hole in b.get('holes') or ()]))
                      for b in clip.get('sections') or ()]
    def host_at(z):
        for lo, hi, poly in clip_bands:
            if lo - 1e-9 <= z < hi + 1e-9:
                return poly
        return clip_host
    original_areas, legal_take_areas = [], []
    for z in fractions:
        section = transformed.slice(z * height)
        if clip_host is None:
            original_areas.append(float(section.area()))
            legal_take_areas.append(0.0)
            continue
        region = None
        for contour in section.to_polygons():
            ring = Polygon(contour)
            if ring.is_empty or ring.area <= 0:
                continue
            region = ring if region is None else region.symmetric_difference(ring)
        whole = float(region.area) if region is not None else 0.0
        inside = float(region.intersection(host_at(z)).area) if region is not None else 0.0
        floor_index = len(original_areas)
        if floor_index in removed_by_law:
            if inside > 1.0:
                # The law left room for this floor and the delivery has none there.
                raise ValueError('authored BOOK floor has no delivered occupied section')
            inside = 0.0
        original_areas.append(inside)
        legal_take_areas.append(whole - inside)
    resolutions = [section_export_area_resolution(p, matrix) for p in sections]
    coplanar_areas = [section_coplanar_skin_area(vertices, triangles, z, matrix) for z in fractions]
    area_scale = abs(matrix[0][0]*matrix[1][1] - matrix[0][1]*matrix[1][0])
    authored_areas = storeys.get('actual_floor_areas_m2')
    if authored_areas is not None and len(authored_areas) != count:
        raise ValueError('authored BOOK floor-area schedule count mismatch')
    transported_areas = [float(a) * area_scale for a in authored_areas] if authored_areas is not None else None
    # A published decimal floor schedule has its own last-place rounding.
    # Derive that resolution from the supplied values, not another hardcoded
    # geometry tolerance or a duplicate of the portfolio writer's precision.
    from decimal import Decimal
    authored_resolutions = [resolution + .5 * 10.0 ** Decimal(str(a)).as_tuple().exponent * area_scale
                            for a, resolution in zip(authored_areas, resolutions)] if authored_areas is not None else None
    issues = []
    for index, (actual, reference, missing, resolution) in enumerate(zip(
            areas, original_areas, missing_areas, resolutions), 1):
        if abs(actual - reference) > resolution:
            issues.append(f'floor_{index}_original_export_area_mismatch:{reference:.9f}->{actual:.9f}')
        if missing > resolution:
            issues.append(f'floor_{index}_mesh_area_missing_from_proxy:{missing:.9f}')
        if coplanar_areas[index-1] > resolution:
            issues.append(f'floor_{index}_ambiguous_horizontal_skin_at_center:{coplanar_areas[index-1]:.9f}')
        if transported_areas is not None and clip_host is None and (
                not isfinite(transported_areas[index-1])
                or abs(actual - transported_areas[index-1]) > authored_resolutions[index-1]):
            issues.append(f'floor_{index}_authored_export_area_mismatch:{transported_areas[index-1]:.9f}->{actual:.9f}')
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import shape_id
    return {
        'schema': 'arr.maas.book_delivered_floor_measurement.v1',
        'basis': 'delivered SourceSurface mesh at transformed authored floor centers',
        'legal_clip': clip_host is not None,
        'legal_take_areas_m2': [round(a, 6) for a in legal_take_areas],
        'floors_removed_by_law': sorted(index + 1 for index in removed_by_law),
        'placement_policy': 'host-fitted XY affine; independently requested Z stature',
        'center_basis': center_basis,
        'original_floor_center_elevations_m': centers,
        'delivered_floor_center_elevations_m': [z * height for z in fractions],
        'actual_floor_areas_m2': areas,
        'actual_gfa_m2': sum(areas),
        'source_shape_id': shape_id(source),
        'original_transformed_floor_areas_m2': original_areas,
        'authored_floor_areas_at_executed_xy_m2': transported_areas,
        'authored_floor_area_comparison_resolution_m2': authored_resolutions,
        'coplanar_skin_area_at_floor_center_m2': coplanar_areas,
        # Only when a probe moved: the key would change every earlier
        # seat's certificate otherwise (comp23's sheet ghosted all of them).
        **({'floor_center_probe_offsets': probe_offsets} if any(probe_offsets) else {}),
        'export_area_comparison_resolution_m2': resolutions,
        'measurement_consistent': not issues,
        'measurement_issues': issues,
        'mesh_projection_m2': _mesh_plan_projection_area(vertices, triangles),
        'proxy_floor_areas_m2': proxy_areas,
        'mesh_floor_area_missing_from_proxy_m2': missing_areas,
        'xy_area_scale': area_scale,
        'z_scale': matrix[2][2] * height,
        'normalized_host_fit_matrix4': matrix,
        'requested_plan_area_m2': bridge.get('effective_target_plan_area'),
        'plan_area_target_satisfied': bridge.get('minimum_plan_area_target_satisfied'),
        'plan_area_shortfall_ratio': bridge.get('minimum_plan_area_shortfall_ratio'),
    }


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
    except GEOSException as exc:
        return None, f'BOOK delivered floor measurement: {type(exc).__name__}: {exc}'
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


def _refused(source, site) -> str:
    """Why this mass cannot be judged, or an empty string.

    Standing first - a body with nothing under it is not a proposal - then the
    room rule, which is what separates a building from a sculpture at this
    scale.
    """

    from backend.app.modules.design.generation.maas.massv2.plausibility import assess as plausibility_of  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.structure import assess_standing  # noqa: E402

    from backend.app.modules.design.generation.maas.massv2.plausibility import slenderness_limit  # noqa: E402

    height_m = float(source.metadata.get("authored_height_m") or 0.0)
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence
    is_book = 'book_height_certificate' in source.metadata
    gate = storey_limit_evidence(source, site,
            storey_m=source.metadata.get('book_storey_height_m') if is_book else source.metadata.get('authored_floor_height_m'),
            book_floor_count=source.metadata.get('book_floor_count'), source_kind='book' if is_book else 'authored')
    if not gate['satisfied']:
        return 'parcel storey gate: ' + ', '.join(gate['reasons'])
    if is_book:
        from backend.app.modules.design.generation.maas.massv2.parcel_policy import area_limit_evidence
        area = area_limit_evidence(source, site, source.metadata.get('book_floor_area_m2') or 0)
        if not area['satisfied']:
            return 'parcel area gate: ' + ', '.join(area['reasons'])
    try:
        standing = assess_standing(source, height_m=height_m)
    except Exception as exc:  # noqa: BLE001 - a gate that crashes is news
        return f"standing check failed ({type(exc).__name__}: {exc})"
    if not getattr(standing, "stands", True):
        reasons = list(getattr(standing, "reasons", ()) or ())
        label = ('mesh gravity screen refused' if standing.measurement_basis == 'complete_export_mesh'
                 else 'does not stand')
        return f"{label} ({'; '.join(str(r) for r in reasons[:2]) or 'no reason'})"
    try:
        plausible = plausibility_of(
            source,
            parcel_area_m2=float(site.parcel_area_m2),
            max_slenderness=slenderness_limit(
                far_capacity_m2=float(site.far_capacity_m2),
                ground_capacity_m2=float(site.ground_capacity_m2)),
            floor_height_m=float(source.metadata.get('book_storey_height_m') if is_book
                                 and source.metadata.get('book_storey_height_m') else site.floor_height_m))
    except Exception as exc:  # noqa: BLE001
        return f"room check failed ({type(exc).__name__}: {exc})"
    if not plausible.occupiable:
        reasons = list(getattr(plausible, "reasons", ()) or ())
        return f"no room in it ({'; '.join(str(r) for r in reasons[:2])})"
    return ""


def registry() -> dict:
    """Every staged book mass, by its `book:` name -> {book_dir, ...entry}."""

    found: dict = {}
    if BOOKS.exists():
        for path in sorted(BOOKS.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for name, entry in (data.get("entries") or {}).items():
                found[name] = {**entry, "book_dir": data["book_dir"]}
    return found


def entry_for_judged_row(row: dict) -> dict:
    """Resolve the immutable stage and both identities recorded by its jury.

    Inherited names recur across stages. A global lexical winner can therefore
    pair an old certificate with a newly compiled shape after an engine change.
    Delivery must carry this same entry through rebuild and certification.
    """
    name = row.get('name')
    stage = str(row.get('round') or '')
    if (not stage.startswith('vlm-') or len(stage) == 4
            or Path(stage).name != stage or '\\' in stage):
        raise ValueError(f'{name}: missing or invalid judged BOOK snapshot round')
    path = BOOKS / f'{stage[4:]}.json'
    if not path.is_file():
        raise ValueError(f'{name}: missing judged BOOK snapshot {stage}')
    data = json.loads(path.read_text(encoding='utf-8'))
    entry = (data.get('entries') or {}).get(name)
    if entry is None:
        raise ValueError(f'{name}: not present in judged BOOK snapshot {stage}')
    cert = entry.get('numeric_certificate') or {}
    if (not row.get('shape_id') or not row.get('certificate_id')
            or cert.get('name') != name
            or cert.get('shape_id') != row['shape_id']
            or entry.get('delivered_shape_id') != row['shape_id']
            or cert.get('certificate_id') != row['certificate_id']):
        raise ValueError(f'{name}: judged BOOK snapshot identity mismatch')
    return {**entry, 'book_dir': data['book_dir']}


def resolve_entry(name: str, *, row: dict | None = None) -> dict:
    """The one registry entry a BOOK name means, or a refusal that says why.

    With a judged board row, the entry of the stage that row was judged in
    (entry_for_judged_row). Without one, the merged registry - but only when
    every stage holding the name agrees on its certificate; a name whose
    stages disagree cannot be resolved by name, and guessing paired a comp12
    seat with a comp03 entry.
    """

    if row is not None:
        return entry_for_judged_row(row)
    certificates: set[str] = set()
    found = None
    if BOOKS.exists():
        for path in sorted(BOOKS.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = (data.get("entries") or {}).get(name)
            if entry is None:
                continue
            certificates.add(str((entry.get("numeric_certificate") or {}).get("certificate_id") or ""))
            found = {**entry, "book_dir": data["book_dir"]}
    if found is None:
        raise KeyError(name)
    if len(certificates) > 1:
        raise ValueError(f"{name}: recurs in {len(certificates)} stages with different "
                         f"certificates - resolve it by its judged board row")
    return found


def book_rebuild(name: str, site, buildable, *, book_entry=None):
    """A seated book mass, rebuilt exactly as it was judged (for the baker)."""

    entry = book_entry if book_entry is not None else registry().get(name)
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


def main() -> int:
    book_dir = Path(sys.argv[1])
    if not book_dir.is_absolute():
        book_dir = (ROOT / book_dir).resolve()
    stage_name = sys.argv[2]

    from backend.app.modules.massing.workspace_tools.band_probe import corpus  # noqa: E402,F401  (django setup side effect)
    from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import certified_caption, ride_anchors, shape_id  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
    from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402

    records = records_of(book_dir)
    if not records:
        print("FAIL: no records in book artifacts")
        return 1

    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)

    out = ROOT / "runs" / f"vlm-{stage_name}"
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(out.glob("t*.png")) + [out / r for r in ("r1.txt", "r2.txt", "r3.txt")]:
        Path(stale).unlink(missing_ok=True)

    key_rows: list[dict] = []
    entries: dict = {}
    index = 0
    for rec in records:
        source, entry = _compile_record(rec, buildable, site)
        if source is None:
            print(f"  skip {rec.get('trace_sequence_name')}: {entry}")
            continue
        # The same questions every authored mass answers before it is drawn.
        # A book mass skipped all of them and went straight to the jury, so a
        # `lift` whose supports the compile dropped arrived as a slab floating
        # over an empty parcel - 14% coverage, nothing under it - and a juror
        # was asked to score it as architecture. One ruler for everything.
        refusal = _refused(source, site)
        if refusal:
            print(f"  skip {rec.get('trace_sequence_name')}: {refusal}")
            continue
        index += 1
        tile = f"t{index:02d}"
        name = f"book:{rec.get('trace_sequence_name') or tile}"
        # 건폐율/용적률 from the book's own certificate: it counts floors at
        # its own storey height (35 m / 10 floors), which massv2's per-band
        # rounding at the parcel storey cannot reproduce on three fat bands.
        from backend.app.modules.massing.workspace_tools.vlm_shortlist import jury_caption, seat_certificate
        certificate = seat_certificate(name, source, {}, site, book_entry=entry)
        render_masses([(tile, source, jury_caption(
                           source, site, gross_m2=certificate['gross_m2']))],
                      out / f"{tile}.png", site_ring=list(buildable.exterior.coords),
                      columns=1, tile=(900, 820), style="massing")
        from backend.app.modules.massing.workspace_tools.presentation import append_jury_drawings
        drawings = append_jury_drawings(out / f'{tile}.png',
            [(name, source, certificate['storey_m'])], buildable)
        import hashlib
        key_rows.append({"tile": tile, "name": name, "height_m": entry["height_m"],
                         "shape_id": shape_id(source), 'certificate': certificate, 'jury_drawings': drawings,
                         'certificate_id': certificate['certificate_id'],
                         'png_sha256': hashlib.sha256((out / f'{tile}.png').read_bytes()).hexdigest()})
        entries[name] = {**entry, 'delivered_shape_id': certificate['shape_id'],
                         'numeric_certificate': certificate}
    # The registry: how the curator keys a book mass and how the baker
    # rebuilds it once seated. Written per stage, read as a whole.
    BOOKS.mkdir(parents=True, exist_ok=True)
    (BOOKS / f"{stage_name}.json").write_text(
        json.dumps({"book_dir": str(book_dir), "entries": entries},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    if not key_rows:
        print("FAIL: no book record compiled")
        return 1

    # The overseas rubric, from its owner (vlm_shortlist.rubric_for) - never retyped here.
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import BLIND_PREAMBLE, rubric_for  # noqa: E402
    (out / "PROMPT.txt").write_text(BLIND_PREAMBLE + rubric_for("overseas", site=site), encoding="utf-8")

    # Three board seats ride as anchors - the same ride, rebuild and caption
    # every massv2 round uses (vlm_shortlist.ride_anchors owns it).
    ride_anchors(out, key_rows, site=site)

    (out / "key.json").write_text(json.dumps(key_rows, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    candidates = sum(1 for r in key_rows if "anchor" not in r)
    print(f"{len(key_rows)} tiles staged ({candidates} book + "
          f"{len(key_rows) - candidates} anchors) -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

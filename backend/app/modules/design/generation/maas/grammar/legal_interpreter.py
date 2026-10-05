"""Interpret MAAS verb sequences into legal-optimizer seed variants."""

from __future__ import annotations

import os

from shapely.affinity import scale, translate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.grammar.agent_proposals import load_agent_proposal_sequences
from backend.app.modules.design.generation.maas.grammar.sequence_library import SEQUENCES
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.morphology_operators import MorphologyVariant, largest_polygon
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass, source_mass_to_variant


def _clean(poly) -> Polygon | None:
    if poly is None or poly.is_empty:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = largest_polygon(poly)
    if poly.area < 1.0:
        return None
    return poly


def _bounds(poly: Polygon) -> tuple[float, float, float, float, float, float]:
    minx, miny, maxx, maxy = poly.bounds
    return minx, miny, maxx, maxy, maxx - minx, maxy - miny


def _corner_notch(poly: Polygon, corner: str, ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cut_w = width * ratio
    cut_d = depth * ratio
    x0, x1 = (maxx - cut_w, maxx) if "+x" in corner else (minx, minx + cut_w)
    y0, y1 = (maxy - cut_d, maxy) if "+y" in corner else (miny, miny + cut_d)
    return _clean(poly.difference(box(x0, y0, x1, y1)))


def _edge_cave(poly: Polygon, side: str, width_ratio: float, depth_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    if side in ("north", "south"):
        cut_w = width * width_ratio
        x0 = minx + (width - cut_w) / 2
        x1 = x0 + cut_w
        y0, y1 = (maxy - depth * depth_ratio, maxy) if side == "north" else (miny, miny + depth * depth_ratio)
    else:
        cut_d = depth * width_ratio
        y0 = miny + (depth - cut_d) / 2
        y1 = y0 + cut_d
        x0, x1 = (minx, minx + width * depth_ratio) if side == "west" else (maxx - width * depth_ratio, maxx)
    return _clean(poly.difference(box(x0, y0, x1, y1)))


def _courtyard(poly: Polygon, ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cut_w = width * ratio
    cut_d = depth * ratio
    courtyard = box(
        minx + (width - cut_w) / 2,
        miny + (depth - cut_d) / 2,
        minx + (width + cut_w) / 2,
        miny + (depth + cut_d) / 2,
    )
    return _clean(poly.difference(courtyard))


def _split(poly: Polygon, axis: str, gap_ratio: float, bridge_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    if axis == "x":
        gap = width * gap_ratio
        bridge = depth * bridge_ratio
        x0 = (minx + maxx - gap) / 2
        x1 = x0 + gap
        cutter = unary_union([
            box(x0, miny, x1, (miny + maxy - bridge) / 2),
            box(x0, (miny + maxy + bridge) / 2, x1, maxy),
        ])
    else:
        gap = depth * gap_ratio
        bridge = width * bridge_ratio
        y0 = (miny + maxy - gap) / 2
        y1 = y0 + gap
        cutter = unary_union([
            box(minx, y0, (minx + maxx - bridge) / 2, y1),
            box((minx + maxx + bridge) / 2, y0, maxx, y1),
        ])
    return _clean(poly.difference(cutter))


def _bar(poly: Polygon, axis: str, factor: float, shift: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    if axis == "x":
        fp = scale(poly, xfact=1.0, yfact=factor, origin="centroid")
        fp = translate(fp, yoff=depth * shift)
    else:
        fp = scale(poly, xfact=factor, yfact=1.0, origin="centroid")
        fp = translate(fp, xoff=width * shift)
    return _clean(fp.intersection(poly))


def _branch(poly: Polygon, angle: float, trunk_ratio: float, arm_ratio: float) -> Polygon | None:
    from shapely.affinity import rotate

    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    trunk = box(cx - width * trunk_ratio / 2, miny, cx + width * trunk_ratio / 2, maxy)
    arm_len = max(width, depth) * 0.76
    arm_w = min(width, depth) * arm_ratio
    arm = box(cx - arm_w / 2, cy - arm_len * 0.10, cx + arm_w / 2, cy + arm_len * 0.62)
    geom = unary_union([trunk, rotate(arm, angle, origin=(cx, cy)), rotate(arm, -angle, origin=(cx, cy))])
    return _clean(geom.intersection(poly))


def _pinch(poly: Polygon, axis: str, waist_ratio: float, depth_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    if axis == "x":
        cut_w = width * (1.0 - waist_ratio) / 2
        cut_d = depth * depth_ratio
        y0 = miny + (depth - cut_d) / 2
        y1 = y0 + cut_d
        cutters = [box(minx, y0, minx + cut_w, y1), box(maxx - cut_w, y0, maxx, y1)]
    else:
        cut_d = depth * (1.0 - waist_ratio) / 2
        cut_w = width * depth_ratio
        x0 = minx + (width - cut_w) / 2
        x1 = x0 + cut_w
        cutters = [box(x0, miny, x1, miny + cut_d), box(x0, maxy - cut_d, x1, maxy)]
    return _clean(poly.difference(unary_union(cutters)))


def _interlock(poly: Polygon, angle: float, bar_ratio: float) -> Polygon | None:
    from shapely.affinity import rotate

    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    bar_w = min(width, depth) * bar_ratio
    long = max(width, depth) * 1.24
    a = box(cx - long / 2, cy - bar_w / 2, cx + long / 2, cy + bar_w / 2)
    b = box(cx - bar_w / 2, cy - long / 2, cx + bar_w / 2, cy + long / 2)
    return _clean(unary_union([rotate(a, angle, origin=(cx, cy)), rotate(b, angle, origin=(cx, cy))]).intersection(poly))


def _overlap(poly: Polygon, axis: str, slab_ratio: float, shift_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    if axis == "x":
        slab = box(cx - width * 0.37, cy - depth * slab_ratio / 2, cx + width * 0.37, cy + depth * slab_ratio / 2)
        a = translate(slab, xoff=-width * shift_ratio, yoff=-depth * 0.10)
        b = translate(slab, xoff=width * shift_ratio, yoff=depth * 0.10)
    else:
        slab = box(cx - width * slab_ratio / 2, cy - depth * 0.37, cx + width * slab_ratio / 2, cy + depth * 0.37)
        a = translate(slab, xoff=-width * 0.10, yoff=-depth * shift_ratio)
        b = translate(slab, xoff=width * 0.10, yoff=depth * shift_ratio)
    return _clean(unary_union([a, b]).intersection(poly))


def _shift(poly: Polygon, axis: str, distance_ratio: float, clip: Polygon) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(clip)
    shifted = translate(poly, xoff=width * distance_ratio if axis == "x" else 0.0, yoff=depth * distance_ratio if axis == "y" else 0.0)
    return _clean(shifted.intersection(clip))


def _ensure_upper(
    footprint: Polygon,
    upper: Polygon | None,
    *,
    ratio: float,
) -> Polygon | None:
    target = upper if upper is not None else footprint
    return _clean(scale(target, xfact=ratio, yfact=ratio, origin="centroid").intersection(footprint))


def interpret_sequence(base_footprint: Polygon, sequence: VerbSequence) -> MorphologyVariant | None:
    errors = sequence.validate()
    if errors:
        return None

    base = _clean(base_footprint)
    if base is None:
        return None

    source_mass = compile_sequence_to_source_mass(base, sequence)
    if source_mass is not None:
        return source_mass_to_variant(source_mass, sequence)

    footprint = base
    upper = None
    lower_floor_fraction = None

    for call in sequence.calls[1:]:
        params = call.params
        next_fp = footprint
        if call.verb == "notch":
            next_fp = _corner_notch(footprint, params.get("corner", "+x+y"), float(params.get("ratio", 0.24)))
        elif call.verb == "cave":
            next_fp = _edge_cave(footprint, params.get("side", "north"), float(params.get("width_ratio", 0.42)), float(params.get("depth_ratio", 0.28)))
        elif call.verb == "courtyard":
            next_fp = _courtyard(footprint, float(params.get("ratio", 0.26)))
        elif call.verb == "split":
            next_fp = _split(footprint, params.get("axis", "x"), float(params.get("gap_ratio", 0.22)), float(params.get("bridge_ratio", 0.18)))
        elif call.verb == "bar":
            next_fp = _bar(footprint, params.get("axis", "y"), float(params.get("factor", 0.56)), float(params.get("shift", 0.0)))
        elif call.verb == "branch":
            next_fp = _branch(footprint, float(params.get("angle", 34.0)), float(params.get("trunk_ratio", 0.30)), float(params.get("arm_ratio", 0.20)))
        elif call.verb == "pinch":
            next_fp = _pinch(footprint, params.get("axis", "y"), float(params.get("waist_ratio", 0.62)), float(params.get("depth_ratio", 0.36)))
        elif call.verb == "interlock":
            next_fp = _interlock(footprint, float(params.get("angle", 28.0)), float(params.get("bar_ratio", 0.34)))
        elif call.verb == "overlap":
            next_fp = _overlap(footprint, params.get("axis", "x"), float(params.get("slab_ratio", 0.52)), float(params.get("shift_ratio", 0.18)))
        elif call.verb == "shift":
            target = upper if upper is not None else footprint
            shifted = _shift(target, params.get("axis", "x"), float(params.get("distance_ratio", 0.06)), footprint)
            if upper is not None:
                upper = shifted
            else:
                next_fp = shifted
        elif call.verb == "inset":
            factor = float(params.get("factor", 0.92))
            next_fp = _clean(scale(footprint, xfact=factor, yfact=factor, origin="centroid"))
        elif call.verb == "expand":
            factor = float(params.get("factor", 1.08))
            next_fp = _clean(scale(footprint, xfact=factor, yfact=factor, origin="centroid").intersection(base))
        elif call.verb == "lift":
            ratio = float(params.get("upper_ratio", 0.66))
            upper = _clean(scale(footprint, xfact=ratio, yfact=ratio, origin="centroid").intersection(footprint))
            lower_floor_fraction = float(params.get("lower_floor_fraction", 0.45))
        elif call.verb == "taper":
            x_ratio = float(params.get("x_ratio", params.get("top_ratio", 0.74)))
            y_ratio = float(params.get("y_ratio", params.get("top_ratio", 0.74)))
            target = upper if upper is not None else footprint
            tapered = _clean(scale(target, xfact=x_ratio, yfact=y_ratio, origin="centroid").intersection(footprint))
            if upper is not None:
                upper = tapered
            else:
                upper = tapered
                lower_floor_fraction = float(params.get("lower_floor_fraction", 0.45))
        elif call.verb == "grade":
            target = upper if upper is not None else footprint
            graded = _edge_cave(
                target,
                params.get("side", "north"),
                float(params.get("width_ratio", 0.52)),
                float(params.get("depth_ratio", 0.24)),
            )
            if upper is not None:
                upper = graded
            else:
                upper = graded
                lower_floor_fraction = float(params.get("lower_floor_fraction", 0.42))
        elif call.verb == "step_envelope":
            # No plan mutation here. The legal optimizer will build a true
            # floor-by-floor stack from the sunlight/legal envelope.
            lower_floor_fraction = None
        elif call.verb == "diagonal_connect":
            ratio = float(params.get("upper_ratio", 0.72))
            distance = float(params.get("distance_ratio", 0.10))
            axis = params.get("axis", "x")
            upper = _ensure_upper(footprint, upper, ratio=ratio)
            if upper is not None:
                upper = _shift(upper, axis, distance, footprint)
                lower_floor_fraction = float(params.get("lower_floor_fraction", 0.40))
        elif call.verb == "terrace_link":
            side = params.get("side", "north")
            width_ratio = float(params.get("width_ratio", 0.54))
            depth_ratio = float(params.get("depth_ratio", 0.20))
            target = _ensure_upper(footprint, upper, ratio=float(params.get("upper_ratio", 0.82)))
            upper = _edge_cave(target or footprint, side, width_ratio, depth_ratio)
            if upper is not None:
                lower_floor_fraction = float(params.get("lower_floor_fraction", 0.34))
        elif call.verb == "sloped_roof_mass":
            target = _ensure_upper(footprint, upper, ratio=float(params.get("upper_ratio", 0.88)))
            upper = _clean(scale(
                target or footprint,
                xfact=float(params.get("x_ratio", 0.70)),
                yfact=float(params.get("y_ratio", 0.92)),
                origin="centroid",
            ).intersection(footprint))
            if upper is not None:
                lower_floor_fraction = float(params.get("lower_floor_fraction", 0.50))

        if next_fp is not None:
            footprint = next_fp

    footprint = _clean(footprint)
    if footprint is None:
        return None
    if upper is not None:
        upper = _clean(upper.intersection(footprint))

    return MorphologyVariant(
        sequence.name,
        footprint,
        upper_footprint=upper,
        lower_floor_fraction=lower_floor_fraction,
        notes=sequence.notes,
        verb_sequence=tuple(call.to_dict() for call in sequence.calls),
        research_basis={
            "basis": "operative_design_verb_grammar",
            "optimization_mode": "deterministic_fixture_parameter_sweep_requires_llm_authoring"
            if "__sweep_" in sequence.name else "deterministic_sequence_library",
            "implemented_status": "arr_native_approximation",
            "sequence_name": sequence.name,
            "parameter_source": "deterministic_sequence_library",
            "requires_llm_authoring": True,
            "not_full_claim": ["not_full_evomass", "not_full_ssiea", "not_full_d4descent"],
        },
    )


def _with_param(call: VerbCall, **updates) -> VerbCall:
    params = dict(call.params)
    params.update({key: value for key, value in updates.items() if value is not None})
    return VerbCall(call.verb, params)


def _variant_sequence(sequence: VerbSequence, suffix: str, updates: dict[int, dict[str, float | str]]) -> VerbSequence:
    calls = []
    for index, verb_call in enumerate(sequence.calls):
        calls.append(_with_param(verb_call, **updates.get(index, {})))
    return VerbSequence(
        name=f"{sequence.name}__sweep_{suffix}",
        label=f"{sequence.label} {suffix}",
        calls=tuple(calls),
        notes=sequence.notes + (
            "research_basis=deterministic_fixture_parameter_sweep_requires_llm_authoring",
            f"source_sequence={sequence.name}",
        ),
    )


def _deterministic_fixture_parameter_sweeps(sequence: VerbSequence) -> tuple[VerbSequence, ...]:
    """Deterministic fixture variants used until an LLM/optimizer proposal exists.

    This is not EvoMass, SSIEA, or a live architectural-language agent. It
    expands each grammar typology into a small reproducible fixture space so
    the legal pipeline can be tested while keeping the authoring gap explicit.
    """
    variants: list[VerbSequence] = [sequence]
    verbs = [call.verb for call in sequence.calls]

    def idx(verb: str) -> int | None:
        try:
            return verbs.index(verb)
        except ValueError:
            return None

    if sequence.name == "grammar_sunlight_multi_step":
        return tuple(variants)

    if (i := idx("courtyard")) is not None:
        variants.append(_variant_sequence(sequence, "court_open", {i: {"ratio": 0.30}}))
        variants.append(_variant_sequence(sequence, "court_tight", {i: {"ratio": 0.18}}))
    if (i := idx("split")) is not None:
        variants.append(_variant_sequence(sequence, "split_wide", {i: {"gap_ratio": 0.30, "bridge_ratio": 0.16}}))
        variants.append(_variant_sequence(sequence, "split_bridge", {i: {"gap_ratio": 0.18, "bridge_ratio": 0.28}}))
    if (i := idx("bar")) is not None:
        variants.append(_variant_sequence(sequence, "bar_slender", {i: {"factor": 0.46, "shift": -0.10}}))
        variants.append(_variant_sequence(sequence, "bar_offset", {i: {"factor": 0.62, "shift": 0.14}}))
    if (i := idx("overlap")) is not None:
        variants.append(_variant_sequence(sequence, "overlap_long", {i: {"slab_ratio": 0.42, "shift_ratio": 0.24}}))
        variants.append(_variant_sequence(sequence, "overlap_compact", {i: {"slab_ratio": 0.60, "shift_ratio": 0.12}}))
    if (i := idx("branch")) is not None:
        variants.append(_variant_sequence(sequence, "branch_wide", {i: {"angle": 46.0, "trunk_ratio": 0.26, "arm_ratio": 0.18}}))
        variants.append(_variant_sequence(sequence, "branch_compact", {i: {"angle": 24.0, "trunk_ratio": 0.36, "arm_ratio": 0.24}}))
    if (i := idx("cave")) is not None:
        variants.append(_variant_sequence(sequence, "cave_deep", {i: {"width_ratio": 0.58, "depth_ratio": 0.34}}))
        variants.append(_variant_sequence(sequence, "cave_side", {i: {"side": "east", "width_ratio": 0.44, "depth_ratio": 0.30}}))
    if (i := idx("interlock")) is not None:
        variants.append(_variant_sequence(sequence, "interlock_diag", {i: {"angle": -36.0, "bar_ratio": 0.30}}))
        variants.append(_variant_sequence(sequence, "interlock_thick", {i: {"angle": 18.0, "bar_ratio": 0.42}}))
    if (i := idx("lift")) is not None:
        variants.append(_variant_sequence(sequence, "lift_high", {i: {"upper_ratio": 0.62, "lower_floor_fraction": 0.36}}))
        variants.append(_variant_sequence(sequence, "lift_low", {i: {"upper_ratio": 0.82, "lower_floor_fraction": 0.58}}))
    if (i := idx("diagonal_connect")) is not None:
        variants.append(_variant_sequence(sequence, "diag_x", {i: {"axis": "x", "distance_ratio": 0.16, "upper_ratio": 0.74}}))
        variants.append(_variant_sequence(sequence, "diag_y", {i: {"axis": "y", "distance_ratio": 0.16, "upper_ratio": 0.74}}))
    if (i := idx("terrace_link")) is not None:
        variants.append(_variant_sequence(sequence, "terrace_deep", {i: {"width_ratio": 0.72, "depth_ratio": 0.28, "upper_ratio": 0.80}}))
        variants.append(_variant_sequence(sequence, "terrace_offset", {i: {"side": "east", "width_ratio": 0.56, "depth_ratio": 0.24}}))
    if (i := idx("sloped_roof_mass")) is not None:
        variants.append(_variant_sequence(sequence, "slope_long", {i: {"x_ratio": 0.58, "y_ratio": 0.96, "upper_ratio": 0.92}}))
        variants.append(_variant_sequence(sequence, "slope_cross", {i: {"x_ratio": 0.82, "y_ratio": 0.68, "upper_ratio": 0.88}}))
    if (i := idx("taper")) is not None:
        variants.append(_variant_sequence(sequence, "taper_sharp", {i: {"top_ratio": 0.62, "x_ratio": 0.62, "y_ratio": 0.70}}))

    deduped: list[VerbSequence] = []
    seen: set[tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]]] = set()
    for item in variants:
        key = (
            item.name,
            tuple(
                (call.verb, tuple(sorted((str(k), str(v)) for k, v in call.params.items())))
                for call in item.calls
            ),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return tuple(deduped)


def generate_grammar_variants(base_footprint: Polygon, *, building_type: str = "") -> list[MorphologyVariant]:
    variants: list[MorphologyVariant] = []
    # This experimental archive currently fails the strict visual box-bias
    # benchmark. Do not let it displace the stronger grammar/agent population
    # in live legal generation until it passes that gate.
    if os.getenv("MAAS_ENABLE_EXPERIMENTAL_CREATIVE_ARCHIVE") == "1":
        from backend.app.modules.design.generation.maas.program_massing import creative_archive_sequences
        for sequence in creative_archive_sequences(base_footprint, target_count=20):
            variant = interpret_sequence(base_footprint, sequence)
            if variant is not None:
                variants.append(variant)
    agent_sequences = list(load_agent_proposal_sequences())
    fixture_sequences = list(SEQUENCES)
    program_sequences: tuple[VerbSequence, ...] = ()
    if building_type:
        from backend.app.modules.design.generation.maas.program_massing import program_seed_sequences, resolve_program_profile
        program_sequences = program_seed_sequences(building_type)
        profile_id = str(resolve_program_profile(building_type).get("id") or "generic")
        fixture_names_by_profile = {
            "neighborhood_living": {
                "grammar_sunlight_multi_step", "grammar_bar_notch_grade",
                "grammar_clean_podium_bar", "grammar_clean_courtyard_block",
                "grammar_clean_shifted_slab", "grammar_sloped_roof_envelope",
            },
            "gymnasium": {
                "grammar_bar_notch_grade", "grammar_clean_podium_bar",
                "grammar_clean_shifted_slab", "grammar_sloped_roof_envelope",
            },
            "cultural": {
                "grammar_courtyard_lift_taper", "grammar_diagonal_step_connector",
                "grammar_clean_courtyard_block", "grammar_sloped_roof_envelope",
            },
        }
        agent_names_by_profile = {
            "neighborhood_living": {"agent_gallery_bar_piloti_court", "agent_east_terrace_bar"},
            "gymnasium": {"agent_sawtooth_roof_mass", "agent_low_campus_cluster"},
            "cultural": {"agent_courtyard_bridge_ring", "agent_oma_diagonal_plate"},
        }
        if profile_id in fixture_names_by_profile:
            fixture_sequences = [item for item in fixture_sequences if item.name in fixture_names_by_profile[profile_id]]
            agent_sequences = [item for item in agent_sequences if item.name in agent_names_by_profile[profile_id]]

    for sequence in agent_sequences:
        variant = interpret_sequence(base_footprint, sequence)
        if variant is not None:
            variants.append(variant)
    for sequence in fixture_sequences:
        for expanded_sequence in _deterministic_fixture_parameter_sweeps(sequence):
            variant = interpret_sequence(base_footprint, expanded_sequence)
            if variant is not None:
                variants.append(variant)
    for sequence in program_sequences:
        variant = interpret_sequence(base_footprint, sequence)
        if variant is not None:
            variants.append(variant)
    return variants


__all__ = ["generate_grammar_variants", "interpret_sequence"]

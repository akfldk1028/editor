"""Compile MAAS verb sequences into ARR-native source mass geometry.

The clone/MAAS compiler emits OpenSCAD text. This compiler keeps ARR's legal
pipeline as the source of truth by producing Shapely polygons and section
volume hints that can be repaired and evaluated by the existing optimizer.
"""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, pi, radians, sin, sqrt
from typing import Any

from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.llm_proposals import LLM_PARAMETER_SOURCE
from backend.app.modules.design.generation.maas.morphology_operators import MorphologyVariant
from backend.app.modules.design.generation.maas.program_massing.assembly import program_component_family, program_component_specs
from backend.app.modules.design.generation.maas.program_massing.book_projection import book_projection_calls, book_projection_scope
from backend.app.modules.design.generation.maas.program_massing.book_scope import materialize_book_scope
from backend.app.modules.design.generation.maas.program_massing.section_graph import program_section_graph_from_sequence
from backend.app.modules.design.generation.maas.source_geometry.formal_principles import compile_formal_principle_volumes, normalize_formal_principle
from backend.app.modules.design.generation.maas.source_geometry.genome import build_massing_genome
from backend.app.modules.design.generation.maas.source_geometry.graph_materializer import is_graph_native, materialize_graph_states
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface, SourceVolume, VerbTrace
from backend.app.modules.design.generation.maas.source_geometry.coherence import evaluate_source_volume_coherence
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import repair_source_polygon
from backend.app.modules.design.generation.maas.source_geometry.section_fields import build_section_loft_field
from backend.app.modules.design.generation.maas.source_geometry.oblique_fields import build_oblique_envelope_field
from backend.app.modules.design.generation.maas.source_geometry.operative_kernels import BOOK_KERNEL_VERBS, apply_book_plan_kernel
from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph, graph_from_sequence
from backend.app.modules.design.generation.maas.source_geometry.rule_priors import finalize_rule_evidence, get_rule_prior, init_rule_evidence, rule_bounds, rule_default


DEFAULT_PARAMETER_SOURCE = "arr_compiler_default"

CANONICAL_SOURCE_FAMILIES = {
    "courtyard",
    "void_notch",
    "split",
    "diagonal_connect",
    "array_cluster",
    "offset",
    "reflected_pair",
    "slender_bar",
    "bend",
    "interlock",
    "overlap",
    "branch",
    "pinch",
    "embed",
    "expand",
    "extrude",
    "inflate",
    "merge",
    "nest",
    "oblique_transform",
    "sloped_roof",
    "terrace_link",
    "stepback_tower",
}

FAMILY_HINT_PRIORITY = (
    "reflected_pair",
    "extrude",
    "inflate",
    "merge",
    "embed",
    "nest",
    "overlap",
    "offset",
    "branch",
    "pinch",
    "bend",
    "interlock",
    "array_cluster",
    "courtyard",
    "void_notch",
    "split",
    "diagonal_connect",
    "sloped_roof",
    "terrace_link",
    "slender_bar",
    "stepback_tower",
)

TYPOLOGY_FAMILY_ALIASES = {
    "cluster": "array_cluster",
    "array": "array_cluster",
    "bridge": "diagonal_connect",
    "connector": "diagonal_connect",
    "bar_slab": "slender_bar",
    "bar": "slender_bar",
    "bent": "bend",
    "roof_envelope": "sloped_roof",
    "roof": "sloped_roof",
    "void_carve": "void_notch",
    "void": "void_notch",
    "nested": "nest",
    "reflect": "reflected_pair",
    "reflected": "reflected_pair",
    "cave": "void_notch",
    "carve": "void_notch",
    "pinching": "pinch",
    "branching": "branch",
    "pack": "array_cluster",
    "join": "diagonal_connect",
    "intersect": "interlock",
    "skew": "oblique_transform",
    "twist": "oblique_transform",
    "rotate": "oblique_transform",
    "shear": "oblique_transform",
    "lodge": "nest",
    "compress": "slender_bar",
    "fracture": "split",
    "extract": "void_notch",
    "inscribe": "courtyard",
    "puncture": "courtyard",
}


def _param(
    params: dict[str, Any],
    key: str,
    default: Any,
    provenance: list[dict[str, Any]],
    *,
    sequence_source: str,
) -> Any:
    """Read a design parameter and record whether it was authored or defaulted."""
    if key in params:
        value = params[key]
        source = sequence_source
        used_default = False
    else:
        value = default
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
    provenance.append({
        "key": key,
        "value": value,
        "source": source,
        "used_default": used_default,
    })
    return value


def _normalise_family_name(value: Any) -> str | None:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return None
    token = TYPOLOGY_FAMILY_ALIASES.get(token, token)
    return token if token in CANONICAL_SOURCE_FAMILIES else None


def _declared_family(sequence: VerbSequence) -> str | None:
    raw_name = sequence.name.lower()
    for family in FAMILY_HINT_PRIORITY:
        if family in raw_name:
            return family
    for alias, family in sorted(TYPOLOGY_FAMILY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in raw_name:
            return family
    for note in sequence.notes:
        if not isinstance(note, str) or not note.startswith("typology="):
            continue
        direct = _normalise_family_name(note.split("=", 1)[1])
        if direct:
            return direct
        raw = note.split("=", 1)[1].lower().replace("-", "_").replace(" ", "_")
        for family in FAMILY_HINT_PRIORITY:
            if family in raw:
                return family
    return None


def _note_value(sequence: VerbSequence, key: str) -> str:
    prefix = f"{key}="
    for note in sequence.notes:
        if isinstance(note, str) and note.startswith(prefix):
            return note.split("=", 1)[1].strip()
    return ""


def _evolution_family_override(sequence: VerbSequence) -> str | None:
    if _note_value(sequence, "evolution_operator") != "critic_section_mutation":
        return None
    family = _normalise_family_name(_note_value(sequence, "evolution_family_override"))
    if family in {"diagonal_connect", "terrace_link", "sloped_roof"}:
        return family
    return None


def _family_formal_principle(family: str | None, current: str | None) -> str:
    current = normalize_formal_principle(current)
    family = str(family or "")
    family_principle = {
        "split": "split_bridge_connector",
        "diagonal_connect": "split_bridge_connector",
        "terrace_link": "terraced_ribbon_section",
        "sloped_roof": "folded_section",
        "bend": "continuous_ribbon_field",
        "interlock": "torqued_stack",
        "branch": "torqued_stack",
        "pinch": "torqued_stack",
        "oblique_transform": "torqued_stack",
        "inflate": "folded_section",
        "offset": "stacked_shifted_platforms",
        "array_cluster": "stacked_shifted_platforms",
        "reflected_pair": "stacked_shifted_platforms",
        "stack": "stacked_shifted_platforms",
        "courtyard": "carved_atrium",
        "nest": "carved_atrium",
        "embed": "carved_monolith",
        "void_notch": "carved_monolith",
        "extrude": "slender_podium_tower",
        "slender_bar": "slender_podium_tower",
    }.get(family, "")
    # Family is derived from the operations that actually compiled.  A free
    # LLM label such as ``folded_section`` must not override incompatible
    # geometry and collapse branch/bend/array/courtyard populations into one
    # formal bucket.  Explicit principles remain authoritative only when no
    # executable family mapping exists or when they agree with it.
    if family_principle:
        return family_principle
    return current


def _family_from_mass_language(value: str) -> str | None:
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    language_to_family = {
        "courtyard_atrium": "courtyard",
        "notched_void": "void_notch",
        "split_bridge": "split",
        "diagonal_connector": "diagonal_connect",
        "array_cluster": "array_cluster",
        "offset_twin_bar": "offset",
        "reflected_court_pair": "reflected_pair",
        "bar_notch_terrace": "slender_bar",
        "bend_ribbon": "bend",
        "cross_interlock": "interlock",
        "overlap_slabs": "overlap",
        "branch_taper": "branch",
        "pinched_waist": "pinch",
        "embedded_void": "embed",
        "extruded_fin": "extrude",
        "nested_atrium_stack": "nest",
        "nested_stack": "nest",
        "sloped_roof": "sloped_roof",
        "roof_cap": "sloped_roof",
        "roof_section": "sloped_roof",
        "section_cap": "sloped_roof",
        "terrace_ribbon": "terrace_link",
        "terrace": "terrace_link",
        "side_terrace": "terrace_link",
        "ribbon": "terrace_link",
        "bridge": "diagonal_connect",
        "diagonal_bridge": "diagonal_connect",
        "connector": "diagonal_connect",
        "court_liner": "courtyard",
        "court": "courtyard",
        "atrium": "courtyard",
        "void": "void_notch",
        "notch": "void_notch",
        "offset_spine": "offset",
        "spine": "offset",
    }
    return language_to_family.get(token) or _normalise_family_name(token)


def _sequence_supports_declared_family(sequence: VerbSequence, declared_family: str | None) -> bool:
    if not declared_family:
        return False
    verbs = {call.verb for call in sequence.calls}
    family_verbs = {
        "courtyard": {"courtyard"},
        "void_notch": {"notch", "cave"},
        "split": {"split"},
        "diagonal_connect": {"diagonal_connect"},
        "array_cluster": {"array"},
        "offset": {"offset"},
        "reflected_pair": {"reflect"},
        "slender_bar": {"bar"},
        "bend": {"bend"},
        "interlock": {"interlock"},
        "overlap": {"overlap"},
        "branch": {"branch"},
        "pinch": {"pinch"},
        "embed": {"embed"},
        "expand": {"expand"},
        "extrude": {"extrude"},
        "inflate": {"inflate"},
        "merge": {"merge"},
        "nest": {"nest", "stack"},
        "oblique_transform": {"skew", "twist", "rotate", "shear"},
        "sloped_roof": {"sloped_roof_mass", "grade", "taper"},
        "terrace_link": {"terrace_link"},
        "stepback_tower": {"lift", "step_envelope"},
    }
    return bool(verbs & family_verbs.get(declared_family, set()))


def _graph_primary_family(component_graph: MassComponentGraph) -> str | None:
    """Resolve the executable family from the graph's sole primary role.

    LLM names and language notes are provenance, not execution authority.  A
    graph whose primary is ``bend`` must not become an offset-box recipe just
    because an optional support or its prose contains ``offset_twin_bar``.
    """
    primary = next((node for node in component_graph.nodes if node.role == "primary"), None)
    if primary is None:
        return None
    return {
        "bar": "slender_bar",
        "array": "array_cluster",
        "reflect": "reflected_pair",
        "sloped_roof_mass": "sloped_roof",
        "notch": "void_notch",
        "cave": "void_notch",
        "carve": "void_notch",
        "compress": "slender_bar",
        "extract": "void_notch",
        "fracture": "split",
        "inflate": "inflate",
        "inscribe": "courtyard",
        "intersect": "interlock",
        "join": "diagonal_connect",
        "lodge": "nest",
        "merge": "merge",
        "pack": "array_cluster",
        "puncture": "courtyard",
        "rotate": "oblique_transform",
        "shear": "oblique_transform",
        "skew": "oblique_transform",
        "twist": "oblique_transform",
        "lift": "stepback_tower",
        "step_envelope": "stepback_tower",
    }.get(primary.operation.verb, _normalise_family_name(primary.operation.verb))


def _param_float(
    params: dict[str, Any],
    key: str,
    default: float,
    provenance: list[dict[str, Any]],
    *,
    sequence_source: str,
) -> float:
    raw = params.get(key, default)
    if key in params:
        source = sequence_source
        used_default = False
    else:
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
        provenance.append({
            "key": key,
            "value": value,
            "source": source,
            "used_default": used_default,
            "reason": "invalid_float",
        })
        return value
    provenance.append({
        "key": key,
        "value": value,
        "source": source,
        "used_default": used_default,
    })
    return value


def _param_float_any(
    params: dict[str, Any],
    keys: tuple[str, ...],
    default: float,
    provenance: list[dict[str, Any]],
    *,
    canonical_key: str,
    sequence_source: str,
) -> float:
    for key in keys:
        if key in params:
            value = _param_float(params, key, default, provenance, sequence_source=sequence_source)
            if key != canonical_key and provenance:
                provenance[-1]["key"] = canonical_key
                provenance[-1]["alias_key"] = key
            return value
    return _param_float(params, canonical_key, default, provenance, sequence_source=sequence_source)


def _param_int(
    params: dict[str, Any],
    key: str,
    default: int,
    provenance: list[dict[str, Any]],
    *,
    sequence_source: str,
) -> int:
    raw = params.get(key, default)
    if key in params:
        source = sequence_source
        used_default = False
    else:
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(default)
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
        provenance.append({
            "key": key,
            "value": value,
            "source": source,
            "used_default": used_default,
            "reason": "invalid_int",
        })
        return value
    provenance.append({
        "key": key,
        "value": value,
        "source": source,
        "used_default": used_default,
    })
    return value


def _param_int_any(
    params: dict[str, Any],
    keys: tuple[str, ...],
    default: int,
    provenance: list[dict[str, Any]],
    *,
    canonical_key: str,
    sequence_source: str,
) -> int:
    for key in keys:
        if key in params:
            value = _param_int(params, key, default, provenance, sequence_source=sequence_source)
            if key != canonical_key and provenance:
                provenance[-1]["key"] = canonical_key
                provenance[-1]["alias_key"] = key
            return value
    return _param_int(params, canonical_key, default, provenance, sequence_source=sequence_source)


def _param_str(
    params: dict[str, Any],
    key: str,
    default: str,
    provenance: list[dict[str, Any]],
    *,
    sequence_source: str,
) -> str:
    return str(_param(params, key, default, provenance, sequence_source=sequence_source))


def _param_str_any(
    params: dict[str, Any],
    keys: tuple[str, ...],
    default: str,
    provenance: list[dict[str, Any]],
    *,
    canonical_key: str,
    sequence_source: str,
) -> str:
    for key in keys:
        if key in params:
            value = _param_str(params, key, default, provenance, sequence_source=sequence_source)
            if key != canonical_key and provenance:
                provenance[-1]["key"] = canonical_key
                provenance[-1]["alias_key"] = key
            return value
    return _param_str(params, canonical_key, default, provenance, sequence_source=sequence_source)


def _param_position(
    params: dict[str, Any],
    key: str,
    default: list[float],
    provenance: list[dict[str, Any]],
    *,
    sequence_source: str,
) -> list[float]:
    raw = params.get(key, default)
    source = sequence_source if key in params else DEFAULT_PARAMETER_SOURCE
    used_default = key not in params
    if not isinstance(raw, list) or len(raw) < 2:
        raw = default
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
        reason = "invalid_position"
    else:
        reason = None
    try:
        value = [float(raw[0]), float(raw[1]), float(raw[2] if len(raw) > 2 else 0.0)]
    except (TypeError, ValueError):
        value = list(default)
        source = DEFAULT_PARAMETER_SOURCE
        used_default = True
        reason = "invalid_position"
    record = {"key": key, "value": value, "source": source, "used_default": used_default}
    if reason:
        record["reason"] = reason
    provenance.append(record)
    return value


def _largest_polygon(geometry) -> Polygon | None:
    if geometry is None or geometry.is_empty:
        return None
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty:
        return None
    if isinstance(geometry, Polygon):
        return geometry if geometry.area >= 1.0 else None
    if isinstance(geometry, MultiPolygon):
        polygons = [poly for poly in geometry.geoms if poly.area >= 1.0]
        return max(polygons, key=lambda poly: poly.area) if polygons else None
    return None


def _clean(poly) -> Polygon | None:
    return repair_source_polygon(poly, minimum_area=1.0)


def _bounds(poly: Polygon) -> tuple[float, float, float, float, float, float]:
    minx, miny, maxx, maxy = poly.bounds
    return minx, miny, maxx, maxy, maxx - minx, maxy - miny


def _edge_cut(poly: Polygon, side: str, width_ratio: float, depth_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    if side in {"north", "south"}:
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


def _corner_notch(poly: Polygon, corner: str, ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    x0, x1 = (maxx - width * ratio, maxx) if "+x" in corner else (minx, minx + width * ratio)
    y0, y1 = (maxy - depth * ratio, maxy) if "+y" in corner else (miny, miny + depth * ratio)
    return _clean(poly.difference(box(x0, y0, x1, y1)))


def _courtyard(poly: Polygon, ratio: float, open_side: str = "closed") -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    court = box(
        minx + width * (0.5 - ratio / 2),
        miny + depth * (0.5 - ratio / 2),
        minx + width * (0.5 + ratio / 2),
        miny + depth * (0.5 + ratio / 2),
    )
    side = str(open_side or "closed").strip().lower()
    if side in {"south", "north", "east", "west"}:
        mouth_ratio = max(0.42, min(0.72, ratio * 1.8))
        if side in {"south", "north"}:
            mouth_width = width * ratio * mouth_ratio
            x0, x1 = (minx + maxx - mouth_width) / 2, (minx + maxx + mouth_width) / 2
            y0, y1 = (miny, court.bounds[3]) if side == "south" else (court.bounds[1], maxy)
        else:
            mouth_depth = depth * ratio * mouth_ratio
            y0, y1 = (miny + maxy - mouth_depth) / 2, (miny + maxy + mouth_depth) / 2
            x0, x1 = (minx, court.bounds[2]) if side == "west" else (court.bounds[0], maxx)
        court = unary_union((court, box(x0, y0, x1, y1)))
    return _clean(poly.difference(court))


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
        shaped = translate(scale(poly, xfact=1.0, yfact=factor, origin="centroid"), yoff=depth * shift)
    else:
        shaped = translate(scale(poly, xfact=factor, yfact=1.0, origin="centroid"), xoff=width * shift)
    return _clean(shaped.intersection(poly))


def _branch(poly: Polygon, angle: float, trunk_ratio: float, arm_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    trunk = box(cx - width * trunk_ratio / 2, miny, cx + width * trunk_ratio / 2, maxy)
    arm_len = max(width, depth) * 0.82
    arm_w = min(width, depth) * arm_ratio
    arm = box(cx - arm_w / 2, cy - arm_len * 0.08, cx + arm_w / 2, cy + arm_len * 0.62)
    return _clean(unary_union([trunk, rotate(arm, angle, origin=(cx, cy)), rotate(arm, -angle, origin=(cx, cy))]).intersection(poly))


def _interlock(poly: Polygon, angle: float, bar_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    bar_w = min(width, depth) * bar_ratio
    long = max(width, depth) * 1.32
    a = box(cx - long / 2, cy - bar_w / 2, cx + long / 2, cy + bar_w / 2)
    b = box(cx - bar_w / 2, cy - long / 2, cx + bar_w / 2, cy + long / 2)
    return _clean(unary_union([rotate(a, angle, origin=(cx, cy)), rotate(b, angle, origin=(cx, cy))]).intersection(poly))


def _overlap(poly: Polygon, axis: str, slab_ratio: float, shift_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    if axis == "x":
        slab = box(cx - width * 0.38, cy - depth * slab_ratio / 2, cx + width * 0.38, cy + depth * slab_ratio / 2)
        pieces = [translate(slab, xoff=-width * shift_ratio, yoff=-depth * 0.12), translate(slab, xoff=width * shift_ratio, yoff=depth * 0.12)]
    else:
        slab = box(cx - width * slab_ratio / 2, cy - depth * 0.38, cx + width * slab_ratio / 2, cy + depth * 0.38)
        pieces = [translate(slab, xoff=-width * 0.12, yoff=-depth * shift_ratio), translate(slab, xoff=width * 0.12, yoff=depth * shift_ratio)]
    return _clean(unary_union(pieces).intersection(poly))


def _pinch(poly: Polygon, axis: str, waist_ratio: float, depth_ratio: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    if axis == "x":
        cut_w = width * (1.0 - waist_ratio) / 2
        cut_d = depth * depth_ratio
        y0 = miny + (depth - cut_d) / 2
        cutters = [box(minx, y0, minx + cut_w, y0 + cut_d), box(maxx - cut_w, y0, maxx, y0 + cut_d)]
    else:
        cut_d = depth * (1.0 - waist_ratio) / 2
        cut_w = width * depth_ratio
        x0 = minx + (width - cut_w) / 2
        cutters = [box(x0, miny, x0 + cut_w, miny + cut_d), box(x0, maxy - cut_d, x0 + cut_w, maxy)]
    return _clean(poly.difference(unary_union(cutters)))


def _bend(poly: Polygon, axis: str, angle: float, factor: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    if axis == "x":
        bar = box(cx - width * 0.42, cy - depth * factor / 2, cx + width * 0.42, cy + depth * factor / 2)
        offset = translate(bar, yoff=depth * 0.16)
    else:
        bar = box(cx - width * factor / 2, cy - depth * 0.42, cx + width * factor / 2, cy + depth * 0.42)
        offset = translate(bar, xoff=width * 0.16)
    return _clean(unary_union([
        rotate(bar, angle, origin=(cx, cy)),
        rotate(offset, angle * 0.45, origin=(cx, cy)),
    ]).intersection(poly))


def _embed(poly: Polygon, guest_scale: float, position: list[Any] | tuple[Any, ...]) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    px = float(position[0]) if len(position) > 0 else 0.0
    py = float(position[1]) if len(position) > 1 else 0.0
    cx = poly.centroid.x + width * px
    cy = poly.centroid.y + depth * py
    guest = box(
        cx - width * guest_scale / 2,
        cy - depth * guest_scale / 2,
        cx + width * guest_scale / 2,
        cy + depth * guest_scale / 2,
    )
    return _clean(poly.difference(guest))


def _extrude(poly: Polygon, axis: str, length: float, size: float) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    cx, cy = poly.centroid.x, poly.centroid.y
    core = scale(poly, xfact=0.62, yfact=0.72, origin="centroid")
    if axis == "x":
        fin = box(cx - width * size / 2, miny, cx + width * size / 2, miny + depth * (0.58 + length * 0.18))
    else:
        fin = box(minx, cy - depth * size / 2, minx + width * (0.58 + length * 0.18), cy + depth * size / 2)
    return _clean(unary_union([core, fin]).intersection(poly))


def _nest(poly: Polygon, inner_scale: float) -> Polygon | None:
    return _embed(poly, max(0.18, min(0.58, inner_scale)), (0.0, 0.0, 0.0))


def _shift(poly: Polygon, axis: str, distance_ratio: float, clip: Polygon) -> Polygon | None:
    minx, miny, maxx, maxy, width, depth = _bounds(clip)
    moved = translate(poly, xoff=width * distance_ratio if axis == "x" else 0.0, yoff=depth * distance_ratio if axis == "y" else 0.0)
    return _clean(moved.intersection(clip))


def _offset_units(poly: Polygon, axis: str, distance_ratio: float, other_scale: float) -> list[Polygon]:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    base_unit = _clean(scale(poly, xfact=other_scale, yfact=other_scale, origin="centroid").intersection(poly))
    if base_unit is None:
        return [poly]
    moved = translate(
        base_unit,
        xoff=width * distance_ratio if axis == "x" else 0.0,
        yoff=depth * distance_ratio if axis == "y" else 0.0,
    )
    moved = _clean(moved.intersection(poly))
    units = [base_unit]
    if moved is not None:
        units.append(moved)
    return units


def _array_units(
    poly: Polygon,
    axis: str,
    count: int,
    spacing_ratio: float,
    unit_scale: float,
    hierarchy_ratio: float = 0.18,
    stagger_ratio: float = 0.12,
) -> list[Polygon]:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    count = max(2, min(6, count))
    # ``unit_scale`` describes the cross-axis depth of each member, not the
    # size of a full-parcel copy.  The former implementation scaled the whole
    # parcel by e.g. 0.78 and translated four copies by 0.19 of the span.  All
    # copies overlapped and unary-union collapsed the authored cluster into a
    # single box.  Allocate the long axis jointly from n and the requested
    # spacing so every cell is a real, separated mass while remaining derived
    # from the actual parcel envelope.
    span = width if axis == "x" else depth
    cross_span = depth if axis == "x" else width
    gap_fraction = max(0.025, min(0.10, float(spacing_ratio) / count))
    unit_axis_fraction = max(0.08, (1.0 - gap_fraction * (count - 1)) / count)
    cross_fraction = max(0.28, min(0.72, float(unit_scale)))
    hierarchy_ratio = max(0.08, min(0.36, float(hierarchy_ratio)))
    stagger_ratio = max(0.04, min(0.28, float(stagger_ratio)))
    unit_span = span * unit_axis_fraction
    gap = span * gap_fraction
    used = unit_span * count + gap * (count - 1)
    cursor = -used / 2.0 + unit_span / 2.0
    cx, cy = poly.centroid.x, poly.centroid.y
    units: list[Polygon] = []
    for index in range(count):
        along = cursor + index * (unit_span + gap)
        progression = 1.0 - 2.0 * index / max(count - 1, 1)
        member_axis_span = unit_span * (1.0 + progression * hierarchy_ratio * 0.32)
        member_cross_fraction = max(
            0.24,
            min(0.78, cross_fraction * (1.0 + progression * hierarchy_ratio)),
        )
        # The author controls both hierarchy and cross-axis stagger. The
        # compiler derives every dimension from the parcel envelope; there
        # are no named precedent coordinates or fixed building footprints.
        stagger = (
            (1.0 if index % 2 else -1.0)
            * cross_span
            * (1.0 - member_cross_fraction)
            * stagger_ratio
        )
        if axis == "x":
            cell = box(
                cx + along - member_axis_span / 2.0,
                cy + stagger - cross_span * member_cross_fraction / 2.0,
                cx + along + member_axis_span / 2.0,
                cy + stagger + cross_span * member_cross_fraction / 2.0,
            )
        else:
            cell = box(
                cx + stagger - cross_span * member_cross_fraction / 2.0,
                cy + along - member_axis_span / 2.0,
                cx + stagger + cross_span * member_cross_fraction / 2.0,
                cy + along + member_axis_span / 2.0,
            )
        clipped = _clean(cell.intersection(poly))
        if clipped is not None and clipped.area >= max(1.0, poly.area * 0.025):
            units.append(clipped)
    return units or [poly]


def _reflect_units(poly: Polygon, axis: str, gap_ratio: float, unit_scale: float) -> list[Polygon]:
    minx, miny, maxx, maxy, width, depth = _bounds(poly)
    base_unit = _clean(scale(poly, xfact=unit_scale, yfact=unit_scale, origin="centroid").intersection(poly))
    if base_unit is None:
        return [poly]
    offset = (width if axis == "x" else depth) * gap_ratio
    a = translate(base_unit, xoff=-offset if axis == "x" else 0.0, yoff=-offset if axis == "y" else 0.0)
    b = translate(base_unit, xoff=offset if axis == "x" else 0.0, yoff=offset if axis == "y" else 0.0)
    units = []
    for item in (a, b):
        clipped = _clean(item.intersection(poly))
        if clipped is not None:
            units.append(clipped)
    return units or [base_unit]


def _upper_from(poly: Polygon, ratio: float) -> Polygon | None:
    return _clean(scale(poly, xfact=ratio, yfact=ratio, origin="centroid").intersection(poly))


def _piece_from_geometry(
    role: str,
    geom,
    bottom: float,
    top: float,
    verb: str,
    *,
    clip: Polygon,
    min_area: float,
) -> SourceVolume | None:
    shaped = _clean(geom.intersection(clip))
    if shaped is None or shaped.area < min_area:
        return None
    bottom = max(0.0, min(0.94, float(bottom)))
    top = max(bottom + 0.06, min(1.0, float(top)))
    return SourceVolume(role, shaped, bottom, top, verb)


def _rect_piece(
    role: str,
    clip: Polygon,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    bottom: float,
    top: float,
    verb: str,
    *,
    min_area: float,
) -> SourceVolume | None:
    return _piece_from_geometry(role, box(x0, y0, x1, y1), bottom, top, verb, clip=clip, min_area=min_area)


def _rotated_piece(
    role: str,
    clip: Polygon,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    angle: float,
    bottom: float,
    top: float,
    verb: str,
    *,
    min_area: float,
) -> SourceVolume | None:
    cx, cy = clip.centroid.x, clip.centroid.y
    return _piece_from_geometry(
        role,
        rotate(box(x0, y0, x1, y1), angle, origin=(cx, cy)),
        bottom,
        top,
        verb,
        clip=clip,
        min_area=min_area,
    )


def _polygon_piece(
    role: str,
    clip: Polygon,
    coords: list[tuple[float, float]],
    bottom: float,
    top: float,
    verb: str,
    *,
    min_area: float,
) -> SourceVolume | None:
    return _piece_from_geometry(role, Polygon(coords), bottom, top, verb, clip=clip, min_area=min_area)


def _ribbon_piece(
    role: str,
    clip: Polygon,
    points: list[tuple[float, float]],
    width: float,
    bottom: float,
    top: float,
    verb: str,
    *,
    min_area: float,
) -> SourceVolume | None:
    if len(points) < 2 or width <= 0:
        return None
    geom = LineString(points).buffer(width, cap_style=1, join_style=1)
    return _piece_from_geometry(role, geom, bottom, top, verb, clip=clip, min_area=min_area)


def _freeform_piece(
    role: str,
    clip: Polygon,
    centers: list[tuple[float, float]],
    radius: float,
    bottom: float,
    top: float,
    verb: str,
    *,
    min_area: float,
) -> SourceVolume | None:
    if not centers or radius <= 0:
        return None
    blobs = [Point(x, y).buffer(radius, resolution=8) for x, y in centers]
    return _piece_from_geometry(role, unary_union(blobs), bottom, top, verb, clip=clip, min_area=min_area)


def _profile_value(
    params: dict[str, Any],
    keys: tuple[str, ...],
    fallback: float,
    low: float,
    high: float,
    *,
    rule: dict[str, Any] | None = None,
    prior_key: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> float:
    canonical_key = prior_key or keys[0]
    fallback = rule_default(rule, canonical_key, fallback)
    low, high = rule_bounds(rule, canonical_key, (low, high))
    for key in keys:
        if key not in params:
            continue
        try:
            value = float(params[key])
        except (TypeError, ValueError):
            if evidence is not None:
                evidence.setdefault("invalid_params", []).append({
                    "key": canonical_key,
                    "alias_key": key,
                    "raw_value": params.get(key),
                    "reason": "invalid_float",
                })
            continue
        clipped = max(low, min(high, value))
        if evidence is not None:
            evidence.setdefault("llm_authored_params", []).append({
                "key": canonical_key,
                "alias_key": key if key != canonical_key else None,
                "value": round(clipped, 4),
                "source": "llm_arch_language_proposal",
                "bounds": [low, high],
            })
        return clipped
    value = max(low, min(high, float(fallback)))
    if evidence is not None:
        evidence.setdefault("rule_prior_params", []).append({
            "key": canonical_key,
            "value": round(value, 4),
            "source": "architectural_rule_prior",
            "bounds": [low, high],
        })
    return value


def _profile_axis(params: dict[str, Any], fallback: str = "x") -> str:
    axis = str(params.get("axis") or params.get("shift_axis") or fallback).lower()
    return "y" if axis in {"y", "north", "south"} else "x"


def _height_band(
    lower_fraction: float | None,
    upper_ratio: float,
    bottom_offset: float,
    top_offset: float,
) -> tuple[float, float]:
    split = max(0.18, min(0.78, float(lower_fraction if lower_fraction is not None else 0.45)))
    bottom = max(0.0, min(0.88, split * bottom_offset))
    top = max(bottom + 0.08, min(1.0, upper_ratio + (1.0 - upper_ratio) * top_offset))
    return bottom, top


def _family_plan_volumes(
    footprint: Polygon,
    family: str,
    last_verb: str,
    *,
    language_params: dict[str, Any],
    lower_fraction: float | None,
    rule_evidence: dict[str, Any] | None = None,
) -> tuple[SourceVolume, ...]:
    """Decompose plan-language families into distinct source masses.

    These are not zoning constants. They are normalized source-geometry hints
    clipped to the LLM-generated footprint; the legal optimizer still maps them
    into the permitted floor-plate envelope before FAR/BCR/height validation.
    """
    minx, miny, maxx, maxy, width, depth = _bounds(footprint)
    if width <= 0 or depth <= 0:
        return ()
    cx, cy = footprint.centroid.x, footprint.centroid.y
    min_area = max(1.0, footprint.area * 0.035)
    pieces: list[SourceVolume | None] = []
    rule = get_rule_prior(family)
    upper_ratio = _profile_value(language_params, ("upper_ratio", "top_ratio"), 0.82, 0.52, 1.0, rule=rule, prior_key="upper_ratio", evidence=rule_evidence)
    bar_ratio = _profile_value(language_params, ("bar_ratio", "factor", "slab_ratio", "arm_ratio"), 0.30, 0.12, 0.62, rule=rule, prior_key="bar_ratio", evidence=rule_evidence)
    depth_ratio = _profile_value(language_params, ("depth_ratio", "depth", "bridge_ratio"), 0.24, 0.08, 0.58, rule=rule, prior_key="depth_ratio", evidence=rule_evidence)
    side_ratio = _profile_value(language_params, ("width_ratio", "guest_scale", "size", "unit_scale"), 0.34, 0.12, 0.68, rule=rule, prior_key="side_ratio", evidence=rule_evidence)
    gap_ratio = _profile_value(language_params, ("gap_ratio", "gap", "distance_ratio", "distance"), 0.14, 0.03, 0.42, rule=rule, prior_key="gap_ratio", evidence=rule_evidence)
    angle = _profile_value(language_params, ("angle",), 24.0, -55.0, 55.0, rule=rule, prior_key="angle", evidence=rule_evidence)
    axis = _profile_axis(language_params)

    if family == "courtyard":
        court_ratio = _profile_value(language_params, ("ratio", "guest_scale"), 0.24, 0.12, 0.54, rule=rule, prior_key="court_ratio", evidence=rule_evidence)
        band_x = width * max(0.10, (1.0 - court_ratio) / 2)
        band_y = depth * max(0.10, (1.0 - court_ratio) / 2)
        b0, t0 = _height_band(lower_fraction, upper_ratio, 0.0, 0.25)
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.25, 1.0)
        pieces = [
            _rect_piece("courtyard_north_bar", footprint, minx, maxy - band_y, maxx, maxy, b0, t0, last_verb, min_area=min_area),
            _rect_piece("courtyard_south_bar", footprint, minx, miny, maxx, miny + band_y, 0.0, upper_ratio, last_verb, min_area=min_area),
            _rect_piece("courtyard_east_bar", footprint, maxx - band_x, miny, maxx, maxy, b1, t1, last_verb, min_area=min_area),
            _rect_piece("courtyard_west_bar", footprint, minx, miny, minx + band_x, maxy, b0, t1, last_verb, min_area=min_area),
        ]
    elif family == "expand":
        # EXPAND is a sectional operation when the input already occupies the
        # legal envelope: a compact ground plate grows to the full upper
        # plate.  This preserves containment while producing a real 2.5D
        # delta instead of scaling outward and clipping back to no-op.
        inner_ratio = _profile_value(
            language_params,
            ("factor", "lower_ratio"),
            0.78,
            0.58,
            0.90,
            rule=rule,
            prior_key="lower_ratio",
            evidence=rule_evidence,
        )
        lower = repair_source_polygon(
            scale(footprint, xfact=inner_ratio, yfact=inner_ratio, origin="centroid").intersection(footprint),
            minimum_area=min_area,
        )
        if lower is not None:
            pieces = [
                SourceVolume("expand_compact_ground", lower, 0.0, 0.44, last_verb),
                SourceVolume("expand_full_upper", footprint, 0.44, 1.0, last_verb),
            ]
    elif family in {"void_notch", "embed"}:
        cut_ratio = _profile_value(language_params, ("guest_scale", "ratio", "depth_ratio"), 0.32, 0.12, 0.58, rule=rule, prior_key="cut_ratio", evidence=rule_evidence)
        lip = max(0.08, min(0.34, cut_ratio / 2))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.45, 0.75)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.85, 1.0)
        b3, t3 = _height_band(lower_fraction, upper_ratio, 0.20, 0.95)
        pieces = [
            _rect_piece(f"{family}_main_bar", footprint, minx, miny, maxx, cy + depth * lip, 0.0, upper_ratio, last_verb, min_area=min_area),
            _rect_piece(f"{family}_side_lip", footprint, minx, cy - depth * cut_ratio / 2, cx + width * lip, maxy, b1, t1, last_verb, min_area=min_area),
            _rect_piece(f"{family}_raised_liner", footprint, cx - width * lip / 2, miny, maxx, maxy, b2, t2, last_verb, min_area=min_area),
            _rect_piece(f"{family}_void_return", footprint, maxx - width * lip, cy - depth * lip, maxx, maxy, b3, t3, last_verb, min_area=min_area),
        ]
    elif family == "split":
        wing_gap = gap_ratio / 2
        bridge = max(0.06, min(0.30, depth_ratio))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.30, 0.80)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.95, 1.0)
        gap = width * wing_gap
        bearing = width * 0.055
        pieces = [
            _rect_piece("split_west_wing", footprint, minx, miny, cx - gap, maxy, 0.0, upper_ratio, last_verb, min_area=min_area),
            _rect_piece("split_east_wing", footprint, cx + gap, miny, maxx, maxy, b1, t1, last_verb, min_area=min_area),
            _rect_piece(
                "split_bridge_bar",
                footprint,
                cx - gap - bearing,
                cy - depth * bridge / 2,
                cx + gap + bearing,
                cy + depth * bridge / 2,
                b2,
                t2,
                "diagonal_connect" if last_verb == "diagonal_connect" else last_verb,
                min_area=min_area,
            ),
        ]
    elif family == "diagonal_connect":
        connector = max(0.08, min(0.28, depth_ratio))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.80, 1.0)
        pieces = [
            _polygon_piece("polygonal_diagonal_lower_wedge", footprint, [
                (minx, miny),
                (cx + width * gap_ratio, miny),
                (cx + width * (gap_ratio + connector), cy + depth * connector),
                (minx, cy + depth * connector * 1.3),
            ], 0.0, upper_ratio, last_verb, min_area=min_area),
            _polygon_piece("polygonal_diagonal_upper_wedge", footprint, [
                (cx - width * (gap_ratio + connector), cy - depth * connector),
                (maxx, cy - depth * connector * 1.3),
                (maxx, maxy),
                (cx - width * gap_ratio, maxy),
            ], b1, t1, last_verb, min_area=min_area),
            _rotated_piece("diagonal_bridge_bar", footprint, minx, cy - depth * connector / 2, maxx, cy + depth * connector / 2, angle, lower_fraction or 0.32, t1, "diagonal_connect", min_area=min_area),
        ]
    elif family in {"slender_bar", "bend"}:
        bar = max(0.08, min(0.36, bar_ratio / 2))
        return_bar = max(0.08, min(0.32, side_ratio / 2))
        bend_angle = angle if family == "bend" else 0.0
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.45, 0.75)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.85, 1.0)
        long_piece = _rotated_piece(f"{family}_long_bar", footprint, minx, cy - depth * bar, maxx, cy + depth * bar, bend_angle, 0.0, upper_ratio, last_verb, min_area=min_area)
        if family == "bend":
            long_piece = _ribbon_piece("curvilinear_bend_long_ribbon", footprint, [
                (minx, cy - depth * bar),
                (cx - width * 0.18, cy + depth * bar),
                (cx + width * 0.18, cy - depth * bar),
                (maxx, cy + depth * bar),
            ], max(width, depth) * max(0.025, min(0.075, bar)), 0.0, upper_ratio, last_verb, min_area=min_area)
        pieces = [
            long_piece,
            _rotated_piece(f"{family}_return_bar", footprint, cx - width * return_bar, miny, cx + width * return_bar, maxy, -bend_angle if family == "bend" else 90.0, b1, t1, last_verb, min_area=min_area),
            _rect_piece(f"{family}_hinge_core", footprint, cx - width * side_ratio / 2, cy - depth * side_ratio / 2, cx + width * side_ratio / 2, cy + depth * side_ratio / 2, b2, t2, last_verb, min_area=min_area),
        ]
    elif family == "interlock":
        bar = max(0.08, min(0.34, bar_ratio / 2))
        # Read as three attached boxes, not three solids occupying the same
        # vertical space. Small transfer overlaps keep the composition joined
        # while avoiding the collision energy that rejected this whole family.
        b1, t1 = 0.40, 0.76
        b2, t2 = 0.72, 1.0
        pieces = [
            _rotated_piece("interlock_bar_a", footprint, minx, cy - depth * bar, maxx, cy + depth * bar, angle, 0.0, 0.46, last_verb, min_area=min_area),
            _rotated_piece("interlock_bar_b", footprint, cx - width * bar, miny, cx + width * bar, maxy, -angle, b1, t1, last_verb, min_area=min_area),
            _rect_piece("interlock_knuckle", footprint, cx - width * side_ratio / 2, cy - depth * side_ratio / 2, cx + width * side_ratio / 2, cy + depth * side_ratio / 2, b2, t2, last_verb, min_area=min_area),
        ]
    elif family == "overlap":
        slab = max(0.12, min(0.46, bar_ratio))
        shift = max(0.03, min(0.30, gap_ratio))
        b1, t1 = 0.40, 0.78
        pieces = [
            _rect_piece("overlap_slab_low", footprint, minx, miny, cx + width * shift, cy + depth * slab, 0.0, 0.46, last_verb, min_area=min_area),
            _polygon_piece("polygonal_overlap_slab_high", footprint, [
                (cx - width * shift, cy - depth * slab),
                (maxx, cy - depth * slab * 0.65),
                (maxx, maxy),
                (cx + width * shift * 0.4, maxy),
                (cx - width * shift * 1.2, cy + depth * slab * 0.2),
            ], b1, t1, last_verb, min_area=min_area),
            _rect_piece("overlap_shared_core", footprint, cx - width * side_ratio / 2, cy - depth * side_ratio / 2, cx + width * side_ratio / 2, cy + depth * side_ratio / 2, 0.74, 1.0, last_verb, min_area=min_area),
        ]
    elif family == "branch":
        trunk = max(0.08, min(0.36, _profile_value(language_params, ("trunk_ratio",), side_ratio, 0.08, 0.46, rule=rule, prior_key="side_ratio", evidence=rule_evidence) / 2))
        arm = max(0.06, min(0.32, _profile_value(language_params, ("arm_ratio",), bar_ratio, 0.06, 0.42, rule=rule, prior_key="bar_ratio", evidence=rule_evidence) / 2))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.45, 0.90)
        pieces = [
            _rect_piece("branch_trunk", footprint, cx - width * trunk, miny, cx + width * trunk, maxy, 0.0, upper_ratio, last_verb, min_area=min_area),
            _rotated_piece("branch_arm_left", footprint, cx - width * arm, cy - depth * arm, maxx, cy + depth * arm, angle, b1, t1, last_verb, min_area=min_area),
            _rotated_piece("branch_arm_right", footprint, minx, cy - depth * arm, cx + width * arm, cy + depth * arm, -angle, lower_fraction or 0.24, upper_ratio, last_verb, min_area=min_area),
            _freeform_piece("freeform_branch_hinge_canopy", footprint, [
                (cx, cy),
                (cx + width * arm * 1.2, cy + depth * arm),
                (cx - width * arm * 1.2, cy - depth * arm),
            ], max(width, depth) * max(0.035, min(0.10, trunk)), lower_fraction or 0.26, t1, last_verb, min_area=min_area),
        ]
    elif family == "pinch":
        waist = _profile_value(language_params, ("waist_ratio", "factor"), 0.58, 0.28, 0.84, rule=rule, prior_key="waist_ratio", evidence=rule_evidence)
        gap = max(0.02, (1.0 - waist) / 2)
        bridge = max(0.08, min(0.34, depth_ratio))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.40, 0.80)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.85, 1.0)
        pieces = [
            _rect_piece("pinch_lobe_west", footprint, minx, miny, cx - width * gap, maxy, 0.0, upper_ratio, last_verb, min_area=min_area),
            _rect_piece("pinch_lobe_east", footprint, cx + width * gap, miny, maxx, maxy, b1, t1, last_verb, min_area=min_area),
            _rect_piece("pinch_waist_bridge", footprint, minx, cy - depth * bridge / 2, maxx, cy + depth * bridge / 2, b2, t2, last_verb, min_area=min_area),
            _rect_piece("pinch_court_liner", footprint, cx - width * bridge / 2, miny, cx + width * bridge / 2, cy, lower_fraction or 0.24, t1, last_verb, min_area=min_area),
        ]
    elif family == "extrude":
        length = _profile_value(language_params, ("length",), 0.36, 0.12, 0.70, rule=rule, prior_key="length", evidence=rule_evidence)
        fin = max(0.06, min(0.32, side_ratio / 2))
        head = max(0.12, min(0.42, length))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.45, 0.90)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.95, 0.75)
        if axis == "y":
            pieces = [
                _rect_piece("extrude_core", footprint, minx, miny, maxx, cy + depth * fin, 0.0, upper_ratio, last_verb, min_area=min_area),
                _rect_piece("extrude_fin", footprint, cx - width * fin, cy - depth * fin, cx + width * fin, maxy, b1, t1, last_verb, min_area=min_area),
                _rect_piece("extrude_head", footprint, cx - width * head / 2, maxy - depth * head, cx + width * head / 2, maxy, b2, t2, last_verb, min_area=min_area),
            ]
        else:
            pieces = [
                _rect_piece("extrude_core", footprint, minx, miny, cx + width * fin, maxy, 0.0, upper_ratio, last_verb, min_area=min_area),
                _rect_piece("extrude_fin", footprint, cx - width * fin, cy - depth * fin, maxx, cy + depth * fin, b1, t1, last_verb, min_area=min_area),
                _rect_piece("extrude_head", footprint, maxx - width * head, cy - depth * head / 2, maxx, cy + depth * head / 2, b2, t2, last_verb, min_area=min_area),
            ]
    elif family in {"offset", "reflected_pair"}:
        shift = max(0.04, min(0.34, gap_ratio))
        unit = max(0.18, min(0.58, side_ratio))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.45, 0.85)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.80, 1.0)
        if axis == "y":
            pieces = [
                _rect_piece(f"{family}_unit_low", footprint, minx, miny, maxx, cy + depth * unit / 2, 0.0, upper_ratio, last_verb, min_area=min_area),
                _rect_piece(f"{family}_unit_high", footprint, minx, cy - depth * unit / 2, maxx, maxy, b1, t1, last_verb, min_area=min_area),
                _rect_piece(f"{family}_bridge_spine", footprint, cx - width * shift / 2, miny, cx + width * shift / 2, maxy, b2, t2, last_verb, min_area=min_area),
            ]
        else:
            pieces = [
                _rect_piece(f"{family}_unit_low", footprint, minx, miny, cx + width * unit / 2, maxy, 0.0, upper_ratio, last_verb, min_area=min_area),
                _rect_piece(f"{family}_unit_high", footprint, cx - width * unit / 2, miny, maxx, maxy, b1, t1, last_verb, min_area=min_area),
                _rect_piece(f"{family}_bridge_spine", footprint, minx, cy - depth * shift / 2, maxx, cy + depth * shift / 2, b2, t2, last_verb, min_area=min_area),
            ]
    elif family == "nest":
        inner = max(0.18, min(0.58, _profile_value(language_params, ("inner_scale", "guest_scale", "ratio"), 0.42, 0.18, 0.62, rule=rule, prior_key="inner", evidence=rule_evidence)))
        ring = max(0.08, min(0.32, (1.0 - inner) / 2))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.45, 0.85)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.90, 1.0)
        pieces = [
            _rect_piece("nest_outer_shell", footprint, minx, miny, maxx, cy + depth * ring, 0.0, upper_ratio, last_verb, min_area=min_area),
            _rect_piece("nest_inner_volume", footprint, cx - width * inner / 2, cy - depth * inner / 2, cx + width * inner / 2, cy + depth * inner / 2, b1, t1, last_verb, min_area=min_area),
            _rect_piece("nest_liner_spine", footprint, cx - width * ring / 2, miny, cx + width * ring / 2, maxy, b2, t2, last_verb, min_area=min_area),
            _rect_piece("nest_outer_return", footprint, minx, cy - depth * ring, minx + width * ring, maxy, lower_fraction or 0.24, t1, last_verb, min_area=min_area),
        ]
    elif family == "array_cluster":
        count = int(round(_profile_value(language_params, ("n", "count"), 3.0, 2.0, 3.0, rule=rule, prior_key="count", evidence=rule_evidence)))
        unit = max(0.16, min(0.46, _profile_value(language_params, ("unit_scale", "size"), 0.30, 0.16, 0.52, rule=rule, prior_key="unit", evidence=rule_evidence)))
        spacing = max(0.18, min(0.34, _profile_value(language_params, ("spacing_ratio", "spacing"), 0.26, 0.18, 0.38, rule=rule, prior_key="spacing", evidence=rule_evidence)))
        b1, t1 = _height_band(lower_fraction, upper_ratio, 0.35, 0.75)
        b2, t2 = _height_band(lower_fraction, upper_ratio, 0.70, 1.0)
        # A shallow common datum makes the cluster one architectural mass and
        # provides explicit support for the program boxes above it.
        pieces.append(_rect_piece(
            "array_cluster_podium",
            footprint,
            minx,
            miny,
            maxx,
            maxy,
            0.0,
            0.22,
            last_verb,
            min_area=min_area,
        ))
        offsets = [index - (count - 1) / 2 for index in range(count)]
        for index, offset in enumerate(offsets):
            if axis == "y":
                xoff = (index % 2 - 0.5) * width * spacing * 0.55
                yoff = offset * depth * spacing
            else:
                xoff = offset * width * spacing
                yoff = (index % 2 - 0.5) * depth * spacing * 0.55
            cell = box(
                cx + xoff - width * unit / 2,
                cy + yoff - depth * unit / 2,
                cx + xoff + width * unit / 2,
                cy + yoff + depth * unit / 2,
            )
            bottom, top = (0.18, min(0.66, upper_ratio)) if index == 0 else ((b1, t1) if index % 2 else (b2, t2))
            pieces.append(_piece_from_geometry(
                f"array_cluster_cell_{index}",
                cell,
                bottom,
                top,
                last_verb,
                clip=footprint,
                min_area=min_area,
            ))

    volumes = [piece for piece in pieces if piece is not None]
    # Two-part masses (bar+cap, podium+tower, base+step) are complete design
    # languages.  Dropping them here forced downstream selection toward noisy
    # three/four-part compositions.
    return tuple(volumes) if len(volumes) >= 2 else ()


def _compose_secondary_language(
    volumes: tuple[SourceVolume, ...],
    footprint: Polygon,
    primary_family: str | None,
    secondary_family: str | None,
    last_verb: str,
    lower_fraction: float | None,
) -> tuple[SourceVolume, ...]:
    if not volumes or not secondary_family or secondary_family == primary_family:
        return volumes
    if secondary_family in {"legal_envelope_fit", "generic"}:
        return volumes
    if primary_family in {"split", "diagonal_connect"} and secondary_family in {
        "split",
        "diagonal_connect",
        "interlock",
    }:
        # The primary split/bridge principle already materializes its
        # connector. Repeating the semantic label as another site-wide bar
        # produced four colliding boxes and killed the authored graph.
        return volumes
    # Secondary language should clarify an existing composition, not turn a
    # readable primary mass into a six- or seven-piece review fragment.
    if len(volumes) >= 4:
        return volumes
    minx, miny, maxx, maxy, width, depth = _bounds(footprint)
    if width <= 0 or depth <= 0:
        return volumes
    cx, cy = footprint.centroid.x, footprint.centroid.y
    min_area = max(1.0, footprint.area * 0.03)
    split = max(0.24, min(0.62, float(lower_fraction if lower_fraction is not None else 0.40)))
    extra: SourceVolume | None = None

    if secondary_family in {"courtyard", "void_notch", "embed", "nest"}:
        liner = 0.12 if secondary_family != "nest" else 0.18
        extra = _rect_piece(
            f"secondary_{secondary_family}_court_liner",
            footprint,
            minx,
            cy - depth * liner,
            maxx,
            cy + depth * liner,
            split,
            1.0,
            "courtyard" if secondary_family == "courtyard" else "void",
            min_area=min_area,
        )
    elif secondary_family in {"diagonal_connect", "split"}:
        extra = _rotated_piece(
            f"secondary_{secondary_family}_bridge",
            footprint,
            minx,
            cy - depth * 0.07,
            maxx,
            cy + depth * 0.07,
            28.0 if secondary_family == "diagonal_connect" else 0.0,
            split,
            1.0,
            "diagonal_connect" if secondary_family == "diagonal_connect" else "split",
            min_area=min_area,
        )
    elif secondary_family in {"sloped_roof", "terrace_link"}:
        extra = _rect_piece(
            f"secondary_{secondary_family}_section_cap",
            footprint,
            minx,
            maxy - depth * 0.26,
            maxx,
            maxy,
            max(split, 0.46),
            1.0,
            "sloped_roof_mass" if secondary_family == "sloped_roof" else "terrace_link",
            min_area=min_area,
        )
    elif secondary_family in {"offset", "reflected_pair", "array_cluster"}:
        extra = _rect_piece(
            f"secondary_{secondary_family}_alignment_spine",
            footprint,
            cx - width * 0.08,
            miny,
            cx + width * 0.08,
            maxy,
            split,
            1.0,
            "offset",
            min_area=min_area,
        )
    elif secondary_family in {"overlap", "bend", "interlock", "branch", "pinch", "extrude", "slender_bar"}:
        extra = _rect_piece(
            f"secondary_{secondary_family}_ordered_bar",
            footprint,
            minx,
            cy - depth * 0.10,
            maxx,
            cy + depth * 0.10,
            split,
            1.0,
            secondary_family,
            min_area=min_area,
        )

    if extra is None:
        return volumes
    return (*volumes, extra)


def _cap_review_volumes(volumes: tuple[SourceVolume, ...], limit: int = 4) -> tuple[SourceVolume, ...]:
    """Keep a legible primary hierarchy when language composition overproduces pieces."""
    if len(volumes) <= limit:
        return volumes
    # Compiler ordering places the primary/formal series first and optional
    # secondary language last. Preserve the primary series plus one final
    # secondary gesture instead of exposing every helper as a review mass.
    return (*volumes[: limit - 1], volumes[-1])


def _consolidate_section_loft_proxy(
    volumes: tuple[SourceVolume, ...],
    formal_evidence: dict[str, Any] | None,
    formal_volumes: tuple[SourceVolume, ...] = (),
) -> tuple[SourceVolume, ...]:
    """Keep one conservative legal proxy behind one authored loft mesh."""
    section_field = (formal_evidence or {}).get("site_section_field")
    if not isinstance(section_field, dict):
        return volumes
    profiled = [
        volume for volume in volumes
        if volume.verb in {"sloped_roof_mass", "grade", "terrace_link"}
        or any(token in str(volume.role) for token in ("folded", "sloped_roof"))
    ]
    if not profiled:
        return volumes
    # Graph execution can legitimately retain a full-site parent state for a
    # sectional support. The authored folded principle already computes its
    # x/y-ratio plinth; use that bounded solid for legal projection instead of
    # reviving the parent as a 100%-coverage box behind the loft.
    proxy_sources = formal_volumes or tuple(profiled)
    proxy = repair_source_polygon(
        unary_union([volume.footprint for volume in proxy_sources]),
        minimum_area=1.0,
    )
    if proxy is None:
        return volumes
    consolidated = SourceVolume(
        role="primary_agent_section_loft_proxy",
        footprint=proxy,
        bottom_fraction=min(volume.bottom_fraction for volume in proxy_sources),
        top_fraction=max(volume.top_fraction for volume in proxy_sources),
        verb="sloped_roof_mass",
    )
    remaining: list[SourceVolume] = []
    cumulative_section_helpers = {"lift", "taper", "shift", "inset", "expand"}
    for volume in volumes:
        if volume in profiled:
            continue
        if volume.verb in cumulative_section_helpers:
            overlap = float(volume.footprint.intersection(proxy).area) / max(float(volume.footprint.area), 1e-9)
            if overlap >= 0.58:
                # The helper changed the loft's section state; emitting the
                # cumulative state as another solid creates a competing box.
                continue
        remaining.append(volume)
    return (consolidated, *remaining)


def _consolidate_oblique_envelope_proxy(
    volumes: tuple[SourceVolume, ...],
    origin_poly: Polygon,
    formal_evidence: dict[str, Any] | None,
) -> tuple[SourceVolume, ...]:
    """Keep one conservative proxy behind one authored oblique envelope."""
    field_evidence = (formal_evidence or {}).get("site_oblique_envelope")
    if not isinstance(field_evidence, dict):
        return volumes
    field_params = field_evidence.get("field_parameters") if isinstance(field_evidence.get("field_parameters"), dict) else {}
    field = build_oblique_envelope_field(origin_poly, field_params)
    if field is None:
        return volumes
    consolidated = SourceVolume(
        role="primary_agent_oblique_envelope_proxy",
        footprint=field.proxy_footprint,
        bottom_fraction=field.bottom_fraction,
        top_fraction=1.0,
        verb="taper",
    )
    # Ring transformations describe successive states of one envelope. Keep
    # only genuinely external connectors; emitting taper/lift/shift states as
    # independent solids recreates a Lego stack behind the surface mesh.
    remaining = tuple(
        volume for volume in volumes
        if volume.verb in {"diagonal_connect", "terrace_link"}
        and float(volume.footprint.intersection(field.proxy_footprint).area)
        / max(float(volume.footprint.area), 1e-9) < 0.58
    )
    return (consolidated, *remaining)


def _prune_redundant_helper_volumes(volumes: tuple[SourceVolume, ...]) -> tuple[SourceVolume, ...]:
    """Remove helper solids that mostly occupy an already expressed solid.

    Formal-principle recipes use liners, caps and datum cores to describe the
    design intent.  Exposing all of those as translucent review solids makes a
    three-part architectural idea read as six intersecting fragments.  Keep
    the lineage in the genome/rule evidence, but do not materialize a helper
    whose 3D occupancy is already mostly covered by an earlier primary mass.
    """
    kept: list[SourceVolume] = []
    helper_tokens = ("secondary", "liner", "core", "datum", "threshold", "cap")
    for volume in volumes:
        role = str(volume.role or "").lower()
        height = max(float(volume.top_fraction - volume.bottom_fraction), 1e-6)
        redundant = False
        if any(token in role for token in helper_tokens):
            for primary in kept:
                vertical = max(
                    0.0,
                    min(volume.top_fraction, primary.top_fraction)
                    - max(volume.bottom_fraction, primary.bottom_fraction),
                ) / height
                if vertical <= 0.0:
                    continue
                try:
                    planar = float(volume.footprint.intersection(primary.footprint).area) / max(
                        float(volume.footprint.area), 1e-9
                    )
                except Exception:
                    planar = 0.0
                if vertical * planar >= 0.58:
                    redundant = True
                    break
        if not redundant:
            kept.append(volume)
    # Never erase the architectural hierarchy entirely.  The clean-mass gate
    # accepts two coherent solids, while one solid remains a legal fallback.
    return tuple(kept) if len(kept) >= 2 else volumes


def _trace(verb: str, params: dict[str, Any], status: str, footprint: Polygon, upper: Polygon | None, note: str | None = None) -> VerbTrace:
    return VerbTrace(
        verb=verb,
        params=dict(params),
        status=status,
        footprint_area_m2=float(footprint.area),
        upper_area_m2=float(upper.area) if upper is not None else None,
        note=note,
    )


def _volumes(name: str, footprint: Polygon, upper: Polygon | None, lower_fraction: float | None, last_verb: str) -> tuple[SourceVolume, ...]:
    if upper is None:
        return (SourceVolume("single", footprint, 0.0, 1.0, last_verb),)
    split = lower_fraction if lower_fraction is not None else 0.5
    split = max(0.15, min(0.85, split))
    return (
        SourceVolume("lower", footprint, 0.0, split, "base"),
        SourceVolume("upper", upper, split, 1.0, last_verb),
    )


def _layout_volumes(
    footprint: Polygon,
    upper: Polygon | None,
    lower_fraction: float | None,
    last_verb: str,
    *,
    layout_units: list[Polygon],
    stack_spec: dict[str, Any] | None,
    source_family: str | None = None,
    language_params: dict[str, Any] | None = None,
    rule_evidence: dict[str, Any] | None = None,
) -> tuple[SourceVolume, ...]:
    family = str(source_family or "")
    rule = get_rule_prior(family)
    if stack_spec and family in {
        "nest",
        "stepback_tower",
        "sloped_roof",
        "interlock",
        "overlap",
        "diagonal_connect",
        "split",
        "slender_bar",
        "reflected_pair",
        "offset",
    }:
        stack_family = str(stack_spec.get("_source_family") or family)
        max_stack_levels = 6 if stack_family in {"nest", "stepback_tower", "sloped_roof"} else 4
        count = max(2, min(max_stack_levels, int(stack_spec.get("n") or stack_spec.get("levels") or 3)))
        upper_ratio = max(0.45, min(0.92, float(stack_spec.get("upper_ratio") or 0.78)))
        slide_axis = str(stack_spec.get("slide_axis") or "x")
        slide_ratio = float(stack_spec.get("slide_ratio") or 0.0)
        units = layout_units or [upper or footprint]
        volumes: list[SourceVolume] = []
        if family == "interlock":
            minx, miny, maxx, maxy, width, depth = _bounds(footprint)
            cx, cy = footprint.centroid.x, footprint.centroid.y
            for level in range(count):
                bottom = level / count
                top = (level + 1) / count
                scale_factor = max(0.46, upper_ratio ** level)
                plate_w = width * min(0.82, max(0.38, scale_factor))
                plate_d = depth * min(0.70, max(0.30, scale_factor * 0.74))
                dx = width * slide_ratio * (level - (count - 1) / 2) if slide_axis == "x" else 0.0
                dy = depth * slide_ratio * (level - (count - 1) / 2) if slide_axis == "y" else 0.0
                angle = -8.0 + 16.0 * (level / max(1, count - 1))
                plate = rotate(
                    box(cx + dx - plate_w / 2, cy + dy - plate_d / 2, cx + dx + plate_w / 2, cy + dy + plate_d / 2),
                    angle,
                    origin=(cx + dx, cy + dy),
                )
                shaped = _clean(plate.intersection(footprint))
                if shaped is not None:
                    volumes.append(SourceVolume(f"torque_plate_{level}", shaped, bottom, top, "stack"))
            if volumes:
                core = _rect_piece(
                    "torque_stabilizing_core",
                    footprint,
                    cx - width * 0.10,
                    miny,
                    cx + width * 0.10,
                    maxy,
                    0.0,
                    1.0,
                    "interlock",
                    min_area=max(1.0, footprint.area * 0.025),
                )
                if core is not None:
                    volumes.append(core)
            return tuple(volumes)
        for unit_index, unit in enumerate(units):
            current = unit
            for level in range(count):
                bottom = level / count
                top = (level + 1) / count
                scale_factor = upper_ratio ** level
                shaped = _clean(scale(current, xfact=scale_factor, yfact=scale_factor, origin="centroid").intersection(footprint))
                if shaped is None:
                    continue
                if slide_ratio:
                    shaped = _shift(shaped, slide_axis, slide_ratio * level, footprint)
                if shaped is not None:
                    volumes.append(SourceVolume(f"{stack_family}_stack_{unit_index}_{level}", shaped, bottom, top, "stack"))
        if volumes:
            return tuple(volumes)

    if family == "sloped_roof":
        # A full-site rectangular plinth made every folded-roof graph read as
        # another box. Keep the roof family as a bounded object in the site and
        # let the legal projection decide its final permissible footprint.
        base = _clean(scale(footprint, xfact=0.88, yfact=0.88, origin="centroid")) or footprint
        roof = upper if upper is not None else _upper_from(footprint, 0.78)
        roof_params = language_params or {}
        upper_ratio = _profile_value(roof_params, ("upper_ratio", "top_ratio"), 0.82, 0.52, 1.0, rule=rule, prior_key="upper_ratio", evidence=rule_evidence)
        ridge_ratio = _profile_value(roof_params, ("x_ratio", "y_ratio", "factor"), 0.42, 0.16, 0.72, rule=rule, prior_key="ridge_ratio", evidence=rule_evidence)
        axis = _profile_axis(roof_params)
        split = max(0.30, min(0.72, lower_fraction if lower_fraction is not None else 0.56))
        volumes = [SourceVolume("roof_plinth", base, 0.0, split, "base")]
        if roof is not None:
            minx, miny, maxx, maxy, width, depth = _bounds(roof)
            cx, cy = roof.centroid.x, roof.centroid.y
            if axis == "y":
                low = _clean(box(minx, miny, maxx, cy + depth * ridge_ratio / 2).intersection(roof))
                high = _clean(box(minx, cy - depth * ridge_ratio / 2, maxx, maxy).intersection(roof))
            else:
                low = _clean(box(minx, miny, cx + width * ridge_ratio / 2, maxy).intersection(roof))
                high = _clean(box(cx - width * ridge_ratio / 2, miny, maxx, maxy).intersection(roof))
            if low is not None:
                volumes.append(SourceVolume("sloped_roof_low_plane", low, split, max(split + 0.08, upper_ratio), last_verb))
            if high is not None:
                volumes.append(SourceVolume("sloped_roof_high_plane", high, max(split, upper_ratio - 0.16), 1.0, last_verb))
            if len(volumes) < 3:
                if axis == "y":
                    fallback_low = _clean(box(minx, miny, maxx, cy).intersection(base))
                    fallback_high = _clean(box(minx, cy, maxx, maxy).intersection(base))
                else:
                    fallback_low = _clean(box(minx, miny, cx, maxy).intersection(base))
                    fallback_high = _clean(box(cx, miny, maxx, maxy).intersection(base))
                if fallback_low is not None and not any(volume.role == "sloped_roof_low_plane" for volume in volumes):
                    volumes.append(SourceVolume("sloped_roof_low_plane", fallback_low, split, max(split + 0.08, upper_ratio), last_verb))
                if fallback_high is not None and not any(volume.role == "sloped_roof_high_plane" for volume in volumes):
                    volumes.append(SourceVolume("sloped_roof_high_plane", fallback_high, max(split, upper_ratio - 0.16), 1.0, last_verb))
        return tuple(volumes)

    family_volumes = _family_plan_volumes(
        footprint,
        family,
        last_verb,
        language_params=language_params or {},
        lower_fraction=lower_fraction,
        rule_evidence=rule_evidence,
    )
    if family_volumes:
        return family_volumes

    if layout_units:
        split = max(0.20, min(0.70, lower_fraction if lower_fraction is not None else 0.46))
        volumes = []
        for index, unit in enumerate(layout_units):
            unit = _clean(unit.intersection(footprint))
            if unit is None:
                continue
            if family in {"array_cluster", "offset", "reflected_pair", "overlap"}:
                top = max(0.58, min(1.0, 0.82 + 0.09 * ((index + 1) % 3)))
                role_family = "overlap_slab" if family == "overlap" else "unit"
                volumes.append(SourceVolume(f"{role_family}_{index}", unit, 0.0, top, last_verb))
                continue
            top = max(split + 0.12, 1.0 - 0.08 * (index % 3))
            volumes.append(SourceVolume(f"unit_{index}_base", unit, 0.0, split, last_verb))
            upper_unit = _upper_from(unit, 0.72 if upper is None else 0.82)
            if upper_unit is not None:
                volumes.append(SourceVolume(f"unit_{index}_upper", upper_unit, split, top, last_verb))
        if volumes:
            if family in {"offset", "reflected_pair"} and len(layout_units) >= 2:
                minx, miny, maxx, maxy, width, depth = _bounds(footprint)
                cx, cy = footprint.centroid.x, footprint.centroid.y
                params = language_params or {}
                axis = _profile_axis(params)
                bridge_ratio = _profile_value(params, ("bridge_ratio", "gap_ratio", "distance_ratio"), 0.18, 0.06, 0.42, rule=rule, prior_key="gap_ratio", evidence=rule_evidence)
                upper_ratio = _profile_value(params, ("upper_ratio", "top_ratio"), 0.86, 0.58, 1.0, rule=rule, prior_key="upper_ratio", evidence=rule_evidence)
                if axis == "y":
                    bridge_geom = box(minx, cy - depth * bridge_ratio / 2, maxx, cy + depth * bridge_ratio / 2)
                else:
                    bridge_geom = box(cx - width * bridge_ratio / 2, miny, cx + width * bridge_ratio / 2, maxy)
                bridge = _piece_from_geometry(
                    f"{family}_bridge_spine",
                    bridge_geom,
                    split,
                    1.0,
                    last_verb,
                    clip=footprint,
                    min_area=max(1.0, footprint.area * 0.025),
                )
                core = _piece_from_geometry(
                    f"{family}_shared_core",
                    scale(footprint, xfact=max(0.20, min(0.56, bridge_ratio * 1.45)), yfact=max(0.20, min(0.56, bridge_ratio * 1.45)), origin="centroid"),
                    max(0.0, split * 0.65),
                    upper_ratio,
                    last_verb,
                    clip=footprint,
                    min_area=max(1.0, footprint.area * 0.025),
                )
                for extra in (bridge, core):
                    if extra is not None:
                        volumes.append(extra)
            return tuple(volumes)

    return _volumes("source", footprint, upper, lower_fraction, last_verb)


def _surface_points(poly: Polygon, origin: tuple[float, float], z: float) -> tuple[tuple[float, float, float], ...]:
    coords = list(poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return tuple((float(x - origin[0]), float(y - origin[1]), float(z)) for x, y in coords)


def _surface_edges(poly: Polygon, origin: tuple[float, float], z0: float, z1: float) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    coords = list(poly.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    faces: list[tuple[tuple[float, float, float], ...]] = []
    for index, a in enumerate(coords):
        b = coords[(index + 1) % len(coords)]
        faces.append((
            (float(a[0] - origin[0]), float(a[1] - origin[1]), float(z0)),
            (float(b[0] - origin[0]), float(b[1] - origin[1]), float(z0)),
            (float(b[0] - origin[0]), float(b[1] - origin[1]), float(z1)),
            (float(a[0] - origin[0]), float(a[1] - origin[1]), float(z1)),
        ))
    return tuple(faces)


def _source_surfaces(volumes: tuple[SourceVolume, ...], origin_poly: Polygon) -> tuple[SourceSurface, ...]:
    """Build a renderer-neutral source mesh contract from grammar volumes.

    Heights are normalized 0..1 fractions. The legal optimizer later maps these
    volumes into real candidate heights, so this contract records grammar source
    intent without changing FAR/BCR accounting.
    """
    origin = (float(origin_poly.centroid.x), float(origin_poly.centroid.y))
    surfaces: list[SourceSurface] = []
    for volume_index, volume in enumerate(volumes):
        roof = _surface_points(volume.footprint, origin, volume.top_fraction)
        if len(roof) >= 3:
            surfaces.append(SourceSurface(
                role=f"source_roof_{volume.role}",
                volume_role=volume.role,
                verb=volume.verb,
                surface_type="roof_polygon",
                vertices_m=roof,
            ))
        for edge_index, face in enumerate(_surface_edges(volume.footprint, origin, volume.bottom_fraction, volume.top_fraction)):
            surfaces.append(SourceSurface(
                role=f"source_facade_{volume.role}_{edge_index}",
                volume_role=volume.role,
                verb=volume.verb,
                surface_type="facade_quad",
                vertices_m=face,
            ))
    return tuple(surfaces)


def _profiled_component_surfaces(
    specs: tuple[dict[str, Any], ...],
    origin_poly: Polygon,
) -> tuple[SourceSurface, ...]:
    """Build explicit 3D strips for path masses with authored roof profiles."""
    origin = (float(origin_poly.centroid.x), float(origin_poly.centroid.y))
    surfaces: list[SourceSurface] = []
    for spec in specs:
        points = list(spec.get("path_points") or [])
        profile = list(spec.get("roof_profile") or [])
        half_width = float(spec.get("path_width_m") or 0.0)
        width_profile = [float(value) for value in spec.get("path_width_profile_m") or []]
        if len(width_profile) != len(points):
            width_profile = [half_width] * len(points)
        if len(points) < 2 or len(profile) != len(points) or min(width_profile, default=0.0) <= 0:
            continue
        left: list[tuple[float, float]] = []
        right: list[tuple[float, float]] = []
        for index, point in enumerate(points):
            previous = points[max(0, index - 1)]
            following = points[min(len(points) - 1, index + 1)]
            dx = float(following[0]) - float(previous[0])
            dy = float(following[1]) - float(previous[1])
            length = max(hypot(dx, dy), 1e-9)
            nx, ny = -dy / length, dx / length
            local_half_width = width_profile[index]
            left.append((float(point[0]) + nx * local_half_width, float(point[1]) + ny * local_half_width))
            right.append((float(point[0]) - nx * local_half_width, float(point[1]) - ny * local_half_width))
        role = str(spec["role"])
        verb = str(spec["verb"])
        bottom = float(spec["bottom_fraction"])

        def vertex(point: tuple[float, float], z: float) -> tuple[float, float, float]:
            return (point[0] - origin[0], point[1] - origin[1], float(z))

        for index in range(len(points) - 1):
            roof_quad = (
                vertex(left[index], profile[index]),
                vertex(right[index], profile[index]),
                vertex(right[index + 1], profile[index + 1]),
                vertex(left[index + 1], profile[index + 1]),
            )
            surfaces.append(SourceSurface(
                role=f"source_profiled_roof_{role}_{index}",
                volume_role=role,
                verb=verb,
                surface_type="profiled_roof_strip",
                vertices_m=roof_quad,
            ))
            for side_name, bank in (("left", left), ("right", right)):
                surfaces.append(SourceSurface(
                    role=f"source_profiled_facade_{role}_{side_name}_{index}",
                    volume_role=role,
                    verb=verb,
                    surface_type="profiled_facade_quad",
                    vertices_m=(
                        vertex(bank[index], bottom),
                        vertex(bank[index + 1], bottom),
                        vertex(bank[index + 1], profile[index + 1]),
                        vertex(bank[index], profile[index]),
                    ),
                ))
        for end_name, end_index in (("start", 0), ("end", len(points) - 1)):
            surfaces.append(SourceSurface(
                role=f"source_profiled_end_{role}_{end_name}",
                volume_role=role,
                verb=verb,
                surface_type="profiled_end_quad",
                vertices_m=(
                    vertex(left[end_index], bottom),
                    vertex(right[end_index], bottom),
                    vertex(right[end_index], profile[end_index]),
                    vertex(left[end_index], profile[end_index]),
                ),
            ))
    return tuple(surfaces)


def _section_loft_surfaces(
    rows: tuple[tuple[tuple[float, float, float], ...], ...],
    *,
    origin_poly: Polygon,
    role: str,
    verb: str,
    bottom_fraction: float,
) -> tuple[SourceSurface, ...]:
    """Convert one editable section field into a watertight review mesh."""
    if len(rows) < 2 or min((len(row) for row in rows), default=0) < 2:
        return ()
    origin = (float(origin_poly.centroid.x), float(origin_poly.centroid.y))

    def vertex(point: tuple[float, float, float], z: float | None = None) -> tuple[float, float, float]:
        return point[0] - origin[0], point[1] - origin[1], float(point[2] if z is None else z)

    surfaces: list[SourceSurface] = []
    for row_index in range(len(rows) - 1):
        for section_index in range(min(len(rows[row_index]), len(rows[row_index + 1])) - 1):
            surfaces.append(SourceSurface(
                role=f"source_section_loft_roof_{role}_{row_index}_{section_index}",
                volume_role=role,
                verb=verb,
                surface_type="profiled_section_loft_roof",
                vertices_m=(
                    vertex(rows[row_index][section_index]),
                    vertex(rows[row_index][section_index + 1]),
                    vertex(rows[row_index + 1][section_index + 1]),
                    vertex(rows[row_index + 1][section_index]),
                ),
                operator="loft",
                semantic_patch_id=f"{role}:section_loft_roof",
            ))
    boundary_runs = (
        tuple(row[0] for row in rows),
        tuple(row[-1] for row in rows),
        rows[0],
        rows[-1],
    )
    for boundary_index, run in enumerate(boundary_runs):
        for edge_index in range(len(run) - 1):
            left, right = run[edge_index], run[edge_index + 1]
            surfaces.append(SourceSurface(
                role=f"source_section_loft_facade_{role}_{boundary_index}_{edge_index}",
                volume_role=role,
                verb=verb,
                surface_type="profiled_section_loft_facade",
                vertices_m=(
                    vertex(left, bottom_fraction),
                    vertex(right, bottom_fraction),
                    vertex(right),
                    vertex(left),
                ),
                operator="loft",
                semantic_patch_id=f"{role}:section_loft_facade",
            ))
    return tuple(surfaces)


def _oblique_envelope_surfaces(
    rings: tuple[tuple[tuple[float, float, float], ...], ...],
    *,
    origin_poly: Polygon,
    role: str,
) -> tuple[SourceSurface, ...]:
    """Materialize matching polygon rings as one clean oblique mesh."""
    if len(rings) < 2 or min((len(ring) for ring in rings), default=0) < 3:
        return ()
    vertex_count = min(len(ring) for ring in rings)
    origin = (float(origin_poly.centroid.x), float(origin_poly.centroid.y))

    def vertex(point: tuple[float, float, float]) -> tuple[float, float, float]:
        return point[0] - origin[0], point[1] - origin[1], float(point[2])

    surfaces: list[SourceSurface] = []
    for ring_index in range(len(rings) - 1):
        lower, upper = rings[ring_index], rings[ring_index + 1]
        for edge_index in range(vertex_count):
            next_index = (edge_index + 1) % vertex_count
            surfaces.append(SourceSurface(
                role=f"source_oblique_envelope_side_{role}_{ring_index}_{edge_index}",
                volume_role=role,
                verb="taper",
                surface_type="profiled_oblique_envelope_side",
                vertices_m=(
                    vertex(lower[edge_index]),
                    vertex(lower[next_index]),
                    vertex(upper[next_index]),
                    vertex(upper[edge_index]),
                ),
                operator="polygon_ring_loft",
                semantic_patch_id=f"{role}:oblique_envelope_side",
            ))
    top = rings[-1]
    centroid = (
        sum(point[0] for point in top[:vertex_count]) / vertex_count,
        sum(point[1] for point in top[:vertex_count]) / vertex_count,
        sum(point[2] for point in top[:vertex_count]) / vertex_count,
    )
    for edge_index in range(vertex_count):
        next_index = (edge_index + 1) % vertex_count
        surfaces.append(SourceSurface(
            role=f"source_oblique_envelope_roof_{role}_{edge_index}",
            volume_role=role,
            verb="taper",
            surface_type="profiled_oblique_envelope_roof",
            vertices_m=(vertex(centroid), vertex(top[edge_index]), vertex(top[next_index])),
            operator="polygon_ring_loft",
            semantic_patch_id=f"{role}:oblique_envelope_roof",
        ))
    return tuple(surfaces)


def _profiled_formal_surfaces(
    volumes: tuple[SourceVolume, ...],
    origin_poly: Polygon,
    formal_principle: str,
    formal_evidence: dict[str, Any] | None = None,
) -> tuple[tuple[SourceSurface, ...], set[str], dict[str, Any]]:
    """Materialize formal section intent as non-flat renderer/VLM geometry.

    SourceVolume remains the conservative solid used by FAR/BCR and legal
    projection.  These surfaces are the authored roof/facade envelope carried
    by the same graph, so a folded or torqued graph is no longer reviewed as a
    stack of flat proxy boxes.
    """
    principle = normalize_formal_principle(formal_principle)
    if principle not in {
        "folded_section",
        "terraced_ribbon_section",
        "torqued_stack",
        "continuous_ribbon_field",
        "undercut_tapered_tower",
    }:
        return (), set(), {
            "schema_version": "arr.maas.continuous_surface.v1",
            "status": "not_applicable",
            "hard_pass": False,
            "principle": principle,
            "profiled_volume_count": 0,
            "surface_count": 0,
        }
    origin = (float(origin_poly.centroid.x), float(origin_poly.centroid.y))
    design_field = (
        (formal_evidence or {}).get("site_design_field")
        if isinstance((formal_evidence or {}).get("site_design_field"), dict)
        else {}
    )
    field_specs = design_field.get("surface_field_specs") if isinstance(design_field, dict) else None
    if principle == "continuous_ribbon_field" and isinstance(field_specs, list) and field_specs:
        spec_surfaces = _profiled_component_surfaces(tuple(field_specs), origin_poly)
        roles = {str(spec.get("role") or "") for spec in field_specs if spec.get("role")}
        return spec_surfaces, roles, {
            "schema_version": "arr.maas.continuous_surface.v1",
            "status": "materialized" if spec_surfaces else "missing",
            "hard_pass": bool(spec_surfaces),
            "principle": principle,
            "representation": "agent_field_quad_strips",
            "profiled_volume_count": len(roles),
            "surface_count": len(spec_surfaces),
            "profiled_roles": sorted(roles),
        }
    section_field = (
        (formal_evidence or {}).get("site_section_field")
        if isinstance((formal_evidence or {}).get("site_section_field"), dict)
        else {}
    )
    if principle in {"folded_section", "terraced_ribbon_section"} and section_field:
        profiled = tuple(
            volume for volume in volumes
            if volume.verb in {"sloped_roof_mass", "grade", "terrace_link"}
            or any(token in str(volume.role) for token in ("folded", "sloped_roof", "main_long_span_hall"))
        )
        proxy = repair_source_polygon(
            unary_union([volume.footprint for volume in profiled]),
            minimum_area=1.0,
        ) if profiled else None
        field_params = section_field.get("field_parameters") if isinstance(section_field.get("field_parameters"), dict) else {}
        if proxy is not None:
            loft = build_section_loft_field(
                proxy,
                field_params,
                bottom_fraction=min(volume.bottom_fraction for volume in profiled),
                top_fraction=max(volume.top_fraction for volume in profiled),
            )
            if loft is not None:
                role = profiled[0].role
                spec_surfaces = _section_loft_surfaces(
                    loft.rows,
                    origin_poly=origin_poly,
                    role=role,
                    verb="sloped_roof_mass",
                    bottom_fraction=loft.bottom_fraction,
                )
                roles = {volume.role for volume in profiled}
                return spec_surfaces, roles, {
                    "schema_version": "arr.maas.continuous_surface.v1",
                    "status": "materialized" if spec_surfaces else "missing",
                    "hard_pass": bool(spec_surfaces),
                    "principle": principle,
                    "representation": "agent_section_loft_quad_mesh",
                    "profiled_volume_count": len(roles),
                    "surface_count": len(spec_surfaces),
                    "profiled_roles": sorted(roles),
                    "section_field": loft.evidence,
                }
    oblique_field = (
        (formal_evidence or {}).get("site_oblique_envelope")
        if isinstance((formal_evidence or {}).get("site_oblique_envelope"), dict)
        else {}
    )
    if oblique_field:
        field_params = oblique_field.get("field_parameters") if isinstance(oblique_field.get("field_parameters"), dict) else {}
        field = build_oblique_envelope_field(origin_poly, field_params)
        if field is not None:
            role = "primary_agent_oblique_envelope_proxy"
            spec_surfaces = _oblique_envelope_surfaces(field.rings, origin_poly=origin_poly, role=role)
            return spec_surfaces, {role}, {
                "schema_version": "arr.maas.continuous_surface.v1",
                "status": "materialized" if spec_surfaces else "missing",
                "hard_pass": bool(spec_surfaces),
                "principle": principle,
                "representation": "agent_oblique_envelope_mesh",
                "profiled_volume_count": 1,
                "surface_count": len(spec_surfaces),
                "profiled_roles": [role],
                "oblique_field": field.evidence,
            }
    surfaces: list[SourceSurface] = []
    profiled_roles: set[str] = set()
    for volume in volumes:
        role = str(volume.role)
        if principle in {"folded_section", "terraced_ribbon_section"}:
            folded_role = any(token in role for token in (
                "folded_low_plane",
                "folded_high_plane",
                "sloped_roof_low_plane",
                "sloped_roof_high_plane",
                "main_long_span_hall",
            )) or volume.verb in {"sloped_roof_mass", "grade", "terrace_link"}
            if not folded_role:
                continue
        elif (
            principle == "torqued_stack"
            and "torqued_plate" not in role
            and volume.verb not in {"branch", "pinch", "interlock", "overlap", "offset"}
        ):
            continue
        elif principle == "continuous_ribbon_field" and not any(
            token in role for token in ("continuous_ribbon", "branched_ribbon")
        ):
            continue
        surface_footprint = volume.footprint
        if len(surface_footprint.exterior.coords) - 1 > 10:
            original_area = max(float(surface_footprint.area), 1e-9)
            tolerance = sqrt(original_area) * 0.003
            for _ in range(6):
                candidate = repair_source_polygon(
                    surface_footprint.simplify(tolerance, preserve_topology=True),
                    minimum_area=1.0,
                )
                if candidate is not None and candidate.area / original_area >= 0.94:
                    surface_footprint = candidate
                    if len(candidate.exterior.coords) - 1 <= 10:
                        break
                tolerance *= 1.8
        coordinates = list(surface_footprint.exterior.coords)
        if len(coordinates) < 4:
            continue
        coordinates = coordinates[:-1]
        minx, miny, maxx, maxy = surface_footprint.bounds
        width = max(maxx - minx, 1e-9)
        depth = max(maxy - miny, 1e-9)
        # Long-span halls need a real ridge vertex. Four rectangle corners can
        # only describe another flat/shed proxy, regardless of the formal
        # label. Insert ridge points on the two long eaves so the renderer,
        # VLM and downstream graph all see the same folded roof geometry.
        if "main_long_span_hall" in role and len(coordinates) <= 6:
            expanded: list[tuple[float, float]] = []
            for index, left in enumerate(coordinates):
                right = coordinates[(index + 1) % len(coordinates)]
                expanded.append((float(left[0]), float(left[1])))
                if abs(float(left[1]) - float(right[1])) <= depth * 0.02 and abs(float(left[0]) - float(right[0])) >= width * 0.72:
                    expanded.append(((float(left[0]) + float(right[0])) / 2.0, (float(left[1]) + float(right[1])) / 2.0))
            coordinates = expanded
        height_span = max(volume.top_fraction - volume.bottom_fraction, 0.08)

        def roof_height(point: tuple[float, float]) -> float:
            u = max(0.0, min(1.0, (float(point[0]) - minx) / width))
            v = max(0.0, min(1.0, (float(point[1]) - miny) / depth))
            if principle in {"folded_section", "terraced_ribbon_section"}:
                if "main_long_span_hall" in role:
                    rise = 1.0 - abs(u * 2.0 - 1.0)
                else:
                    rise = u if "low_plane" in role else 1.0 - u
                if principle == "terraced_ribbon_section":
                    rise = max(0.0, min(1.0, rise * 0.78 + v * 0.22))
                z = volume.bottom_fraction + height_span * (0.30 + 0.70 * rise)
            elif principle == "torqued_stack":
                # A shallow diagonal warp makes the rotated plates a coherent
                # torque field while keeping every point inside its legal proxy.
                tier_direction = -1.0 if role.endswith("_0") or role.endswith("_2") else 1.0
                field = 0.5 + tier_direction * ((u - 0.5) * 0.55 + (v - 0.5) * 0.25)
                z = volume.bottom_fraction + height_span * max(0.18, min(0.92, field))
            else:
                # The agent-authored section field changes the executable
                # renderer/VLM envelope while the SourceVolume remains the
                # conservative legal/FAR proxy. Keeping these contracts
                # separate makes the representation replaceable.
                profile = list(design_field.get("height_profile_ratios") or (0.64, 0.96, 0.70))
                if len(profile) != 3:
                    profile = [0.64, 0.96, 0.70]
                if u <= 0.5:
                    field = float(profile[0]) + (float(profile[1]) - float(profile[0])) * u * 2.0
                else:
                    field = float(profile[1]) + (float(profile[2]) - float(profile[1])) * (u - 0.5) * 2.0
                field += float(design_field.get("height_wave") or 0.0) * sin(u * 2.0 * pi)
                field += 0.06 * (1.0 - abs(v * 2.0 - 1.0))
                z = volume.bottom_fraction + height_span * max(0.18, min(0.96, field))
            return max(volume.bottom_fraction + 0.02, min(volume.top_fraction, z))

        def vertex(point: tuple[float, float], z: float) -> tuple[float, float, float]:
            return (float(point[0]) - origin[0], float(point[1]) - origin[1], float(z))

        roof_vertices = tuple(vertex(point, roof_height(point)) for point in coordinates)
        surfaces.append(SourceSurface(
            role=f"source_profiled_formal_roof_{role}",
            volume_role=role,
            verb=volume.verb,
            surface_type="profiled_formal_roof",
            vertices_m=roof_vertices,
            operator="loft" if principle in {"folded_section", "terraced_ribbon_section"} else "sweep",
            semantic_patch_id=f"{role}:roof",
        ))
        for edge_index, left in enumerate(coordinates):
            right = coordinates[(edge_index + 1) % len(coordinates)]
            surfaces.append(SourceSurface(
                role=f"source_profiled_formal_facade_{role}_{edge_index}",
                volume_role=role,
                verb=volume.verb,
                surface_type="profiled_formal_facade",
                vertices_m=(
                    vertex(left, volume.bottom_fraction),
                    vertex(right, volume.bottom_fraction),
                    vertex(right, roof_height(right)),
                    vertex(left, roof_height(left)),
                ),
                operator="loft" if principle in {"folded_section", "terraced_ribbon_section"} else "sweep",
                semantic_patch_id=f"{role}:facade",
            ))
        profiled_roles.add(role)
    evidence = {
        "schema_version": "arr.maas.continuous_surface.v1",
        "status": "materialized" if profiled_roles else "missing",
        "hard_pass": bool(profiled_roles),
        "principle": principle,
        "profiled_volume_count": len(profiled_roles),
        "surface_count": len(surfaces),
        "profiled_roles": sorted(profiled_roles),
    }
    return tuple(surfaces), profiled_roles, evidence


def _profiled_program_section_surfaces(
    specs: tuple[dict[str, Any], ...],
    origin_poly: Polygon,
    section_graph: dict[str, Any],
) -> tuple[tuple[SourceSurface, ...], set[str], dict[str, Any]]:
    """Materialize normalized program roof graphs as executable surfaces.

    Section controls are expressed in the hall's local normalized field.  The
    compiler intersects each control interval with the actual program
    footprint, so the same typed ridge/fold/sawtooth/step graph works on every
    parcel without storing parcel coordinates or a finished building shape.
    """
    roof_nodes = tuple(
        node for node in (section_graph.get("nodes") or ())
        if isinstance(node, dict)
        and str(node.get("operator") or "") in {
            "ridge_roof", "folded_roof", "sawtooth_roof", "stepped_section",
            "flat_roof", "shed_roof", "barrel_roof",
        }
    )
    if not roof_nodes:
        return (), set(), {
            "schema_version": "arr.maas.program_section_surface.v1",
            "status": "not_applicable",
            "hard_pass": False,
            "surface_count": 0,
            "profiled_roles": [],
        }
    nodes_by_id = {
        str(node.get("node_id") or ""): node
        for node in (section_graph.get("nodes") or ())
        if isinstance(node, dict)
    }
    origin = (float(origin_poly.centroid.x), float(origin_poly.centroid.y))
    surfaces: list[SourceSurface] = []
    profiled_roles: set[str] = set()
    materialized_nodes: list[dict[str, Any]] = []

    def polygon_parts(geometry: Any) -> tuple[Polygon, ...]:
        if geometry is None or geometry.is_empty:
            return ()
        if geometry.geom_type == "Polygon":
            return (geometry,)
        return tuple(
            part
            for child in getattr(geometry, "geoms", ())
            for part in polygon_parts(child)
        )

    for roof_node in roof_nodes:
        params = roof_node.get("params") if isinstance(roof_node.get("params"), dict) else {}
        controls = tuple(
            (float(item[0]), float(item[1]))
            for item in (params.get("section_controls") or ())
            if isinstance(item, list) and len(item) == 2
        )
        if len(controls) < 3:
            continue
        parent = nodes_by_id.get(str(roof_node.get("parent_id") or ""), {})
        parent_params = parent.get("params") if isinstance(parent.get("params"), dict) else {}
        span_axis = str(parent_params.get("span_axis") or "x")
        section_axis = "y" if span_axis == "x" else "x"
        component_role = str(roof_node.get("component_role") or "")
        applicable_specs = tuple(
            spec for spec in specs
            if str(spec.get("role") or "") == component_role
            or str(spec.get("role") or "").startswith(f"{component_role}__book_")
            or any(
                str(node.get("node_id") or "") == str(roof_node.get("node_id") or "")
                for node in (spec.get("section_nodes") or ())
                if isinstance(node, dict)
            )
        )
        node_surface_count = 0
        for spec in applicable_specs:
            role = str(spec["role"])
            footprint = spec["footprint"]
            bottom = float(spec["bottom_fraction"])
            top = float(spec["top_fraction"])
            height_span = max(0.08, top - bottom)
            minx, miny, maxx, maxy = footprint.bounds
            width = max(maxx - minx, 1e-9)
            depth = max(maxy - miny, 1e-9)
            axis_min = miny if section_axis == "y" else minx
            axis_span = depth if section_axis == "y" else width
            pad = max(width, depth) + 1.0

            def normalized_position(point: tuple[float, float]) -> float:
                coordinate = float(point[1]) if section_axis == "y" else float(point[0])
                return max(0.0, min(1.0, (coordinate - axis_min) / axis_span))

            def profile_height(position: float) -> float:
                position = max(0.0, min(1.0, float(position)))
                for index in range(len(controls) - 1):
                    left, right = controls[index], controls[index + 1]
                    if position <= right[0] + 1e-9:
                        interval = max(right[0] - left[0], 1e-9)
                        amount = max(0.0, min(1.0, (position - left[0]) / interval))
                        value = left[1] + (right[1] - left[1]) * amount
                        return max(bottom + 0.02, min(top, bottom + height_span * value))
                return max(bottom + 0.02, min(top, bottom + height_span * controls[-1][1]))

            def vertex(point: tuple[float, float], z: float) -> tuple[float, float, float]:
                return (float(point[0]) - origin[0], float(point[1]) - origin[1], float(z))

            # One planar patch per normalized control interval preserves real
            # folds, vertical-ish sawtooth faces and stepped section changes.
            for interval_index, (left, right) in enumerate(zip(controls, controls[1:])):
                low = axis_min + axis_span * left[0]
                high = axis_min + axis_span * right[0]
                if high <= low + 1e-8:
                    continue
                clip = (
                    box(minx - pad, low, maxx + pad, high)
                    if section_axis == "y"
                    else box(low, miny - pad, high, maxy + pad)
                )
                for part_index, part in enumerate(polygon_parts(footprint.intersection(clip))):
                    if part.area < 0.05:
                        continue
                    coordinates = tuple((float(x), float(y)) for x, y in list(part.exterior.coords)[:-1])
                    if len(coordinates) < 3:
                        continue
                    surfaces.append(SourceSurface(
                        role=f"source_program_section_roof_{role}_{interval_index}_{part_index}",
                        volume_role=role,
                        verb=str(spec["verb"]),
                        surface_type="profiled_program_section_roof",
                        vertices_m=tuple(
                            vertex(point, profile_height(normalized_position(point)))
                            for point in coordinates
                        ),
                        operator=str(roof_node.get("operator") or "loft"),
                        semantic_patch_id=f"{role}:program_section_roof:{roof_node.get('node_id')}:{interval_index}:{part_index}",
                    ))
                    node_surface_count += 1
            # Facades close the authored roof envelope while SourceVolume
            # remains the conservative legal/FAR proxy.
            coordinates = tuple((float(x), float(y)) for x, y in list(footprint.exterior.coords)[:-1])
            for edge_index, left in enumerate(coordinates):
                right = coordinates[(edge_index + 1) % len(coordinates)]
                surfaces.append(SourceSurface(
                    role=f"source_program_section_facade_{role}_{edge_index}",
                    volume_role=role,
                    verb=str(spec["verb"]),
                    surface_type="profiled_program_section_facade",
                    vertices_m=(
                        vertex(left, bottom),
                        vertex(right, bottom),
                        vertex(right, profile_height(normalized_position(right))),
                        vertex(left, profile_height(normalized_position(left))),
                    ),
                    operator=str(roof_node.get("operator") or "loft"),
                    semantic_patch_id=f"{role}:program_section_facade:{edge_index}",
                ))
                node_surface_count += 1
            profiled_roles.add(role)
        materialized_nodes.append({
            "node_id": str(roof_node.get("node_id") or ""),
            "operator": str(roof_node.get("operator") or ""),
            "component_role": component_role,
            "section_axis": section_axis,
            "section_controls": [[round(x, 4), round(y, 4)] for x, y in controls],
            "surface_count": node_surface_count,
        })
    evidence = {
        "schema_version": "arr.maas.program_section_surface.v1",
        "status": "materialized" if profiled_roles else "missing",
        "hard_pass": bool(profiled_roles),
        "representation": "normalized_section_graph_planar_strips",
        "surface_count": len(surfaces),
        "profiled_volume_count": len(profiled_roles),
        "profiled_roles": sorted(profiled_roles),
        "materialized_nodes": materialized_nodes,
        "graph_operators": sorted({
            str(node.get("operator") or "")
            for node in (section_graph.get("nodes") or ())
            if isinstance(node, dict) and node.get("operator")
        }),
        "graph_relations": sorted({
            str(node.get("relation") or "")
            for node in (section_graph.get("nodes") or ())
            if isinstance(node, dict) and node.get("relation")
        }),
        "graph_schema_version": section_graph.get("schema_version"),
        "mutation_trace": list(section_graph.get("mutation_trace") or ()),
        "book_mutation": dict(section_graph.get("book_mutation") or {}),
    }
    return tuple(surfaces), profiled_roles, evidence


def _project_program_specs_with_book_calls(
    specs: tuple[dict[str, Any], ...],
    sequence: VerbSequence,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Mutate one dominant program component without erasing its role graph.

    The program template remains the source of hall/service/entry semantics.
    Explicitly marked BOOK calls are compiled on the largest occupiable
    component and their real volumes replace that component.  This prevents
    the former final program-template override from silently discarding every
    architectural operation appended by the agent.
    """
    calls = book_projection_calls(sequence)
    if not specs or not calls:
        return specs, {}
    dominant_index = max(
        range(len(specs)),
        key=lambda index: float(specs[index]["footprint"].area)
        * max(0.0, float(specs[index]["top_fraction"]) - float(specs[index]["bottom_fraction"])),
    )
    dominant = specs[dominant_index]
    scope_definition = book_projection_scope(sequence)
    scope = materialize_book_scope(dominant["footprint"], scope_definition)
    projection_sequence = VerbSequence(
        name=f"book_projection_kernel_{'_'.join(call.verb for call in calls)}",
        label="typed BOOK projection kernel",
        calls=(VerbCall("base", {}), *calls),
        notes=("parameter_source=book_program_projection_v1",),
    )
    projected = compile_sequence_to_source_mass(scope.footprint, projection_sequence)
    if projected is None or not projected.volumes:
        return specs, {
            "schema_version": "arr.maas.program_book_projection.v1",
            "status": "compile_failed",
            "operations": [call.verb for call in calls],
            "primary_role": str(dominant["role"]),
            "scope": {
                "base_volume_label": scope_definition.label,
                "requested_fraction": scope.requested_fraction,
                "measured_plan_fraction": scope.measured_plan_fraction,
                "orientation": scope.orientation,
            },
        }
    remaining_count = len(specs) - 1
    # Program templates already satisfy their use-specific component-count
    # range.  Replacing one primary with several operation states must not add
    # components on top of that baseline. Reserve at least one subordinate
    # anchor and trade the least significant supports for sectional states.
    program_volume_cap = 5
    # Preserve a second body only when the BOOK sentence ends in a genuinely
    # relational/multi-volume operation.  The former unconditional one-volume
    # truncation erased split/offset/aggregation grammar after it compiled.
    # Subordinate service/entry/public anchors remain hard requirements, so the
    # global clean-mass cap determines whether one or two projected bodies fit.
    multi_result_verbs = {
        "array", "branch", "embed", "extract", "inscribe", "interlock",
        "intersect", "join", "lift", "lodge", "nest", "offset", "overlap",
        "pack", "puncture", "reflect", "rotate", "shift", "split", "stack",
    }
    requested_projected = 2 if calls[-1].verb in multi_result_verbs else 1
    program_host_count = 1 if (
        scope.orientation == "vertical"
        or scope.measured_plan_fraction < 1.0 - 1e-6
    ) else 0
    maximum_projected = max(
        1,
        min(requested_projected, program_volume_cap - remaining_count - program_host_count),
    )
    projected_volumes = sorted(
        projected.volumes,
        key=lambda volume: float(volume.footprint.area)
        * max(0.0, float(volume.top_fraction) - float(volume.bottom_fraction)),
        reverse=True,
    )[:maximum_projected]
    base_bottom = float(dominant["bottom_fraction"])
    base_top = float(dominant["top_fraction"])
    span = max(0.08, base_top - base_bottom)
    replacements: list[dict[str, Any]] = []
    host_replacements: list[dict[str, Any]] = []
    operation_label = "_".join(call.verb for call in calls)
    residual = dominant["footprint"].difference(scope.footprint)
    section_split_fraction: float | None = None
    additive_scope_growth_factor = 1.0
    if scope.orientation == "vertical":
        host_top = base_bottom + span * max(0.0, 1.0 - scope.height_fraction)
        if host_top > base_bottom + 0.02:
            # A vertical p.3 scope is a band of the dominant program volume,
            # not a replacement for the whole hall.  Keeping the lower host
            # makes 1/16 a real sectional mutation while retaining program
            # capacity, hierarchy and the service/entry role graph.
            host_replacements.append({
                "role": f"{dominant['role']}__book_host",
                "footprint": dominant["footprint"],
                "bottom_fraction": base_bottom,
                "top_fraction": host_top,
                "verb": str(dominant["verb"]),
                "section_nodes": (),
                "subtractive_relations": tuple(dominant.get("subtractive_relations") or ()),
            })
    elif not residual.is_empty and scope.measured_plan_fraction < 1.0 - 1e-6:
        # A partial plan scope becomes an upper sectional band over one clean
        # continuous hall host.  Unioning the operated strip back into the
        # residual produced 12-15-edge tortuous outlines at 1/8.  This graph
        # relation keeps the early mass connected, preserves capacity and
        # makes the selected BOOK fraction visible as a real step/roof body.
        section_split_fraction = max(
            0.38,
            min(0.58, 0.42 + 0.16 * (1.0 - sqrt(scope.measured_plan_fraction))),
        )
        additive_count = sum(
            call.verb in {"branch", "expand", "inflate", "merge"}
            for call in calls
        )
        if additive_count:
            additive_scope_growth_factor = min(
                1.38,
                1.0
                + 0.28 * (1.0 - sqrt(scope.measured_plan_fraction))
                + 0.12 * min(2, additive_count),
            )
        host_top = base_bottom + span * section_split_fraction
        host_replacements.append({
            "role": f"{dominant['role']}__book_host",
            "footprint": dominant["footprint"],
            "bottom_fraction": base_bottom,
            "top_fraction": host_top,
            "verb": str(dominant["verb"]),
            "section_nodes": (),
            "subtractive_relations": tuple(dominant.get("subtractive_relations") or ()),
        })
    for index, volume in enumerate(projected_volumes):
        replacement_footprint = volume.footprint
        if additive_scope_growth_factor > 1.0:
            growth_basis = unary_union((replacement_footprint, scope.footprint))
            grown = scale(
                growth_basis,
                xfact=additive_scope_growth_factor,
                yfact=additive_scope_growth_factor,
                origin="centroid",
            ).intersection(dominant["footprint"])
            repaired_grown = repair_source_polygon(grown, minimum_area=1.0)
            if repaired_grown is not None:
                replacement_footprint = repaired_grown
        if scope.orientation == "vertical":
            # The selected p.3 fraction is a sectional band. Preserve the
            # lower host and apply the operation to the upper relative band.
            mapped_bottom = max(0.0, 1.0 - scope.height_fraction + scope.height_fraction * float(volume.bottom_fraction))
            mapped_top = max(mapped_bottom + 0.02, 1.0 - scope.height_fraction + scope.height_fraction * float(volume.top_fraction))
        elif section_split_fraction is not None:
            upper_span = 1.0 - section_split_fraction
            mapped_bottom = section_split_fraction + upper_span * float(volume.bottom_fraction)
            mapped_top = max(
                mapped_bottom + 0.02,
                section_split_fraction + upper_span * float(volume.top_fraction),
            )
        else:
            mapped_bottom = float(volume.bottom_fraction)
            mapped_top = float(volume.top_fraction)
        replacement_footprint = repair_source_polygon(replacement_footprint, minimum_area=1.0)
        if replacement_footprint is not None:
            replacement_footprint = repair_source_polygon(
                replacement_footprint.intersection(dominant["footprint"]),
                minimum_area=1.0,
            )
        if replacement_footprint is None:
            continue
        band_marker = "__program_section_band" if section_split_fraction is not None else ""
        replacements.append({
            "role": f"{dominant['role']}{band_marker}__book_{operation_label}_{index}",
            "footprint": replacement_footprint,
            "bottom_fraction": base_bottom + span * mapped_bottom,
            "top_fraction": base_bottom + span * min(1.0, mapped_top),
            "verb": volume.verb,
            "section_nodes": tuple(dominant.get("section_nodes") or ()),
            "subtractive_relations": tuple(dominant.get("subtractive_relations") or ()),
        })
    subordinates = [dict(spec) for index, spec in enumerate(specs) if index != dominant_index]
    result = [*host_replacements, *replacements, *subordinates]
    return tuple(result), {
        "schema_version": "arr.maas.program_book_projection.v1",
        "status": "materialized",
        "operations": [call.verb for call in calls],
        "primary_role": str(dominant["role"]),
        "source_volume_count": len(projected.volumes),
        "retained_projected_volume_count": len(replacements),
        "retained_vertical_host_volume_count": len(host_replacements) if scope.orientation == "vertical" else 0,
        "retained_program_host_volume_count": len(host_replacements),
        "section_split_fraction": round(section_split_fraction, 6) if section_split_fraction is not None else None,
        "additive_scope_growth_factor": round(additive_scope_growth_factor, 6),
        "requested_projected_volume_count": requested_projected,
        "subordinate_role_count": remaining_count,
        "clean_volume_cap": program_volume_cap,
        "source_signature": projected.signature(),
        "scope": {
            "node_id": "book_scope",
            "parent_role": str(dominant["role"]),
            "relation": "select_relative_volume",
            "base_volume_label": scope_definition.label,
            "requested_fraction": scope.requested_fraction,
            "measured_plan_fraction": scope.measured_plan_fraction,
            "height_fraction": scope.height_fraction,
            "orientation": scope.orientation,
        },
        "projection_graph": {
            "schema_version": "arr.maas.book_projection_graph.v1",
            "nodes": [
                {"node_id": "program_dominant", "role": str(dominant["role"]), "operation": "program_anchor"},
                {"node_id": "book_scope", "parent_id": "program_dominant", "operation": "select_book_scope", "params": {"base_volume_label": scope_definition.label, "orientation": scope.orientation}},
                *[
                    {"node_id": f"book_operation_{index}", "parent_id": "book_scope" if index == 0 else f"book_operation_{index - 1}", "operation": call.verb, "params": dict(call.params)}
                    for index, call in enumerate(calls)
                ],
            ],
        },
    }


def _compile_component_graph_to_source_mass(
    base_footprint: Polygon,
    sequence: VerbSequence,
    component_graph: MassComponentGraph,
) -> SourceMass | None:
    errors = [*sequence.validate(), *component_graph.validate()]
    base = _clean(base_footprint)
    if errors or base is None:
        return None
    is_authored = sequence.name.startswith(("agent_", "llm_"))
    sequence_source = (
        LLM_PARAMETER_SOURCE if sequence.name.startswith("llm_") else (
            "clone_maas_agent_arch_language" if sequence.name.startswith("agent_") else "deterministic_sequence_library"
        )
    )
    parameter_provenance: list[dict[str, Any]] = []

    footprint = base
    upper: Polygon | None = None
    lower_fraction: float | None = None
    layout_units: list[Polygon] = []
    stack_spec: dict[str, Any] | None = None
    language_params: dict[str, Any] = {}
    root_node = component_graph.nodes[0]
    trace: list[VerbTrace] = [_trace("base", root_node.operation.params, "ok", footprint, upper)]
    family = None
    last_verb = "base"
    node_states: dict[str, dict[str, Any]] = {
        root_node.node_id: {
            "footprint": footprint,
            "upper": upper,
            "lower_fraction": lower_fraction,
            "layout_units": list(layout_units),
            "stack_spec": stack_spec,
            "language_params": dict(language_params),
            "family": family,
            "last_verb": last_verb,
        }
    }

    for node in component_graph.nodes[1:]:
        parent_state = node_states.get(str(node.parent_id))
        if parent_state is None:
            return None
        footprint = parent_state["footprint"]
        upper = parent_state["upper"]
        lower_fraction = parent_state["lower_fraction"]
        layout_units = list(parent_state["layout_units"])
        stack_spec = dict(parent_state["stack_spec"]) if isinstance(parent_state["stack_spec"], dict) else None
        language_params = dict(parent_state["language_params"])
        family = parent_state["family"]
        last_verb = parent_state["last_verb"]
        call = node.operation
        params = call.params
        next_fp: Polygon | None = footprint
        note = None
        if call.verb in BOOK_KERNEL_VERBS:
            kernel = apply_book_plan_kernel(call.verb, footprint, base, params)
            if kernel is None:
                next_fp = None
                note = "book_kernel_failed"
            else:
                next_fp = kernel.footprint
                upper = kernel.upper if kernel.upper is not None else upper
                if kernel.layout_units:
                    layout_units = list(kernel.layout_units)
                lower_fraction = _param_float(
                    params,
                    "lower_floor_fraction",
                    lower_fraction or 0.52,
                    parameter_provenance,
                    sequence_source=sequence_source,
                )
                family = family or kernel.family
                note = kernel.note
        elif call.verb == "notch":
            corner = _param_str(params, "corner", "+x+y", parameter_provenance, sequence_source=sequence_source)
            ratio = _param_float_any(
                params,
                ("ratio", "size"),
                0.24,
                parameter_provenance,
                canonical_key="ratio",
                sequence_source=sequence_source,
            )
            next_fp = _corner_notch(footprint, corner, ratio)
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.92, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None and upper is None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.55, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "void_notch"
        elif call.verb == "cave":
            face = _param_str_any(
                params,
                ("side", "face"),
                "north",
                parameter_provenance,
                canonical_key="side",
                sequence_source=sequence_source,
            )
            face = {"+y": "north", "-y": "south", "+x": "east", "-x": "west"}.get(face, face)
            next_fp = _edge_cut(
                footprint,
                face,
                _param_float(params, "width_ratio", 0.46, parameter_provenance, sequence_source=sequence_source),
                _param_float_any(
                    params,
                    ("depth_ratio", "depth"),
                    0.28,
                    parameter_provenance,
                    canonical_key="depth_ratio",
                    sequence_source=sequence_source,
                ),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.90, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None and upper is None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.45, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "void_notch"
        elif call.verb == "courtyard":
            next_fp = _courtyard(
                footprint,
                _param_float(params, "ratio", 0.22, parameter_provenance, sequence_source=sequence_source),
                _param_str_any(
                    params,
                    ("open_side", "side"),
                    "closed",
                    parameter_provenance,
                    canonical_key="open_side",
                    sequence_source=sequence_source,
                ),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.88, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.48, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "courtyard"
        elif call.verb == "split":
            next_fp = _split(
                footprint,
                _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float_any(
                    params,
                    ("gap_ratio", "gap"),
                    0.22,
                    parameter_provenance,
                    canonical_key="gap_ratio",
                    sequence_source=sequence_source,
                ),
                _param_float(params, "bridge_ratio", 0.18, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _shift(
                _upper_from(
                    next_fp,
                    _param_float(params, "upper_ratio", 0.72, parameter_provenance, sequence_source=sequence_source),
                ) or next_fp,
                _param_str(params, "shift_axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "distance_ratio", 0.05, parameter_provenance, sequence_source=sequence_source),
                next_fp,
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.42, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "split"
        elif call.verb == "bar":
            next_fp = _bar(
                footprint,
                _param_str(params, "axis", "y", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "factor", 0.56, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "shift", 0.0, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.88, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None and upper is None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.60, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "slender_bar"
        elif call.verb == "branch":
            next_fp = _branch(
                footprint,
                _param_float(params, "angle", 34.0, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "trunk_ratio", 0.30, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "arm_ratio", 0.20, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.78, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.46, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "branch"
        elif call.verb == "pinch":
            next_fp = _pinch(
                footprint,
                _param_str(params, "axis", "y", parameter_provenance, sequence_source=sequence_source),
                _param_float_any(
                    params,
                    ("waist_ratio", "factor"),
                    0.62,
                    parameter_provenance,
                    canonical_key="waist_ratio",
                    sequence_source=sequence_source,
                ),
                _param_float(params, "depth_ratio", 0.36, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.82, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.50, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "pinch"
        elif call.verb == "bend":
            # Bend is a continuous design-field operation for every graph,
            # including legacy sequences.  Pre-bending the parcel into two
            # proxy bars left too little domain for the formal compiler and
            # made a valid bend graph fall back to box geometry.
            next_fp = footprint
            upper = None
            note = "site_design_field_deferred_to_formal_compiler"
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.44, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "bend"
        elif call.verb == "embed":
            position = _param_position(params, "position", [0.0, 0.0, 0.0], parameter_provenance, sequence_source=sequence_source)
            next_fp = _embed(
                footprint,
                _param_float(params, "guest_scale", 0.42, parameter_provenance, sequence_source=sequence_source),
                position,
            )
            upper = _shift(
                _upper_from(
                    next_fp,
                    _param_float(params, "upper_ratio", 0.74, parameter_provenance, sequence_source=sequence_source),
                ) or next_fp,
                _param_str(params, "shift_axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "distance_ratio", 0.06, parameter_provenance, sequence_source=sequence_source),
                next_fp,
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.38, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "embed"
        elif call.verb == "extrude":
            next_fp = _extrude(
                footprint,
                _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "length", 0.36, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "size", 0.34, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.68, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.34, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "extrude"
        elif call.verb == "nest":
            next_fp = _nest(
                footprint,
                _param_float(params, "inner_scale", 0.46, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.76, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.42, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "nest"
        elif call.verb == "stack":
            levels = _param_int_any(
                params,
                ("levels", "n"),
                2,
                parameter_provenance,
                canonical_key="levels",
                sequence_source=sequence_source,
            )
            z_step_ratio = _param_float_any(
                params,
                ("z_step_ratio", "gap"),
                0.08,
                parameter_provenance,
                canonical_key="z_step_ratio",
                sequence_source=sequence_source,
            )
            slide_axis = _param_str(params, "slide_axis", "x", parameter_provenance, sequence_source=sequence_source)
            slide_ratio = _param_float(params, "slide_ratio", 0.0, parameter_provenance, sequence_source=sequence_source)
            upper = _upper_from(
                footprint,
                _param_float(params, "upper_ratio", 0.76, parameter_provenance, sequence_source=sequence_source),
            )
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.34, parameter_provenance, sequence_source=sequence_source
            )
            stack_spec = dict(params)
            stack_spec["levels"] = levels
            stack_spec["n"] = levels
            stack_spec["z_step_ratio"] = z_step_ratio
            stack_spec["gap"] = z_step_ratio
            stack_spec["slide_axis"] = slide_axis
            stack_spec["slide_ratio"] = slide_ratio
            family = family or "stack"
        elif call.verb == "offset":
            axis = _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source)
            layout_units = _offset_units(
                footprint,
                axis,
                _param_float_any(
                    params,
                    ("distance_ratio", "distance"),
                    0.24,
                    parameter_provenance,
                    canonical_key="distance_ratio",
                    sequence_source=sequence_source,
                ),
                _param_float(params, "other_scale", 0.68, parameter_provenance, sequence_source=sequence_source),
            )
            next_fp = _clean(unary_union(layout_units).intersection(footprint))
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.78, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None and upper is None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.42, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "offset"
        elif call.verb == "array":
            layout_units = _array_units(
                footprint,
                _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_int(params, "n", 3, parameter_provenance, sequence_source=sequence_source),
                _param_float_any(
                    params,
                    ("spacing_ratio", "spacing"),
                    0.22,
                    parameter_provenance,
                    canonical_key="spacing_ratio",
                    sequence_source=sequence_source,
                ),
                _param_float(params, "unit_scale", 0.34, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "hierarchy_ratio", 0.18, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "stagger_ratio", 0.12, parameter_provenance, sequence_source=sequence_source),
            )
            # The repeated cells are program boxes above a common massing
            # datum. Shrinking the canonical footprint to their union reduced
            # legal BCR to ~3% and made the final card read as a toy. Preserve
            # the authored footprint as the podium/support source of truth;
            # ``layout_units`` still controls the upper box locations.
            next_fp = footprint
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.36, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "array_cluster"
        elif call.verb == "reflect":
            layout_units = _reflect_units(
                footprint,
                _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "gap_ratio", 0.12, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "unit_scale", 0.50, parameter_provenance, sequence_source=sequence_source),
            )
            next_fp = _clean(unary_union(layout_units).intersection(footprint))
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.80, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None and upper is None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.44, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "reflected_pair"
        elif call.verb == "interlock":
            next_fp = _interlock(
                footprint,
                _param_float(params, "angle", 28.0, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "bar_ratio", 0.34, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _shift(
                _upper_from(
                    next_fp,
                    _param_float(params, "upper_ratio", 0.72, parameter_provenance, sequence_source=sequence_source),
                ) or next_fp,
                _param_str(params, "shift_axis", "y", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "distance_ratio", 0.06, parameter_provenance, sequence_source=sequence_source),
                next_fp,
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.46, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "interlock"
        elif call.verb == "overlap":
            next_fp = _overlap(
                footprint,
                _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "slab_ratio", 0.52, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "shift_ratio", 0.18, parameter_provenance, sequence_source=sequence_source),
            )
            upper = _shift(
                _upper_from(
                    next_fp,
                    _param_float(params, "upper_ratio", 0.78, parameter_provenance, sequence_source=sequence_source),
                ) or next_fp,
                _param_str(params, "shift_axis", "y", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "distance_ratio", 0.06, parameter_provenance, sequence_source=sequence_source),
                next_fp,
            ) if next_fp is not None else upper
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.44, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "overlap"
        elif call.verb == "lift":
            upper = _upper_from(footprint, _param_float(params, "upper_ratio", 0.72, parameter_provenance, sequence_source=sequence_source))
            lower_fraction = _param_float(params, "lower_floor_fraction", lower_fraction or 0.45, parameter_provenance, sequence_source=sequence_source)
            family = family or "stepback_tower"
        elif call.verb == "taper":
            target = upper if upper is not None else footprint
            upper = _clean(scale(
                target,
                xfact=_param_float_any(
                    params,
                    ("x_ratio", "top_ratio"),
                    0.78,
                    parameter_provenance,
                    canonical_key="x_ratio",
                    sequence_source=sequence_source,
                ),
                yfact=_param_float_any(
                    params,
                    ("y_ratio", "top_ratio"),
                    0.78,
                    parameter_provenance,
                    canonical_key="y_ratio",
                    sequence_source=sequence_source,
                ),
                origin="centroid",
            ).intersection(footprint))
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.48, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "taper"
        elif call.verb == "grade":
            target = upper if upper is not None else footprint
            side = _param_str(params, "side", "north", parameter_provenance, sequence_source=sequence_source)
            upper = _edge_cut(
                target,
                side,
                _param_float(params, "width_ratio", 0.52, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "depth_ratio", 0.24, parameter_provenance, sequence_source=sequence_source),
            )
            lower_fraction = _param_float(
                params, "lower_floor_fraction", lower_fraction or 0.42, parameter_provenance, sequence_source=sequence_source
            )
            family = family or "grade"
        elif call.verb == "shift":
            target = upper if upper is not None else footprint
            shifted = _shift(
                target,
                _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                _param_float_any(
                    params,
                    ("distance_ratio", "distance"),
                    0.06,
                    parameter_provenance,
                    canonical_key="distance_ratio",
                    sequence_source=sequence_source,
                ),
                footprint,
            )
            if upper is not None:
                upper = shifted
            else:
                next_fp = shifted
            family = family or "shift"
        elif call.verb == "diagonal_connect":
            upper = _upper_from(footprint, _param_float(params, "upper_ratio", 0.78, parameter_provenance, sequence_source=sequence_source))
            if upper is not None:
                upper = _shift(
                    upper,
                    _param_str(params, "axis", "x", parameter_provenance, sequence_source=sequence_source),
                    _param_float(params, "distance_ratio", 0.10, parameter_provenance, sequence_source=sequence_source),
                    footprint,
                )
            lower_fraction = _param_float(params, "lower_floor_fraction", lower_fraction or 0.40, parameter_provenance, sequence_source=sequence_source)
            family = family or "diagonal_connect"
        elif call.verb == "terrace_link":
            target = _upper_from(footprint, _param_float(params, "upper_ratio", 0.84, parameter_provenance, sequence_source=sequence_source)) or footprint
            upper = _edge_cut(
                target,
                _param_str(params, "side", "north", parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "width_ratio", 0.62, parameter_provenance, sequence_source=sequence_source),
                _param_float(params, "depth_ratio", 0.20, parameter_provenance, sequence_source=sequence_source),
            )
            lower_fraction = _param_float(params, "lower_floor_fraction", lower_fraction or 0.34, parameter_provenance, sequence_source=sequence_source)
            family = family or "terrace_link"
        elif call.verb == "sloped_roof_mass":
            target = _upper_from(footprint, _param_float(params, "upper_ratio", 0.90, parameter_provenance, sequence_source=sequence_source)) or footprint
            upper = _clean(scale(
                target,
                xfact=_param_float(params, "x_ratio", 0.70, parameter_provenance, sequence_source=sequence_source),
                yfact=_param_float(params, "y_ratio", 0.92, parameter_provenance, sequence_source=sequence_source),
                origin="centroid",
            ).intersection(footprint))
            lower_fraction = _param_float(params, "lower_floor_fraction", lower_fraction or 0.50, parameter_provenance, sequence_source=sequence_source)
            family = family or "sloped_roof"
        elif call.verb == "step_envelope":
            lower_fraction = None
            note = "legal_floor_plate_stack_required"
            family = family or "stepback_tower"
        elif call.verb == "inset":
            factor = _param_float(
                params,
                "factor",
                0.92,
                parameter_provenance,
                sequence_source=sequence_source,
            )
            next_fp = _clean(scale(footprint, xfact=factor, yfact=factor, origin="centroid").intersection(base))
            upper = _upper_from(
                next_fp,
                _param_float(params, "upper_ratio", 0.90, parameter_provenance, sequence_source=sequence_source),
            ) if next_fp is not None else upper
            family = family or "inset"
        elif call.verb == "expand":
            # The base geometry is already the legal clip.  Outward scaling
            # followed by clipping is necessarily a no-op, so EXPAND is
            # represented by compact lower and full upper volume bands.
            _param_float(
                params,
                "factor",
                0.78,
                parameter_provenance,
                sequence_source=sequence_source,
            )
            next_fp = footprint
            upper = footprint
            lower_fraction = _param_float(
                params,
                "lower_floor_fraction",
                lower_fraction or 0.44,
                parameter_provenance,
                sequence_source=sequence_source,
            )
            family = family or "expand"
        else:
            note = "unsupported_verb_kept_as_trace"

        if next_fp is not None:
            footprint = next_fp
        if upper is not None:
            upper = _clean(upper.intersection(footprint))
        language_params.update(params)
        last_verb = call.verb
        trace.append(_trace(call.verb, params, "ok" if next_fp is not None or note else "no_geometry_change", footprint, upper, note))
        node_states[node.node_id] = {
            "footprint": footprint,
            "upper": upper,
            "lower_fraction": lower_fraction,
            "layout_units": list(layout_units),
            "stack_spec": dict(stack_spec) if isinstance(stack_spec, dict) else None,
            "language_params": dict(language_params),
            "family": family,
            "last_verb": last_verb,
        }

    declared_family = _declared_family(sequence)
    evolution_family = _evolution_family_override(sequence)
    graph_primary_family = _graph_primary_family(component_graph) if is_graph_native(component_graph) else None
    effective_family = (
        graph_primary_family
        if graph_primary_family else
        evolution_family
        if evolution_family else
        declared_family
        if declared_family and sequence.name.startswith("llm_") and _sequence_supports_declared_family(sequence, declared_family)
        else family
    )
    primary_language = _note_value(sequence, "primary_language") or _note_value(sequence, "mass_language")
    secondary_language = _note_value(sequence, "secondary_language")
    reference_basis = _note_value(sequence, "reference_basis")
    formal_principle = _family_formal_principle(effective_family, _note_value(sequence, "formal_principle"))
    if evolution_family and formal_principle not in {"folded_section", "split_bridge_connector"}:
        formal_principle = _family_formal_principle(evolution_family, formal_principle)
    dominant_gesture = _note_value(sequence, "dominant_gesture")
    secondary_family = _family_from_mass_language(secondary_language) if secondary_language else None
    massing_genome = build_massing_genome(
        sequence,
        family=effective_family,
        primary_language=primary_language,
        secondary_language=secondary_language,
        formal_principle=formal_principle,
        reference_basis=reference_basis,
        dominant_gesture=dominant_gesture,
    )
    if massing_genome is not None:
        formal_principle = massing_genome.formal_principle
        reference_basis = massing_genome.reference_basis
        dominant_gesture = massing_genome.dominant_gesture
    rule_evidence = init_rule_evidence(
        effective_family,
        sequence_name=sequence.name,
        sequence_source=sequence_source,
        language_params=language_params,
    )
    formal_result = compile_formal_principle_volumes(
        footprint,
        formal_principle=formal_principle,
        dominant_gesture=dominant_gesture,
        language_params=language_params,
        lower_fraction=lower_fraction,
        last_verb=last_verb,
        massing_genome=massing_genome.to_dict() if massing_genome is not None else None,
    )
    graph_materialization_evidence: dict[str, Any] = {}
    graph_native_volumes, graph_materialization_evidence = (
        materialize_graph_states(component_graph, node_states)
        if is_graph_native(component_graph)
        else ((), {})
    )
    if graph_native_volumes and formal_principle != "continuous_ribbon_field":
        # The executable graph is the geometry source of truth. A declared
        # precedent/formal label may score the result but cannot replace its
        # branches with a canned volume template.
        volumes = graph_native_volumes
    elif formal_result is not None:
        volumes = formal_result.volumes
        # The formal-principle compiler already materializes the effective
        # primary family. Re-composing that same family as a secondary gesture
        # duplicated bars/liners and forced every candidate to four pieces.
        # A continuous ribbon's compatible secondary language is expressed in
        # its profile/surface field. Adding a generic rectangular roof/terrace
        # volume here created the exact box-on-ribbon collision visible in the
        # review PNG and made all-lane coherence detection impossible.
        if formal_principle != "continuous_ribbon_field":
            volumes = _compose_secondary_language(
                volumes,
                footprint,
                effective_family,
                secondary_family,
                last_verb,
                lower_fraction,
            )
    else:
        volumes = _layout_volumes(
            footprint,
            upper,
            lower_fraction,
            last_verb,
            layout_units=layout_units,
            stack_spec={**stack_spec, "_source_family": effective_family} if stack_spec is not None else None,
            source_family=effective_family,
            language_params=language_params,
            rule_evidence=rule_evidence,
        )
        volumes = _compose_secondary_language(
            volumes,
            footprint,
            effective_family,
            secondary_family,
            last_verb,
            lower_fraction,
        )
    program_section_graph = program_section_graph_from_sequence(sequence)
    program_component_relation_evidence: dict[str, Any] = {}
    program_specs = program_component_specs(
        sequence.name,
        base_footprint,
        language_params,
        program_section_graph,
    )
    program_book_projection_evidence: dict[str, Any] = {}
    if program_specs:
        program_specs, program_book_projection_evidence = _project_program_specs_with_book_calls(
            program_specs,
            sequence,
        )
        volumes = tuple(SourceVolume(
            role=str(spec["role"]),
            footprint=spec["footprint"],
            bottom_fraction=float(spec["bottom_fraction"]),
            top_fraction=float(spec["top_fraction"]),
            verb=str(spec["verb"]),
        ) for spec in program_specs)
        program_union = _clean(unary_union([volume.footprint for volume in volumes]))
        if program_union is not None:
            footprint = program_union
        upper = None
        lower_fraction = None
        family = program_component_family(sequence.name) or family
        if program_section_graph or any(
            spec.get("roof_profile")
            or "main_long_span_hall" in str(spec.get("role") or "")
            for spec in program_specs
        ):
            # Program assemblies carry semantic roof geometry of their own.
            # A gym sequence starts with a bar for plan efficiency, but its
            # authored long-span ridge must still reach the profiled folded
            # surface compiler instead of inheriting `slender_podium_tower`
            # from that first plan operation.
            formal_principle = "folded_section"
        compiled_attachment_edges = [
            {
                "child_role": str(spec.get("role") or ""),
                "child_component_role": str(spec.get("component_role") or spec.get("role") or ""),
                **dict(edge),
            }
            for spec in program_specs
            for edge in (spec.get("typed_attachment_evidence") or ())
            if isinstance(edge, dict)
        ]
        failed_attachment_edges = [
            edge for edge in compiled_attachment_edges
            if str(edge.get("status") or "") not in {"already_materialized", "materialized"}
        ]
        program_component_relation_evidence = {
            "schema_version": "arr.maas.compiled_program_relations.v1",
            "status": "materialized" if compiled_attachment_edges else "not_applicable",
            "hard_pass": not failed_attachment_edges,
            "attach_edge_count": len(compiled_attachment_edges),
            "failed_attach_edge_count": len(failed_attachment_edges),
            "attach_edges": compiled_attachment_edges,
        }
    volumes = _consolidate_section_loft_proxy(
        volumes,
        formal_result.evidence if formal_result is not None else None,
        formal_result.volumes if formal_result is not None else (),
    )
    volumes = _consolidate_oblique_envelope_proxy(
        volumes,
        footprint,
        formal_result.evidence if formal_result is not None else None,
    )
    volumes = _prune_redundant_helper_volumes(volumes)
    review_volume_limit = 5 if sequence.name.startswith(("creative_voxel_cascade", "creative_cluster_village")) else 4
    volumes = _cap_review_volumes(volumes, limit=review_volume_limit)
    coherence_evidence = evaluate_source_volume_coherence(volumes)
    rule_evidence = finalize_rule_evidence(rule_evidence, [volume.role for volume in volumes])
    component_profiled_roles = {str(spec["role"]) for spec in program_specs if spec.get("roof_profile")}
    formal_surfaces, formal_profiled_roles, continuous_surface_evidence = _profiled_formal_surfaces(
        volumes,
        footprint,
        formal_principle,
        formal_result.evidence if formal_result is not None else None,
    )
    program_section_surfaces, program_section_profiled_roles, program_section_graph_evidence = (
        _profiled_program_section_surfaces(program_specs, footprint, program_section_graph)
    )
    if program_section_graph_evidence and program_component_relation_evidence:
        program_section_graph_evidence["compiled_relation_evidence"] = program_component_relation_evidence
    if program_section_profiled_roles:
        formal_surfaces = tuple(
            surface for surface in formal_surfaces
            if surface.volume_role not in program_section_profiled_roles
        )
        continuous_surface_evidence = {
            "schema_version": "arr.maas.continuous_surface.v1",
            "status": "materialized",
            "hard_pass": True,
            "principle": formal_principle,
            "representation": "program_section_graph_planar_strips",
            "profiled_volume_count": len(program_section_profiled_roles),
            "surface_count": len(program_section_surfaces),
            "profiled_roles": sorted(program_section_profiled_roles),
            "program_section_graph": program_section_graph_evidence,
        }
    profiled_roles = component_profiled_roles | formal_profiled_roles | program_section_profiled_roles
    standard_surface_volumes = tuple(volume for volume in volumes if volume.role not in profiled_roles)
    surfaces = (
        _source_surfaces(standard_surface_volumes, footprint)
        + _profiled_component_surfaces(program_specs, footprint)
        + program_section_surfaces
        + formal_surfaces
    )
    parameter_source = sequence_source
    parameter_default_count = sum(1 for item in parameter_provenance if item.get("used_default"))
    if evolution_family:
        family = evolution_family
    elif declared_family and sequence.name.startswith("llm_") and _sequence_supports_declared_family(sequence, declared_family):
        family = declared_family
    return SourceMass(
        name=sequence.name,
        footprint=footprint,
        upper_footprint=upper,
        lower_floor_fraction=lower_fraction,
        volumes=volumes,
        surfaces=surfaces,
        verb_trace=tuple(trace),
        notes=tuple(sequence.notes) + ("source_geometry_compiled=arr_native_v2",),
        metadata={
            "family": family,
            "parameter_source": parameter_source,
            "parameter_provenance": parameter_provenance,
            "parameter_default_count": parameter_default_count,
            "rule_evidence": rule_evidence,
            "primary_language": primary_language,
            "secondary_language": secondary_language,
            "reference_basis": reference_basis,
            "formal_principle": formal_principle,
            "dominant_gesture": dominant_gesture,
            "massing_genome": massing_genome.to_dict() if massing_genome is not None else {},
            "massing_genome_circuit": massing_genome.to_circuit() if massing_genome is not None else {},
            "component_graph": component_graph.to_dict(),
            "graph_materialization_evidence": graph_materialization_evidence,
            "coherence_evidence": coherence_evidence,
            "continuous_surface_evidence": continuous_surface_evidence,
            "program_section_graph_evidence": program_section_graph_evidence,
            "program_component_relation_evidence": program_component_relation_evidence,
            "program_book_projection_evidence": program_book_projection_evidence,
            "architectural_ambition_evidence": formal_result.evidence if formal_result is not None else {},
            "secondary_family": secondary_family,
            "requires_llm_authoring": not is_authored,
            "asymmetry_hint": "upper_offset_or_cut" if upper is not None and not upper.centroid.equals(footprint.centroid) else "plan_or_section_cut",
        },
    )


def compile_component_graph_to_source_mass(
    base_footprint: Polygon,
    component_graph: MassComponentGraph,
) -> SourceMass | None:
    """Compile a hierarchy directly; parent state controls every node input."""
    sequence = component_graph.to_sequence(name=component_graph.name)
    return _compile_in_site_frame(base_footprint, sequence, component_graph)


def compile_sequence_to_source_mass(base_footprint: Polygon, sequence: VerbSequence) -> SourceMass | None:
    """Compatibility adapter from legacy flat MassDSL into a dependency graph."""
    component_graph = graph_from_sequence(sequence)
    return _compile_in_site_frame(base_footprint, sequence, component_graph)


def _site_frame_angle(footprint: Polygon) -> float:
    """Return the dominant minimum-rectangle axis in world degrees."""
    rectangle = footprint.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    edges = [
        (hypot(right[0] - left[0], right[1] - left[1]), left, right)
        for left, right in zip(coordinates, coordinates[1:])
    ]
    if not edges:
        return 0.0
    _, left, right = max(edges, key=lambda item: item[0])
    angle = degrees(atan2(right[1] - left[1], right[0] - left[0]))
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def _compile_in_site_frame(
    base_footprint: Polygon,
    sequence: VerbSequence,
    component_graph: MassComponentGraph,
) -> SourceMass | None:
    """Generate along the parcel's own axis, then restore world coordinates."""
    angle = _site_frame_angle(base_footprint)
    center = (float(base_footprint.centroid.x), float(base_footprint.centroid.y))
    aligned = rotate(base_footprint, -angle, origin=center) if abs(angle) > 1e-6 else base_footprint
    source = _compile_component_graph_to_source_mass(aligned, sequence, component_graph)
    if source is None:
        return None
    frame_evidence = {
        "schema_version": "arr.maas.site_local_frame.v1",
        "dominant_axis_world_degrees": round(angle, 4),
        "generation_axis": "local_x",
        "restored_to_world_coordinates": True,
        "site_aspect_ratio": round(
            max(aligned.bounds[2] - aligned.bounds[0], aligned.bounds[3] - aligned.bounds[1])
            / max(min(aligned.bounds[2] - aligned.bounds[0], aligned.bounds[3] - aligned.bounds[1]), 1e-9),
            4,
        ),
    }
    if abs(angle) <= 1e-6:
        return SourceMass(
            name=source.name,
            footprint=source.footprint,
            upper_footprint=source.upper_footprint,
            lower_floor_fraction=source.lower_floor_fraction,
            volumes=source.volumes,
            surfaces=source.surfaces,
            verb_trace=source.verb_trace,
            notes=source.notes,
            status=source.status,
            fallback_reason=source.fallback_reason,
            metadata={**source.metadata, "site_frame_evidence": frame_evidence},
        )
    theta = radians(angle)

    def rotate_vertex(vertex: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = vertex
        return (x * cos(theta) - y * sin(theta), x * sin(theta) + y * cos(theta), z)

    return SourceMass(
        name=source.name,
        footprint=rotate(source.footprint, angle, origin=center),
        upper_footprint=rotate(source.upper_footprint, angle, origin=center) if source.upper_footprint is not None else None,
        lower_floor_fraction=source.lower_floor_fraction,
        volumes=tuple(SourceVolume(
            volume.role,
            rotate(volume.footprint, angle, origin=center),
            volume.bottom_fraction,
            volume.top_fraction,
            volume.verb,
        ) for volume in source.volumes),
        surfaces=tuple(SourceSurface(
            surface.role,
            surface.volume_role,
            surface.verb,
            surface.surface_type,
            tuple(rotate_vertex(vertex) for vertex in surface.vertices_m),
            surface.operator,
            surface.semantic_patch_id,
        ) for surface in source.surfaces),
        verb_trace=source.verb_trace,
        notes=source.notes,
        status=source.status,
        fallback_reason=source.fallback_reason,
        metadata={**source.metadata, "site_frame_evidence": frame_evidence},
    )


def source_mass_to_variant(source: SourceMass, sequence: VerbSequence) -> MorphologyVariant:
    is_llm = sequence.name.startswith("llm_")
    is_agent = sequence.name.startswith("agent_")
    is_grammar = sequence.name.startswith("grammar_")
    is_program = sequence.name.startswith("program_")
    is_authored_sequence = is_llm or is_agent or is_grammar or is_program
    research_basis = {
        "basis": "operative_design_verb_grammar",
        "optimization_mode": "llm_arch_language_proposal"
        if is_llm else (
            "agent_arch_language_proposal" if is_agent else (
            "grammar_agent_formal_principle_inference" if is_grammar else (
            "program_conditioned_massing_profile" if is_program else (
            "deterministic_fixture_parameter_sweep_requires_llm_authoring"
            if "__sweep_" in sequence.name else "deterministic_sequence_library"
            )
            )
            )
        ),
        "implemented_status": "arr_native_approximation",
        "sequence_name": sequence.name,
        "parameter_source": LLM_PARAMETER_SOURCE
        if is_llm else ("clone_maas_agent_arch_language" if is_agent else ("grammar_agent_formal_principle_inference" if is_grammar else ("program_massing_profile_v1" if is_program else "deterministic_sequence_library"))),
        "requires_llm_authoring": not is_authored_sequence,
        "legal_solver_role": "validate_clip_or_reject_only",
        "not_full_claim": ["not_full_evomass", "not_full_ssiea", "not_full_d4descent"],
    }
    return MorphologyVariant(
        source.name,
        source.footprint,
        upper_footprint=source.upper_footprint,
        lower_floor_fraction=source.lower_floor_fraction,
        notes=source.notes,
        verb_sequence=tuple(call.to_dict() for call in sequence.calls),
        source_geometry_status=source.status,
        source_verb_trace=tuple(trace.to_dict() for trace in source.verb_trace),
        source_signature=source.signature(),
        source_volumes=source.source_volume_signatures(),
        source_surfaces=source.source_surface_signatures(),
        research_basis=research_basis,
        source_mass=source,
    )

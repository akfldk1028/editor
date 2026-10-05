"""Cached competition-grade gestalt measured from the certified final mesh."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import json
from math import atan2, cos, radians, sin, sqrt
from threading import RLock
from typing import Any
import weakref

from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize, unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import has_strict_height_dependent_legal_section_contraction
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import safe_unary_union
from backend.app.modules.design.generation.maas.program_massing.visual_silhouette import visual_silhouette_view_variants


ProjectionMask = tuple[int, ...]
ProjectionVariant = tuple[
    ProjectionMask,
    ProjectionMask,
    ProjectionMask,
    ProjectionMask,
]

_GRID_SIZE = 24
_SOURCE_CACHE_LIMIT = 512
_PAIR_CACHE_LIMIT = 32_768
_AUTHORED_STEP_OPERATORS = frozenset({
    "setback",
    "stepped_mass",
    "terrace",
    "stepped_section",
    "book_grade",
})


@dataclass(frozen=True)
class CompetitionGestaltKey:
    """Hashable normalized measurements for one certified final solid."""

    projection_variants: tuple[ProjectionVariant, ...]
    floor_area_by_height: tuple[float, ...]
    setback_transition_sequence: tuple[tuple[float, ...], ...]
    roof_breakline_profile: tuple[float, ...]
    plan_profile: tuple[float, ...]
    visible_stepped: bool
    authored_stepped: bool
    legal_seam_stepped: bool
    projection_mode: str
    measurement_authority: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.competition_gestalt.v1",
            "measurement_authority": self.measurement_authority,
            "projection_mode": self.projection_mode,
            "projection_variant_count": len(self.projection_variants),
            "projection_grid_size": _GRID_SIZE,
            "floor_area_by_height": list(self.floor_area_by_height),
            "setback_transition_sequence": [
                list(transition)
                for transition in self.setback_transition_sequence
            ],
            "roof_breakline_profile": list(self.roof_breakline_profile),
            "plan_profile": list(self.plan_profile),
            "visible_stepped": self.visible_stepped,
            "authored_stepped": self.authored_stepped,
            "legal_seam_stepped": self.legal_seam_stepped,
        }

    def to_payload(self) -> dict[str, Any]:
        """Serialize every measurement needed for an independent audit."""

        return {
            **self.evidence(),
            "projection_variants": [
                [list(mask) for mask in variant]
                for variant in self.projection_variants
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CompetitionGestaltKey":
        if payload.get("schema_version") != "arr.maas.competition_gestalt.v1":
            raise ValueError("competition gestalt schema mismatch")
        raw_variants = payload.get("projection_variants")
        if not isinstance(raw_variants, list) or not raw_variants:
            raise ValueError("competition gestalt projection variants missing")
        variants: list[ProjectionVariant] = []
        for raw_variant in raw_variants:
            if not isinstance(raw_variant, list) or len(raw_variant) != 4:
                raise ValueError("competition gestalt projection variant invalid")
            masks: list[ProjectionMask] = []
            for raw_mask in raw_variant:
                if not isinstance(raw_mask, list) or len(raw_mask) != _GRID_SIZE:
                    raise ValueError("competition gestalt projection mask invalid")
                masks.append(tuple(int(value) for value in raw_mask))
            variants.append(tuple(masks))  # type: ignore[arg-type]
        return cls(
            projection_variants=tuple(variants),
            floor_area_by_height=tuple(
                float(value)
                for value in payload.get("floor_area_by_height") or ()
            ),
            setback_transition_sequence=tuple(
                tuple(float(value) for value in transition)
                for transition in (
                    payload.get("setback_transition_sequence") or ()
                )
            ),
            roof_breakline_profile=tuple(
                float(value)
                for value in payload.get("roof_breakline_profile") or ()
            ),
            plan_profile=tuple(
                float(value)
                for value in payload.get("plan_profile") or ()
            ),
            visible_stepped=payload.get("visible_stepped") is True,
            authored_stepped=payload.get("authored_stepped") is True,
            legal_seam_stepped=payload.get("legal_seam_stepped") is True,
            projection_mode=str(payload.get("projection_mode") or ""),
            measurement_authority=str(
                payload.get("measurement_authority") or ""
            ),
        )


_CERTIFIED_MORPHOLOGY_FIELDS = (
    "body_phenotype",
    "roof_archetype",
    "chassis_family",
    "plan_family",
)


def certified_mesh_morphology_payload_hash(
    morphology: dict[str, Any],
) -> str:
    normalized = {
        key: morphology.get(key)
        for key in (
            *_CERTIFIED_MORPHOLOGY_FIELDS,
            "solid_genus",
            "wedge_like",
            "pyramidal_like",
            "winged_or_curved",
        )
    }
    return _canonical_payload_hash(normalized)


def build_certified_mesh_gestalt_evidence(
    *,
    gestalt_key: CompetitionGestaltKey,
    visual_hash: str,
    exact_mesh_payload_hash: str,
    morphology: dict[str, Any],
) -> dict[str, Any]:
    """Bind measured gestalt/morphology facts to one exact visual mesh."""

    core = {
        "schema_version": "arr.maas.certified_mesh_gestalt.v1",
        "measurement_authority": "certified_projected_visual_mesh",
        "visual_hash": str(visual_hash or ""),
        "exact_mesh_payload_hash": str(exact_mesh_payload_hash or ""),
        "gestalt_payload_hash": _canonical_payload_hash(
            gestalt_key.to_payload()
        ),
        "morphology_payload_hash": (
            certified_mesh_morphology_payload_hash(morphology)
        ),
        "morphology": {
            key: morphology.get(key)
            for key in (
                *_CERTIFIED_MORPHOLOGY_FIELDS,
                "solid_genus",
                "wedge_like",
                "pyramidal_like",
                "winged_or_curved",
            )
        },
    }
    return {
        **core,
        "evidence_hash": _canonical_payload_hash(core),
    }


def validate_certified_mesh_gestalt_evidence(
    payload: dict[str, Any] | None,
    *,
    expected_visual_hash: str,
    expected_exact_mesh_payload_hash: str,
    expected_morphology_payload_hash: str,
    gestalt_payload: dict[str, Any],
) -> tuple[str, ...]:
    """Validate integrity and exact selected-visual binding."""

    evidence = dict(payload) if isinstance(payload, dict) else {}
    if not evidence:
        return ("certified_mesh_evidence_missing",)
    issues: list[str] = []
    if (
        evidence.get("schema_version")
        != "arr.maas.certified_mesh_gestalt.v1"
    ):
        issues.append("certified_mesh_schema_mismatch")
    if (
        evidence.get("measurement_authority")
        != "certified_projected_visual_mesh"
    ):
        issues.append("certified_mesh_authority_mismatch")
    visual_hash = str(evidence.get("visual_hash") or "").strip()
    if not visual_hash or visual_hash != str(expected_visual_hash or ""):
        issues.append("certified_mesh_visual_hash_mismatch")
    exact_mesh_payload_hash = str(
        evidence.get("exact_mesh_payload_hash") or ""
    ).strip()
    if (
        not exact_mesh_payload_hash
        or exact_mesh_payload_hash
        != str(expected_exact_mesh_payload_hash or "").strip()
    ):
        issues.append("certified_mesh_payload_hash_mismatch")
    try:
        expected_gestalt_hash = _canonical_payload_hash(gestalt_payload)
    except (TypeError, ValueError):
        expected_gestalt_hash = ""
    if (
        not expected_gestalt_hash
        or str(evidence.get("gestalt_payload_hash") or "")
        != expected_gestalt_hash
    ):
        issues.append("certified_mesh_gestalt_hash_mismatch")
    claimed_evidence_hash = str(evidence.pop("evidence_hash", "") or "")
    try:
        measured_evidence_hash = _canonical_payload_hash(evidence)
    except (TypeError, ValueError):
        measured_evidence_hash = ""
    if (
        not claimed_evidence_hash
        or claimed_evidence_hash != measured_evidence_hash
    ):
        issues.append("certified_mesh_evidence_hash_mismatch")
    morphology = evidence.get("morphology")
    morphology = morphology if isinstance(morphology, dict) else {}
    try:
        measured_morphology_hash = (
            certified_mesh_morphology_payload_hash(morphology)
        )
    except (TypeError, ValueError):
        measured_morphology_hash = ""
    claimed_morphology_hash = str(
        evidence.get("morphology_payload_hash") or ""
    )
    if (
        not measured_morphology_hash
        or claimed_morphology_hash != measured_morphology_hash
        or claimed_morphology_hash
        != str(expected_morphology_payload_hash or "")
    ):
        issues.append("certified_mesh_morphology_hash_mismatch")
    for field in _CERTIFIED_MORPHOLOGY_FIELDS:
        if not str(morphology.get(field) or "").strip():
            issues.append(f"certified_mesh_morphology_missing:{field}")
    genus = morphology.get("solid_genus")
    if (
        isinstance(genus, bool)
        or not isinstance(genus, int)
        or genus < 0
    ):
        issues.append("certified_mesh_morphology_invalid:solid_genus")
    for field in (
        "wedge_like",
        "pyramidal_like",
        "winged_or_curved",
    ):
        if not isinstance(morphology.get(field), bool):
            issues.append(f"certified_mesh_morphology_invalid:{field}")
    return tuple(dict.fromkeys(issues))


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class _SourceEntry:
    source_ref: weakref.ReferenceType[SourceMass]
    key: CompetitionGestaltKey


@dataclass(frozen=True)
class _PairEntry:
    left_ref: weakref.ReferenceType[SourceMass]
    right_ref: weakref.ReferenceType[SourceMass]
    distance: float


_SOURCE_CACHE: OrderedDict[int, _SourceEntry] = OrderedDict()
_PAIR_CACHE: OrderedDict[tuple[int, int], _PairEntry] = OrderedDict()
_SOURCE_INFLIGHT: dict[int, Future[CompetitionGestaltKey]] = {}
_PAIR_INFLIGHT: dict[tuple[int, int], Future[float]] = {}
_CACHE_LOCK = RLock()
_CACHE_METRICS = {
    "descriptor_build_count": 0,
    "descriptor_cache_hit_count": 0,
    "pair_evaluation_count": 0,
    "pair_cache_hit_count": 0,
}


def competition_gestalt_key(source: SourceMass) -> CompetitionGestaltKey:
    """Build or reuse the certified-mesh composite descriptor for ``source``."""

    cache_id = id(source)
    with _CACHE_LOCK:
        cached = _SOURCE_CACHE.get(cache_id)
        if cached is not None and cached.source_ref() is source:
            _SOURCE_CACHE.move_to_end(cache_id)
            _CACHE_METRICS["descriptor_cache_hit_count"] += 1
            return cached.key
        if cached is not None:
            _SOURCE_CACHE.pop(cache_id, None)
        future = _SOURCE_INFLIGHT.get(cache_id)
        owner = future is None
        if owner:
            future = Future()
            _SOURCE_INFLIGHT[cache_id] = future
    assert future is not None
    if not owner:
        key = future.result()
        with _CACHE_LOCK:
            _CACHE_METRICS["descriptor_cache_hit_count"] += 1
        return key

    try:
        key = _build_key(source)

        def release(reference: weakref.ReferenceType[SourceMass]) -> None:
            with _CACHE_LOCK:
                current = _SOURCE_CACHE.get(cache_id)
                if current is not None and current.source_ref is reference:
                    _SOURCE_CACHE.pop(cache_id, None)

        reference = weakref.ref(source, release)
        with _CACHE_LOCK:
            _CACHE_METRICS["descriptor_build_count"] += 1
            _SOURCE_CACHE[cache_id] = _SourceEntry(reference, key)
            _SOURCE_CACHE.move_to_end(cache_id)
            while len(_SOURCE_CACHE) > _SOURCE_CACHE_LIMIT:
                _SOURCE_CACHE.popitem(last=False)
            future.set_result(key)
            _SOURCE_INFLIGHT.pop(cache_id, None)
        return key
    except BaseException as exc:
        with _CACHE_LOCK:
            future.set_exception(exc)
            _SOURCE_INFLIGHT.pop(cache_id, None)
        raise


def competition_gestalt_distance(
    left: SourceMass | CompetitionGestaltKey,
    right: SourceMass | CompetitionGestaltKey,
) -> float:
    """Return a bounded 0..1 certified-mesh gestalt distance."""

    if left is right:
        return 0.0
    if isinstance(left, CompetitionGestaltKey):
        left_key = left
        left_source = None
    else:
        left_key = None
        left_source = left
    if isinstance(right, CompetitionGestaltKey):
        right_key = right
        right_source = None
    else:
        right_key = None
        right_source = right
    if left_source is None or right_source is None:
        return _distance_from_keys(
            left_key or competition_gestalt_key(left_source),
            right_key or competition_gestalt_key(right_source),
        )
    if id(right_source) < id(left_source):
        left_source, right_source = right_source, left_source
    pair_id = (id(left_source), id(right_source))
    with _CACHE_LOCK:
        cached = _PAIR_CACHE.get(pair_id)
        if (
            cached is not None
            and cached.left_ref() is left_source
            and cached.right_ref() is right_source
        ):
            _PAIR_CACHE.move_to_end(pair_id)
            _CACHE_METRICS["pair_cache_hit_count"] += 1
            return cached.distance
        if cached is not None:
            _PAIR_CACHE.pop(pair_id, None)
        future = _PAIR_INFLIGHT.get(pair_id)
        owner = future is None
        if owner:
            future = Future()
            _PAIR_INFLIGHT[pair_id] = future
    assert future is not None
    if not owner:
        distance = float(future.result())
        with _CACHE_LOCK:
            _CACHE_METRICS["pair_cache_hit_count"] += 1
        return distance

    try:
        distance = _distance_from_keys(
            competition_gestalt_key(left_source),
            competition_gestalt_key(right_source),
        )
        left_ref = weakref.ref(left_source)
        right_ref = weakref.ref(right_source)
        with _CACHE_LOCK:
            _CACHE_METRICS["pair_evaluation_count"] += 1
            _PAIR_CACHE[pair_id] = _PairEntry(
                left_ref,
                right_ref,
                distance,
            )
            _PAIR_CACHE.move_to_end(pair_id)
            while len(_PAIR_CACHE) > _PAIR_CACHE_LIMIT:
                _PAIR_CACHE.popitem(last=False)
            future.set_result(distance)
            _PAIR_INFLIGHT.pop(pair_id, None)
        return distance
    except BaseException as exc:
        with _CACHE_LOCK:
            future.set_exception(exc)
            _PAIR_INFLIGHT.pop(pair_id, None)
        raise


def competition_gestalt_cache_metrics() -> dict[str, int]:
    with _CACHE_LOCK:
        return {
            **_CACHE_METRICS,
            "descriptor_cache_size": len(_SOURCE_CACHE),
            "pair_cache_size": len(_PAIR_CACHE),
        }


def reset_competition_gestalt_cache() -> None:
    with _CACHE_LOCK:
        _SOURCE_CACHE.clear()
        _PAIR_CACHE.clear()
        _SOURCE_INFLIGHT.clear()
        _PAIR_INFLIGHT.clear()
        for metric in _CACHE_METRICS:
            _CACHE_METRICS[metric] = 0


def _build_key(source: SourceMass) -> CompetitionGestaltKey:
    view_variants = visual_silhouette_view_variants(source)
    mesh_triangles = _principal_mesh_triangles(source)
    isometric_variants = _isometric_edge_variants(mesh_triangles)
    projection_variants = tuple(
        (
            _polygon_mask(top),
            _polygon_mask(front),
            _polygon_mask(side),
            (
                isometric_variants[index]
                if index < len(isometric_variants)
                else _empty_mask()
            ),
        )
        for index, (top, front, side) in enumerate(view_variants)
    )
    layer_sections = _layer_sections(mesh_triangles)
    floor_area_profile = _floor_area_profile(layer_sections)
    transitions = _setback_transitions(mesh_triangles)
    authored_stepped = _authored_stepped(source)
    projection_mode = _projection_mode(source)
    legal_seam_stepped = (
        projection_mode == "intentional_floorwise_stepped"
    )
    legal_contraction = mandatory_legal_contraction(source)
    significant_transitions = sum(
        max(abs(value) for value in transition[:3]) >= 0.08
        for transition in transitions
    )
    visible_stepped = bool(
        significant_transitions >= 1
        and (
            authored_stepped
            or legal_seam_stepped
            or not legal_contraction
        )
    )
    plan_section = max(
        (section for _height, section in layer_sections),
        key=lambda section: float(section.area),
        default=Polygon(),
    )
    return CompetitionGestaltKey(
        projection_variants=projection_variants,
        floor_area_by_height=floor_area_profile,
        setback_transition_sequence=transitions,
        roof_breakline_profile=_roof_breakline_profile(mesh_triangles),
        plan_profile=_plan_profile(plan_section),
        visible_stepped=visible_stepped,
        authored_stepped=authored_stepped,
        legal_seam_stepped=legal_seam_stepped,
        projection_mode=projection_mode,
        measurement_authority=(
            "certified_final_mesh"
            if _certified_projection(source)
            else "final_source_mesh"
        ),
    )


def mandatory_legal_contraction(source: SourceMass) -> bool:
    """Identify a measured contraction imposed by certified legal clipping."""

    certificate = source.metadata.get("floorwise_visual_projection") or {}
    if not isinstance(certificate, dict):
        return False
    certified_operation = (
        str(certificate.get("certification_mode") or ""),
        str(certificate.get("visible_geometry_operation") or ""),
    )
    if not (
        certificate.get("status") == "certified"
        and certificate.get("hard_pass") is True
        and certified_operation in {
            (
                "floorwise_profiled_continuous_envelope_clip",
                "authored_profiled_mesh_continuous_legal_envelope_intersection",
            ),
            (
                "floorwise_profiled_legal_clip",
                "authored_profiled_mesh_legal_solid_intersection",
            ),
            (
                "floorwise_csg_section_loft",
                "exact_legal_section_profile_loft",
            ),
        }
        and certificate.get("visible_step_fallback") is False
    ):
        return False
    return has_strict_height_dependent_legal_section_contraction(certificate)


def _distance_from_keys(
    left: CompetitionGestaltKey,
    right: CompetitionGestaltKey,
) -> float:
    if not left.projection_variants or not right.projection_variants:
        return 1.0
    left_projection = left.projection_variants[0]
    projection_distance = min(
        (
            _mask_distance(left_projection[0], variant[0]) * 0.14
            + _mask_distance(left_projection[1], variant[1]) * 0.13
            + _mask_distance(left_projection[2], variant[2]) * 0.13
            + _mask_distance(left_projection[3], variant[3]) * 0.10
        )
        for variant in right.projection_variants
    )
    distance = (
        projection_distance
        + _vector_distance(
            left.floor_area_by_height,
            right.floor_area_by_height,
        ) * 0.10
        + _transition_distance(
            left.setback_transition_sequence,
            right.setback_transition_sequence,
        ) * 0.12
        + _vector_distance(
            left.roof_breakline_profile,
            right.roof_breakline_profile,
        ) * 0.08
        + _vector_distance(
            left.plan_profile,
            right.plan_profile,
        ) * 0.20
    )
    return round(min(1.0, max(0.0, distance)), 8)


def _layer_sections(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
) -> tuple[tuple[float, Polygon], ...]:
    levels = _mesh_z_levels(triangles)
    sections: list[tuple[float, Polygon]] = []
    for lower, upper in zip(levels, levels[1:]):
        if upper - lower <= 1e-9:
            continue
        height = (lower + upper) / 2.0
        section = _mesh_section_polygon(triangles, height)
        if isinstance(section, Polygon) and not section.is_empty:
            sections.append((height, section))
    return tuple(sections)


def _floor_area_profile(
    sections: tuple[tuple[float, Polygon], ...],
) -> tuple[float, ...]:
    if not sections:
        return ()
    areas = [float(section.area) for _height, section in sections]
    maximum = max(areas, default=0.0)
    if maximum <= 1e-9:
        return tuple(0.0 for _area in areas)
    return tuple(round(area / maximum, 6) for area in areas)


def _setback_transitions(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
) -> tuple[tuple[float, ...], ...]:
    levels = _mesh_z_levels(triangles)
    if len(levels) < 3:
        return ()
    section_samples = _layer_sections(triangles)
    if not section_samples:
        return ()
    maximum_width = max(
        section.bounds[2] - section.bounds[0]
        for _height, section in section_samples
    )
    maximum_depth = max(
        section.bounds[3] - section.bounds[1]
        for _height, section in section_samples
    )
    maximum_area = max(
        float(section.area)
        for _height, section in section_samples
    )
    scale = max(maximum_width, maximum_depth, 1e-9)
    transitions: list[tuple[float, ...]] = []
    for index, level in enumerate(levels[1:-1], start=1):
        local_span = min(
            level - levels[index - 1],
            levels[index + 1] - level,
        )
        epsilon = max(local_span * 1e-3, 1e-7)
        below = _mesh_section_polygon(triangles, level - epsilon)
        above = _mesh_section_polygon(triangles, level + epsilon)
        if below is None or above is None:
            continue
        before = _section_features(
            below,
            maximum_width=maximum_width,
            maximum_depth=maximum_depth,
            maximum_area=maximum_area,
            scale=scale,
        )
        after = _section_features(
            above,
            maximum_width=maximum_width,
            maximum_depth=maximum_depth,
            maximum_area=maximum_area,
            scale=scale,
        )
        transition = (
            *(
                round(after[index] - before[index], 6)
                for index in range(3)
            ),
            round(abs(after[3] - before[3]), 6),
            round(abs(after[4] - before[4]), 6),
        )
        if max(abs(value) for value in transition[:3]) >= 0.08:
            transitions.append(transition)
    return tuple(transitions)


def _section_features(
    section: Polygon,
    *,
    maximum_width: float,
    maximum_depth: float,
    maximum_area: float,
    scale: float,
) -> tuple[float, ...]:
    return (
        (section.bounds[2] - section.bounds[0])
        / max(maximum_width, 1e-9),
        (section.bounds[3] - section.bounds[1])
        / max(maximum_depth, 1e-9),
        float(section.area) / max(maximum_area, 1e-9),
        float(section.centroid.x) / scale,
        float(section.centroid.y) / scale,
    )


def _principal_mesh_triangles(
    source: SourceMass,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    triangles = tuple(
        tuple(
            tuple(float(value) for value in vertex)
            for vertex in surface.vertices_m[:3]
        )
        for surface in source.surfaces
        if (
            surface.surface_type.startswith("profiled_")
            and len(surface.vertices_m) >= 3
        )
    )
    if not triangles:
        return ()
    projected = []
    for triangle in triangles:
        polygon = Polygon(tuple(
            (vertex[0], vertex[1])
            for vertex in triangle
        ))
        if polygon.is_valid and float(polygon.area) > 1e-10:
            projected.append(polygon)
    plan = safe_unary_union(projected)
    if plan is None or plan.is_empty:
        return triangles
    rectangle = plan.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    edges = [
        (
            (x2 - x1) ** 2 + (y2 - y1) ** 2,
            atan2(y2 - y1, x2 - x1),
        )
        for (x1, y1), (x2, y2) in zip(
            coordinates,
            coordinates[1:],
        )
    ]
    major_squared, major_angle = max(edges, key=lambda edge: edge[0])
    major_length = sqrt(major_squared)
    if major_length <= 1e-9:
        return triangles
    center = plan.centroid
    min_z = min(
        vertex[2]
        for triangle in triangles
        for vertex in triangle
    )
    theta = -major_angle
    cosine = cos(theta)
    sine = sin(theta)
    return tuple(
        tuple(
            (
                round(
                    (
                        (vertex[0] - center.x) * cosine
                        - (vertex[1] - center.y) * sine
                    ) / major_length,
                    9,
                ),
                round(
                    (
                        (vertex[0] - center.x) * sine
                        + (vertex[1] - center.y) * cosine
                    ) / major_length,
                    9,
                ),
                round((vertex[2] - min_z) / major_length, 9),
            )
            for vertex in triangle
        )
        for triangle in triangles
    )


def _mesh_z_levels(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
) -> tuple[float, ...]:
    return tuple(sorted({
        round(float(vertex[2]), 8)
        for triangle in triangles
        for vertex in triangle
    }))


def _mesh_section_polygon(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
    z: float,
) -> Polygon | None:
    segments: list[LineString] = []
    epsilon = 1e-8
    for triangle in triangles:
        intersections: list[tuple[float, float]] = []
        for left, right in zip(triangle, (*triangle[1:], triangle[0])):
            left_z = left[2] - z
            right_z = right[2] - z
            if abs(left_z) <= epsilon:
                intersections.append((left[0], left[1]))
            if left_z * right_z < -(epsilon * epsilon):
                amount = (z - left[2]) / (right[2] - left[2])
                intersections.append((
                    left[0] + (right[0] - left[0]) * amount,
                    left[1] + (right[1] - left[1]) * amount,
                ))
        unique: list[tuple[float, float]] = []
        for point in intersections:
            rounded = (
                round(float(point[0]), 7),
                round(float(point[1]), 7),
            )
            if rounded not in unique:
                unique.append(rounded)
        if len(unique) >= 2 and unique[0] != unique[1]:
            segments.append(LineString((unique[0], unique[1])))
    if not segments:
        return None
    polygons = tuple(polygonize(unary_union(segments)))
    if not polygons:
        return None
    hole_regions = tuple(
        Polygon(interior)
        for polygon in polygons
        for interior in polygon.interiors
    )
    retained = tuple(
        polygon
        for polygon in polygons
        if not any(
            hole.covers(polygon.representative_point())
            for hole in hole_regions
        )
    )
    section = unary_union(retained or polygons)
    return (
        section
        if isinstance(section, Polygon) and not section.is_empty
        else None
    )


def _roof_breakline_profile(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
) -> tuple[float, ...]:
    edges = _mesh_edges(triangles)
    if not edges:
        return (0.0,) * 6
    lengths = [0.0] * 4
    levels: set[float] = set()
    total = 0.0
    for first, second in edges:
        dx = second[0] - first[0]
        dy = second[1] - first[1]
        dz = second[2] - first[2]
        plan_length = sqrt(dx * dx + dy * dy)
        length = sqrt(plan_length * plan_length + dz * dz)
        if length <= 1e-9:
            continue
        total += length
        slope = abs(dz) / length
        bucket = (
            0
            if slope <= 0.05
            else 1
            if slope <= 0.45
            else 2
            if slope <= 0.90
            else 3
        )
        lengths[bucket] += length
        levels.update((round(first[2], 5), round(second[2], 5)))
    denominator = max(total, 1e-9)
    return (
        *(round(length / denominator, 6) for length in lengths),
        round(min(1.0, len(levels) / 12.0), 6),
        round(min(1.0, len(edges) / 256.0), 6),
    )


def _plan_profile(footprint: Polygon) -> tuple[float, ...]:
    if footprint.is_empty:
        return (0.0, 0.0, 0.0, 0.0)
    hull_area = float(footprint.convex_hull.area)
    holes_area = sum(
        float(Polygon(interior).area)
        for interior in footprint.interiors
    )
    return (
        round(float(footprint.area) / max(hull_area, 1e-9), 6),
        1.0 if footprint.interiors else 0.0,
        round(holes_area / max(hull_area, 1e-9), 6),
        round(min(1.0, len(footprint.exterior.coords) / 32.0), 6),
    )


def _authored_stepped(source: SourceMass) -> bool:
    program = source.metadata.get("geometry_program") or {}
    nodes = program.get("nodes") if isinstance(program, dict) else ()
    return any(
        str(node.get("operator") or "") in _AUTHORED_STEP_OPERATORS
        or (
            str(node.get("operator") or "") == "profiled_hall"
            and str((node.get("parameters") or {}).get("section_family") or "")
            == "stepped"
        )
        for node in (nodes or ())
        if isinstance(node, dict)
    )


def _projection_mode(source: SourceMass) -> str:
    for key in (
        "legal_field_affine_placement",
        "floorwise_legal_projection",
        "authored_legal_preservation",
        "floorwise_legal_matrix_stack",
    ):
        evidence = source.metadata.get(key)
        if not isinstance(evidence, dict):
            continue
        mode = str(evidence.get("projection_mode") or "")
        if mode:
            return mode
    return ""


def _certified_projection(source: SourceMass) -> bool:
    if not source.surfaces:
        return False
    for key in (
        "legal_field_affine_placement",
        "floorwise_legal_projection",
        "authored_legal_preservation",
    ):
        evidence = source.metadata.get(key)
        if not isinstance(evidence, dict):
            continue
        if (
            evidence.get("status") == "certified"
            or evidence.get("hard_pass") is True
            or evidence.get("projection_mode")
        ):
            return True
    return False


def _isometric_edge_variants(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
) -> tuple[ProjectionMask, ...]:
    edges = _mesh_edges(triangles)
    if not edges:
        return ()
    variants = []
    for angle_degrees in (0.0, 90.0, 180.0, 270.0):
        theta = radians(angle_degrees)
        for mirror_x in (False, True):
            lines = []
            for first, second in edges:
                projected = []
                for x, y, z in (first, second):
                    x = -x if mirror_x else x
                    rotated_x = x * cos(theta) - y * sin(theta)
                    rotated_y = x * sin(theta) + y * cos(theta)
                    projected.append((
                        (rotated_x - rotated_y) / sqrt(2.0),
                        z + (rotated_x + rotated_y) * 0.35,
                    ))
                if projected[0] != projected[1]:
                    lines.append(LineString(projected))
            variants.append(_line_mask(lines))
    return tuple(variants)


def _mesh_edges(
    triangles: tuple[tuple[tuple[float, float, float], ...], ...],
) -> tuple[
    tuple[tuple[float, float, float], tuple[float, float, float]],
    ...,
]:
    edges: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        tuple[tuple[float, float, float], tuple[float, float, float]],
    ] = {}
    for triangle in triangles:
        vertices = tuple(
            tuple(round(float(value), 7) for value in vertex)
            for vertex in triangle
        )
        for first, second in zip(vertices, (*vertices[1:], vertices[0])):
            key = tuple(sorted((first, second)))
            edges[key] = (first, second)
    return tuple(edges.values())


def _polygon_mask(polygon: Polygon) -> ProjectionMask:
    if polygon.is_empty:
        return _empty_mask()
    min_x, min_y, max_x, max_y = polygon.bounds
    span = max(max_x - min_x, max_y - min_y)
    if span <= 1e-9:
        return _empty_mask()
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    return _geometry_mask(
        polygon,
        center_x=center_x,
        center_y=center_y,
        span=span,
    )


def _line_mask(lines: list[LineString]) -> ProjectionMask:
    if not lines:
        return _empty_mask()
    geometry = safe_unary_union(lines)
    if geometry is None or geometry.is_empty:
        return _empty_mask()
    min_x, min_y, max_x, max_y = geometry.bounds
    span = max(max_x - min_x, max_y - min_y)
    if span <= 1e-9:
        return _empty_mask()
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    buffered = geometry.buffer(span / _GRID_SIZE * 0.35)
    return _geometry_mask(
        buffered,
        center_x=center_x,
        center_y=center_y,
        span=span,
    )


def _geometry_mask(
    geometry: Any,
    *,
    center_x: float,
    center_y: float,
    span: float,
) -> ProjectionMask:
    half = span * 0.55
    cell = (half * 2.0) / _GRID_SIZE
    rows = []
    for row in range(_GRID_SIZE):
        bits = 0
        lower_y = center_y - half + row * cell
        for column in range(_GRID_SIZE):
            lower_x = center_x - half + column * cell
            pixel = box(
                lower_x,
                lower_y,
                lower_x + cell,
                lower_y + cell,
            )
            if geometry.intersects(pixel):
                bits |= 1 << column
        rows.append(bits)
    return tuple(rows)


def _empty_mask() -> ProjectionMask:
    return (0,) * _GRID_SIZE


def _mask_distance(left: ProjectionMask, right: ProjectionMask) -> float:
    intersection = sum(
        (left_row & right_row).bit_count()
        for left_row, right_row in zip(left, right)
    )
    union = sum(
        (left_row | right_row).bit_count()
        for left_row, right_row in zip(left, right)
    )
    return 0.0 if union == 0 else 1.0 - intersection / union


def _vector_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    length = max(len(left), len(right))
    if length == 0:
        return 0.0
    return min(1.0, sum(
        abs(
            (left[index] if index < len(left) else 0.0)
            - (right[index] if index < len(right) else 0.0)
        )
        for index in range(length)
    ) / length)


def _transition_distance(
    left: tuple[tuple[float, ...], ...],
    right: tuple[tuple[float, ...], ...],
) -> float:
    length = max(len(left), len(right))
    if length == 0:
        return 0.0
    total = 0.0
    for index in range(length):
        left_transition = left[index] if index < len(left) else ()
        right_transition = right[index] if index < len(right) else ()
        total += _vector_distance(left_transition, right_transition)
    return min(1.0, total / length)


__all__ = [
    "CompetitionGestaltKey",
    "competition_gestalt_cache_metrics",
    "competition_gestalt_distance",
    "competition_gestalt_key",
    "reset_competition_gestalt_cache",
]

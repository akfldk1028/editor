"""Measured candidate analysis shared by generation, VLM and selection."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, isfinite, pi, sin, sqrt
from typing import Any

from backend.app.modules.design.generation.maas.book_language.mass_passport_bridge import resolve_capacity_band_evidence

from backend.app.modules.design.generation.maas.geometry_language.program_controller_contract import is_materialized_program_controller

from shapely.errors import GEOSException
from shapely.geometry import Polygon, shape

from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.chassis_taxonomy import classify_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.assembly_budget import assembly_budget_nodes
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence
from backend.app.modules.design.generation.maas.program_massing import resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.assembly import program_component_chassis
from backend.app.modules.design.generation.maas.program_massing.morphology import authoritative_surface_morphology, intrinsic_section_profile_distance, intrinsic_silhouette_distance
from backend.app.modules.design.generation.maas.program_massing.competition_gestalt import competition_gestalt_distance, competition_gestalt_key, mandatory_legal_contraction
from backend.app.modules.design.generation.maas.book_language.agent_authored_supply import AgentAuthoredAdmission, CODEX_OAUTH_AUTHOR_PROVIDER, is_validated_codex_oauth_candidate
from backend.app.modules.design.generation.maas.book_language.paid_provider_admission import is_admitted_paid_provider_program

@dataclass(frozen=True)
class _Candidate:
    principle_id: str
    principle_kind: str
    operation: str
    sequence: VerbSequence
    source: Any
    feature: dict[str, Any]
    score: float


def _distance(left: _Candidate, right: _Candidate) -> float:
    return competition_gestalt_distance(left.source, right.source)


def _silhouette_distance(left: _Candidate, right: _Candidate) -> float:
    visual = float(intrinsic_silhouette_distance(left.source, right.source))
    left_recursive = bool((left.source.metadata.get("geometry_program_bridge_evidence") or {}).get("status") == "materialized")
    right_recursive = bool((right.source.metadata.get("geometry_program_bridge_evidence") or {}).get("status") == "materialized")
    if left_recursive or right_recursive:
        # The full manifold mesh already contributes top/front/side surfaces.
        # Mixing in the legacy seed's section controls made genuinely distinct
        # recursive solids appear 50% identical and collapsed selection.
        return visual
    section = float(intrinsic_section_profile_distance(left.source, right.source))
    left_section = left.source.metadata.get("program_section_graph_evidence") or {}
    right_section = right.source.metadata.get("program_section_graph_evidence") or {}
    has_profiles = bool(
        isinstance(left_section, dict) and left_section.get("materialized_nodes")
        and isinstance(right_section, dict) and right_section.get("materialized_nodes")
    )
    return min(1.0, visual * 0.50 + section * 0.50) if has_profiles else visual


def _scope_key(candidate: _Candidate) -> str:
    evidence = candidate.source.metadata.get("program_book_projection_evidence") or {}
    scope = evidence.get("scope") if isinstance(evidence, dict) else {}
    return str(scope.get("base_volume_label") or "1/1") if isinstance(scope, dict) else "1/1"


def _portfolio_diversity_key(candidate: _Candidate) -> str:
    """The axis a portfolio quota should spread over: delivered ground take.

    The quota used to count BOOK base volume scopes, an authoring abstraction
    that does not survive into the form - all six scopes delivered masses with
    the same hierarchy and, more tellingly, the same silhouette envelope. It was
    forcing diversity along an axis nobody can see in the result.

    The ground take is measured on the delivered mass, against the capacity the
    law certifies, so two candidates in different positions here are two
    different propositions to an architect. Candidates measured before this
    evidence exists fall back to the scope so the quota never silently collapses
    to one bucket.
    """

    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    evidence = metadata.get("delivered_ground_take") if isinstance(metadata, dict) else None
    if isinstance(evidence, dict):
        band_id = str(evidence.get("band_id") or "")
        if band_id:
            void = metadata.get("delivered_void")
            void_id = (
                str(void.get("band_id") or "")
                if isinstance(void, dict)
                else ""
            )
            # Two axes, one cell. A courtyard scheme and a solid block on the
            # same ground take are different propositions, and a portfolio that
            # spreads only over ground would count them as the same position.
            return (
                f"ground_take:{band_id}|void:{void_id}"
                if void_id
                else f"ground_take:{band_id}"
            )
    return f"book_scope:{_scope_key(candidate)}"


def _capacity_alternative_key(candidate: _Candidate) -> str:
    """Return only the highest achieved selectable capacity band.

    Requested alternatives remain useful diagnostic evidence, but a request
    that the compiled solid did not achieve cannot describe archive or
    portfolio coverage.
    """

    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    evidence = (
        metadata.get("capacity_alternative_projection")
        if isinstance(metadata, dict)
        else {}
    ) or {}
    if not isinstance(evidence, dict):
        return ""
    # Requiring the selectable measurement marker prevents the canonical
    # resolver's legacy requested-label branch from becoming portfolio
    # authority.
    if "selectable_capacity_hard_pass" not in evidence:
        return ""
    measurement = (
        metadata.get("source_capacity_measurement")
        if isinstance(metadata, dict)
        else {}
    ) or {}
    resolution = resolve_capacity_band_evidence(
        evidence,
        capacity_measurement=(
            measurement if isinstance(measurement, dict) else {}
        ),
    )
    if resolution["resolved_capacity_hard_pass"] is not True:
        return ""
    return str(resolution["resolved_capacity_alternative_id"] or "")


def _requested_capacity_alternative_key(candidate: _Candidate) -> str:
    """Return requested capacity intent for diagnostics only."""

    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    evidence = (
        metadata.get("capacity_alternative_projection")
        if isinstance(metadata, dict)
        else {}
    ) or {}
    if not isinstance(evidence, dict):
        return ""
    return str(
        evidence.get("requested_capacity_alternative_id")
        or evidence.get("alternative_id")
        or ""
    )


def _capacity_target_gate(candidate: _Candidate) -> bool | None:
    """Return the measured ALT gate, or ``None`` for legacy/test candidates.

    Generation deliberately keeps target misses available to the typed VLM
    repair stage. Selection is the boundary where a measured miss becomes
    non-negotiable; an unmeasured legacy candidate remains compatible with
    older isolated selection tests and never masquerades as a measured pass.
    """

    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    evidence = (
        metadata.get("capacity_alternative_projection")
        if isinstance(metadata, dict)
        else {}
    ) or {}
    if not isinstance(evidence, dict) or (
        "selectable_capacity_hard_pass" not in evidence
        and "target_hard_pass" not in evidence
    ):
        return None
    if "selectable_capacity_hard_pass" in evidence:
        measurement = (
            metadata.get("source_capacity_measurement")
            if isinstance(metadata, dict)
            else {}
        ) or {}
        if isinstance(measurement, dict) and measurement:
            return bool(resolve_capacity_band_evidence(
                evidence,
                capacity_measurement=measurement,
            )["resolved_capacity_hard_pass"])
        return bool(evidence.get("selectable_capacity_hard_pass"))
    return bool(evidence.get("target_hard_pass"))


def _capacity_minimum_gate(candidate: _Candidate) -> bool | None:
    """Return the measured feasible-capacity floor gate when available."""

    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    evidence = (
        metadata.get("source_capacity_measurement")
        if isinstance(metadata, dict)
        else {}
    ) or {}
    if not isinstance(evidence, dict) or "hard_pass" not in evidence:
        return None
    return bool(evidence.get("hard_pass"))


def _seed_family(candidate: _Candidate) -> str:
    return candidate.sequence.name.split("__book_", 1)[0].split("__search_", 1)[0]


def _section_family(candidate: _Candidate) -> str:
    geometry_family = _geometry_program_family(candidate)
    if geometry_family:
        morphology = _solid_morphology_metrics(candidate)
        if morphology.get("profiled_section_family"):
            return f"recursive_section:{morphology['profiled_section_family']}"
        return f"recursive:{morphology['phenotype']}"
    evidence = candidate.source.metadata.get("program_section_graph_evidence") or {}
    nodes = evidence.get("materialized_nodes") if isinstance(evidence, dict) else ()
    operators = tuple(
        str(node.get("operator") or "")
        for node in (nodes or ())
        if isinstance(node, dict) and node.get("operator")
    )
    if operators:
        graph_operators = set(evidence.get("graph_operators") or ())
        modifiers = graph_operators & {"carved_entry", "daylight_monitor"}
        return "+".join(sorted(set(operators) | modifiers))
    signature = candidate.source.signature()
    return str(signature.get("formal_principle") or signature.get("family") or "flat_proxy")


def _roof_archetype(candidate: _Candidate) -> str:
    """Collapse decorative graph variants into their visible roof genotype."""
    geometry_family = _geometry_program_family(candidate)
    if geometry_family:
        morphology = _solid_morphology_metrics(candidate)
        if morphology.get("profiled_section_family"):
            return f"recursive_roof:{morphology['profiled_section_family']}"
        return f"recursive:{morphology['phenotype']}"
    evidence = candidate.source.metadata.get("program_section_graph_evidence") or {}
    operators = set(evidence.get("graph_operators") or ()) if isinstance(evidence, dict) else set()
    for operator, archetype in (
        ("ridge_roof", "gable_ridge"),
        ("flat_roof", "flat_box"),
        ("shed_roof", "mono_shed"),
        ("barrel_roof", "barrel_vault"),
        ("folded_roof", "folded"),
        ("sawtooth_roof", "sawtooth"),
        ("stepped_section", "stepped"),
    ):
        if operator in operators:
            return archetype
    return "flat_proxy"


def _chassis_family(candidate: _Candidate) -> str:
    """Return the normalized program-plan chassis independently of its roof."""
    geometry_family = _geometry_program_family(candidate)
    if geometry_family:
        program = _candidate_geometry_program_payload(candidate)
        metadata = program.get("metadata") if isinstance(program, dict) else {}
        nodes = program.get("nodes") if isinstance(program, dict) else ()
        source_operators = {
            str(node.get("operator") or "")
            for node in (nodes or ())
            if isinstance(node, dict)
            and str((node.get("provenance") or {}).get("source") or "")
            != "book_recursive_projection"
        }
        taxonomy = classify_geometry_program(
            family=geometry_family,
            source_operators=source_operators,
            declared_base_seed=(metadata or {}).get("base_seed"),
        )
        return f"recursive_chassis:{taxonomy['chassis']}"
    return program_component_chassis(candidate.sequence.name) or "generic_chassis"


def _geometry_program_family(candidate: _Candidate) -> str:
    evidence = candidate.source.metadata.get("geometry_program_bridge_evidence") or {}
    if not isinstance(evidence, dict) or evidence.get("status") != "materialized":
        return ""
    program = _candidate_geometry_program_payload(candidate)
    metadata = program.get("metadata") if isinstance(program, dict) else {}
    return str(
        (metadata or {}).get("family")
        or candidate.source.metadata.get("family")
        or "recursive_solid"
    )


def _geometry_program_metadata(candidate: _Candidate) -> dict[str, Any]:
    program = _candidate_geometry_program_payload(candidate)
    metadata = program.get("metadata") if isinstance(program, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _candidate_geometry_program_payload(
    candidate: _Candidate,
    *,
    prefer_authored: bool = True,
) -> dict[str, Any]:
    source = candidate.source if hasattr(candidate, "source") else candidate
    metadata = getattr(source, "metadata", {})
    if not isinstance(metadata, dict):
        return {}
    authored_payload = metadata.get("authored_geometry_program")
    geometry_payload = metadata.get("geometry_program")
    if prefer_authored and isinstance(authored_payload, dict):
        return deepcopy(authored_payload)
    if isinstance(geometry_payload, dict):
        return deepcopy(geometry_payload)
    if isinstance(authored_payload, dict):
        return deepcopy(authored_payload)
    return {}


def _plan_family(candidate: Any) -> str:
    """Classify the final measured footprint, never an authored family label."""

    source = candidate.source if hasattr(candidate, "source") else candidate
    footprint = getattr(source, "footprint", None)
    if footprint is None or footprint.is_empty:
        return "empty"
    if getattr(footprint, "geoms", None):
        parts = tuple(footprint.geoms)
        if len(parts) > 1:
            return "distributed"
        footprint = parts[0]
    if len(getattr(footprint, "interiors", ())) > 0:
        return "courtyard"
    minx, miny, maxx, maxy = footprint.bounds
    tolerance = max(maxx - minx, maxy - miny, 1e-7) * 0.015
    simplified = footprint.simplify(tolerance, preserve_topology=True)
    if simplified.is_empty or not hasattr(simplified, "exterior"):
        return "complex"
    vertex_count = max(0, len(tuple(simplified.exterior.coords)) - 1)
    convex_hull_area = max(float(simplified.convex_hull.area), 1e-9)
    convexity = float(simplified.area) / convex_hull_area
    if convexity < 0.90:
        return "articulated"
    if vertex_count == 3:
        return "triangular"
    aspect = _oriented_aspect(simplified)
    if vertex_count == 4:
        return "bar" if aspect >= 2.2 else "quadrilateral"
    if 5 <= vertex_count <= 7:
        return "faceted"
    return "curved_or_complex"


def _form_bank_lane(candidate: _Candidate) -> str:
    """Return the pre-program geometry-author lane retained in the exact AST."""
    return str(_geometry_program_metadata(candidate).get("form_bank_lane") or "")


def _vlm_reviewed_program_candidate(candidate: _Candidate) -> bool:
    metadata = _geometry_program_metadata(candidate)
    return bool(
        metadata.get("vlm_geometry_critic_active")
        and metadata.get("vlm_program_fit_hard_pass")
    )


def _validated_paid_provider_candidate(candidate: _Candidate) -> bool:
    program_payload = _candidate_geometry_program_payload(candidate)
    if not isinstance(program_payload, dict):
        return False
    try:
        current_hash = GeometryProgram.from_dict(
            program_payload
        ).program_hash()
    except (TypeError, ValueError):
        return False
    metadata = _geometry_program_metadata(candidate)
    source = candidate.source if hasattr(candidate, "source") else candidate
    source_metadata = getattr(source, "metadata", {})
    bridge = (
        source_metadata.get("geometry_program_bridge_evidence")
        if isinstance(source_metadata, dict)
        else {}
    ) or {}
    proof = bridge.get("pre_book_lineage_parent_proof") or {}
    response_id = str(metadata.get("author_response_id") or "")
    author_diagnostics = metadata.get("author_failure_diagnostics") or {}
    initial_hash = str(
        bridge.get("initial_llm_authored_pre_book_program_hash") or ""
    )
    return bool(
        metadata.get("author_provider") == "openai_llm_geometry_author"
        and metadata.get("llm_geometry_author_active") is True
        and metadata.get("author_representation") == "typed_json_ast"
        and response_id
        and str(metadata.get("author_prompt_contract") or "").startswith(
            "arr.maas.geometry_llm_author."
        )
        and metadata.get("author_provider_request_kind")
        in {
            "geometry_author_initial",
            "geometry_author_replenishment",
            "provider_retry",
        }
        and isinstance(author_diagnostics, dict)
        and author_diagnostics.get("schema_version")
        == "arr.maas.geometry_author_failure_diagnostics.v1"
        and int(author_diagnostics.get("valid_program_count") or 0) >= 1
        and is_admitted_paid_provider_program(
            response_id=response_id,
            request_kind=str(
                metadata.get("author_provider_request_kind") or ""
            ),
            prompt_contract=str(
                metadata.get("author_prompt_contract") or ""
            ),
            program_hash=initial_hash,
        )
        and isinstance(bridge, dict)
        and isinstance(proof, dict)
        and bridge.get("llm_geometry_author_active") is True
        and bridge.get("author_provider") == "openai_llm_geometry_author"
        and bridge.get("author_response_id") == response_id
        and bridge.get("post_book_authored_program_hash") == current_hash
        and initial_hash
        and proof.get("program_hash") == initial_hash
        and proof.get("compiler_clean") is True
        and proof.get("contained") is True
    )


def _llm_authored_candidate(
    candidate: _Candidate,
    *,
    codex_admission: AgentAuthoredAdmission | None = None,
) -> bool:
    metadata = _geometry_program_metadata(candidate)
    if metadata.get("author_provider") == CODEX_OAUTH_AUTHOR_PROVIDER:
        return is_validated_codex_oauth_candidate(
            candidate,
            admission=codex_admission,
        )
    return _validated_paid_provider_candidate(candidate)


def _seed_is_llm_authored(seed: VerbSequence) -> bool:
    return any(
        note == "geometry_program_llm_author_active=True"
        for note in seed.notes
    )


def _verified_exact_profiled_sloped_mesh(source: Any) -> bool:
    """Verify a physical sloped subset on the current exact visible mesh."""

    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    certificate = metadata.get("floorwise_visual_projection")
    bridge = metadata.get("geometry_program_bridge_evidence")
    payload = metadata.get("authored_geometry_program")
    if (
        not isinstance(certificate, dict)
        or certificate.get("schema_version")
        != "arr.maas.floorwise_visual_projection.v1"
        or certificate.get("hard_pass") is not True
        or certificate.get("status") != "certified"
        or (
            certificate.get("certification_mode"),
            certificate.get("visible_geometry_operation"),
        ) not in {
            (
                "floorwise_profiled_continuous_envelope_clip",
                "authored_profiled_mesh_continuous_legal_envelope_intersection",
            ),
            (
                "floorwise_profiled_legal_clip",
                "authored_profiled_mesh_legal_solid_intersection",
            ),
        }
        or certificate.get("visible_step_fallback") is not False
        or not isinstance(bridge, dict)
        or not isinstance(payload, dict)
    ):
        return False
    try:
        effective_height_m = float(
            certificate.get("effective_height_m") or 0.0
        )
    except (TypeError, ValueError):
        return False
    sloped_hash = str(
        certificate.get("verified_profiled_sloped_surface_hash") or ""
    )
    authored_hash = str(certificate.get("authored_program_hash") or "")
    if (
        not isfinite(effective_height_m)
        or effective_height_m <= 0.0
        or not sloped_hash
        or not authored_hash
    ):
        return False
    current_height = 0.0
    for context in (
        metadata.get("program_dimensional_context"),
        metadata.get("candidate_floor_context"),
        metadata.get("legal_generation_context_evidence"),
    ):
        if not isinstance(context, dict):
            continue
        for field in (
            "effective_height_m",
            "height_m",
            "requested_program_height_m",
        ):
            try:
                current_height = float(context.get(field) or 0.0)
            except (TypeError, ValueError):
                continue
            if isfinite(current_height) and current_height > 0.0:
                break
        if current_height > 0.0:
            break
    if (
        not isfinite(current_height)
        or abs(current_height - effective_height_m) > 1e-8
    ):
        return False
    try:
        authored = GeometryProgram.from_dict(payload)
    except (TypeError, ValueError):
        return False
    if (
        authored.validate()
        or authored.program_hash() != authored_hash
        or str(bridge.get("upstream_authored_program_hash") or "")
        != authored_hash
    ):
        return False

    from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import _exact_surface_payload_hash, floorwise_authority_binding_hash, profiled_sloped_mesh_evidence

    exact_surface_hash = _exact_surface_payload_hash(
        tuple(source.surfaces)
    )
    if (
        exact_surface_hash
        != str(certificate.get("exact_surface_payload_hash") or "")
    ):
        return False
    evidence = profiled_sloped_mesh_evidence(
        tuple(source.surfaces),
        effective_height_m=effective_height_m,
    )
    if (
        evidence["sloped_surface_hash"] != sloped_hash
        or round(float(evidence["sloped_surface_area"]), 8)
        != round(float(
            certificate.get("verified_profiled_sloped_surface_area")
            or 0.0
        ), 8)
        or round(float(evidence["sloped_surface_ratio"]), 8)
        != round(float(
            certificate.get("verified_profiled_sloped_surface_ratio")
            or 0.0
        ), 8)
    ):
        return False
    required = (
        "section_profile_hash",
        "capacity_volume_hash",
        "floor_capacity_plan_hash",
        "matrix4_stack_hash",
    )
    if any(not str(certificate.get(field) or "") for field in required):
        return False
    try:
        from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import valid_floor_center_numeric_equivalence
        if not valid_floor_center_numeric_equivalence(certificate):
            return False
        rebound = floorwise_authority_binding_hash(
            section_profile_hash=str(certificate["section_profile_hash"]),
            capacity_volume_hash=str(certificate["capacity_volume_hash"]),
            floor_capacity_plan_hash=str(
                certificate["floor_capacity_plan_hash"]
            ),
            matrix4_stack_hash=str(certificate["matrix4_stack_hash"]),
            exact_surface_payload_hash=exact_surface_hash,
            certification_mode=str(certificate["certification_mode"]),
            visible_geometry_operation=str(
                certificate["visible_geometry_operation"]
            ),
            visible_step_fallback=False,
            authored_program_hash=authored_hash,
            effective_height_m=effective_height_m,
            verified_profiled_sloped_surface_area=float(
                evidence["sloped_surface_area"]
            ),
            verified_profiled_sloped_surface_ratio=float(
                evidence["sloped_surface_ratio"]
            ),
            verified_profiled_sloped_surface_hash=sloped_hash,
            section_numeric_epsilon_m=float(
                certificate.get("section_numeric_epsilon_m") or 0.0
            ),
            floor_center_numeric_equivalence_schema=str(
                certificate.get(
                    "floor_center_numeric_equivalence_schema"
                ) or ""
            ),
            max_section_area_delta_m2=float(
                certificate.get("max_section_area_delta_m2") or 0.0
            ),
            max_section_symdiff_m2=float(
                certificate.get("max_section_symdiff_m2") or 0.0
            ),
            max_section_hausdorff_m=float(
                certificate.get("max_section_hausdorff_m") or 0.0
            ),
            max_section_area_bound_m2=float(
                certificate.get("max_section_area_bound_m2") or 0.0
            ),
            mesh_numeric_repair_schema=str(
                certificate.get("mesh_numeric_repair_schema") or ""
            ),
            mesh_cleanup_collapse_threshold_m=float(
                certificate.get(
                    "mesh_cleanup_collapse_threshold_m"
                ) or 0.0
            ),
            mesh_cleanup_max_physical_displacement_m=float(
                certificate.get(
                    "mesh_cleanup_max_physical_displacement_m"
                ) or 0.0
            ),
            mesh_cleanup_raw_indexed_mesh_hash=str(
                certificate.get(
                    "mesh_cleanup_raw_indexed_mesh_hash"
                ) or ""
            ),
            mesh_cleanup_raw_gate_failure_codes=tuple(
                certificate.get(
                    "mesh_cleanup_raw_gate_failure_codes"
                ) or ()
            ),
            mesh_cleanup_clean_indexed_mesh_hash=str(
                certificate.get(
                    "mesh_cleanup_clean_indexed_mesh_hash"
                ) or ""
            ),
            mesh_cleanup_clean_gate_hard_pass=bool(
                certificate.get("mesh_cleanup_clean_gate_hard_pass")
            ),
            section_geometry_binding_hash=str(
                certificate.get("section_geometry_binding_hash") or ""
            ),
        )
    except (TypeError, ValueError):
        return False
    if rebound != str(certificate.get("authority_binding_hash") or ""):
        return False
    return True


def _solid_morphology_metrics(candidate: Any) -> dict[str, Any]:
    """Measure the rendered recursive mesh, not its family label."""
    source = candidate.source if hasattr(candidate, "source") else candidate
    cached = source.metadata.get("measured_solid_morphology")
    if isinstance(cached, dict):
        required_step_fields = {
            "visible_stepped",
            "authored_stepped",
            "legal_seam_stepped",
            "mandatory_legal_contraction",
        }
        if required_step_fields <= set(cached):
            return cached
        origins = _step_origin_evidence(
            source,
            fallback_visible=(
                cached.get("body_phenotype") == "stepped"
                or cached.get("section_phenotype") == "stepped"
                or cached.get("phenotype") == "stepped"
            ),
        )
        enriched = {**cached, **origins}
        authoritative = authoritative_surface_morphology(source)
        if authoritative.get("hard_pass") is True:
            enriched.update({
                "phenotype": str(authoritative["phenotype"]),
                "body_phenotype": str(authoritative["phenotype"]),
                "visible_stepped": bool(
                    authoritative.get("visible_stepped")
                ),
                "pyramidal_like": bool(
                    authoritative.get("pyramidal_like")
                ),
                "measurement_authority": (
                    "renderer_authoritative_profiled_surface_mesh"
                ),
            })
        source.metadata["measured_solid_morphology"] = enriched
        return enriched
    total_area = horizontal_area = vertical_area = sloped_area = 0.0
    dimensional_context = source.metadata.get("program_dimensional_context") or {}
    candidate_floor_context = (
        source.metadata.get("candidate_floor_context") or {}
    )
    legal_context = source.metadata.get("legal_generation_context_evidence") or {}
    height_scale = float(
        dimensional_context.get("effective_height_m")
        or candidate_floor_context.get("height_m")
        or legal_context.get("requested_program_height_m")
        or 1.0
    )
    normal_bins: set[tuple[int, int, int]] = set()
    horizontal_levels: set[int] = set()
    triangle_count = 0
    z_values: list[float] = []
    for surface in source.surfaces:
        if surface.surface_type != "profiled_recursive_solid_mesh" or len(surface.vertices_m) < 3:
            continue
        a, b, c = tuple(
            (float(vertex[0]), float(vertex[1]), float(vertex[2]) * height_scale)
            for vertex in surface.vertices_m[:3]
        )
        z_values.extend((float(a[2]), float(b[2]), float(c[2])))
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        magnitude = sqrt(nx * nx + ny * ny + nz * nz)
        if magnitude <= 1e-12:
            continue
        area = magnitude / 2.0
        nx, ny, nz = nx / magnitude, ny / magnitude, nz / magnitude
        absolute_z = abs(nz)
        total_area += area
        triangle_count += 1
        normal_bins.add((round(nx * 4), round(ny * 4), round(nz * 4)))
        if absolute_z >= 0.90:
            horizontal_area += area
            horizontal_levels.add(round(sum(vertex[2] for vertex in (a, b, c)) / 3.0 * 20))
        elif absolute_z <= 0.12:
            vertical_area += area
        else:
            sloped_area += area
    denominator = max(total_area, 1e-9)
    program = source.metadata.get("geometry_program") or {}
    nodes = program.get("nodes") if isinstance(program, dict) else ()
    operators = {
        str(node.get("operator") or "")
        for node in (nodes or ())
        if isinstance(node, dict)
    }
    verified_profiled_sloped_mesh = (
        _verified_exact_profiled_sloped_mesh(source)
    )
    curved_intent = bool(operators & {"bend", "bent_bar", "sweep", "inflate", "twist"})
    oblique_intent = bool(operators & {"slice", "clip"})
    stepped_intent = bool(operators & {"setback", "stepped_mass", "terrace", "book_grade", "stack"})
    voided_intent = bool(operators & {"courtyard", "carve_void", "book_carve", "book_fracture", "book_notch", "book_extract", "notch", "embed_void", "puncture"})
    winged_intent = bool(operators & {"book_branch", "book_split", "book_lift", "book_lodge", "book_rotate", "related_array", "cross_mass", "split_wing", "radial_array", "mirror_array", "linear_array"})
    sloped_ratio = sloped_area / denominator
    horizontal_ratio = horizontal_area / denominator
    normal_bin_count = len(normal_bins)
    compilation = source.metadata.get("geometry_program_compilation") or {}
    compilation_metrics = compilation.get("metrics") if isinstance(compilation, dict) else {}
    genus = int((compilation_metrics or {}).get("genus") or 0)
    component_count = int((compilation_metrics or {}).get("component_count") or 1)
    footprint = source.footprint
    convex_hull_area = float(footprint.convex_hull.area) if not footprint.is_empty else 0.0
    plan_convexity = float(footprint.area) / max(convex_hull_area, 1e-9)
    upper_area_ratio = (
        float(source.upper_footprint.area) / max(float(footprint.area), 1e-9)
        if source.upper_footprint is not None and not source.upper_footprint.is_empty
        else 1.0
    )
    oriented_plan_aspect = _oriented_aspect(footprint) if not footprint.is_empty else 1.0
    profiled_section_family = next((
        str((node.get("parameters") or {}).get("section_family") or "")
        for node in (nodes or ())
        if isinstance(node, dict) and node.get("operator") == "profiled_hall"
    ), "")
    measured_profiled_hall = bool(
        profiled_section_family
        and oriented_plan_aspect >= 1.45
        and component_count == 1
    )
    horizontal_level_count = len(horizontal_levels)
    wedge_like, pyramidal_like = _section_silhouette_flags(
        sloped_surface_ratio=sloped_ratio,
        upper_area_ratio=upper_area_ratio,
        horizontal_level_count=horizontal_level_count,
        vertical_surface_ratio=vertical_area / denominator,
    )
    collapsed_profiled_tent_like = bool(
        measured_profiled_hall
        and (
            (
                # A usable hall needs a retained occupied enclosure below its
                # roof. If the upper occupied band falls below ten percent and
                # almost no vertical envelope remains, the result is a canopy
                # or tent regardless of how many triangulation levels it has.
                upper_area_ratio < 0.10
                and vertical_area / denominator < 0.03
            )
            or
            (
                upper_area_ratio <= 0.14
                and horizontal_ratio >= 0.90
                and vertical_area / denominator <= 0.03
                and horizontal_level_count >= 6
            )
            or (
                # A second failure mode is a shallow stack of sloped/horizontal
                # caps whose upper occupied plate almost disappears. It reads
                # as a tent even though the roof profile node itself is valid.
                upper_area_ratio <= 0.20
                and horizontal_ratio >= 0.84
                and sloped_ratio <= 0.17
                and vertical_area / denominator <= 0.03
                and horizontal_level_count >= 10
            )
            or (
                # A broader low-vertical barrel/canopy can keep more upper
                # plan area yet still collapse the occupied hall enclosure
                # into one triangular tent silhouette.
                upper_area_ratio <= 0.35
                and horizontal_ratio >= 0.80
                and sloped_ratio <= 0.20
                and vertical_area / denominator <= 0.03
                and horizontal_level_count >= 12
            )
        )
    )
    if measured_profiled_hall:
        # A measured elongated hall with an executable transverse section is
        # not automatically a compact pyramid merely because its ridge
        # reduces upper plan area.  The exception must not hide a collapsed
        # terrace/tent whose upper enclosure has nearly disappeared.
        pyramidal_like = collapsed_profiled_tent_like
        wedge_like = profiled_section_family == "shed"
    degenerate_sheet_like = bool(
        (
            upper_area_ratio < 0.06
            and horizontal_level_count >= 6
        )
        or (
            horizontal_ratio >= 0.94
            and vertical_area / denominator <= 0.01
            and sloped_ratio <= 0.06
            and normal_bin_count >= 20
        )
    )

    # Intent labels are only priors.  The final compiled solid is the
    # authority: a scoped cross/step/notch that disappears inside a union must
    # not make an otherwise calm prism count as a different phenotype.
    measured_void = genus > 0
    measured_wing = (
        winged_intent
        and (plan_convexity <= 0.84 or component_count > 1)
    )
    measured_curve = (
        curved_intent
        and normal_bin_count >= 11
        and (sloped_ratio >= 0.025 or normal_bin_count >= 14)
    )
    measured_step = (
        (not measured_profiled_hall and horizontal_level_count >= 4)
        or (stepped_intent and horizontal_level_count >= 3 and normal_bin_count >= 8)
    )
    step_origins = _step_origin_evidence(
        source,
        fallback_visible=measured_step,
    )
    measured_step = bool(step_origins["visible_stepped"])
    measured_prism = (
        genus == 0
        and component_count == 1
        and sloped_ratio < 0.06
        and horizontal_level_count <= 3
        and normal_bin_count <= 10
        and plan_convexity >= 0.88
    )
    measured_oblique = (
        (
            oblique_intent
            and sloped_ratio >= 0.055
            and normal_bin_count <= 10
            and component_count == 1
        )
        or (
            verified_profiled_sloped_mesh
            and sloped_ratio >= 0.055
            and component_count == 1
        )
    )
    section_graph_evidence = source.metadata.get("program_section_graph_evidence") or {}
    section_graph_operators = set(
        section_graph_evidence.get("graph_operators") or ()
    ) if isinstance(section_graph_evidence, dict) else set()
    section_graph_phenotype = _program_section_phenotype(section_graph_operators)
    section_phenotype = (
        {
            "barrel": "curved",
            "sawtooth": "stepped",
            "stepped": "stepped",
            "ridge": "oblique",
            "shed": "oblique",
            "folded": "oblique",
        }.get(profiled_section_family, "oblique")
        if measured_profiled_hall
        else section_graph_phenotype
    )
    # Roof/section language is already measured independently.  Do not let a
    # barrel or sawtooth terminal node erase the body's courtyard, wing,
    # curve, lift or oblique mutation.  Portfolio diversity must compare both
    # axes instead of counting the roof twice.
    if measured_void:
        phenotype = "voided"
    elif measured_wing:
        phenotype = "winged"
    elif measured_step:
        # A certified visible setback is a body-level fact. Sloped faces may
        # coexist with that step, but must not erase it into the broader
        # oblique class or the final portfolio loses the actual stepped mass.
        phenotype = "stepped"
    elif measured_oblique:
        phenotype = "oblique"
    elif measured_curve:
        phenotype = "curved"
    elif step_origins["mandatory_legal_contraction"]:
        phenotype = "legal_tapered"
    elif triangle_count == 0 and section_graph_phenotype:
        # Legacy/program-role solids do not carry recursive-mesh surface tags,
        # but their executable typed section graph still changes the rendered
        # roof.  Treating every one as a prism hid gable/folded/barrel/sawtooth
        # repetition and made the phenotype cap meaningless.
        phenotype = section_graph_phenotype
    elif sloped_ratio >= 0.24:
        phenotype = "oblique"
    elif measured_prism:
        phenotype = "prismatic"
    elif voided_intent and plan_convexity <= 0.82:
        # An open notch has genus zero, but a clearly concave plan still
        # carries a void/carve phenotype in the rendered mass.
        phenotype = "voided"
    elif winged_intent and plan_convexity <= 0.90:
        phenotype = "winged"
    else:
        phenotype = "prismatic"
    result = {
        "phenotype": phenotype,
        "wedge_like": wedge_like,
        "pyramidal_like": pyramidal_like,
        "collapsed_profiled_tent_like": collapsed_profiled_tent_like,
        "body_phenotype": phenotype,
        "section_phenotype": section_phenotype or "none",
        "degenerate_sheet_like": degenerate_sheet_like,
        "horizontal_surface_ratio": round(horizontal_ratio, 4),
        "vertical_surface_ratio": round(vertical_area / denominator, 4),
        "sloped_surface_ratio": round(sloped_ratio, 4),
        "normal_direction_bin_count": normal_bin_count,
        "horizontal_level_count": horizontal_level_count,
        "plan_convexity": round(plan_convexity, 4),
        "upper_area_ratio": round(upper_area_ratio, 4),
        "genus": genus,
        "component_count": component_count,
        "oriented_plan_aspect_ratio": round(oriented_plan_aspect, 4),
        "profiled_section_family": profiled_section_family,
        "measured_profiled_hall": measured_profiled_hall,
        "verified_exact_profiled_sloped_mesh": (
            verified_profiled_sloped_mesh
        ),
        **step_origins,
        "recursive_triangle_count": triangle_count,
        "solid_height_m": round(max(z_values) - min(z_values), 4) if z_values else 0.0,
        "measurement_authority": (
            "profiled_recursive_solid_mesh"
            if triangle_count
            else "compiled_program_section_graph"
        ),
    }
    authoritative = authoritative_surface_morphology(source)
    if authoritative.get("hard_pass") is True:
        result.update({
            "phenotype": str(authoritative["phenotype"]),
            "body_phenotype": str(authoritative["phenotype"]),
            "visible_stepped": bool(
                authoritative.get("visible_stepped")
            ),
            "pyramidal_like": bool(
                authoritative.get("pyramidal_like")
            ),
            "measurement_authority": (
                "renderer_authoritative_profiled_surface_mesh"
            ),
        })
    source.metadata["measured_solid_morphology"] = result
    return result


def _step_origin_evidence(
    source: Any,
    *,
    fallback_visible: bool,
) -> dict[str, Any]:
    """Separate visible, authored, and legal-seam sources of stepping."""

    metadata = getattr(source, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    program = metadata.get("geometry_program") or {}
    nodes = program.get("nodes") if isinstance(program, dict) else ()
    authored = any(
        str(node.get("operator") or "") in {
            "setback",
            "stepped_mass",
            "terrace",
            "stepped_section",
            "book_grade",
        }
        or (
            str(node.get("operator") or "") == "profiled_hall"
            and str((node.get("parameters") or {}).get("section_family") or "")
            == "stepped"
        )
        for node in (nodes or ())
        if isinstance(node, dict)
    )
    projection_mode = next((
        str(evidence.get("projection_mode") or "")
        for key in (
            "legal_field_affine_placement",
            "floorwise_legal_projection",
            "authored_legal_preservation",
            "floorwise_legal_matrix_stack",
        )
        for evidence in (metadata.get(key),)
        if isinstance(evidence, dict) and evidence.get("projection_mode")
    ), "")
    legal_seam = projection_mode == "intentional_floorwise_stepped"
    competition_evidence: dict[str, Any] = {}
    legal_contraction = mandatory_legal_contraction(source)
    visible = bool(fallback_visible)
    if (
        getattr(source, "volumes", ())
        and getattr(source, "surfaces", ())
    ):
        gestalt = competition_gestalt_key(source)
        visible = gestalt.visible_stepped
        authored = gestalt.authored_stepped
        legal_seam = gestalt.legal_seam_stepped
        projection_mode = gestalt.projection_mode
        competition_evidence = gestalt.evidence()
        metadata["competition_gestalt"] = competition_evidence
    return {
        "visible_stepped": visible,
        "authored_stepped": authored,
        "legal_seam_stepped": legal_seam,
        "mandatory_legal_contraction": legal_contraction,
        "step_projection_mode": projection_mode,
        "competition_gestalt": competition_evidence,
    }


def _section_silhouette_flags(
    *,
    sloped_surface_ratio: float,
    upper_area_ratio: float,
    horizontal_level_count: int,
    vertical_surface_ratio: float,
) -> tuple[bool, bool]:
    """Classify visible convergence without topology-based exemptions.

    A carved, multi-component, or highly faceted solid can still read as the
    same wedge/pyramid silhouette on a review board.  Genus, component count,
    and normal-bin complexity therefore must not excuse that repetition.
    """
    wedge_like = bool(
        sloped_surface_ratio >= 0.18
        or (sloped_surface_ratio >= 0.10 and upper_area_ratio <= 0.74)
    )
    pyramidal_like = bool(
        (upper_area_ratio <= 0.68 and horizontal_level_count >= 4)
        or (
            sloped_surface_ratio >= 0.08
            and horizontal_level_count >= 10
            and vertical_surface_ratio <= 0.03
        )
    )
    return wedge_like, pyramidal_like


def _program_form_gate(source: Any, building_type: str) -> dict[str, Any]:
    """Reject measured forms that erase a program's dominant spatial relation.

    This is deliberately relation-based rather than a named-form template.
    A gym may be rectilinear, curved, gabled, folded, sawtoothed, or stepped,
    but its dominant mass must still enclose a usable long-span hall.  A stack
    of horizontal plates with virtually no vertical enclosure cannot satisfy
    that invariant even when its metadata calls it a hall.
    """
    metrics = _solid_morphology_metrics(source)
    program_key = str(building_type or "").strip().lower()
    failures: list[str] = []
    composition = _architectural_articulation_metrics(source)
    evidence: dict[str, Any] = {
        "program": program_key,
        "measured_morphology": metrics,
        "architectural_articulation": composition,
        "rule": "program invariant retained by compiled solid",
    }
    if composition["budget_failures"]:
        failures.append("architectural_body_rule_budget_exceeded")
        failures.extend(f"architectural_{reason}" for reason in composition["budget_failures"])
    if composition["duplicated_structural_families"]:
        failures.append("architectural_body_rule_family_repeated")
    if "gym" in program_key or "체육" in program_key:
        level_count = int(metrics.get("horizontal_level_count") or 0)
        horizontal_ratio = float(metrics.get("horizontal_surface_ratio") or 0.0)
        vertical_ratio = float(metrics.get("vertical_surface_ratio") or 0.0)
        sloped_ratio = float(metrics.get("sloped_surface_ratio") or 0.0)
        cake_tier_without_hall_enclosure = bool(
            level_count >= 8
            and horizontal_ratio >= 0.78
            and vertical_ratio <= 0.04
        )
        sloped_cascade_without_hall_enclosure = bool(
            level_count >= 4
            and horizontal_ratio >= 0.55
            and sloped_ratio >= 0.28
            and vertical_ratio <= 0.04
        )
        cascade_without_hall_enclosure = bool(
            cake_tier_without_hall_enclosure
            or sloped_cascade_without_hall_enclosure
        )
        evidence["required_relation"] = "dominant clear-span hall with vertical enclosure and legible roof/section"
        evidence["cake_tier_without_hall_enclosure"] = cake_tier_without_hall_enclosure
        evidence["sloped_cascade_without_hall_enclosure"] = sloped_cascade_without_hall_enclosure
        evidence["cascade_without_hall_enclosure"] = cascade_without_hall_enclosure
        measured_profiled_hall = bool(metrics.get("measured_profiled_hall"))
        evidence["measured_profiled_hall"] = measured_profiled_hall
        dominant_enclosure_erased = bool(
            float(metrics.get("upper_area_ratio") or 1.0) < 0.10
            and vertical_ratio < 0.03
        )
        evidence["dominant_enclosure_erased"] = dominant_enclosure_erased
        dimensional_context = (
            source.metadata.get("program_dimensional_context")
            if hasattr(source, "metadata") and isinstance(source.metadata, dict)
            else {}
        ) or {}
        short_span, long_span = _oriented_plan_dimensions(getattr(source, "footprint", None))
        solid_height = float(metrics.get("solid_height_m") or 0.0)
        minimum_span = float(dimensional_context.get("minimum_clear_span_m") or 0.0)
        maximum_height_ratio = float(
            dimensional_context.get("maximum_height_to_clear_span_ratio") or 0.0
        )
        height_to_span = solid_height / max(short_span, 1e-9) if short_span > 0 and solid_height > 0 else 0.0
        evidence["dimensional_context"] = deepcopy(dimensional_context)
        evidence["measured_clear_span_m"] = round(short_span, 3)
        evidence["measured_long_axis_m"] = round(long_span, 3)
        evidence["measured_solid_height_m"] = round(solid_height, 3)
        evidence["height_to_clear_span_ratio"] = round(height_to_span, 3)
        if minimum_span and short_span + 1e-6 < minimum_span:
            failures.append("gym_clear_span_below_program_minimum")
        if maximum_height_ratio and height_to_span > maximum_height_ratio + 1e-6:
            failures.append("gym_height_to_clear_span_ratio_exceeded")
        if bool(metrics.get("pyramidal_like")) or dominant_enclosure_erased or (
            not measured_profiled_hall and cascade_without_hall_enclosure
        ):
            failures.append("gym_dominant_hall_erased_by_cascade_or_pyramid")
    return {
        **evidence,
        "hard_pass": not failures,
        "failures": failures,
    }


_BODY_RULE_FAMILIES = {
    "bend": "deformation",
    "bent_bar": "deformation",
    "twist": "deformation",
    "inflate": "deformation",
    "pinch": "deformation",
    "taper": "deformation",
    "shear": "deformation",
    "setback": "step",
    "stepped_mass": "step",
    "terrace": "step",
    "courtyard": "void",
    "carve_void": "void",
    "notch": "void",
    "book_carve": "void",
    "book_fracture": "cut",
    "book_grade": "step",
    "book_notch": "void",
    "book_extract": "void",
    "embed_void": "void",
    "puncture": "void",
    "cut_corner": "void",
    "slice": "cut",
    "clip": "cut",
    "radial_array": "array",
    "linear_array": "array",
    "mirror_array": "array",
    "cross_mass": "array",
    "book_branch": "array",
    "related_array": "array",
    "split_wing": "array",
    "book_split": "array",
    "book_lift": "array",
    "book_lodge": "array",
    "book_rotate": "array",
    "cantilever": "support",
    "lift": "support",
    "scale": "transform",
    "boundary_expand": "transform",
    "translate": "transform",
    "shift_related": "transform",
    "join_related": "composition",
    "rotate": "transform",
    "union": "composition",
    "intersection": "composition",
    "difference": "composition",
}


def _architectural_articulation_metrics(source: Any) -> dict[str, Any]:
    """Return a cross-layer body-rule budget from the actual recursive AST.

    Program synthesis and BOOK projection used to validate independently. A
    stepped/cantilever body could therefore receive stack+bend and still pass
    because the final Boolean was one manifold component. The resulting object
    is technically clean but architecturally reads as accumulated effects.

    One architectural effect is one program rule. Constructive joins and their
    exclusive affine operand placement chains use the shared assembly budget.
    A BOOK call may expand to helper
    nodes (for example rotate+intersection), so it is counted once through the
    causal ``book_call_index`` written by the adapter. Administrative p.3
    clip/recompose nodes and the protected roof/section invariant are excluded.
    """
    payload = source.metadata.get("geometry_program") if hasattr(source, "metadata") else None
    nodes = payload.get("nodes") if isinstance(payload, dict) else ()
    authored_sources = {
        "procedural_geometry_synthesis_agent", "openai_llm_geometry_author",
        "critic_geometry_edit", "post_book_program_projection",
    }
    assembly_roots, assembly_implementation = set(), set()
    if isinstance(payload, dict):
        try:
            program = GeometryProgram.from_dict(payload)
            assembly_roots, assembly_implementation = assembly_budget_nodes(
                program, eligible_node_ids={
                    node.id for node in program.nodes
                    if node.provenance.get("source") in authored_sources
                },
            )
        except (KeyError, TypeError, ValueError):
            # Malformed graphs earn no exemption; existing validity gates own
            # their refusal. Do not infer an assembly from labels alone.
            pass
    program_rules: list[dict[str, Any]] = []
    threshold_rules: list[dict[str, Any]] = []
    program_space_rules: list[dict[str, Any]] = []
    book_groups: dict[int | str, list[dict[str, Any]]] = {}
    for order, raw in enumerate(nodes or ()):
        if not isinstance(raw, dict):
            continue
        operator = str(raw.get("operator") or "")
        if operator == "profiled_hall":
            continue
        provenance = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}
        source_kind = str(provenance.get("source") or "")
        if source_kind in authored_sources:
            node_id = str(raw.get("id") or "")
            if node_id in assembly_implementation:
                continue
            family = ("composition" if node_id in assembly_roots
                      else _BODY_RULE_FAMILIES.get(operator))
            if family:
                parameters = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
                semantic_role = str(raw.get("semantic_role") or "")
                public_threshold = bool(
                    operator in {"courtyard", "carve_void"}
                    and str(parameters.get("open_side") or "closed") != "closed"
                ) or bool(operator == "notch" and parameters.get("side")) \
                    or bool(
                        operator in {"lift", "split_wing", "book_split"}
                        and str(parameters.get("access_side") or "closed") != "closed"
                    )
                program_public_space = semantic_role == "program_public_space"
                target = (
                    program_space_rules
                    if program_public_space
                    else threshold_rules
                    if public_threshold
                    else program_rules
                )
                target.append({
                    "layer": (
                        "program_public_space"
                        if program_public_space
                        else "public_threshold"
                        if public_threshold
                        else "program"
                    ),
                    "operator": operator,
                    "family": family,
                    "node_id": str(raw.get("id") or ""),
                    "order": order,
                })
            continue
        if source_kind != "book_recursive_projection":
            continue
        verb = str(provenance.get("book_verb") or "")
        call_index = provenance.get("book_call_index", -1)
        if verb in {"select_book_scope", "recompose_book_scope"} or int(call_index or -1) < 0:
            continue
        book_groups.setdefault(call_index, []).append({
            "operator": operator,
            "verb": verb,
            "node_id": str(raw.get("id") or ""),
            "order": order,
        })

    book_rules: list[dict[str, Any]] = []
    for call_index, group in sorted(book_groups.items(), key=lambda item: int(item[0])):
        terminal = max(group, key=lambda item: item["order"])
        family = _BODY_RULE_FAMILIES.get(terminal["operator"])
        if not family:
            continue
        book_rules.append({
            "layer": "book",
            "operator": terminal["operator"],
            "verb": terminal["verb"],
            "family": family,
            "call_index": int(call_index),
            "node_id": terminal["node_id"],
            "order": terminal["order"],
        })

    rules = sorted(
        (*program_rules, *threshold_rules, *program_space_rules, *book_rules),
        key=lambda item: item["order"],
    )
    family_counts = Counter(rule["family"] for rule in rules)
    program_structural_families = {
        rule["family"] for rule in program_rules
        if rule["family"] in {"void", "step", "array", "support"}
    }
    book_structural_families = {
        rule["family"] for rule in book_rules
        if rule["family"] in {"void", "step", "array", "support"}
    }
    # Repetition inside one BOOK sentence is intentional language
    # (inscribe+inscribe, split+split). Only accidental cross-layer stacking
    # is a conflict. Public-threshold rules have their own one-rule budget.
    duplicated_structural_families = sorted(
        program_structural_families & book_structural_families
    )
    program_family_counts = Counter(rule["family"] for rule in program_rules)
    duplicated_program_families = sorted(
        family for family, count in program_family_counts.items() if count > 1
    )
    # Extended CSG programs need one dominant body operation plus one
    # supporting operation (for example bend+setback or void+wing).  The old
    # one-rule budget contradicted the synthesis grammar's bounded depth=2 and
    # erased every such lineage after VLM approval.  Keep the stack small and
    # reject repeated effect families instead of pretending all composition is
    # Lego fragmentation; manifold/coherence/volume gates remain unchanged.
    program_rule_budget = 2
    threshold_rule_budget = 1
    program_space_rule_budget = 1
    book_rule_budget = 3
    budget_failures = []
    if len(program_rules) > program_rule_budget:
        budget_failures.append("program_body_rule_budget_exceeded")
    if duplicated_program_families:
        budget_failures.append("program_body_rule_family_repeated")
    if len(threshold_rules) > threshold_rule_budget:
        budget_failures.append("public_threshold_rule_budget_exceeded")
    if len(program_space_rules) > program_space_rule_budget:
        budget_failures.append("program_public_space_rule_budget_exceeded")
    if len(book_rules) > book_rule_budget:
        budget_failures.append("book_sentence_rule_budget_exceeded")
    if duplicated_structural_families:
        budget_failures.append("cross_layer_structural_family_repeated")
    return {
        "body_rule_count": len(program_rules) + len(program_space_rules) + len(book_rules),
        "program_rule_count": len(program_rules),
        "public_threshold_rule_count": len(threshold_rules),
        "program_public_space_rule_count": len(program_space_rules),
        "book_rule_count": len(book_rules),
        "rules": [
            {key: value for key, value in rule.items() if key != "order"}
            for rule in rules
        ],
        "family_counts": dict(sorted(family_counts.items())),
        "duplicated_structural_families": duplicated_structural_families,
        "duplicated_program_families": duplicated_program_families,
        "budget_failures": budget_failures,
        "hard_pass": not budget_failures,
        "budget": {
            "program_body_rules": program_rule_budget,
            "public_threshold_rules": threshold_rule_budget,
            "program_public_space_rules": program_space_rule_budget,
            "book_sentence_rules": book_rule_budget,
        },
        "book_internal_repetition_is_authored_language": True,
        "program_composition_contract": "one_dominant_plus_one_supporting_distinct_family",
        "section_invariant_excluded": True,
        "scope_administration_excluded": True,
    }


def _design_concept_descriptor(candidate: Any) -> dict[str, Any]:
    """Describe the architectural causal chain encoded by the geometry AST.

    Low-level silhouette and operator counts cannot tell whether a courtyard
    actually opens to the verified access edge, or whether it is merely a
    centered hole.  This descriptor uses a preserved authored AST payload
    when available, and falls back to final program data otherwise.
    """
    source = candidate.source if hasattr(candidate, "source") else candidate
    payload = _candidate_geometry_program_payload(candidate)
    nodes = payload.get("nodes") if isinstance(payload, dict) else ()
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    context = source.metadata.get("program_context") or {}
    target_side = str(context.get("site_access_side_in_program_frame") or "closed")
    graph = (
        source.metadata.get("authored_geometry_graph_snapshot")
        or source.metadata.get("geometry_graph_snapshot")
        or {}
    )
    design_graph = graph.get("design_concept_graph") if isinstance(graph, dict) else {}
    concept_nodes = design_graph.get("concept_nodes") if isinstance(design_graph, dict) else ()
    threshold_concept = next((
        item for item in concept_nodes or ()
        if isinstance(item, dict) and item.get("concept_id") == "concept:public_threshold"
    ), {})
    graph_threshold_controller_ids = {
        str(node_id) for node_id in threshold_concept.get("controller_node_ids") or ()
    }
    open_voids: list[dict[str, str]] = []
    closed_void_ids: list[str] = []
    frontage_notches: list[dict[str, str]] = []
    frontage_relations: list[dict[str, str]] = []
    threshold_controller_ids: list[str] = []
    for raw in nodes or ():
        if not isinstance(raw, dict):
            continue
        operator = str(raw.get("operator") or "")
        node_id = str(raw.get("id") or "")
        parameters = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
        materialized_controller = bool(
            node_id in graph_threshold_controller_ids
            or is_materialized_program_controller(raw)
        )
        if materialized_controller:
            threshold_controller_ids.append(node_id)
        if materialized_controller and operator == "notch" and parameters.get("side"):
            frontage_notches.append({
                "node_id": node_id,
                "side": str(parameters.get("side") or "").lower(),
            })
        if materialized_controller and operator in {"lift", "split_wing"} and parameters.get("access_side"):
            frontage_relations.append({
                "node_id": node_id,
                "operator": operator,
                "access_side": str(parameters.get("access_side") or "closed").lower(),
            })
        if not materialized_controller or operator not in {"courtyard", "carve_void"}:
            continue
        open_side = str(parameters.get("open_side") or "closed").lower()
        if open_side == "closed":
            closed_void_ids.append(node_id)
        else:
            open_voids.append({"node_id": node_id, "open_side": open_side})

    aligned_open_ids = [
        item["node_id"] for item in open_voids
        if target_side != "closed" and item["open_side"] == target_side
    ]
    aligned_notch_ids = [
        item["node_id"] for item in frontage_notches
        if target_side != "closed" and item["side"] == target_side
    ]
    aligned_relation_ids = [
        item["node_id"] for item in frontage_relations
        if target_side != "closed" and item["access_side"] == target_side
    ]
    frontage_aligned_ids = [*aligned_open_ids, *aligned_notch_ids, *aligned_relation_ids]
    operators = {
        str(raw.get("operator") or "")
        for raw in nodes or ()
        if isinstance(raw, dict)
    }
    aligned_lift_ids = [
        item["node_id"] for item in frontage_relations
        if item["operator"] == "lift" and item["node_id"] in aligned_relation_ids
    ]
    aligned_split_ids = [
        item["node_id"] for item in frontage_relations
        if item["operator"] == "split_wing" and item["node_id"] in aligned_relation_ids
    ]
    # A universal court or split chassis remains a real spatial relation even
    # when the post-BOOK access controller is a separate notch/lift. Mutating
    # that upstream node after later BOOK operations can invalidate nested
    # contact. Classify the composed relation instead: chassis + verified
    # frontage threshold. BOOK split/branch nodes use distinct operator names
    # and therefore never impersonate this program concept.
    has_court_chassis = bool(operators & {"courtyard", "carve_void"})
    has_split_chassis = "split_wing" in operators
    if aligned_open_ids:
        ground_strategy = "frontage_open_court"
    elif has_court_chassis and frontage_aligned_ids:
        ground_strategy = "frontage_court_threshold"
    elif has_split_chassis and frontage_aligned_ids:
        ground_strategy = "frontage_split_threshold"
    elif aligned_notch_ids:
        ground_strategy = "frontage_entry_notch"
    elif aligned_lift_ids:
        ground_strategy = "frontage_lifted_threshold"
    elif aligned_split_ids:
        ground_strategy = "frontage_split_threshold"
    elif open_voids:
        ground_strategy = "misaligned_open_court"
    elif operators & {"lift", "cantilever"}:
        ground_strategy = "lifted_threshold"
    elif operators & {"split_wing"}:
        ground_strategy = "split_threshold"
    elif "notch" in operators:
        ground_strategy = "carved_notch"
    elif closed_void_ids:
        ground_strategy = "internal_court"
    else:
        ground_strategy = "direct_edge"

    articulation = _architectural_articulation_metrics(source)
    program_rule = next((
        rule for rule in articulation["rules"]
        if rule.get("layer") == "program"
    ), None)
    body_strategy = str((program_rule or {}).get("operator") or "prismatic")
    base_seed = (metadata or {}).get("base_seed") if isinstance(metadata, dict) else "unknown"
    if isinstance(base_seed, dict):
        base_seed = base_seed.get("id") or base_seed.get("seed_id") or "unknown"
    concept_nodes = design_graph.get("concept_nodes") if isinstance(design_graph, dict) else ()
    snapshot_missing_concepts = sorted(
        str(item.get("concept_id") or "")
        for item in (concept_nodes or ())
        if isinstance(item, dict) and item.get("missing_controller")
    )
    section_controller_operators = {
        "barrel_roof", "folded_roof", "loft", "profiled_prism",
        "ridge_roof", "sawtooth_roof", "shed_roof", "stepped_section",
        "sweep", "taper", "tapered_tower", "twist",
    }
    section_controller_ids = [
        str(raw.get("id") or "")
        for raw in nodes or ()
        if isinstance(raw, dict)
        and str(raw.get("operator") or "") in section_controller_operators
        and raw.get("id")
    ]
    roof = _roof_archetype(candidate) if hasattr(candidate, "source") else "unmeasured"
    program_controller_ids = [
        str(rule.get("node_id") or "")
        for rule in articulation["rules"]
        if rule.get("layer") == "program" and rule.get("node_id")
    ]
    final_controller_ids_by_concept = {
        "concept:dominant_program_space": program_controller_ids,
        "concept:public_threshold": threshold_controller_ids,
        "concept:structure_daylight_section": section_controller_ids,
    }
    resolved_snapshot_concepts = sorted(
        concept_id for concept_id in snapshot_missing_concepts
        if final_controller_ids_by_concept.get(concept_id)
    )
    missing_concepts = sorted(
        concept_id for concept_id in snapshot_missing_concepts
        if not final_controller_ids_by_concept.get(concept_id)
    )
    concept_key = "|".join((str(base_seed), ground_strategy, body_strategy, roof))
    return {
        "schema_version": "arr.maas.final_design_concept_descriptor.v1",
        "base_seed": str(base_seed or "unknown"),
        "target_access_side_in_program_frame": target_side,
        "ground_strategy": ground_strategy,
        "body_strategy": body_strategy,
        "roof_section_strategy": roof,
        "concept_key": concept_key,
        "threshold_controller_node_ids": threshold_controller_ids,
        "program_controller_node_ids": program_controller_ids,
        "section_controller_node_ids": section_controller_ids,
        "open_voids": open_voids,
        "frontage_notches": frontage_notches,
        "frontage_relations": frontage_relations,
        "closed_void_node_ids": closed_void_ids,
        "frontage_aligned_controller_node_ids": frontage_aligned_ids,
        "frontage_aligned": bool(frontage_aligned_ids),
        "missing_required_concepts": missing_concepts,
        "snapshot_missing_required_concepts": snapshot_missing_concepts,
        "resolved_snapshot_concepts_from_final_ast": resolved_snapshot_concepts,
        "derived_from_final_recursive_ast": True,
    }


def _program_section_phenotype(operators: set[str]) -> str:
    """Map an executable roof/section graph to its visible broad phenotype."""
    if "barrel_roof" in operators:
        return "curved"
    if operators & {"ridge_roof", "shed_roof", "folded_roof"}:
        return "oblique"
    if operators & {"sawtooth_roof", "stepped_section"}:
        return "stepped"
    if "flat_roof" in operators:
        return "prismatic"
    return ""


def _oriented_aspect(poly: Polygon) -> float:
    rectangle = poly.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    lengths = sorted(
        (((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2) ** 0.5)
        for left, right in zip(coordinates, coordinates[1:])
        if left != right
    )
    return float(lengths[-1] / max(lengths[0], 1e-9)) if lengths else 1.0


def _oriented_plan_dimensions(poly: Polygon) -> tuple[float, float]:
    if poly is None or poly.is_empty:
        return (0.0, 0.0)
    rectangle = poly.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    lengths = sorted(
        (((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2) ** 0.5)
        for left, right in zip(coordinates, coordinates[1:])
        if left != right
    )
    if len(lengths) < 2:
        return (0.0, 0.0)
    return (float(lengths[0]), float(lengths[-1]))


def _program_dimensional_context(
    generation_site: Polygon,
    building_type: str,
    requested_height_m: float,
    requested_floors: int,
) -> dict[str, Any]:
    """Select a feasible program subtype before authoring geometry.

    The previous gym benchmark forced an 18 m hall onto every parcel. On the
    current 103 m2 legal host this produced 3--6 m short spans with height/span
    ratios above 3, so pyramids were inevitable. Dimensional requirements are
    program data and normalized site measurements, never parcel templates.
    """
    profile = resolve_program_profile(building_type)
    requirements = profile.get("dimensional_requirements")
    short_axis, long_axis = _oriented_plan_dimensions(generation_site)
    span_capacity = short_axis * 0.92
    base = {
        "schema_version": "arr.maas.program_dimensional_context.v1",
        "program_id": str(profile.get("id") or "generic"),
        "requested_height_m": round(float(requested_height_m), 3),
        "requested_floors": int(requested_floors),
        "generation_host_area_m2": round(float(generation_site.area), 3),
        "generation_host_short_axis_m": round(short_axis, 3),
        "generation_host_long_axis_m": round(long_axis, 3),
        "estimated_clear_span_capacity_m": round(span_capacity, 3),
        "parcel_coordinates_used": False,
    }
    if not isinstance(requirements, dict) or not requirements.get("subtypes"):
        return {
            **base,
            "status": "not_required",
            "selected_subtype": "generic",
            "effective_height_m": round(float(requested_height_m), 3),
            "effective_floors": int(requested_floors),
        }
    selected = next((
        dict(item)
        for item in requirements.get("subtypes") or ()
        if isinstance(item, dict)
        and span_capacity >= float(item.get("minimum_clear_span_m") or 0.0)
        and float(generation_site.area) >= float(item.get("minimum_host_area_m2") or 0.0)
    ), None)
    if selected is None:
        return {
            **base,
            "status": "infeasible",
            "selected_subtype": "none",
            "effective_height_m": 0.0,
            "effective_floors": 0,
            "failure_reasons": ["legal_generation_site_cannot_fit_minimum_program_span"],
            "available_subtypes": [str(item.get("id") or "") for item in requirements.get("subtypes") or ()],
        }
    minimum_height = float(selected.get("minimum_height_m") or 0.0)
    maximum_height = float(selected.get("maximum_height_m") or requested_height_m)
    maximum_ratio = float(selected.get("maximum_height_to_clear_span_ratio") or 1.0)
    target_ratio = float(selected.get("target_height_to_clear_span_ratio") or maximum_ratio)
    ratio_height = span_capacity * min(target_ratio, maximum_ratio)
    effective_height = min(float(requested_height_m), maximum_height, ratio_height)
    if effective_height < minimum_height:
        return {
            **base,
            "status": "infeasible",
            "selected_subtype": str(selected.get("id") or "none"),
            "effective_height_m": round(effective_height, 3),
            "effective_floors": 0,
            "failure_reasons": ["clear_span_cannot_support_minimum_program_height"],
        }
    return {
        **base,
        "status": "adapted" if effective_height < float(requested_height_m) else "feasible",
        "selected_subtype": str(selected.get("id") or "generic"),
        "minimum_clear_span_m": float(selected.get("minimum_clear_span_m") or 0.0),
        "maximum_height_to_clear_span_ratio": maximum_ratio,
        "target_height_to_clear_span_ratio": target_ratio,
        "effective_height_m": round(effective_height, 3),
        "effective_floors": min(int(requested_floors), int(selected.get("maximum_floors") or requested_floors)),
    }


def _fingerprint(candidate: _Candidate) -> tuple[Any, ...]:
    volume_key = tuple(sorted((
        tuple(round(value, 3) for value in volume.footprint.bounds),
        round(float(volume.footprint.area), 3),
        round(float(volume.bottom_fraction), 3),
        round(float(volume.top_fraction), 3),
    ) for volume in candidate.source.volumes))
    section = candidate.source.metadata.get("program_section_graph_evidence") or {}
    section_key = tuple(
        (
            str(node.get("operator") or ""),
            tuple(tuple(round(float(value), 4) for value in item) for item in (node.get("section_controls") or ())),
        )
        for node in (section.get("materialized_nodes") or ())
        if isinstance(node, dict)
    ) if isinstance(section, dict) else ()
    geometry_evidence = candidate.source.metadata.get("geometry_program_bridge_evidence") or {}
    geometry_key = str(geometry_evidence.get("geometry_hash") or "") if isinstance(geometry_evidence, dict) else ""
    return volume_key, section_key, geometry_key


def _inside_site(source: Any, site: Polygon) -> bool:
    try:
        return all(
            volume.footprint.is_valid
            and volume.footprint.difference(site).area <= 1e-6
            for volume in source.volumes
        )
    except (GEOSException, ValueError):
        return False


def _clean_mass_gate(source: Any) -> tuple[bool, dict[str, Any]]:
    """Enforce one connected, bounded-complexity architectural solid."""
    signature = source.signature()
    continuous_surface_evidence = (
        signature.get("continuous_surface_evidence") or {}
    )
    continuous_surface_evidence = (
        continuous_surface_evidence
        if isinstance(continuous_surface_evidence, dict)
        else {}
    )
    floorwise_stack = source.metadata.get("floorwise_legal_matrix_stack")
    floorwise_stack = (
        floorwise_stack
        if isinstance(floorwise_stack, dict)
        and floorwise_stack.get("status") == "materialized"
        else {}
    )
    floor_band_count = max(0, int(floorwise_stack.get("floor_count") or 0))
    if not floor_band_count:
        # The stack record is not always attached where this gate runs, and
        # falling back to the flat complexity limit judges a floor-band
        # serialization by a rule the comment below says does not apply to it.
        # The bands are readable from the geometry itself: one band is one
        # distinct (bottom, top) pair, which is exactly what the stack would
        # have reported. A mass that is not banded measures one band and keeps
        # the old limit unchanged.
        #
        # Measured on PNU 4115011300106840001 once ground-take bands made
        # stacks taller: masses with mesh_component_count 1 - one connected
        # building - were rejected at 9 volumes against a limit of 5 because
        # floor_band_count read 0, and program_passed halved.
        try:
            floor_band_count = len({
                (round(float(volume.bottom_fraction), 6),
                 round(float(volume.top_fraction), 6))
                for volume in source.volumes
            })
        except (AttributeError, TypeError, ValueError):
            # A volume that does not state its height band cannot be counted as
            # one; keep the flat limit rather than assume a band.
            floor_band_count = 0
    raw_surfaces = int(signature.get("surface_count") or 0)
    effective_surfaces = int(signature.get("effective_surface_count") or raw_surfaces)
    profiled = bool(continuous_surface_evidence.get("hard_pass"))
    recursive_mesh = bool(source.metadata.get("geometry_program_bridge_evidence"))
    raw_surface_limit = 2048 if recursive_mesh else (160 if profiled else 48)
    failures: list[str] = []
    # A floorwise projection serializes one authored connected building as
    # legal height bands. Its volume count is therefore driven by the
    # law-derived floor count, not by visible object/component complexity.
    volume_limit = max(5, floor_band_count * 4) if floor_band_count else 5
    if len(source.volumes) > volume_limit:
        failures.append("visible_volume_count")
    if raw_surfaces > raw_surface_limit:
        failures.append("raw_surface_count")
    if effective_surfaces > 28:
        failures.append("effective_surface_count")
    compilation_metrics = (
        source.metadata.get("geometry_program_compilation") or {}
    ).get("metrics") or {}
    component_count = int(compilation_metrics.get("component_count") or 1)
    visible_component_count = (
        component_count
        if floor_band_count
        else len(source.volumes)
    )
    if recursive_mesh and component_count > 1:
        # A union-shaped AST may still compile to disconnected shells. Large
        # detached pieces are no more architectural than small Lego specks;
        # split wings and arrays must be joined by an explicit bridge/spine.
        failures.append("disconnected_mesh_component_count")
    polygon_footprints = tuple(
        footprint
        for footprint in (
            getattr(volume, "footprint", None)
            for volume in source.volumes
        )
        if footprint is not None
    )
    polygon_areas = tuple(
        float(getattr(footprint, "area", 0.0) or 0.0)
        for footprint in polygon_footprints
    )
    measurements = {
        "components": {
            "mesh_component_count": component_count,
            "visible_component_count": visible_component_count,
            "minimum_component_volume_ratio": float(
                compilation_metrics.get("minimum_component_volume_ratio")
                or 0.0
            ),
        },
        "manifold": {
            "continuous_surface_hard_pass": profiled,
            "boundary_edge_count": int(
                continuous_surface_evidence.get("boundary_edge_count") or 0
            ),
            "non_manifold_edge_count": int(
                continuous_surface_evidence.get("non_manifold_edge_count")
                or 0
            ),
        },
        "volumes": {
            "visible_volume_count": len(source.volumes),
            "volume_limit": volume_limit,
            "floor_band_count": floor_band_count,
        },
        "topology": {
            "raw_surface_count": raw_surfaces,
            "raw_surface_limit": raw_surface_limit,
            "effective_surface_count": effective_surfaces,
            "effective_surface_limit": 28,
            "recursive_mesh": recursive_mesh,
        },
        "polygon_quality": {
            "evaluated_polygon_count": len(polygon_footprints),
            "valid_polygon_count": sum(
                bool(getattr(footprint, "is_valid", False))
                for footprint in polygon_footprints
            ),
            "empty_polygon_count": sum(
                bool(getattr(footprint, "is_empty", True))
                for footprint in polygon_footprints
            ),
            "minimum_polygon_area_m2": (
                min(polygon_areas) if polygon_areas else 0.0
            ),
        },
    }
    return not failures, {
        "schema_version": "arr.maas.clean_mass_gate.v2",
        "hard_pass": not failures,
        "failure_reasons": failures,
        "subreasons": list(failures),
        "measurements": measurements,
        "visible_volume_count": len(source.volumes),
        "visible_component_count": visible_component_count,
        "floor_band_count": floor_band_count,
        "volume_limit": volume_limit,
        "raw_surface_count": raw_surfaces,
        "raw_surface_limit": raw_surface_limit,
        "effective_surface_count": effective_surfaces,
        "effective_surface_limit": 28,
        "recursive_mesh": recursive_mesh,
        "mesh_component_count": component_count,
        "minimum_component_volume_ratio": float(
            compilation_metrics.get("minimum_component_volume_ratio") or 0.0
        ),
    }


def _site_access_side_in_principal_frame(
    site: Polygon,
    site_access_geometry: dict[str, Any] | None,
) -> str:
    """Map a live road frontage to the normalized solid principal frame.

    Recursive programs stay coordinate-free. The source bridge later aligns
    their local x/y axes to the legal host's principal frame, so this adapter
    expresses access only as one of four semantic sides in that same frame.
    """
    if not isinstance(site_access_geometry, dict):
        return "closed"
    try:
        access = shape(site_access_geometry)
        midpoint = access.centroid
        rectangle = site.minimum_rotated_rectangle
        coordinates = list(rectangle.exterior.coords)
        edges = [
            (hypot(x2 - x1, y2 - y1), degrees(atan2(y2 - y1, x2 - x1)))
            for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
        ]
        edges.sort(reverse=True)
        theta = (edges[0][1] if edges else 0.0) * pi / 180.0
        dx = float(midpoint.x - site.centroid.x)
        dy = float(midpoint.y - site.centroid.y)
        along_long = dx * cos(theta) + dy * sin(theta)
        along_short = -dx * sin(theta) + dy * cos(theta)
        if abs(along_long) >= abs(along_short):
            return "east" if along_long >= 0.0 else "west"
        return "north" if along_short >= 0.0 else "south"
    except Exception:
        return "closed"



__all__ = ["_Candidate","_distance","_silhouette_distance","_scope_key","_capacity_alternative_key","_requested_capacity_alternative_key","_capacity_target_gate","_capacity_minimum_gate","_seed_family","_section_family","_roof_archetype","_chassis_family","_geometry_program_family","_geometry_program_metadata","_plan_family","_vlm_reviewed_program_candidate","_llm_authored_candidate","_seed_is_llm_authored","_solid_morphology_metrics","_section_silhouette_flags","_program_form_gate","_architectural_articulation_metrics","_design_concept_descriptor","_program_section_phenotype","_oriented_aspect","_oriented_plan_dimensions","_program_dimensional_context","_fingerprint","_inside_site","_clean_mass_gate","_site_access_side_in_principal_frame","competition_gestalt_distance","competition_gestalt_key"]

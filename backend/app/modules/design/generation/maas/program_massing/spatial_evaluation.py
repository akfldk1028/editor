"""Geometry-based architectural checks beyond family labels and counters."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.semantic_projection import project_spatial_roles
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import repaired_volume_records, safe_unary_union
from backend.app.modules.design.generation.maas.program_massing.semantic_carriers import REQUIRED_RELATIONS, audit_program_semantic_carrier_geometry


ROLE_GROUPS = {
    "housing": (("living_",), ("entry_core", "circulation_bridge", "gateway"), ("north_living", "south_living", "west_living", "east_living", "podium", "gateway", "cantilever")),
    "cafe": (("room",), ("canopy", "roof"), ("service", "hearth", "court_room_west")),
    "neighborhood_living": (("primary_",), ("podium", "terrace", "platform", "ribbon"), ("tower", "folded", "shifted", "upper", "canopy", "lane_2")),
    "gymnasium": (("main", "hall"), ("service",), ("entry", "daylight", "monitor", "canopy")),
    "cultural": (("gallery", "hall"), ("court", "public"), ("entry", "bridge", "ramp")),
}

DOMINANT_RANGES = {"housing": (0.28, 0.58), "cafe": (0.38, 0.74), "neighborhood_living": (0.38, 0.82), "gymnasium": (0.62, 0.90), "cultural": (0.32, 0.75)}
COVERAGE_RANGES = {"housing": (0.28, 0.72), "cafe": (0.22, 0.62), "neighborhood_living": (0.38, 0.92), "gymnasium": (0.48, 0.84), "cultural": (0.24, 0.76)}
# How much of the ground a proposal takes is judged against the ground it is
# *allowed* to take. Measured against the setback host section instead, the
# ratio cannot reach these ranges wherever 건폐율 binds hard: on PNU
# 4115011300106840001 the host section is 1922.226 m2 while 건폐율 (20%) caps the
# footprint at 499.938 m2, so the highest ratio any lawful building can reach is
# 0.26 - below the low end of every range here. The gate then required roughly
# 87% of the legal footprint before a mass could score 0.55, which is why
# filling the coverage was not one proposal among several but a pass condition.
#
# Against the lawful capacity the upper end belongs to the law, not to this
# gate: taking all the 건폐율 allows is lawful, and the coverage hard gate
# already enforces the ceiling. Re-judging it here punished a legal building
# twice. Only the lower end stays a program judgement - how little ground a
# program can take and still read as that building.
LAWFUL_COVERAGE_CEILING = 1.0


def attach_program_spatial_evidence(feature: dict[str, Any], *, building_type: str, site_area_m2: float | None = None) -> dict[str, Any]:
    props = feature.setdefault("properties", {})
    profile_id = resolve_program_profile(building_type)["id"]
    repaired = repaired_volume_records(feature)
    records = [record for record, _ in repaired]
    # Multiple height bands with the same role are 2.5D proxies of one typed
    # component (for example a taper or loft), not independent buildings.
    # Aggregate them for plan hierarchy while retaining raw height levels.
    grouped: dict[str, list[Any]] = {}
    for record, geometry in repaired:
        grouped.setdefault(str(record.get("role") or ""), []).append(geometry)
    geometries = [safe_unary_union(items) for items in grouped.values()]
    geometries = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    areas = [float(item.area) for item in geometries]
    total_component_area = sum(areas)
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    bridge = (
        signature.get("geometry_program_bridge_evidence")
        if isinstance(signature.get("geometry_program_bridge_evidence"), dict)
        else {}
    )
    final_floorwise_authority = (
        str(
            signature.get("geometry_authority")
            or bridge.get("geometry_authority")
            or ""
        )
        in {
            "authored_projected_surface_payload",
            "authored_compiled_surface_payload",
            "final_floorwise_legal_geometry_program",
        }
        or str(
            (
                signature.get("program_semantic_carrier_evidence")
                if isinstance(
                    signature.get("program_semantic_carrier_evidence"),
                    dict,
                )
                else {}
            ).get("projection_method")
            or ""
        )
        == "final_floor_band_principal_frame_partition"
    )
    program_space_zones = (
        signature.get("program_space_zones")
        if (
            not final_floorwise_authority
            and isinstance(signature.get("program_space_zones"), list)
        )
        else []
    )
    carrier_evidence = (
        signature.get("program_semantic_carrier_evidence")
        if isinstance(
            signature.get("program_semantic_carrier_evidence"),
            dict,
        )
        else {}
    )
    actual_program_hash, actual_geometry_hash = _actual_final_hashes(
        signature,
        bridge,
    )
    carrier_audit = audit_program_semantic_carrier_geometry(
        carrier_evidence,
        actual_program_hash=actual_program_hash,
        actual_geometry_hash=actual_geometry_hash,
        actual_surface_payload_hash=str(
            signature.get("actual_surface_payload_hash") or ""
        ),
        surface_payload_complete=bool(
            int(signature.get("surface_count") or 0) > 0
            and bridge.get("surface_export_complete") is True
            and int(bridge.get("raw_mesh_triangle_count") or 0)
            == int(signature.get("surface_count") or 0)
            and int(bridge.get("exported_surface_count") or 0)
            == int(signature.get("surface_count") or 0)
        ),
        program_id=profile_id,
        current_context=(
            signature.get("final_semantic_projection_context")
            if isinstance(
                signature.get("final_semantic_projection_context"),
                dict,
            )
            else {}
        ),
        repaired_volume_records=repaired,
        final_program_payload=(
            signature.get("geometry_program")
            if isinstance(signature.get("geometry_program"), dict)
            else {}
        ),
    ) if final_floorwise_authority else {
        "schema_version": "arr.maas.final_semantic_projection_audit.v1",
        "hard_pass": False,
        "accepted_carrier_count": 0,
        "accepted_carriers": [],
        "failures": ["not_final_floorwise_authority"],
    }
    bridge_identity_failures = []
    if str(bridge.get("program_hash") or "") != actual_program_hash:
        bridge_identity_failures.append("final_program_hash_mismatch")
    if str(bridge.get("geometry_hash") or "") != actual_geometry_hash:
        bridge_identity_failures.append("final_geometry_hash_mismatch")
    if bridge_identity_failures:
        carrier_audit = dict(carrier_audit)
        carrier_audit["failures"] = sorted(set(
            list(carrier_audit.get("failures") or ())
            + bridge_identity_failures
        ))
        carrier_audit["hard_pass"] = False
        carrier_audit["accepted_carriers"] = []
    accepted_carriers = (
        carrier_audit.get("accepted_carriers")
        if carrier_audit.get("hard_pass")
        and isinstance(carrier_audit.get("accepted_carriers"), list)
        else []
    )
    zone_area = max(areas, default=0.0) * sum(
        max(0.0, min(0.45, float(zone.get("plan_area_ratio") or 0.0)))
        for zone in program_space_zones
        if isinstance(zone, dict)
    )
    union = safe_unary_union(geometries)
    union_area = float(union.area) if union is not None and not union.is_empty else 0.0
    denominator = float(site_area_m2 or props.get("benchmark_site_area_m2") or union_area or 1.0)
    coverage_numerator = union_area
    coverage_measurement_mode = "all_volume_plan_union"
    if final_floorwise_authority:
        minimum_bottom_height = min(
            (
                float(record.get("bottom_height") or 0.0)
                for record, _geometry in repaired
            ),
            default=0.0,
        )
        ground_union = safe_unary_union(
            geometry
            for record, geometry in repaired
            if float(record.get("bottom_height") or 0.0)
            == minimum_bottom_height
        )
        coverage_numerator = (
            float(ground_union.area)
            if ground_union is not None and not ground_union.is_empty
            else 0.0
        )
        candidate_floor_context = (
            props.get("candidate_floor_context")
            if isinstance(props.get("candidate_floor_context"), dict)
            else {}
        )
        legal_floor_areas = candidate_floor_context.get(
            "legal_floor_section_areas_m2"
        )
        ground_host_area = (
            float(legal_floor_areas[0])
            if (
                isinstance(legal_floor_areas, (list, tuple))
                and legal_floor_areas
                and type(legal_floor_areas[0]) in (int, float)
                and float(legal_floor_areas[0]) > 0.0
            )
            else 0.0
        )
        denominator = float(
            ground_host_area
            or props.get("benchmark_site_area_m2")
            or site_area_m2
            or union_area
            or 1.0
        )
        coverage_measurement_mode = "lowest_occupied_floor_band"
        projection_certificate = (
            bridge.get("authored_legal_projection_certificate")
            if isinstance(
                bridge.get("authored_legal_projection_certificate"),
                dict,
            )
            else {}
        )
        certified_floor_areas = projection_certificate.get(
            "achieved_floor_areas_m2"
        )
        if (
            projection_certificate.get("hard_pass") is True
            and isinstance(certified_floor_areas, (list, tuple))
            and certified_floor_areas
            and type(certified_floor_areas[0]) in (int, float)
            and float(certified_floor_areas[0]) > 0.0
        ):
            coverage_numerator = float(certified_floor_areas[0])
            coverage_measurement_mode = (
                "certified_projected_ground_floor_area"
            )
    lawful_ground_capacity = _lawful_ground_capacity(props)
    if lawful_ground_capacity > 1e-9:
        denominator = min(denominator, lawful_ground_capacity)
        coverage_measurement_mode = f"{coverage_measurement_mode}_over_lawful_ground"
        coverage_range_ceiling = LAWFUL_COVERAGE_CEILING
    else:
        coverage_range_ceiling = None
    coverage = coverage_numerator / max(denominator, 1e-9)
    all_height_projected_plan_union_ratio = (
        union_area / max(denominator, 1e-9)
    )
    geometric_dominant = max(areas, default=0.0) / max(total_component_area, 1e-9)
    dominant = max(areas, default=0.0) / max(total_component_area + zone_area, 1e-9)
    roles = [str(role).lower() for role in grouped]
    roles.extend(
        str(zone.get("role") or "").lower()
        for zone in program_space_zones
        if isinstance(zone, dict) and zone.get("role")
    )
    if accepted_carriers:
        carrier_areas: dict[str, float] = {}
        for carrier in accepted_carriers:
            relation = str(carrier.get("source_relation") or "")
            carrier_areas[relation] = (
                carrier_areas.get(relation, 0.0)
                + float(carrier.get("measured_area_m2") or 0.0)
            )
        total_carrier_area = sum(carrier_areas.values())
        dominant = max(
            carrier_areas.values(),
            default=0.0,
        ) / max(total_carrier_area, 1e-9)
        roles = [
            str(carrier.get("semantic_role") or "").lower()
            for carrier in accepted_carriers
        ]
    groups = ROLE_GROUPS.get(profile_id, ())
    role_projection = project_spatial_roles(feature)
    if profile_id == "neighborhood_living":
        role_hits = [
            bool(role_projection["primary_mass_present"]),
            bool(role_projection["active_ground_mass_present"]),
            bool(role_projection["public_spatial_gesture_present"]),
        ]
    else:
        required_relations = REQUIRED_RELATIONS.get(profile_id)
        if accepted_carriers and required_relations:
            present_relations = {
                str(carrier.get("source_relation") or "")
                for carrier in accepted_carriers
            }
            role_hits = [
                relation in present_relations
                for relation in required_relations
            ]
        else:
            role_hits = _distinct_role_group_hits(roles, groups)
    role_score = sum(role_hits) / len(role_hits) if role_hits else 0.6
    top_levels = {round(float(item.get("top_height") or 0.0), 2) for item in records}
    bottom_levels = {round(float(item.get("bottom_height") or 0.0), 2) for item in records}
    zone_top_levels = {
        round(float(zone.get("top_fraction") or 0.0), 2)
        for zone in program_space_zones if isinstance(zone, dict)
    }
    zone_bottom_levels = {
        round(float(zone.get("bottom_fraction") or 0.0), 2)
        for zone in program_space_zones if isinstance(zone, dict)
    }
    zone_top_levels.update(
        round(float(carrier.get("top_fraction") or 0.0), 2)
        for carrier in accepted_carriers
    )
    zone_bottom_levels.update(
        round(float(carrier.get("bottom_fraction") or 0.0), 2)
        for carrier in accepted_carriers
    )
    semantic_top_level_count = len(top_levels) + len(zone_top_levels)
    semantic_bottom_level_count = len(bottom_levels) + len(zone_bottom_levels)
    hierarchy_score = min(
        1.0,
        (semantic_top_level_count - 1) / 2
        + (0.2 if semantic_bottom_level_count > 1 else 0.0),
    )
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    continuous_surface = (
        signature.get("continuous_surface_evidence")
        if isinstance(signature.get("continuous_surface_evidence"), dict)
        else {}
    )
    profiled_patch_count = int(continuous_surface.get("profiled_volume_count") or 0)
    section_field = (
        continuous_surface.get("section_field")
        if isinstance(continuous_surface.get("section_field"), dict)
        else {}
    )
    agent_section_loft = bool(
        continuous_surface.get("representation") == "agent_section_loft_quad_mesh"
        and int(section_field.get("section_control_point_count") or 0) >= 4
        and float(section_field.get("section_height_range") or 0.0) >= 0.18
    )
    oblique_field = (
        continuous_surface.get("oblique_field")
        if isinstance(continuous_surface.get("oblique_field"), dict)
        else {}
    )
    agent_oblique_envelope = bool(
        continuous_surface.get("representation") == "agent_oblique_envelope_mesh"
        and 3 <= int(oblique_field.get("plan_control_point_count") or 0) <= 8
        and float(oblique_field.get("oblique_displacement") or 0.0) >= 0.08
    )
    single_solid_profiled_field = bool(
        len(geometries) == 1
        and continuous_surface.get("hard_pass")
        and (profiled_patch_count >= 2 or agent_section_loft or agent_oblique_envelope)
    )
    if single_solid_profiled_field:
        # The legal/FAR proxy is deliberately one watertight union, while the
        # executable roof field retains distinct trunk/arm patches.  Use those
        # geometry patches for hierarchy rather than penalizing the clean
        # solid as a monolithic box.
        if profiled_patch_count >= 2:
            dominant = 1.0 / profiled_patch_count
            hierarchy_score = max(hierarchy_score, min(1.0, (profiled_patch_count - 1) / 2.0))
        else:
            # A section loft is one watertight body by design. Its hierarchy
            # is carried by the authored section extrema, not fake helper
            # solids. Keep geometric_dominant_component_ratio=1.0 as honest
            # evidence and score the explicit internal field separately.
            hierarchy_score = max(hierarchy_score, 0.75)
    dominant_score = _range_score(dominant, DOMINANT_RANGES.get(profile_id, (0.3, 0.85)))
    if agent_section_loft or agent_oblique_envelope:
        dominant_score = max(dominant_score, 0.85)
    if bool(coherence.get("intentional_cluster_exception")):
        # A balanced 3-4 member field intentionally has no 38% dominant
        # object. Judge its hierarchy by the expected 1/n share rather than a
        # monolithic-building range; all other spatial hard gates still bind.
        dominant_score = max(dominant_score, _range_score(dominant, (0.20, 0.42)))
    coverage_range = COVERAGE_RANGES.get(profile_id, (0.2, 0.85))
    if coverage_range_ceiling is not None:
        coverage_range = (
            min(coverage_range[0], coverage_range_ceiling),
            coverage_range_ceiling,
        )
    coverage_score = _range_score(coverage, coverage_range)
    coherence_score = float(coherence.get("score") or 0.0)
    score = role_score * 0.34 + dominant_score * 0.20 + coverage_score * 0.18 + hierarchy_score * 0.14 + coherence_score * 0.14
    evidence = {
        "schema_version": "arr.maas.program_spatial_evidence.v1",
        "profile_id": profile_id,
        "roles": roles,
        "required_role_hits": role_hits,
        "spatial_role_projection": role_projection,
        "role_coverage_score": round(role_score, 3),
        "dominant_component_ratio": round(dominant, 3),
        "geometric_dominant_component_ratio": round(geometric_dominant, 3),
        "program_space_zone_count": len(program_space_zones),
        "program_space_zone_area_ratio": round(zone_area / max(max(areas, default=0.0), 1e-9), 3),
        "profiled_design_patch_count": profiled_patch_count,
        "single_solid_profiled_field": single_solid_profiled_field,
        "agent_section_loft": agent_section_loft,
        "agent_oblique_envelope": agent_oblique_envelope,
        "dominant_ratio_score": round(dominant_score, 3),
        "site_coverage_ratio": round(coverage, 3),
        "site_coverage_score": round(coverage_score, 3),
        "all_height_projected_plan_union_ratio": round(
            all_height_projected_plan_union_ratio,
            3,
        ),
        "coverage_numerator_m2": round(coverage_numerator, 3),
        "coverage_denominator_m2": round(denominator, 3),
        "coverage_measurement_mode": coverage_measurement_mode,
        "lawful_ground_capacity_m2": round(lawful_ground_capacity, 3),
        "coverage_range": [round(value, 3) for value in coverage_range],
        "height_level_count": semantic_top_level_count,
        "section_level_count": semantic_bottom_level_count,
        "hierarchy_score": round(hierarchy_score, 3),
        "coherence_score": round(coherence_score, 3),
        "architectural_score": round(max(0.0, min(1.0, score)), 3),
        "hard_pass": bool(all(role_hits) and dominant_score >= 0.55 and coverage_score >= 0.55 and hierarchy_score >= 0.5 and coherence.get("hard_pass", False)),
        "semantic_carrier_audit": carrier_audit,
        "verified_semantic_carrier_count": len(accepted_carriers),
    }
    props["program_spatial_evidence"] = evidence
    return evidence


def _lawful_ground_capacity(props: dict[str, Any]) -> float:
    """The 건폐율 capacity this candidate was certified against, or zero.

    Read from the run's own capacity contract, never derived here. Zero means
    the contract is absent - a legacy or synthetic feature - and the coverage
    judgement stays exactly as it was rather than inventing a ceiling.
    """

    for key in ("base_capacity_contract", "candidate_capacity_contract"):
        contract = props.get(key)
        if not isinstance(contract, dict):
            continue
        for holder in (contract.get("legal_floor_field"), contract):
            if not isinstance(holder, dict):
                continue
            raw = holder.get("bcr_footprint_capacity_m2")
            if type(raw) not in (int, float):
                continue
            capacity = float(raw)
            if capacity > 0.0:
                return capacity
    return 0.0


def _range_score(value: float, target: tuple[float, float]) -> float:
    low, high = target
    if low <= value <= high:
        center = (low + high) / 2
        half = max((high - low) / 2, 1e-9)
        return max(0.75, 1.0 - abs(value - center) / half * 0.25)
    distance = low - value if value < low else value - high
    return max(0.0, 0.75 - distance * 3.0)


def _distinct_role_group_hits(
    roles: list[str],
    groups: tuple[tuple[str, ...], ...],
) -> list[bool]:
    unused = set(range(len(roles)))
    hits: list[bool] = []
    for group in groups:
        match = next((
            index
            for index in sorted(unused)
            if any(token in roles[index] for token in group)
        ), None)
        hits.append(match is not None)
        if match is not None:
            unused.remove(match)
    return hits


def _actual_final_hashes(
    signature: dict[str, Any],
    bridge: dict[str, Any],
) -> tuple[str, str]:
    if str(signature.get("geometry_authority") or "") in {
        "authored_projected_surface_payload",
        "authored_compiled_surface_payload",
    }:
        # The stored program and certified authored triangles are the same
        # visual authority. Surface-payload and semantic audits independently
        # verify the bridge; legal proxy volumes are not recompiled here.
        return (
            str(bridge.get("program_hash") or ""),
            str(bridge.get("geometry_hash") or ""),
        )
    payload = signature.get("geometry_program")
    if isinstance(payload, dict) and payload.get("nodes"):
        try:
            from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, compile_geometry_program
            program = GeometryProgram.from_dict(payload)
            compilation = compile_geometry_program(program)
            return program.program_hash(), compilation.geometry_hash
        except (TypeError, ValueError):
            return "", ""
    return (
        str(bridge.get("program_hash") or ""),
        str(bridge.get("geometry_hash") or ""),
    )


__all__ = ["attach_program_spatial_evidence"]

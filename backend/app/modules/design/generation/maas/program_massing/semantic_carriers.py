"""Verified semantic partitions of the unchanged final legal floor bands."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from math import atan2, cos, degrees, hypot, radians, sin, sqrt
from typing import Any

from shapely.affinity import rotate
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.geometry_language.source_bridge import source_surface_payload_hash
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass
from backend.app.modules.design.generation.maas.program_massing.assembly import load_component_assemblies
from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.profiles import program_reference_contract


SCHEMA_VERSION = "arr.maas.final_semantic_projection.v1"

REQUIRED_RELATIONS = {
    "gymnasium": (
        "dominant_hall",
        "service_support",
        "public_entry_daylight",
    ),
    "cultural": (
        "public_gallery_hall",
        "court_public_space",
        "public_entry_path",
    ),
    "neighborhood_living": (
        "primary_program_mass",
        "active_ground_program",
        "public_spatial_gesture",
    ),
}
BINDING_KEYS = (
    "program_id",
    "final_program_hash",
    "final_geometry_hash",
    "final_surface_payload_hash",
    "floor_capacity_plan_hash",
    "pnu",
    "site_context_hash",
    "capacity_alternative_id",
    "achieved_capacity_band",
    "capacity_measurement_hash",
)


def canonical_semantic_carrier_payload_hash(
    carriers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> str:
    return _canonical_hash(list(carriers))


def semantic_site_context_hash(
    *,
    pnu: str,
    building_type: str,
    site: Any,
) -> str:
    return _canonical_hash({
        "pnu": str(pnu or ""),
        "program_id": _normalized_program_id(building_type),
        "site_wkb_hex": site.normalize().wkb_hex,
    })


def semantic_capacity_measurement_hash(
    measurement: dict[str, Any],
    projection: dict[str, Any],
) -> str:
    return _canonical_hash({
        "measurement": measurement,
        "projection": projection,
    })


def semantic_audit_context_hash(context: dict[str, Any]) -> str:
    return _canonical_hash(context)


def bind_source_role_scaffold_to_program(
    program: Any,
    source: SourceMass,
    *,
    program_id: str,
    failure_sink: list[dict[str, Any]] | None = None,
) -> Any | None:
    """Bind the compiled source-role identity into a reachable AST node."""

    normalized = _normalized_program_id(program_id)
    scaffold, provenance, failures = _source_role_scaffold(
        source,
        program_id=normalized,
    )
    if failures or not scaffold:
        if failure_sink is not None:
            failure_sink.append({
                "reason": "source_role_scaffold_invalid",
                "program_id": normalized,
                "required_relations": list(REQUIRED_RELATIONS.get(normalized, ())),
                "available_relations": sorted({
                    str(record.get("source_relation") or "")
                    for record in scaffold
                    if isinstance(record, dict) and record.get("source_relation")
                }),
                "scaffold_failures": list(failures),
                "component_graph_provenance": provenance,
            })
        return None
    from backend.app.modules.design.generation.maas.geometry_language import GeometryNode
    from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import identity_matrix4, matrix4_to_lists

    origin = _source_role_origin(
        scaffold,
        provenance,
        program_id=normalized,
    )
    scaffold_by_relation = {
        str(record.get("source_relation") or ""): record
        for record in scaffold
        if isinstance(record, dict)
    }
    required_relations = tuple(REQUIRED_RELATIONS.get(normalized, ()))
    if (
        not required_relations
        or any(
            relation not in scaffold_by_relation
            for relation in required_relations
        )
    ):
        if failure_sink is not None:
            failure_sink.append({
                "reason": "required_source_relations_missing",
                "program_id": normalized,
                "required_relations": list(required_relations),
                "available_relations": sorted(
                    relation for relation in scaffold_by_relation if relation
                ),
                "missing_relations": [
                    relation
                    for relation in required_relations
                    if relation not in scaffold_by_relation
                ],
                "component_graph_provenance": provenance,
            })
        return None
    existing = set(program.node_map)
    relation_nodes = []
    reachable_root_id = program.root_id
    for relation in required_relations:
        record = scaffold_by_relation[relation]
        relation_payload = {
            "schema_version": "arr.maas.source_role_relation_binding.v1",
            "program_id": normalized,
            "source_relation": relation,
            "source_component_id": str(
                record.get("source_component_id") or ""
            ),
            "semantic_role": str(record.get("semantic_role") or ""),
        }
        if (
            not relation_payload["source_component_id"]
            or not relation_payload["semantic_role"]
        ):
            if failure_sink is not None:
                failure_sink.append({
                    "reason": "source_relation_identity_incomplete",
                    "program_id": normalized,
                    "required_relations": list(required_relations),
                    "source_relation": relation,
                    "source_component_id": relation_payload["source_component_id"],
                    "semantic_role": relation_payload["semantic_role"],
                })
            return None
        relation_payload["relation_hash"] = _canonical_hash(
            relation_payload
        )
        base_relation_id = (
            f"semantic_projection:{normalized}:source_role:{relation}"
        )
        relation_node_id = base_relation_id
        relation_suffix = 2
        while relation_node_id in existing:
            relation_node_id = f"{base_relation_id}:{relation_suffix}"
            relation_suffix += 1
        existing.add(relation_node_id)
        relation_node = GeometryNode(
            id=relation_node_id,
            kind="transform",
            operator="matrix4",
            inputs=(reachable_root_id,),
            parameters={
                "matrix4": matrix4_to_lists(identity_matrix4()),
                "source_role_relation_binding": relation_payload,
            },
            semantic_role="source_role_relation_binding",
            provenance={
                "source": "compiled_source_role_relation_binding",
                "program_id": normalized,
                "source_relation": relation,
                "source_component_id": relation_payload[
                    "source_component_id"
                ],
                "geometry_effect": "identity",
                "reachable_final_root_required": True,
            },
        )
        relation_nodes.append(relation_node)
        reachable_root_id = relation_node.id
    base_id = f"semantic_projection:{normalized}:source_role_origin"
    node_id = base_id
    suffix = 2
    while node_id in existing:
        node_id = f"{base_id}:{suffix}"
        suffix += 1
    node = GeometryNode(
        id=node_id,
        kind="transform",
        operator="matrix4",
        inputs=(reachable_root_id,),
        parameters={
            "matrix4": matrix4_to_lists(identity_matrix4()),
            "source_role_scaffold_origin": origin,
        },
        semantic_role="source_role_scaffold_origin",
        provenance={
            "source": "compiled_source_role_scaffold_binding",
            "program_id": normalized,
            "geometry_effect": "identity",
            "reachable_final_root_required": True,
        },
    )
    return replace(
        program,
        nodes=(*program.nodes, *relation_nodes, node),
        root_id=node.id,
    )


def rebind_semantic_projection_capacity(
    evidence: dict[str, Any],
    *,
    achieved_capacity_band: str,
    capacity_measurement_hash: str,
) -> dict[str, Any]:
    rebound = dict(evidence)
    rebound["achieved_capacity_band"] = str(achieved_capacity_band or "")
    rebound["capacity_measurement_hash"] = str(capacity_measurement_hash or "")
    payload = {
        key: rebound.get(key)
        for key in BINDING_KEYS
    }
    payload.update({
        "source_role_scaffold_hash": str(
            rebound.get("source_role_scaffold_hash") or ""
        ),
        "program_contract_hash": str(
            rebound.get("program_contract_hash") or ""
        ),
        "projection_method": str(rebound.get("projection_method") or ""),
        "carriers": rebound.get("carriers") or [],
    })
    rebound["semantic_projection_hash"] = _canonical_hash(payload)
    return rebound


def build_program_semantic_carrier_evidence(
    authored_source: SourceMass,
    final_source: SourceMass,
    *,
    program_id: str,
    final_program_hash: str,
    final_geometry_hash: str,
    floor_capacity_plan_hash: str,
    pnu: str,
    site_context_hash: str,
    capacity_alternative_id: str,
    achieved_capacity_band: str,
    capacity_measurement_hash: str,
) -> dict[str, Any]:
    program_id = _normalized_program_id(program_id)
    if program_id not in REQUIRED_RELATIONS:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "not_required",
            "hard_pass": True,
            "geometry_authority": False,
            "program_id": program_id,
            "projection_method": "not_required_for_unresolved_program",
            "carriers": [],
            "failures": [],
        }
    failures: list[str] = []
    bridge = _dict(final_source.metadata.get("geometry_program_bridge_evidence"))
    actual_surface_hash = source_surface_payload_hash(tuple(final_source.surfaces))
    bound_surface_hash = str(
        bridge.get("surface_payload_hash")
        or final_source.metadata.get("final_surface_payload_hash")
        or ""
    )
    bindings = {
        "program_id": program_id,
        "final_program_hash": str(final_program_hash or ""),
        "final_geometry_hash": str(final_geometry_hash or ""),
        "final_surface_payload_hash": actual_surface_hash,
        "floor_capacity_plan_hash": str(floor_capacity_plan_hash or ""),
        "pnu": str(pnu or ""),
        "site_context_hash": str(site_context_hash or ""),
        "capacity_alternative_id": str(capacity_alternative_id or ""),
        "achieved_capacity_band": str(achieved_capacity_band or ""),
        "capacity_measurement_hash": str(capacity_measurement_hash or ""),
    }
    required_binding_keys = tuple(bindings)
    if any(not bindings[key] for key in required_binding_keys):
        failures.append("missing_semantic_projection_binding")
    if str(bridge.get("program_hash") or "") != bindings["final_program_hash"]:
        failures.append("final_program_hash_mismatch")
    if str(bridge.get("geometry_hash") or "") != bindings["final_geometry_hash"]:
        failures.append("final_geometry_hash_mismatch")
    if bound_surface_hash != actual_surface_hash:
        failures.append("final_surface_payload_hash_mismatch")
    try:
        raw_surface_count = int(bridge.get("raw_mesh_triangle_count") or 0)
        exported_surface_count = int(bridge.get("exported_surface_count") or 0)
    except (TypeError, ValueError):
        raw_surface_count = exported_surface_count = 0
    if (
        not final_source.surfaces
        or bridge.get("surface_export_complete") is not True
        or raw_surface_count != len(final_source.surfaces)
        or exported_surface_count != len(final_source.surfaces)
    ):
        failures.append("final_surface_payload_incomplete")

    contract_hash = _canonical_hash(program_reference_contract(program_id))
    scaffold, scaffold_provenance, scaffold_failures = _source_role_scaffold(
        authored_source,
        program_id=program_id,
    )
    failures.extend(scaffold_failures)
    recomputed_source_role_origin = _source_role_origin(
        scaffold,
        scaffold_provenance,
        program_id=program_id,
    )
    source_role_origin = _resolve_reachable_source_role_origin(
        final_source.metadata.get("geometry_program"),
        scaffold=scaffold,
        provenance=scaffold_provenance,
        program_id=program_id,
    )
    if source_role_origin is None:
        failures.append(
            "source_role_scaffold_not_bound_to_reachable_final_ast"
        )
        source_role_origin = recomputed_source_role_origin
    else:
        bound_components = {
            str(component.get("source_relation") or ""): component
            for component in source_role_origin.get("source_components") or ()
            if isinstance(component, dict)
        }
        scaffold = [
            {
                **record,
                "source_component_id": str(
                    bound_components.get(
                        str(record.get("source_relation") or ""),
                        {},
                    ).get("source_component_id") or ""
                ),
            }
            for record in scaffold
        ]
    scaffold_hash = _canonical_hash({
        "program_contract_hash": contract_hash,
        "provenance": scaffold_provenance,
        "records": scaffold,
    })
    required = REQUIRED_RELATIONS.get(program_id, ())
    scaffold_relations = {
        str(record.get("source_relation") or "") for record in scaffold
    }
    for relation in required:
        if relation not in scaffold_relations:
            failures.append(f"missing_required_source_relation:{relation}")

    carriers, projection_failures = _project_scaffold_to_final_bands(
        scaffold,
        final_source,
    )
    failures.extend(projection_failures)
    contained, disjoint = _carrier_geometry_invariants(carriers, final_source)
    if not contained:
        failures.append("semantic_carrier_not_contained")
    if not disjoint:
        failures.append("semantic_carriers_overlap")
    if not carriers:
        failures.append("empty_semantic_carrier_payload")
    carrier_relations = {
        str(record.get("source_relation") or "") for record in carriers
        if float(record.get("measured_area_m2") or 0.0) > 0.0
    }
    for relation in required:
        if relation not in carrier_relations:
            failures.append(f"required_carrier_projection_empty:{relation}")

    envelope_payload = {
        **bindings,
        "source_role_scaffold_hash": scaffold_hash,
        "program_contract_hash": contract_hash,
        "projection_method": "final_floor_band_principal_frame_partition",
        "carriers": carriers,
    }
    semantic_projection_hash = _canonical_hash(envelope_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "verified" if not failures else "rejected",
        "hard_pass": not failures,
        "geometry_authority": False,
        "projection_method": "final_floor_band_principal_frame_partition",
        **bindings,
        "source_role_scaffold_hash": scaffold_hash,
        "program_contract_hash": contract_hash,
        "source_role_scaffold": scaffold,
        "source_role_scaffold_provenance": scaffold_provenance,
        "source_role_scaffold_origin": source_role_origin,
        "carrier_payload_hash": canonical_semantic_carrier_payload_hash(carriers),
        "semantic_projection_hash": semantic_projection_hash,
        "carriers": carriers,
        "all_carriers_contained": contained,
        "all_carriers_disjoint": disjoint,
        "failures": sorted(set(failures)),
    }


def audit_program_semantic_carrier_evidence(
    evidence: dict[str, Any],
    *,
    actual_program_hash: str,
    actual_geometry_hash: str,
    actual_surface_payload_hash: str,
    surface_payload_complete: bool,
    current_context: dict[str, Any],
    repaired_volume_records: list[tuple[dict[str, Any], Any]],
    final_program_payload: dict[str, Any] | None = None,
    audit_scope: str = "full_identity",
) -> dict[str, Any]:
    geometry_only = audit_scope == "spatial_geometry"
    failures: list[str] = []
    carriers = evidence.get("carriers") if isinstance(evidence.get("carriers"), list) else []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        failures.append("semantic_projection_schema_mismatch")
    if not surface_payload_complete:
        failures.append("final_surface_payload_incomplete")
    comparisons = {
        "final_program_hash": actual_program_hash,
        "final_geometry_hash": actual_geometry_hash,
        "final_surface_payload_hash": actual_surface_payload_hash,
        "floor_capacity_plan_hash": str(current_context.get("floor_capacity_plan_hash") or ""),
        "pnu": str(current_context.get("pnu") or ""),
        "site_context_hash": str(current_context.get("site_context_hash") or ""),
        "capacity_alternative_id": str(current_context.get("capacity_alternative_id") or ""),
    }
    if not geometry_only:
        comparisons.update({
            "achieved_capacity_band": str(current_context.get("achieved_capacity_band") or ""),
            "capacity_measurement_hash": str(current_context.get("capacity_measurement_hash") or ""),
        })
    resolved_program_id = _normalized_program_id(
        str(current_context.get("program_id") or "")
    )
    if (
        not resolved_program_id
        or str(evidence.get("program_id") or "") != resolved_program_id
    ):
        failures.append("program_id_mismatch")
    for key, actual in comparisons.items():
        if not actual or str(evidence.get(key) or "") != str(actual):
            failures.append(f"{key}_mismatch")
    if (
        str(evidence.get("carrier_payload_hash") or "")
        != canonical_semantic_carrier_payload_hash(carriers)
    ):
        failures.append("carrier_payload_hash_mismatch")
    envelope_payload = {
        key: evidence.get(key)
        for key in BINDING_KEYS
    }
    envelope_payload.update({
        "source_role_scaffold_hash": str(
            evidence.get("source_role_scaffold_hash") or ""
        ),
        "program_contract_hash": str(
            evidence.get("program_contract_hash") or ""
        ),
        "projection_method": str(evidence.get("projection_method") or ""),
        "carriers": carriers,
    })
    if (
        str(evidence.get("semantic_projection_hash") or "")
        != _canonical_hash(envelope_payload)
    ):
        failures.append("semantic_projection_hash_mismatch")
    expected_contract_hash = _canonical_hash(
        program_reference_contract(resolved_program_id)
    )
    if str(evidence.get("program_contract_hash") or "") != expected_contract_hash:
        failures.append("program_contract_hash_mismatch")
    scaffold = (
        evidence.get("source_role_scaffold")
        if isinstance(evidence.get("source_role_scaffold"), list)
        else []
    )
    scaffold_provenance = (
        evidence.get("source_role_scaffold_provenance")
        if isinstance(evidence.get("source_role_scaffold_provenance"), dict)
        else {}
    )
    source_role_origin = (
        evidence.get("source_role_scaffold_origin")
        if isinstance(
            evidence.get("source_role_scaffold_origin"),
            dict,
        )
        else {}
    )
    if not _final_program_has_reachable_source_role_origin(
        final_program_payload,
        expected_origin=source_role_origin,
    ):
        failures.append(
            "source_role_scaffold_not_bound_to_reachable_final_ast"
        )
    if str(evidence.get("source_role_scaffold_hash") or "") != _canonical_hash({
        "program_contract_hash": expected_contract_hash,
        "provenance": scaffold_provenance,
        "records": scaffold,
    }):
        failures.append("source_role_scaffold_hash_mismatch")
    required_relations = REQUIRED_RELATIONS.get(resolved_program_id, ())
    scaffold_by_relation: dict[str, dict[str, Any]] = {}
    source_ids: set[str] = set()
    for record in scaffold:
        relation = str(record.get("source_relation") or "")
        source_id = str(record.get("source_component_id") or "")
        if (
            relation not in required_relations
            or not source_id
            or source_id in source_ids
            or relation in scaffold_by_relation
        ):
            failures.append("invalid_or_duplicate_source_scaffold_relation")
            continue
        source_ids.add(source_id)
        scaffold_by_relation[relation] = record
    if any(relation not in scaffold_by_relation for relation in required_relations):
        failures.append("required_source_scaffold_relation_missing")
    if not carriers:
        failures.append("empty_semantic_carrier_payload")

    bands = _feature_bands(repaired_volume_records)
    accepted: list[dict[str, Any]] = []
    carrier_ids: set[str] = set()
    by_floor: dict[int, list[Any]] = defaultdict(list)
    for index, carrier in enumerate(carriers):
        if not isinstance(carrier, dict):
            failures.append(f"carrier_{index}_invalid")
            continue
        try:
            floor_index = int(carrier.get("floor_index"))
            geometry = shape(carrier.get("final_polygon_utm"))
            measured = float(carrier.get("measured_area_m2") or 0.0)
        except (TypeError, ValueError):
            failures.append(f"carrier_{index}_invalid")
            continue
        carrier_id = str(carrier.get("carrier_id") or "")
        relation = str(carrier.get("source_relation") or "")
        scaffold_record = scaffold_by_relation.get(relation)
        if (
            not carrier_id
            or carrier_id in carrier_ids
            or scaffold_record is None
            or str(carrier.get("semantic_role") or "")
            != str(scaffold_record.get("semantic_role") or "")
            or str(carrier.get("source_component_id") or "")
            != str(scaffold_record.get("source_component_id") or "")
        ):
            failures.append(f"carrier_{index}_scaffold_mismatch")
            continue
        carrier_ids.add(carrier_id)
        host = bands.get(floor_index)
        if (
            host is None
            or geometry.is_empty
            or measured <= 0.0
            or abs(float(geometry.area) - measured) > max(1e-6, measured * 1e-6)
            or not host.buffer(1e-8).covers(geometry)
            or str(carrier.get("final_volume_band_key") or "")
            != _band_key(floor_index, host, carrier)
        ):
            failures.append(f"carrier_{index}_outside_or_unmeasured")
            continue
        if any(geometry.intersection(other).area > 1e-8 for other in by_floor[floor_index]):
            failures.append(f"carrier_{index}_overlap")
            continue
        by_floor[floor_index].append(geometry)
        accepted.append(dict(carrier))
    if evidence.get("hard_pass") is not True:
        failures.extend(str(value) for value in evidence.get("failures") or ())
    accepted_relations = {
        str(carrier.get("source_relation") or "")
        for carrier in accepted
    }
    if any(relation not in accepted_relations for relation in required_relations):
        failures.append("required_carrier_relation_missing")
    return {
        "schema_version": (
            "arr.maas.final_semantic_geometry_audit.v1"
            if geometry_only
            else "arr.maas.final_semantic_projection_audit.v1"
        ),
        "audit_scope": audit_scope,
        "hard_pass": not failures,
        "semantic_projection_hash": str(
            evidence.get("semantic_projection_hash") or ""
        ),
        "accepted_carrier_count": len(accepted),
        "accepted_carriers": accepted if not failures else [],
        "failures": sorted(set(failures)),
    }


def audit_program_semantic_carrier_geometry(
    evidence: dict[str, Any],
    *,
    actual_program_hash: str,
    actual_geometry_hash: str,
    actual_surface_payload_hash: str,
    surface_payload_complete: bool,
    program_id: str,
    current_context: dict[str, Any],
    repaired_volume_records: list[tuple[dict[str, Any], Any]],
    final_program_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit final-solid program carriers without capacity identity."""

    return audit_program_semantic_carrier_evidence(
        evidence,
        actual_program_hash=actual_program_hash,
        actual_geometry_hash=actual_geometry_hash,
        actual_surface_payload_hash=actual_surface_payload_hash,
        surface_payload_complete=surface_payload_complete,
        current_context={
            **current_context,
            "program_id": program_id,
        },
        repaired_volume_records=repaired_volume_records,
        final_program_payload=final_program_payload,
        audit_scope="spatial_geometry",
    )


def audit_source_semantic_projection(
    source: SourceMass,
    *,
    building_type: str,
    expected_context: dict[str, Any],
) -> dict[str, Any]:
    program_id = _normalized_program_id(building_type)
    if program_id not in REQUIRED_RELATIONS:
        return {
            "schema_version": "arr.maas.final_semantic_projection_audit.v1",
            "status": "not_required",
            "hard_pass": True,
            "accepted_carriers": [],
            "failures": [],
        }
    if source.metadata.get("geometry_authority") not in {
        "authored_projected_surface_payload",
        "authored_compiled_surface_payload",
    }:
        return {
            "schema_version": "arr.maas.final_semantic_projection_audit.v1",
            "status": "rejected",
            "hard_pass": False,
            "accepted_carriers": [],
            "failures": [
                "authored_surface_geometry_authority_required"
            ],
        }
    signature = source.signature()
    bridge = _dict(signature.get("geometry_program_bridge_evidence"))
    program_hash = str(bridge.get("program_hash") or "")
    geometry_hash = str(bridge.get("geometry_hash") or "")
    payload = signature.get("geometry_program")
    if isinstance(payload, dict) and payload.get("nodes"):
        try:
            from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, compile_geometry_program
            program = GeometryProgram.from_dict(payload)
            compile_geometry_program(program)
            program_hash = program.program_hash()
        except (TypeError, ValueError):
            program_hash = geometry_hash = ""
    surface_count = len(source.surfaces)
    complete = bool(
        surface_count
        and bridge.get("surface_export_complete") is True
        and int(bridge.get("raw_mesh_triangle_count") or 0) == surface_count
        and int(bridge.get("exported_surface_count") or 0) == surface_count
    )
    audit = audit_program_semantic_carrier_evidence(
        _dict(source.metadata.get("program_semantic_carrier_evidence")),
        actual_program_hash=program_hash,
        actual_geometry_hash=geometry_hash,
        actual_surface_payload_hash=source_surface_payload_hash(
            tuple(source.surfaces)
        ),
        surface_payload_complete=complete,
        current_context={
            **expected_context,
            "program_id": program_id,
        },
        repaired_volume_records=[
            (
                {
                    "bottom_height": float(volume.bottom_fraction),
                    "top_height": float(volume.top_fraction),
                },
                volume.footprint,
            )
            for volume in source.volumes
        ],
        final_program_payload=(
            payload if isinstance(payload, dict) else {}
        ),
    )
    bridge_identity_failures = []
    if str(bridge.get("program_hash") or "") != program_hash:
        bridge_identity_failures.append("final_program_hash_mismatch")
    if str(bridge.get("geometry_hash") or "") != geometry_hash:
        bridge_identity_failures.append("final_geometry_hash_mismatch")
    if bridge_identity_failures:
        audit = dict(audit)
        audit["failures"] = sorted(set(
            list(audit.get("failures") or ())
            + bridge_identity_failures
        ))
        audit["hard_pass"] = False
        audit["accepted_carriers"] = []
    if source.metadata.get("program_space_zones"):
        audit = dict(audit)
        failures = list(audit.get("failures") or ())
        failures.append("stale_program_space_zones_present")
        audit["failures"] = sorted(set(failures))
        audit["hard_pass"] = False
        audit["accepted_carriers"] = []
    audited_context = {
        **expected_context,
        "program_id": program_id,
    }
    audit = dict(audit)
    audit["status"] = "verified" if audit.get("hard_pass") else "rejected"
    audit["audited_context"] = audited_context
    audit["audited_context_hash"] = semantic_audit_context_hash(
        audited_context
    )
    return audit


def _source_role_scaffold(
    source: SourceMass,
    *,
    program_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    failures: list[str] = []
    graph = (
        source.metadata.get("component_graph")
        if isinstance(source.metadata.get("component_graph"), dict)
        else {}
    )
    graph_name = str(graph.get("name") or "")
    graph_schema = str(graph.get("schema_version") or "")
    notes = [str(value) for value in graph.get("notes") or ()]
    templates = load_component_assemblies().get("templates") or {}
    template_key = next((
        key
        for key in sorted(templates)
        if graph_name == key or graph_name.startswith(f"{key}__")
    ), "")
    expected_prefix = {
        "gymnasium": "program_gym_",
        "cultural": "program_cultural_",
        "neighborhood_living": "program_neighborhood_",
    }.get(program_id, "")
    template = (
        templates.get(template_key)
        if template_key.startswith(expected_prefix)
        and isinstance(templates.get(template_key), dict)
        else {}
    )
    if (
        graph_schema != "arr.maas.component_graph.v2"
        or not template
        or f"program_profile={program_id}" not in notes
    ):
        failures.append("untrusted_component_graph_provenance")
    canonical_roles = {
        str(component.get("role") or "")
        for component in template.get("components") or ()
        if isinstance(component, dict) and component.get("role")
    }
    provenance = {
        "component_graph_schema": graph_schema,
        "component_graph_name": graph_name,
        "component_template_id": template_key,
        "program_profile_note": f"program_profile={program_id}",
        "canonical_component_ids": sorted(canonical_roles),
        "compiled_source_identity_method": (
            "canonical_role_plus_normalized_volume_geometry"
        ),
    }
    grouped: dict[str, list[Any]] = defaultdict(list)
    for volume in source.volumes:
        raw_role = str(volume.role or "")
        canonical_role = _canonical_source_component_role(
            raw_role,
            canonical_roles,
        )
        if not canonical_role:
            failures.append(f"untrusted_source_component_role:{raw_role}")
            continue
        grouped[canonical_role].append(volume)
    if not grouped:
        return [], provenance, failures
    dominant_role, dominant = max(
        grouped.items(),
        key=lambda item: sum(
            float(volume.footprint.area)
            * (float(volume.top_fraction) - float(volume.bottom_fraction))
            for volume in item[1]
        ),
    )
    dominant_geometry = unary_union([volume.footprint for volume in dominant])
    angle, width, depth = _principal_frame(source.footprint)
    theta = radians(angle)
    origin = source.footprint.centroid
    dominant_area = max(float(dominant_geometry.area), 1e-9)
    scaffold_by_relation: dict[str, dict[str, Any]] = {}
    for role, volumes in sorted(grouped.items()):
        geometry = unary_union([volume.footprint for volume in volumes])
        component_identity = (
            f"{template_key}:{role}:"
            f"{_canonical_hash([{
                'role': str(volume.role or ''),
                'footprint_wkb_hex': volume.footprint.normalize().wkb_hex,
                'bottom_fraction': round(float(volume.bottom_fraction), 8),
                'top_fraction': round(float(volume.top_fraction), 8),
                'verb': str(volume.verb or ''),
            } for volume in volumes])[:20]}"
        )
        center = geometry.centroid
        dx, dy = center.x - origin.x, center.y - origin.y
        u = 0.5 + (dx * cos(theta) + dy * sin(theta)) / max(width, 1e-9)
        v = 0.5 + (-dx * sin(theta) + dy * cos(theta)) / max(depth, 1e-9)
        for relation in _source_relations(
            program_id,
            role,
            dominant=(role == dominant_role),
        ):
            scaffold_by_relation.setdefault(relation, {
                "semantic_role": role,
                "source_component_id": (
                    f"{component_identity}:{relation}"
                ),
                "source_relation": relation,
                "normalized_center": [round(u, 8), round(v, 8)],
                "normalized_area_ratio": round(
                    min(1.0, float(geometry.area) / dominant_area),
                    8,
                ),
                "bottom_fraction": round(
                    min(float(volume.bottom_fraction) for volume in volumes),
                    8,
                ),
                "top_fraction": round(
                    max(float(volume.top_fraction) for volume in volumes),
                    8,
                ),
            })
    scaffold = [
        scaffold_by_relation[relation]
        for relation in REQUIRED_RELATIONS.get(program_id, ())
        if relation in scaffold_by_relation
    ]
    return scaffold, provenance, failures


def _canonical_source_component_role(
    raw_role: str,
    canonical_roles: set[str],
) -> str:
    for canonical_role in sorted(
        canonical_roles,
        key=lambda role: (-len(role), role),
    ):
        if raw_role == canonical_role:
            return canonical_role
        if raw_role.startswith(f"{canonical_role}__book_"):
            return canonical_role
        marker = f"{canonical_role}__program_section_band__book_"
        if not raw_role.startswith(marker):
            continue
        lineage = raw_role[len(marker):]
        if lineage and all(
            character.isalnum() or character in {"_", "+", "-"}
            for character in lineage
        ):
            return canonical_role
    return ""


def _source_role_origin(
    scaffold: list[dict[str, Any]],
    provenance: dict[str, Any],
    *,
    program_id: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": "arr.maas.source_role_scaffold_origin.v1",
        "program_id": _normalized_program_id(program_id),
        "component_graph_hash": _canonical_hash(provenance),
        "source_components": [
            {
                "source_component_id": str(
                    record.get("source_component_id") or ""
                ),
                "semantic_role": str(record.get("semantic_role") or ""),
                "source_relation": str(record.get("source_relation") or ""),
            }
            for record in scaffold
        ],
    }
    return {
        **payload,
        "origin_hash": _canonical_hash(payload),
    }


def _final_program_has_reachable_source_role_origin(
    payload: Any,
    *,
    expected_origin: dict[str, Any],
) -> bool:
    if not isinstance(payload, dict) or not payload.get("nodes"):
        return False
    try:
        from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram

        program = GeometryProgram.from_dict(payload)
        reachable_ids: set[str] = set()
        pending = [program.root_id]
        while pending:
            node_id = pending.pop()
            if node_id in reachable_ids:
                continue
            node = program.node_map.get(node_id)
            if node is None:
                return False
            reachable_ids.add(node_id)
            pending.extend(node.inputs)
        nodes = [
            node for node in program.topological_nodes()
            if node.id in reachable_ids
        ]
    except (TypeError, ValueError):
        return False
    matches = [
        node
        for node in nodes
        if node.semantic_role == "source_role_scaffold_origin"
        and node.kind == "transform"
        and node.operator == "matrix4"
        and node.parameters.get("source_role_scaffold_origin")
        == expected_origin
    ]
    if len(matches) != 1:
        return False
    expected_components = tuple(
        component
        for component in expected_origin.get("source_components") or ()
        if isinstance(component, dict)
    )
    expected_by_relation = {
        str(component.get("source_relation") or ""): component
        for component in expected_components
    }
    relation_nodes = [
        node
        for node in nodes
        if node.semantic_role == "source_role_relation_binding"
        and node.kind == "transform"
        and node.operator == "matrix4"
    ]
    if len(relation_nodes) != len(expected_by_relation):
        return False
    observed_relations: set[str] = set()
    for node in relation_nodes:
        binding = node.parameters.get("source_role_relation_binding")
        if not isinstance(binding, dict):
            return False
        relation = str(binding.get("source_relation") or "")
        expected = expected_by_relation.get(relation)
        relation_hash = str(binding.get("relation_hash") or "")
        hash_payload = {
            key: value
            for key, value in binding.items()
            if key != "relation_hash"
        }
        if (
            expected is None
            or relation in observed_relations
            or str(binding.get("program_id") or "")
            != str(expected_origin.get("program_id") or "")
            or str(binding.get("source_component_id") or "")
            != str(expected.get("source_component_id") or "")
            or str(binding.get("semantic_role") or "")
            != str(expected.get("semantic_role") or "")
            or relation_hash != _canonical_hash(hash_payload)
        ):
            return False
        observed_relations.add(relation)
    return observed_relations == set(expected_by_relation)


def _resolve_reachable_source_role_origin(
    payload: Any,
    *,
    scaffold: list[dict[str, Any]],
    provenance: dict[str, Any],
    program_id: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload.get("nodes"):
        return None
    candidates = [
        node.get("parameters", {}).get("source_role_scaffold_origin")
        for node in payload.get("nodes") or ()
        if isinstance(node, dict)
        and node.get("semantic_role") == "source_role_scaffold_origin"
        and node.get("kind") == "transform"
        and node.get("operator") == "matrix4"
    ]
    candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    if len(candidates) != 1:
        return None
    origin = candidates[0]
    normalized = _normalized_program_id(program_id)
    if (
        origin.get("schema_version")
        != "arr.maas.source_role_scaffold_origin.v1"
        or str(origin.get("program_id") or "") != normalized
        or str(origin.get("component_graph_hash") or "")
        != _canonical_hash(provenance)
        or str(origin.get("origin_hash") or "")
        != _canonical_hash({
            key: value for key, value in origin.items()
            if key != "origin_hash"
        })
        or not _final_program_has_reachable_source_role_origin(
            payload,
            expected_origin=origin,
        )
    ):
        return None
    expected_roles = {
        str(record.get("source_relation") or ""): str(
            record.get("semantic_role") or ""
        )
        for record in scaffold
    }
    bound_roles = {
        str(component.get("source_relation") or ""): str(
            component.get("semantic_role") or ""
        )
        for component in origin.get("source_components") or ()
        if isinstance(component, dict)
    }
    if bound_roles != expected_roles:
        return None
    return dict(origin)


def _project_scaffold_to_final_bands(
    scaffold: list[dict[str, Any]],
    final_source: SourceMass,
) -> tuple[list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    carriers: list[dict[str, Any]] = []
    source_by_relation = {
        str(record.get("source_relation") or ""): record
        for record in scaffold
    }
    dominant_relation = next(
        (
            relation for relation in source_by_relation
            if relation in {
                "dominant_hall",
                "public_gallery_hall",
                "primary_program_mass",
            }
        ),
        "",
    )
    bands = _source_bands(final_source)
    for floor_index, (bottom, top, host) in enumerate(bands):
        available = host
        subordinate = [
            record for relation, record in source_by_relation.items()
            if relation and relation != dominant_relation
            and float(record.get("top_fraction") or 0.0) > bottom + 1e-9
            and float(record.get("bottom_fraction") or 0.0) < top - 1e-9
        ]
        for record in subordinate:
            requested = _normalized_patch(host, record)
            projected = requested.intersection(available)
            if projected.is_empty or projected.area <= 1e-8:
                failures.append(
                    f"required_carrier_projection_empty:{record.get('source_relation')}"
                )
                continue
            projected = projected.buffer(0)
            carrier = _carrier_record(
                record,
                floor_index=floor_index,
                bottom=bottom,
                top=top,
                polygon=projected,
                host=host,
            )
            carriers.append(carrier)
            available = available.difference(projected).buffer(0)
        if dominant_relation:
            dominant_record = source_by_relation[dominant_relation]
            if available.is_empty or available.area <= 1e-8:
                failures.append(
                    f"required_carrier_projection_empty:{dominant_relation}"
                )
            else:
                carriers.append(_carrier_record(
                    dominant_record,
                    floor_index=floor_index,
                    bottom=bottom,
                    top=top,
                    polygon=available,
                    host=host,
                ))
    return carriers, failures


def _normalized_patch(host: Any, record: dict[str, Any]) -> Any:
    u, v = (float(value) for value in record["normalized_center"])
    ratio = max(0.0, min(0.45, float(record.get("normalized_area_ratio") or 0.0)))
    angle, width, depth = _principal_frame(host.convex_hull)
    theta = radians(angle)
    origin = host.centroid
    x = origin.x + (u - 0.5) * width * cos(theta) - (v - 0.5) * depth * sin(theta)
    y = origin.y + (u - 0.5) * width * sin(theta) + (v - 0.5) * depth * cos(theta)
    scale = sqrt(max(ratio, 1e-9))
    patch = box(
        x - width * scale / 2.0,
        y - depth * scale / 2.0,
        x + width * scale / 2.0,
        y + depth * scale / 2.0,
    )
    return rotate(patch, angle, origin=(x, y), use_radians=False)


def _carrier_record(
    record: dict[str, Any],
    *,
    floor_index: int,
    bottom: float,
    top: float,
    polygon: Any,
    host: Any,
) -> dict[str, Any]:
    carrier = {
        "carrier_id": (
            f"carrier:{record.get('source_relation')}:{floor_index}"
        ),
        "semantic_role": str(record.get("semantic_role") or ""),
        "source_component_id": str(record.get("source_component_id") or ""),
        "source_relation": str(record.get("source_relation") or ""),
        "floor_index": floor_index,
        "bottom_fraction": round(bottom, 8),
        "top_fraction": round(top, 8),
        "normalized_center": list(record.get("normalized_center") or ()),
        "requested_area_ratio": round(
            float(record.get("normalized_area_ratio") or 0.0),
            8,
        ),
        "final_polygon_utm": mapping(polygon),
        "measured_area_m2": round(float(polygon.area), 8),
    }
    carrier["final_volume_band_key"] = _band_key(
        floor_index,
        host,
        carrier,
    )
    return carrier


def _carrier_geometry_invariants(
    carriers: list[dict[str, Any]],
    final_source: SourceMass,
) -> tuple[bool, bool]:
    bands = {
        index: host for index, (_bottom, _top, host)
        in enumerate(_source_bands(final_source))
    }
    contained = True
    disjoint = True
    by_floor: dict[int, list[Any]] = defaultdict(list)
    for carrier in carriers:
        floor_index = int(carrier["floor_index"])
        polygon = shape(carrier["final_polygon_utm"])
        host = bands.get(floor_index)
        contained = contained and bool(
            host is not None and host.buffer(1e-8).covers(polygon)
        )
        if any(polygon.intersection(other).area > 1e-8 for other in by_floor[floor_index]):
            disjoint = False
        by_floor[floor_index].append(polygon)
    return contained, disjoint


def _source_bands(source: SourceMass) -> list[tuple[float, float, Any]]:
    grouped: dict[tuple[float, float], list[Any]] = defaultdict(list)
    for volume in source.volumes:
        grouped[
            (
                round(float(volume.bottom_fraction), 8),
                round(float(volume.top_fraction), 8),
            )
        ].append(volume.footprint)
    return [
        (bottom, top, unary_union(parts).buffer(0))
        for (bottom, top), parts in sorted(grouped.items())
    ]


def _feature_bands(
    records: list[tuple[dict[str, Any], Any]],
) -> dict[int, Any]:
    grouped: dict[tuple[float, float], list[Any]] = defaultdict(list)
    for record, geometry in records:
        grouped[(
            round(float(record.get("bottom_height") or 0.0), 8),
            round(float(record.get("top_height") or 0.0), 8),
        )].append(geometry)
    return {
        index: unary_union(parts).buffer(0)
        for index, (_key, parts) in enumerate(sorted(grouped.items()))
    }


def _band_key(
    floor_index: int,
    host: Any,
    carrier: dict[str, Any],
) -> str:
    return _canonical_hash({
        "floor_index": floor_index,
        "bottom_fraction": carrier.get("bottom_fraction"),
        "top_fraction": carrier.get("top_fraction"),
        "host_wkb_hex": host.normalize().wkb_hex,
    })


def _source_relations(
    program_id: str,
    role: str,
    *,
    dominant: bool,
) -> tuple[str, ...]:
    text = str(role or "").lower()
    if program_id == "gymnasium":
        if dominant and any(token in text for token in ("main", "hall")):
            return ("dominant_hall",)
        if "service" in text:
            return ("service_support",)
        if any(token in text for token in ("entry", "daylight", "monitor", "canopy")):
            return ("public_entry_daylight",)
    elif program_id == "cultural":
        if dominant and any(token in text for token in ("gallery", "hall")):
            return ("public_gallery_hall",)
        if any(token in text for token in ("court", "public", "atrium")):
            return ("court_public_space",)
        if any(token in text for token in ("entry", "bridge", "ramp")):
            return ("public_entry_path",)
    elif program_id == "neighborhood_living":
        relations = []
        if "primary" in text:
            relations.append("primary_program_mass")
        if any(
            token in text
            for token in ("active", "ground", "platform", "podium")
        ):
            relations.append("active_ground_program")
        if any(token in text for token in ("entry", "canopy", "terrace", "public")):
            relations.append("public_spatial_gesture")
        return tuple(relations)
    return ()


def _normalized_program_id(value: str) -> str:
    resolved = str(resolve_program_profile(value).get("id") or "")
    if resolved and resolved != "generic":
        return resolved
    text = str(value or "").lower()
    if "gym" in text:
        return "gymnasium"
    if any(token in text for token in ("cultural", "museum")):
        return "cultural"
    if "neighborhood" in text:
        return "neighborhood_living"
    return text


def _principal_frame(poly: Polygon) -> tuple[float, float, float]:
    coordinates = list(poly.minimum_rotated_rectangle.exterior.coords)
    edges = [
        (hypot(x2 - x1, y2 - y1), degrees(atan2(y2 - y1, x2 - x1)))
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
    ]
    edges.sort(reverse=True)
    return (
        edges[0][1] if edges else 0.0,
        edges[0][0] if edges else 0.0,
        edges[-1][0] if edges else 0.0,
    )


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "REQUIRED_RELATIONS",
    "SCHEMA_VERSION",
    "audit_program_semantic_carrier_evidence",
    "audit_program_semantic_carrier_geometry",
    "audit_source_semantic_projection",
    "build_program_semantic_carrier_evidence",
    "canonical_semantic_carrier_payload_hash",
    "rebind_semantic_projection_capacity",
    "semantic_capacity_measurement_hash",
    "semantic_site_context_hash",
]

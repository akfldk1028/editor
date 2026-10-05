"""One typed manifest for the complete MAAS architectural-language pipeline.

This module is intentionally an aggregator.  The BOOK transcription, base
seeds, early chassis and program catalog remain owned by their small source
modules; the frontend and memory exporters consume this read-only view instead
of recreating counts or flattening the layers into one list of tags.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

from math import prod
import os
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.book_language.corpus_contract import AGGREGATION_CONTRACTS, BASE_OPERATIVES, BASE_VOLUME_FRACTIONS, BOOK_ORIENTATIONS, BOOK_PAGE_COUNT, BOOK_VARIATION_COUNT, CASE_STUDY_CONTRACTS, COMBINATION_CONTRACTS
from backend.app.modules.design.generation.maas.book_language.base_volume_contract import BOOK_BASE_VOLUME_SPECS
from backend.app.modules.design.generation.maas.book_language.capacity_alternatives import capacity_alternative_catalog
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_SEED_SPECS
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import matrix4_to_lists, scale_matrix4
from backend.app.modules.design.generation.maas.geometry_language.typology_priors import TYPOLOGY_PRIORS
from backend.app.modules.design.generation.maas.geometry_language.universal_form_bank import universal_form_bank_contract, universal_form_programs
from backend.app.modules.design.generation.maas.geometry_language.system_contract import build_extended_csg_contract
from backend.app.modules.design.generation.maas.book_language.source_bundle import load_book_source_bundle
from backend.app.modules.design.generation.maas.program_massing.profiles import load_program_profiles
from backend.app.modules.design.generation.maas.book_exploration_graph import build_book_exploration_graph


SCHEMA_VERSION = "arr.maas.language_system.v3"


def _bounded_environment_int(name: str, default: int, ceiling: int) -> int:
    try:
        return max(0, min(ceiling, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _reference_context_status() -> dict[str, Any]:
    """Expose evidence provenance and effective cost guards to read-only clients."""

    reference_root = _design_paths.workspace_root() / "docs" / "ai-session-memory" / "reference-corpus"
    archdaily_root = reference_root / "archdaily"
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    try:
        files = [path for path in archdaily_root.rglob("*") if path.is_file()]
    except OSError:
        files = []
    return {
        "source": "ArchDaily API + curated seeds",
        "available": bool(files),
        "collection_count": sum(path.name == "metadata.jsonl" for path in files),
        "image_count": sum(path.suffix.lower() in image_suffixes for path in files),
        "transfer_contract": "whole-building relations and operations only; never copy completed form",
        "pipeline_order": [
            "program-matched retrieval",
            "whole-building image audit",
            "relation-only author context",
            "post-program VLM critic",
        ],
        "live_vlm_policy": {
            "reference_images_per_request": _bounded_environment_int(
                "MAAS_PREFERENCE_VLM_REFERENCE_LIMIT", 2, 3
            ),
            "process_request_cap": _bounded_environment_int(
                "MAAS_LIVE_VLM_MAX_REQUESTS", 24, 10_000
            ),
            "retry_count": _bounded_environment_int(
                "MAAS_PREFERENCE_VLM_RETRIES", 1, 8
            ),
            "launch_mode": "cache-first; live run is an explicit external action",
        },
    }


def _principles() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend({
        "id": item.principle_id,
        "label": item.verb,
        "stage": "operative",
        "page": item.page,
        "verbs": [item.verb],
        "transformation": item.transformation,
        "cardinality": item.cardinality,
    } for item in BASE_OPERATIVES)
    rows.extend({
        "id": f"book:combination:{index:02d}:{item.first}+{item.second}",
        "label": f"{item.first} + {item.second}",
        "stage": "combination",
        "page": item.page,
        "verbs": [item.first, item.second],
    } for index, item in enumerate(COMBINATION_CONTRACTS, start=1))
    rows.extend({
        "id": f"book:aggregation:{'+'.join(item.methods)}:{item.operative}",
        "label": f"{' + '.join(item.methods)} · {item.operative}",
        "stage": "aggregation",
        "page": item.page,
        "verbs": [item.operative, *item.methods],
    } for item in AGGREGATION_CONTRACTS)
    rows.extend({
        "id": f"book:case:{item.page}:{'+'.join(item.verbs)}",
        "label": item.label,
        "stage": "case_study",
        "page": item.page,
        "verbs": list(item.verbs),
        "implementation_elements": list(item.implementation_elements),
    } for item in CASE_STUDY_CONTRACTS)
    return rows


def build_language_system_manifest() -> dict[str, Any]:
    """Return the BOOK-faithful explicit exploration graph used by API and UI."""

    spec_by_label = {item.label: item for item in BOOK_BASE_VOLUME_SPECS}
    principles = _principles()
    program_profiles = load_program_profiles()
    capacity_alternatives = capacity_alternative_catalog()
    axis_counts = {
        "base_models": 1,
        "base_volumes": len(BASE_VOLUME_FRACTIONS),
        "orientations": len(BOOK_ORIENTATIONS),
        "base_seeds": len(BASE_SEED_SPECS),
        "chassis": len(TYPOLOGY_PRIORS),
        "principles": len(principles),
        "variations": BOOK_VARIATION_COUNT,
        "programs": len(program_profiles),
        "capacity_alternatives": len(capacity_alternatives),
    }
    base_seed_scope_instances = prod(axis_counts[key] for key in (
        "base_volumes", "orientations", "base_seeds",
    ))
    book_variant_paths = base_seed_scope_instances * axis_counts["principles"] * axis_counts["variations"]
    program_conditioned_paths = book_variant_paths * axis_counts["programs"]
    capacity_conditioned_paths = (
        program_conditioned_paths * axis_counts["capacity_alternatives"]
    )
    theoretical_paths = capacity_conditioned_paths * axis_counts["chassis"]
    exploration_graph = build_book_exploration_graph()
    geometry_language_contract = build_extended_csg_contract()
    source_bundle = load_book_source_bundle()

    base_volumes = [{
        "id": f"book:base-volume:{label.replace('/', '-')}",
        "label": label,
        "fraction": fraction,
        "topology": spec_by_label[label].topology,
        "page": 3,
        "meaning": (
            "canonical UnitBox authority"
            if label == "1/1"
            else "derived occupancy/partition state of the 1/1 UnitBox"
        ),
        "role": "canonical_base_model" if label == "1/1" else "derived_volume",
    } for label, fraction in BASE_VOLUME_FRACTIONS]
    base_seeds = [{
        "id": item.seed_id,
        "label": item.label,
        "normalized_scale": list(item.normalized_scale),
        "matrix4": matrix4_to_lists(scale_matrix4(item.normalized_scale)),
        "architectural_use": item.architectural_use,
        "primitive_operator": item.primitive_operator,
    } for item in BASE_SEED_SPECS]
    chassis = [{
        "id": item.typology_id,
        "label": item.label,
        "relation_class": item.relation_class,
        "primary_operator": item.primary_operator,
        "preferred_base_seeds": list(item.preferred_base_seeds),
        "generation_scope": "universal_pre_program",
        "downstream_program_compatibility_hints": list(item.program_ids),
    } for item in TYPOLOGY_PRIORS]
    programs = []
    for profile in program_profiles:
        aliases = [str(alias) for alias in profile.get("aliases") or ()]
        korean_alias = next((
            alias for alias in aliases
            if any("\uac00" <= char <= "\ud7a3" for char in alias)
        ), "")
        programs.append({
            "id": str(profile.get("id") or "generic"),
            "label": korean_alias or str(profile.get("id") or "generic").replace("_", " ").title(),
            "design_intent": str(profile.get("design_intent") or ""),
            "target_floor_range": list(profile.get("target_floor_range") or [1, 40]),
            "profile_authority": "program_profiles.v1",
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "system_id": "maas_book_architectural_language",
        "source": {
            "page_count": BOOK_PAGE_COUNT,
            "base_volume_page": 3,
            "principle_count": len(principles),
            "authority": "docs/260506/BOOK",
            "bundle": source_bundle,
        },
        "geometry_language_contract": geometry_language_contract,
        "semantic_order": [
            "base_model", "derived_volume", "orientation", "operation_family", "cardinality",
            "book_operation", "variation", "book_extension", "program", "capacity_alternative",
            "hard_gates", "live_vlm", "portfolio",
        ],
        "form_bank_contract": {
            **universal_form_bank_contract(),
            "stage_order": [
                "base_model_selection", "derived_volume_selection", "implementation_detail", "orientation",
                "book_operation", "book_extension", "program_projection",
                "capacity_alternative_projection", "hard_gates", "live_vlm",
            ],
            "program_count": len(universal_form_programs()),
            "dominant_solid_authority": "unitbox_1_1_then_explicit_derivation",
            "program_role": "downstream_projection_and_gate",
            "vlm_role": "post_program_typed_critic_and_repair",
        },
        "base_volume_contract": {
            "rule": "1/1 UnitBox is the sole public root; BOOK ratios, seed proportions and chassis are derived implementation states",
            "canonical_base_model": "1/1 UnitBox",
            "affine_representation": "homogeneous_matrix4",
            "examples": [
                {"base_volume": "1/1", "base_seed": "slab", "reads_as": "wide plate / full podium datum"},
                {"base_volume": "1/2", "base_seed": "slab", "reads_as": "half plate / podium band"},
                {"base_volume": "1/1", "base_seed": "tower", "reads_as": "complete tower body"},
                {"base_volume": "1/4", "base_seed": "bar", "reads_as": "local linear wing segment"},
            ],
        },
        "reference_context": _reference_context_status(),
        "exploration_graph": exploration_graph,
        "axes": {
            "base_volumes": base_volumes,
            "orientations": [
                {"id": value, "label": value.replace("_", " ")} for value in BOOK_ORIENTATIONS
            ],
            "base_seeds": base_seeds,
            "chassis": chassis,
            "principles": principles,
            "variations": [
                {"id": f"variation-{index + 1:02d}", "label": f"v{index + 1:02d}", "index": index}
                for index in range(BOOK_VARIATION_COUNT)
            ],
            "programs": programs,
            "capacity_alternatives": capacity_alternatives,
            "hard_gates": [
                {"id": "connected_solid", "label": "Connected solid"},
                {"id": "program_fit", "label": "Program fit"},
                {"id": "capacity_target", "label": "FAR alternative target"},
                {"id": "legal", "label": "Legal envelope"},
                {"id": "geometry_retention", "label": "Geometry retention"},
                {"id": "parking", "label": "Parking"},
            ],
            "live_vlm": [
                {"id": "geometry_critic", "label": "Geometry critic"},
                {"id": "typed_revision", "label": "Typed graph revision"},
                {"id": "portfolio_critic", "label": "Portfolio critic"},
            ],
        },
        "counts": {
            **axis_counts,
            "base_seed_scope_instances": base_seed_scope_instances,
            "book_variant_paths": book_variant_paths,
            "program_conditioned_paths": program_conditioned_paths,
            "capacity_conditioned_paths": capacity_conditioned_paths,
            "theoretical_language_paths": theoretical_paths,
            "universal_form_programs": len(universal_form_programs()),
            "declared_search_units": exploration_graph["counts"]["node_count"],
            "declared_execution_edges": exploration_graph["counts"]["execution_edge_count"],
        },
        "count_formula": "explicit BOOK transitions only; no Cartesian path claim",
        "compatibility_contract": {
            "legacy_theoretical_count_is_diagnostic_only": True,
            "exploration_graph_edges_are_authoritative": True,
            "exploration_starts_at_book_base_model": True,
            "base_seed_and_chassis_are_detail_only": True,
            "invalid_pairs_are_rejected_not_padded": True,
            "live_vlm_is_typed_critic_not_geometry_authority": True,
            "program_and_vlm_do_not_author_universal_form_bank": True,
            "visualization_is_design_flow_not_model_neuron_internals": True,
            "capacity_alternatives_are_site_derived": True,
            "capacity_alternatives_are_stratified_not_exhaustively_materialized": True,
        },
    }


__all__ = ["SCHEMA_VERSION", "build_language_system_manifest"]

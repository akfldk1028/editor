"""Audited reference context shared by authors and final VLM review."""

from __future__ import annotations

import os
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, audit_reference_matches_for_massing, retrieve_geometry_reference_matches

def _audited_final_book_references(
    program: GeometryProgram,
    *,
    building_type: str,
    reference_provider: Any | None = None,
    explicit_matches: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return enough verified whole-building references without weakening the gate.

    A ten-project search can contain mostly interiors, detail shots, or a scale
    typology excluded by the program contract.  Previously that retrieval
    accident became a *candidate* failure even when the archive contained more
    suitable projects.  Expand the corpus search only when the unchanged
    program-specific three-image hard requirement is not met.
    """

    initial_limit = 10
    if reference_provider is not None:
        raw_references = list(reference_provider(program) or ())
    else:
        explicit_kwargs = (
            {"explicit_matches": list(explicit_matches)}
            if explicit_matches else {}
        )
        raw_references = retrieve_geometry_reference_matches(
            program,
            building_type=building_type,
            limit=initial_limit,
            **explicit_kwargs,
        )
    audit = audit_reference_matches_for_massing(
        raw_references,
        building_type=building_type,
        model=os.getenv("MAAS_PREFERENCE_VLM_MODEL") or None,
        limit=5,
    )
    initial_evidence = {
        "input_image_count": int(audit.get("input_image_count") or len(raw_references)),
        "massing_suitable_program_image_count": int(
            audit.get("massing_suitable_program_image_count") or 0
        ),
        "hard_pass": bool(audit.get("hard_pass")),
    }
    expansion_attempted = False
    expanded_limit = initial_limit
    if reference_provider is None and not bool(audit.get("hard_pass")):
        try:
            expanded_limit = max(12, min(32, int(os.getenv(
                "MAAS_FINAL_BOOK_REFERENCE_POOL_LIMIT",
                "24",
            ))))
        except (TypeError, ValueError):
            expanded_limit = 24
        expanded = retrieve_geometry_reference_matches(
            program,
            building_type=building_type,
            limit=expanded_limit,
            **explicit_kwargs,
        )
        if len(expanded) > len(raw_references):
            expansion_attempted = True
            raw_references = expanded
            audit = audit_reference_matches_for_massing(
                raw_references,
                building_type=building_type,
                model=os.getenv("MAAS_PREFERENCE_VLM_MODEL") or None,
                limit=5,
            )
    audit = {
        **audit,
        "adaptive_retrieval_attempted": expansion_attempted,
        "initial_retrieval": initial_evidence,
        "expanded_retrieval_limit": expanded_limit if expansion_attempted else initial_limit,
        "hard_requirement_was_not_relaxed": True,
    }
    return list(audit.get("accepted") or ()), audit


def _reference_language_author_context(
    references: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Lower audited precedent images into transferable author relations.

    The LLM never receives a famous building as a coordinate/template record.
    It receives only image-grounded whole-building traits and program/scale
    evidence, while the image VLM retains authority in the later critic pass.
    """

    records: list[dict[str, Any]] = []
    for item in references:
        if not isinstance(item, dict):
            continue
        image_audit = item.get("massing_image_audit")
        image_audit = image_audit if isinstance(image_audit, dict) else {}
        records.append({
            "source_id": str(item.get("source_id") or ""),
            "title": str(item.get("title") or ""),
            "selection_role": str(item.get("selection_role") or "similar"),
            "program_match_tier": str(item.get("program_match_tier") or ""),
            "building_scale_typology": str(image_audit.get("building_scale_typology") or "unknown"),
            "primary_building_typology": str(image_audit.get("primary_building_typology") or "unknown"),
            "visible_form_traits": [
                str(value) for value in image_audit.get("visible_form_traits") or ()
                if str(value).strip()
            ][:12],
            "massing_legibility": float(image_audit.get("massing_legibility") or 0.0),
            "operation_clarity": float(image_audit.get("operation_clarity") or 0.0),
        })
    return {
        "schema_version": "arr.maas.reference_vlm_author_context.v1",
        "status": "verified" if audit.get("hard_pass") else "insufficient_verified_archive",
        "program_id": str(audit.get("program_id") or ""),
        "whole_building_program_reference_count": int(
            audit.get("massing_suitable_program_image_count") or 0
        ),
        "minimum_required_count": int(audit.get("minimum_program_specific_images") or 0),
        "hard_pass": bool(audit.get("hard_pass")),
        "selection_authority": "none_author_prior_only",
        "copy_completed_form": False,
        "transfer_only_relations_and_operations": True,
        "references": records,
    }


__all__ = ["_audited_final_book_references","_reference_language_author_context"]


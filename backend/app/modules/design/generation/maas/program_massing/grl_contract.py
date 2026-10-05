"""Portable GRL audit contract for a selected MAAS massing archive.

GRL is deliberately used as an evidence/lineage viewer, not as a geometry
generator.  The executable generator remains MassDSL + source geometry; this
adapter makes site, principle, compiled candidate, score and morphology
neighborhoods inspectable without changing those responsibilities.
"""

from __future__ import annotations

from typing import Any


def build_archive_grl_contract(
    *,
    dataset_id: str,
    title: str,
    source_path: str,
    site: dict[str, Any],
    candidates: list[dict[str, Any]],
    morphology_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    features: list[dict[str, Any]] = [{
        "id": "feature:site",
        "label": str(site.get("pnu") or site.get("boundary_source") or "massing site"),
        "kind": "site_constraint",
        "confidence": 1.0,
        "pipelineStage": "site_context",
        "evidenceDensity": 1.0,
        "metadata": {
            "pnu": str(site.get("pnu") or ""),
            "boundary_source": str(site.get("boundary_source") or ""),
            "area_m2": str(site.get("area_m2") or ""),
            "access_edge": str((site.get("access_context") or {}).get("primary_access_edge") or ""),
        },
    }]
    evidence: list[dict[str, Any]] = []
    circuits: list[dict[str, Any]] = []
    principle_ids: dict[str, str] = {}

    for index, candidate in enumerate(candidates, start=1):
        candidate_id = f"feature:candidate:{index:02d}"
        principle = str(candidate.get("formal_principle") or "unclassified")
        principle_id = principle_ids.setdefault(principle, f"feature:principle:{_slug(principle)}")
        if not any(item["id"] == principle_id for item in features):
            features.append({
                "id": principle_id,
                "label": principle,
                "kind": "formal_principle",
                "confidence": 1.0,
                "pipelineStage": "architectural_language",
                "evidenceDensity": 1.0,
                "metadata": {"principle": principle},
            })
        vlm_score = _score(candidate.get("vlm_design_score"))
        features.append({
            "id": candidate_id,
            "label": str(candidate.get("variant_id") or f"candidate {index:02d}"),
            "kind": "compiled_mass_candidate",
            "confidence": vlm_score,
            "pipelineStage": "selected_archive",
            "evidenceDensity": 5.0,
            "metadata": {
                "language_group": str(candidate.get("language_group") or ""),
                "formal_principle": principle,
                "far_utilization": str(candidate.get("normalized_far_utilization") or ""),
                "volume_count": str(candidate.get("volume_count") or ""),
                "surface_count": str(candidate.get("surface_count") or ""),
            },
        })
        evidence_id = f"evidence:candidate:{index:02d}"
        evidence.append({
            "id": evidence_id,
            "featureId": candidate_id,
            "sourcePath": source_path,
            "excerpt": (
                f"principle={principle}; group={candidate.get('language_group')}; "
                f"VLM={vlm_score:.4f}; FAR-utilization={candidate.get('normalized_far_utilization')}; "
                f"volumes={candidate.get('volume_count')}; surfaces={candidate.get('surface_count')}"
            ),
            "evidenceType": "executable_geometry_metrics",
            "confidence": 1.0,
        })
        circuits.extend((
            {
                "id": f"circuit:site-candidate:{index:02d}",
                "sourceFeatureId": "feature:site",
                "targetFeatureId": candidate_id,
                "type": "constrains",
                "confidence": 1.0,
                "evidenceDensity": 1.0,
                "edgeWeight": 1.0,
                "evidenceIds": [evidence_id],
            },
            {
                "id": f"circuit:principle-candidate:{index:02d}",
                "sourceFeatureId": principle_id,
                "targetFeatureId": candidate_id,
                "type": "materializes_as",
                "confidence": vlm_score,
                "evidenceDensity": 5.0,
                "edgeWeight": 1.0,
                "evidenceIds": [evidence_id],
            },
        ))

    relations = []
    for index, relation in enumerate(morphology_relations, start=1):
        distance = max(0.0, min(1.0, float(relation.get("distance") or 0.0)))
        relations.append({
            "id": f"relation:morphology:{index:03d}",
            "sourceNodeId": f"feature:candidate:{int(relation['left']) + 1:02d}",
            "targetNodeId": f"feature:candidate:{int(relation['right']) + 1:02d}",
            "type": str(
                relation.get("repeat_kind")
                or ("intrinsic_geometry_duplicate" if distance < 0.20 else "morphology_neighbor")
            ),
            "confidence": round(1.0 - distance, 4),
            "metadata": {
                "intrinsic_distance": f"{distance:.4f}",
                "pose_invariant": "true",
            },
        })

    return {
        "schemaVersion": "grl/v1",
        "dataset": {
            "id": dataset_id,
            "title": title,
            "source": source_path,
            "description": "MAAS site/principle/compiled-geometry/VLM archive audit",
        },
        "stages": [
            {"id": "site_context", "label": "Site context"},
            {"id": "architectural_language", "label": "Architectural language"},
            {"id": "selected_archive", "label": "Selected executable mass"},
        ],
        "features": features,
        "evidence": evidence,
        "circuits": circuits,
        "relations": relations,
        "queryHints": [
            "Find rotation-invariant duplicate candidates",
            "Trace each formal principle to executable geometry evidence",
            "Inspect which language groups repeat despite different graph names",
        ],
    }


def _score(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def _slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in slug.split("_") if part) or "unclassified"


__all__ = ["build_archive_grl_contract"]

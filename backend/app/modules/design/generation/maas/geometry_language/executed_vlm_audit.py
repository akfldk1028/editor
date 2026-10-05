"""Bounded paid VLM audits for already-selected, actually rendered MASSes."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import uuid
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.program_massing.profiles import program_reference_contract
from backend.app.modules.design.generation.maas.preference.reference_paths import reference_image_preview_url
from backend.app.modules.design.generation.maas.design_memory.reference_events import build_reference_review_events

from backend.app.modules.design.generation.maas.geometry_language.executed_archive import archived_compilation, materialize_executed_mass_preview
from backend.app.modules.design.generation.maas.geometry_language.outcome_graph import GeometryOutcomeGraph
from backend.app.modules.design.generation.maas.geometry_language.vlm_adapter import retrieve_geometry_reference_matches, score_geometry_program_with_openai_vlm


AUDIT_SCHEMA_VERSION = "arr.maas.executed_mass_vlm_audits.v1"
AUDIT_FILENAME = "maas-paid-individual-vlm-audits.json"


def audit_executed_masses_with_openai_vlm(
    *,
    run_id: str,
    indices: Iterable[int],
    model: str | None = None,
    reference_limit: int = 3,
) -> dict[str, Any]:
    """Audit a bounded selection and atomically bind the evidence to its run.

    One candidate call is made per requested MASS. Reference-image suitability
    audits remain content-addressed and may be served from their existing cache.
    """

    selected_indices = tuple(dict.fromkeys(int(value) for value in indices))
    if not selected_indices:
        raise ValueError("at least one MASS index is required")
    if len(selected_indices) > 12:
        raise ValueError("post-run individual VLM audit is bounded to 12 MASSes")
    limit = max(1, min(5, int(reference_limit)))
    prepared: list[dict[str, Any]] = []
    archive_path: Path | None = None
    for index in selected_indices:
        compilation, artifact, row, current_archive = archived_compilation(index, run_id)
        if archive_path is None:
            archive_path = current_archive
        elif archive_path != current_archive:
            raise ValueError("all MASS indices must belong to one execution archive")
        projection = compilation.program.metadata.get("program_projection")
        projection = projection if isinstance(projection, dict) else {}
        building_type = str(
            projection.get("program_id")
            or compilation.program.metadata.get("family")
            or "generic"
        )
        references = retrieve_geometry_reference_matches(
            compilation.program,
            building_type=building_type,
            limit=limit,
        )
        prepared.append({
            "index": index,
            "compilation": compilation,
            "artifact": artifact,
            "row": row,
            "preview": materialize_executed_mass_preview(index, run_id),
            "building_type": building_type,
            "references": references,
        })
    assert archive_path is not None
    audit_records: list[dict[str, Any]] = []
    for item in prepared:
        result = score_geometry_program_with_openai_vlm(
            item["compilation"].program,
            item["compilation"],
            item["preview"],
            reference_matches=item["references"],
            building_type=item["building_type"],
            program_context=program_reference_contract(item["building_type"]),
            model=model,
        )
        _normalize_reference_preview_urls(result)
        audit_records.append({
            "index": item["index"],
            "variant_id": str(item["row"].get("variant_id") or f"maas_{item['index']:02d}"),
            "source_sequence": str(item["row"].get("source_sequence") or ""),
            "program_hash": item["compilation"].program.program_hash(),
            "geometry_hash": str(item["compilation"].geometry_hash or ""),
            "preview_path": str(item["preview"].resolve()),
            "building_type": item["building_type"],
            "audit": result,
        })
    _persist_audits(archive_path, run_id=run_id, audit_records=audit_records)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "run_id": run_id,
        "request_count": len(audit_records),
        "reference_limit_per_mass": limit,
        "records": audit_records,
        "audit_path": str((archive_path.parent / AUDIT_FILENAME).resolve()),
    }


def _persist_audits(
    archive_path: Path,
    *,
    run_id: str,
    audit_records: list[dict[str, Any]],
) -> None:
    archive = _read_object(archive_path)
    records = [item for item in archive.get("records") or () if isinstance(item, dict)]
    summary_path = archive_path.with_name("maas-book-programs-summary.json")
    summary = _read_object(summary_path)
    summary_program = next(
        (item for item in summary.get("programs") or () if isinstance(item, dict)),
        None,
    )
    summary_rows = {
        str(item.get("source_sequence") or ""): item
        for item in (summary_program or {}).get("rows") or ()
        if isinstance(item, dict)
    }
    audit_by_index = {int(item["index"]): item for item in audit_records}
    for index, record in enumerate(records, start=1):
        if index not in audit_by_index:
            continue
        artifact = record.get("geometry_artifact")
        if not isinstance(artifact, dict):
            raise ValueError(f"MASS {index} has no geometry artifact")
        bound = audit_by_index[index]
        artifact["vlmAudit"] = deepcopy(bound["audit"])
        source_sequence = str(bound.get("source_sequence") or "")
        if source_sequence in summary_rows:
            summary_rows[source_sequence]["individual_vlm_audit"] = deepcopy(bound["audit"])
    public_records = [_compact_audit_record(item) for item in audit_records]
    archive["post_run_individual_vlm_audits"] = public_records
    if summary_program is not None:
        summary_program["individual_mass_vlm_audits"] = public_records

    graph_path = archive_path.with_name("maas-geometry-mutation-outcome-graph.json")
    graph = GeometryOutcomeGraph.load(graph_path, pnu=str(archive.get("pnu") or summary.get("pnu") or ""))
    program_slug = str((summary_program or {}).get("slug") or "")
    for item in audit_records:
        graph.observe_executed_mass_vlm_audit(
            program_slug=program_slug,
            source_seed=str(item.get("source_sequence") or ""),
            program_hash=str(item.get("program_hash") or ""),
            geometry_hash=str(item.get("geometry_hash") or ""),
            preview_path=str(item.get("preview_path") or ""),
            audit=item["audit"],
        )
        image_inputs = item["audit"].get("vlm_image_inputs")
        image_inputs = image_inputs if isinstance(image_inputs, dict) else {}
        retrieved = image_inputs.get("retrieved_references")
        if not isinstance(retrieved, list):
            retrieved = list(image_inputs.get("references") or ())
        graph.observe_design_memory_events(build_reference_review_events(
            retrieved_references=retrieved,
            vlm_result=item["audit"],
            program_hash=str(item.get("program_hash") or ""),
            geometry_hash=str(item.get("geometry_hash") or ""),
        ))
    graph_payload = graph.save()
    graph_summary = summary.get("geometry_mutation_outcome_graph")
    if isinstance(graph_summary, dict):
        graph_summary.update({
            "node_count": graph_payload["node_count"],
            "edge_count": graph_payload["edge_count"],
            "observation_count": graph_payload["observation_count"],
        })
    audit_payload = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "run_id": run_id,
        "request_count": len(audit_records),
        "records": public_records,
    }
    _atomic_write_json(archive_path, archive)
    _atomic_write_json(summary_path, summary)
    _atomic_write_json(archive_path.with_name(AUDIT_FILENAME), audit_payload)


def _compact_audit_record(item: dict[str, Any]) -> dict[str, Any]:
    audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
    concept_scores = deepcopy(audit.get("concept_scores") or {})
    score_values = [
        float(value) for value in concept_scores.values()
        if isinstance(value, (int, float))
    ]
    critic_score = float(audit.get("critic_score") or (
        sum(score_values) / len(score_values) if score_values else 0.0
    ))
    hard_pass = bool(
        audit.get("hard_pass")
        if "hard_pass" in audit
        else audit.get("program_fit_hard_pass", True)
    )
    return {
        "index": int(item.get("index") or 0),
        "variant_id": str(item.get("variant_id") or ""),
        "source_sequence": str(item.get("source_sequence") or ""),
        "program_hash": str(item.get("program_hash") or ""),
        "geometry_hash": str(item.get("geometry_hash") or ""),
        "preview_path": str(item.get("preview_path") or ""),
        "building_type": str(item.get("building_type") or ""),
        "model": str(audit.get("model") or ""),
        "response_id": str(audit.get("response_id") or ""),
        "hard_pass": hard_pass,
        "program_fit_hard_pass": bool(audit.get("program_fit_hard_pass", True)),
        "critic_score": round(critic_score, 4),
        "critic_actions": [str(value) for value in audit.get("critic_actions") or ()],
        "concept_scores": concept_scores,
        "vlm_image_inputs": deepcopy(audit.get("vlm_image_inputs") or {}),
        "cache_hit": bool(audit.get("cache_hit")),
    }


def _normalize_reference_preview_urls(audit: dict[str, Any]) -> None:
    image_inputs = audit.get("vlm_image_inputs")
    image_inputs = image_inputs if isinstance(image_inputs, dict) else {}
    for item in image_inputs.get("references") or ():
        if not isinstance(item, dict):
            continue
        local_preview = reference_image_preview_url(str(item.get("local_path") or ""))
        if local_preview:
            item["preview_url"] = local_preview


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


__all__ = ["AUDIT_FILENAME", "AUDIT_SCHEMA_VERSION", "audit_executed_masses_with_openai_vlm"]

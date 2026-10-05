"""Export MAAS job/evidence examples for translator/reviewer fine-tuning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.evidence import build_maas_evidence_bundle


SYSTEM_PROMPT = (
    "You review ARR MAAS evidence. Do not change geometry. "
    "Report status, missing evidence, and recommended next deterministic tool action."
)


def evidence_to_review_example(evidence: dict[str, Any]) -> dict[str, Any]:
    candidate = evidence.get("candidate") or {}
    geometry = evidence.get("geometry") or {}
    final = evidence.get("final_decision") or {}
    missing = final.get("missing_evidence") or []
    sequence = geometry.get("verb_sequence") or []
    prompt = {
        "schema_version": evidence.get("schema_version"),
        "bundle_id": evidence.get("bundle_id"),
        "candidate": {
            "candidate_id": candidate.get("candidate_id"),
            "mass_shape": candidate.get("mass_shape"),
            "concept": candidate.get("maas_concept"),
            "diversity": candidate.get("diversity"),
        },
        "geometry_metrics": geometry.get("geometry_metrics") or {},
        "verb_sequence": sequence,
        "check_status_counts": _status_counts(evidence.get("checks") or []),
    }
    answer = {
        "review_status": final.get("status") or "unknown",
        "missing_evidence": missing,
        "must_not_claim_legal_pass": bool(missing or final.get("status") != "pass"),
        "recommended_tools": _recommended_tools(missing),
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))},
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False, separators=(",", ":"))},
        ],
        "source": "arr.maas.evidence.v0",
        "bundle_id": evidence.get("bundle_id"),
        "candidate_id": candidate.get("candidate_id"),
    }


def _status_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for check in checks:
        status = str(check.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _recommended_tools(missing: list[str]) -> list[str]:
    tools = ["validate_mass_candidate"]
    missing_text = " ".join(str(item) for item in missing)
    if "daylight" in missing_text or "sunlight" in missing_text:
        tools.append("render_mass_evidence")
    if "vworld" in missing_text.lower() or "visual" in missing_text.lower():
        tools.append("vworld_visual_check")
    if "parking" in missing_text or "fire" in missing_text or "energy" in missing_text:
        tools.append("maas_review")
    return tools


def build_examples_from_design_results(*, limit: int = 100, job_id: str | None = None) -> list[dict[str, Any]]:
    from backend.app.adapters.design_storage.models import DesignResult

    if limit <= 0:
        return []
    qs = DesignResult.objects.select_related("job").order_by("-job__created_at", "design_id")
    if job_id:
        qs = qs.filter(job_id=job_id)
    examples: list[dict[str, Any]] = []
    for design in qs.iterator(chunk_size=100):
        if not _is_maas_design_result(design):
            continue
        evidence = build_maas_evidence_bundle(job=design.job, design=design)
        examples.append(evidence_to_review_example(evidence))
        if len(examples) >= limit:
            break
    return examples


def _is_maas_design_result(design: Any) -> bool:
    job_options = getattr(design.job, "job_spec", {}) or {}
    if isinstance(job_options, dict):
        job_algorithm = ((job_options.get("options") or {}).get("algorithm"))
        if job_algorithm == "maas_legal_envelope":
            return True

    feature = design.mass_geojson if isinstance(design.mass_geojson, dict) else {}
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return (
        props.get("algorithm") == "maas_legal_envelope"
        or isinstance(props.get("maas_model"), dict)
        or bool(props.get("maas_verb_sequence"))
    )


def export_job_sft(path: str | Path, *, limit: int = 100, job_id: str | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for example in build_examples_from_design_results(limit=limit, job_id=job_id):
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
    return target


__all__ = ["build_examples_from_design_results", "evidence_to_review_example", "export_job_sft"]

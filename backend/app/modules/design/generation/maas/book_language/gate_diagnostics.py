"""Diagnostics emitted by candidate hard gates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

def _empty_gate_diagnostic() -> dict[str, Any]:
    gate_names = ("role_coverage", "dominant_ratio", "site_coverage", "hierarchy", "coherence", "program_form")
    return {
        "candidate_count": 0,
        "hard_pass_count": 0,
        "failed_candidate_count": 0,
        "gate_failed_counts": {name: 0 for name in gate_names},
        "exclusive_gate_failed_counts": {name: 0 for name in gate_names},
        "failure_signature_counts": {},
        "program_form_failure_counts": {},
        "coherence_failure_counts": {},
        "polygon_quality_failure_counts": {},
        "metric_samples": {
            "role_coverage_score": [],
            "dominant_component_ratio": [],
            "dominant_ratio_score": [],
            "site_coverage_ratio": [],
            "site_coverage_score": [],
            "hierarchy_score": [],
            "coherence_score": [],
        },
    }


def _record_gate_diagnostic(
    diagnostic: dict[str, Any],
    *,
    spatial: dict[str, Any],
    hard_pass: bool,
    failed_gates: tuple[str, ...],
    program_form_failures: tuple[str, ...] = (),
    coherence_evidence: dict[str, Any] | None = None,
) -> None:
    diagnostic["candidate_count"] += 1
    diagnostic["hard_pass_count" if hard_pass else "failed_candidate_count"] += 1
    for name in failed_gates:
        diagnostic["gate_failed_counts"][name] += 1
    if len(failed_gates) == 1:
        diagnostic["exclusive_gate_failed_counts"][failed_gates[0]] += 1
    signature = "+".join(failed_gates) if failed_gates else "none"
    diagnostic["failure_signature_counts"][signature] = diagnostic["failure_signature_counts"].get(signature, 0) + 1
    for reason in program_form_failures:
        diagnostic["program_form_failure_counts"][reason] = (
            diagnostic["program_form_failure_counts"].get(reason, 0) + 1
        )
    coherence = coherence_evidence if isinstance(coherence_evidence, dict) else {}
    if "coherence" in failed_gates:
        for reason, failed in (
            ("volume_count", int(coherence.get("volume_count") or 0) > 5),
            ("redundant_overlap", int(coherence.get("redundant_overlap_pair_count") or 0) > 1),
            ("spatial_component_count", int(coherence.get("spatial_component_count") or 0) > 1),
            (
                "plan_component_count",
                int(coherence.get("plan_component_count") or 0)
                > int(coherence.get("plan_component_allowance") or 2),
            ),
            ("small_fragment", int(coherence.get("small_fragment_count") or 0) > 1),
            ("polygon_quality", not bool(coherence.get("polygon_quality_hard_pass", True))),
            ("score", float(coherence.get("score") or 0.0) < 0.62),
        ):
            if failed:
                diagnostic["coherence_failure_counts"][reason] = (
                    diagnostic["coherence_failure_counts"].get(reason, 0) + 1
                )
        for polygon in coherence.get("polygon_quality") or ():
            if not isinstance(polygon, dict):
                continue
            for reason in polygon.get("failure_reasons") or ():
                diagnostic["polygon_quality_failure_counts"][str(reason)] = (
                    diagnostic["polygon_quality_failure_counts"].get(str(reason), 0) + 1
                )
    for name in diagnostic["metric_samples"]:
        diagnostic["metric_samples"][name].append(float(spatial.get(name) or 0.0))


def _metric_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "minimum": 0.0, "mean": 0.0, "maximum": 0.0}
    return {
        "count": len(values),
        "minimum": round(min(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "maximum": round(max(values), 4),
    }


def _summarize_gate_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    result = {key: deepcopy(value) for key, value in diagnostic.items() if key != "metric_samples"}
    result["metric_summaries"] = {
        name: _metric_summary(values)
        for name, values in diagnostic["metric_samples"].items()
    }
    return result


def _merge_gate_diagnostics(by_scope: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gate_names = ("role_coverage", "dominant_ratio", "site_coverage", "hierarchy", "coherence", "program_form")
    total = {
        "candidate_count": sum(item["candidate_count"] for item in by_scope.values()),
        "hard_pass_count": sum(item["hard_pass_count"] for item in by_scope.values()),
        "failed_candidate_count": sum(item["failed_candidate_count"] for item in by_scope.values()),
        "gate_failed_counts": {
            name: sum(item["gate_failed_counts"][name] for item in by_scope.values())
            for name in gate_names
        },
        "exclusive_gate_failed_counts": {
            name: sum(item["exclusive_gate_failed_counts"][name] for item in by_scope.values())
            for name in gate_names
        },
        "failure_signature_counts": {},
        "program_form_failure_counts": {},
        "coherence_failure_counts": {},
        "polygon_quality_failure_counts": {},
    }
    for item in by_scope.values():
        for signature, count in item["failure_signature_counts"].items():
            total["failure_signature_counts"][signature] = total["failure_signature_counts"].get(signature, 0) + count
        for reason, count in item["program_form_failure_counts"].items():
            total["program_form_failure_counts"][reason] = total["program_form_failure_counts"].get(reason, 0) + count
        for reason, count in item.get("coherence_failure_counts", {}).items():
            total["coherence_failure_counts"][reason] = total["coherence_failure_counts"].get(reason, 0) + count
        for reason, count in item.get("polygon_quality_failure_counts", {}).items():
            total["polygon_quality_failure_counts"][reason] = total["polygon_quality_failure_counts"].get(reason, 0) + count
    return total



__all__ = ["_empty_gate_diagnostic","_record_gate_diagnostic","_metric_summary","_summarize_gate_diagnostic","_merge_gate_diagnostics"]


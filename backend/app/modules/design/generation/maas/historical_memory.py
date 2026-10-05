"""Build a bounded, local-only GRL memory projection from ARR history."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Iterable


def build_historical_envelope(*, references: Iterable[Any], design_results: Iterable[Any], project_key: str = "arr-global-precedents") -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {}
    by_family: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for item in references:
        source = str(getattr(item, "source", "reference") or "reference")
        source_id = str(getattr(item, "source_id", "") or getattr(item, "title", "reference"))
        feature_id = f"feature:precedent:{_stable_id(source, source_id)}"
        evidence_id = f"evidence:precedent:{_stable_id(source, source_id)}"
        tags = [str(tag) for tag in getattr(item, "tags", ())]
        family = _family(" ".join([str(getattr(item, "title", "")), *tags]))
        caption = str(getattr(item, "caption", "") or getattr(item, "title", ""))
        features.append({
            "id": feature_id,
            "label": str(getattr(item, "title", "") or source_id),
            "kind": "precedent",
            "confidence": 0.72,
            "pipelineStage": "reference_corpus",
            "evidenceDensity": max(1, len(tags)),
            "metadata": {"family": family, "source": source},
        })
        evidence.append({
            "id": evidence_id,
            "featureId": feature_id,
            "sourcePath": str(getattr(item, "local_path", "") or getattr(item, "page_url", "") or source),
            "excerpt": caption[:1000] or f"ARR precedent {source_id}",
            "evidenceType": "reference_metadata",
            "confidence": 0.72,
        })
        payloads[feature_id] = {
            "family": family,
            "source": {
                "source": source,
                "sourceId": source_id,
                "tags": tags,
                "imageUrl": str(getattr(item, "image_url", "")),
                "pageUrl": str(getattr(item, "page_url", "")),
            },
        }
        by_family[family].append((feature_id, evidence_id))

    for result in design_results:
        mass = result.mass_geojson if isinstance(getattr(result, "mass_geojson", None), dict) else {}
        props = mass.get("properties") if isinstance(mass.get("properties"), dict) else {}
        source_id = f"{getattr(result, 'job_id', 'job')}:{getattr(result, 'design_id', 'design')}:{getattr(result, 'pk', 'row')}"
        feature_id = f"feature:design-result:{_stable_id(source_id)}"
        evidence_id = f"evidence:design-result:{_stable_id(source_id)}"
        family = _family(str(props.get("mass_shape") or props.get("algorithm") or "mass"))
        is_pareto = bool(getattr(result, "is_pareto_optimal", False))
        features.append({
            "id": feature_id,
            "label": str(props.get("mass_shape") or f"Design {source_id}"),
            "kind": "evaluated_design",
            "confidence": 0.9 if is_pareto else 0.76,
            "pipelineStage": "design_history",
            "evidenceDensity": 3 if is_pareto else 1,
            "metadata": {"family": family, "pareto": "true" if is_pareto else "false"},
        })
        evidence.append({
            "id": evidence_id,
            "featureId": feature_id,
            "sourcePath": f"DesignResult/{getattr(result, 'pk', source_id)}",
            "excerpt": f"feasible={bool(getattr(result, 'is_feasible', False))}; pareto={is_pareto}; ranking={getattr(result, 'ranking', None)}",
            "evidenceType": "evaluated_design_result",
            "confidence": 0.9 if is_pareto else 0.76,
        })
        metrics = {
            key: float(props[key]) for key in ("bcr", "far", "height", "floor_area", "footprint_area")
            if isinstance(props.get(key), int | float)
        }
        payload: dict[str, Any] = {
            "family": family,
            "metrics": metrics,
            "source": {
                "designResultId": str(getattr(result, "pk", "")),
                "jobId": str(getattr(result, "job_id", "")),
                "designId": int(getattr(result, "design_id", 0)),
                "isFeasible": bool(getattr(result, "is_feasible", False)),
                "isParetoOptimal": is_pareto,
            },
        }
        component_graph = props.get("component_graph")
        if isinstance(component_graph, dict):
            payload["componentGraph"] = _camel_component_graph(component_graph)
        payloads[feature_id] = payload
        by_family[family].append((feature_id, evidence_id))

    circuits: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    edge_index = 0
    # Sparse observations: connect adjacent evidence within each inferred family.
    for family, members in sorted(by_family.items()):
        for (source, source_evidence), (target, target_evidence) in zip(members, members[1:]):
            circuits.append({
                "id": f"circuit:history:{edge_index}",
                "sourceFeatureId": source,
                "targetFeatureId": target,
                "type": "same_family_observation",
                "confidence": 0.68,
                "evidenceDensity": 2,
                "edgeWeight": 0.7,
                "evidenceIds": [source_evidence, target_evidence],
            })
            relations.append({
                "id": f"relation:history:{edge_index}",
                "sourceNodeId": source,
                "targetNodeId": target,
                "type": "shares_inferred_family",
                "confidence": 0.68,
                "evidenceIds": [source_evidence, target_evidence],
                "metadata": {"family": family, "source": "arr_history"},
            })
            edge_index += 1

    return {
        "schemaVersion": "mass-brain/v1",
        "projectKey": project_key,
        "contract": {
            "schemaVersion": "grl/v1",
            "dataset": {"id": project_key, "title": "ARR global precedent and evaluated-design memory", "source": "ARR local history"},
            "stages": [
                {"id": "reference_corpus", "label": "Reference Corpus"},
                {"id": "design_history", "label": "Design History"},
            ],
            "features": features,
            "evidence": evidence,
            "circuits": circuits,
            "relations": relations,
            "queryHints": ["Find evidence-backed precedents and evaluated designs sharing a mass family"],
        },
        "domainPayloads": payloads,
    }


def _stable_id(*parts: str) -> str:
    text = ":".join(parts)
    readable = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-")[:48]
    return f"{readable or 'item'}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


def _family(text: str) -> str:
    value = text.lower()
    for family, words in (
        ("court", ("court", "courtyard", "atrium")),
        ("connector", ("bridge", "link", "connector", "interlock")),
        ("section", ("terrace", "step", "slope", "taper")),
        ("bar", ("bar", "ribbon", "linear", "slab")),
        ("cluster", ("cluster", "branch", "village", "campus")),
        ("tower", ("tower", "vertical", "high-rise")),
    ):
        if any(word in value for word in words):
            return family
    return "mass"


def _camel_component_graph(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(value.get("name") or "historical_graph"),
        "label": str(value.get("label") or value.get("name") or "Historical graph"),
        "nodes": [
            {
                "nodeId": str(node.get("nodeId") or node.get("node_id") or ""),
                "role": str(node.get("role") or "support"),
                "parentId": node.get("parentId", node.get("parent_id")),
                "optional": bool(node.get("optional", False)),
                "operation": node.get("operation") if isinstance(node.get("operation"), dict) else {},
            }
            for node in value.get("nodes", []) if isinstance(node, dict)
        ],
    }


__all__ = ["build_historical_envelope"]

"""Existing-source legal evidence adapter owned by ``law_graph_agent``."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import sys
import os
import socket
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

import httpx

from backend.app.modules.design.generation.maas.agents.shared.types import AgentEvidence, ExecutionIdentity
from backend.app.modules.design.generation.maas.law_provenance import build_law_provenance_projection


GraphLoader = Callable[[], Mapping[str, Any]]
LawSearcher = Callable[[str, int], Mapping[str, Any]]

LAW_SEARCH_TIMEOUT_SECONDS = 6.0


def numeric_verdict_status(payload: Mapping[str, Any]) -> str:
    """One contract for live binding and persisted numeric evidence.

    Explicit failure wins. Success needs both actual evaluation and a literal
    boolean pass; flags, aliases or partial producer payloads cannot imply it.
    """
    raw_status = payload.get("status")
    status = raw_status.strip().lower() if isinstance(raw_status, str) else ""
    if payload.get("hard_pass") is False or status in {"fail", "failed"}:
        return "failed"
    if raw_status is not None and not isinstance(raw_status, str):
        return "needs_evidence"
    if (payload.get("evaluated") is True and payload.get("hard_pass") is True
            and status in {"", "pass", "passed"}):
        return "passed"
    return "needs_evidence"


def collect_law_agent_evidence(
    identity: ExecutionIdentity,
    context: Mapping[str, Any],
    *,
    graph_loader: GraphLoader | None = None,
    searcher: LawSearcher | None = None,
) -> AgentEvidence:
    """Collect provenance without allowing availability failures to pass."""

    snapshot = collect_law_source_snapshot(
        context,
        graph_loader=graph_loader,
        searcher=searcher,
    )
    return bind_law_agent_evidence(identity, context, snapshot)


def collect_law_agent_evidence_batch(
    requests: Sequence[tuple[ExecutionIdentity, Mapping[str, Any]]],
    *,
    graph_loader: GraphLoader | None = None,
    searcher: LawSearcher | None = None,
) -> tuple[AgentEvidence, ...]:
    """Load one immutable source snapshot and bind it to every final MASS."""

    normalized = tuple(requests)
    if not normalized:
        return ()
    building_types = {
        str(context.get("building_type") or "building mass")
        for _identity, context in normalized
    }
    if len(building_types) != 1:
        raise ValueError(
            "one law evidence batch requires one building program"
        )
    snapshot = collect_law_source_snapshot(
        normalized[0][1],
        graph_loader=graph_loader,
        searcher=searcher,
    )
    return tuple(
        bind_law_agent_evidence(identity, context, snapshot)
        for identity, context in normalized
    )


def collect_law_source_snapshot(
    context: Mapping[str, Any],
    *,
    graph_loader: GraphLoader | None = None,
    searcher: LawSearcher | None = None,
) -> dict[str, Any]:
    """Collect the PNU-independent graph/search source once per program."""

    resolved_graph_loader = graph_loader or _fast_graph_projection
    try:
        graph_projection = dict(resolved_graph_loader() or {})
    except Exception as exc:  # external boundary: preserve a bounded error
        graph_projection = {
            "graph_status": {
                "attempted": True,
                "available": False,
                "error_category": type(exc).__name__,
            },
            "articles": [],
        }
    graph_status = graph_projection.get("graph_status")
    graph_status = dict(graph_status) if isinstance(graph_status, Mapping) else {}
    graph_status.setdefault("attempted", True)
    graph_status["available"] = bool(graph_status.get("available"))

    resolved_searcher = searcher or _bounded_law_domain_search
    building_type = str(context.get("building_type") or "building mass")
    query = f"{building_type} 용적률 건폐율 높이 주차"
    try:
        law_search = dict(resolved_searcher(query, 3) or {})
    except Exception as exc:  # external boundary: preserve a bounded error only
        law_search = {
            "attempted": True,
            "available": False,
            "error_category": _error_category(exc),
            "results": [],
        }
    law_search.setdefault("attempted", True)
    law_search["available"] = bool(law_search.get("available"))
    law_search["query"] = str(law_search.get("query") or query)
    search_results = [row for row in law_search.get("results") or () if isinstance(row, Mapping)]
    law_search["result_count"] = len(search_results)

    articles = [row for row in graph_projection.get("articles") or () if isinstance(row, Mapping)]
    article_ids = [
        str(row.get("id") or row.get("full_id") or row.get("ref_id") or "")
        for row in articles
    ]
    article_ids = [value for value in article_ids if value]
    search_result_ids = [
        str(row.get("hang_id") or row.get("id") or row.get("source_id") or "")
        for row in search_results
    ]
    search_result_ids = [value for value in search_result_ids if value]
    snapshot = {
        "schema_version": "arr.maas.law_source_snapshot.v1",
        "building_type": building_type,
        "neo4j": graph_status,
        "law_search": {
            key: value
            for key, value in law_search.items()
            if key != "results"
        },
        "articles": [dict(row) for row in articles],
        "search_results": [dict(row) for row in search_results],
        "article_ids": article_ids,
        "search_result_ids": search_result_ids,
    }
    snapshot["source_snapshot_hash"] = _canonical_payload_hash(snapshot)
    return deepcopy(snapshot)


def bind_law_agent_evidence(
    identity: ExecutionIdentity,
    context: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
) -> AgentEvidence:
    """Bind one shared source snapshot to one exact final MASS identity."""

    law = context.get("law")
    law = dict(law) if isinstance(law, Mapping) else {}
    snapshot = deepcopy(dict(source_snapshot or {}))
    graph_status = snapshot.get("neo4j")
    graph_status = (
        dict(graph_status) if isinstance(graph_status, Mapping) else {}
    )
    graph_status["available"] = bool(graph_status.get("available"))
    law_search = snapshot.get("law_search")
    law_search = (
        dict(law_search) if isinstance(law_search, Mapping) else {}
    )
    law_search["available"] = bool(law_search.get("available"))
    article_ids = [
        str(value) for value in snapshot.get("article_ids") or () if value
    ]
    search_result_ids = [
        str(value)
        for value in snapshot.get("search_result_ids") or ()
        if value
    ]

    missing: list[str] = []
    claimed_snapshot_hash = str(snapshot.get("source_snapshot_hash") or "")
    if not claimed_snapshot_hash:
        missing.append("source_snapshot_hash_missing")
    elif claimed_snapshot_hash != _canonical_payload_hash({
        key: value for key, value in snapshot.items() if key != "source_snapshot_hash"
    }):
        missing.append("source_snapshot_hash_mismatch")
    if snapshot.get("building_type") != str(context.get("building_type") or "building mass"):
        missing.append("source_program_mismatch")
    if not graph_status["available"]:
        missing.append("neo4j_unavailable")
    elif not article_ids:
        missing.append("neo4j_articles_unresolved")
    if not law_search["available"]:
        missing.append("law_search_unavailable")
    elif not search_result_ids:
        missing.append("law_search_results_empty")
    if identity.pnu == "PNU_UNRESOLVED":
        missing.append("pnu_unresolved")
    if (
        not identity.floor_capacity_plan_hash
        or "UNRESOLVED" in identity.floor_capacity_plan_hash.upper()
    ):
        missing.append("floor_capacity_plan_hash_unresolved")
    # A numeric verdict that never ran is not a numeric verdict that passed.
    # Without this the agent reports "passed" on an empty preflight and the
    # selector, which reads only statuses, turns it into an acceptance.
    numeric_status = numeric_verdict_status(law)
    if numeric_status == "needs_evidence":
        missing.append("numeric_law_unevaluated")

    if numeric_status == "failed":
        status = "failed"
    elif missing:
        status = "needs_evidence"
    else:
        status = "passed"

    result = AgentEvidence(
        evidence_id="evidence:law_graph_agent",
        agent="law_graph_agent",
        status=status,
        summary=(
            "supplied numeric preflight passed; source evidence bound to this mass"
            if status == "passed"
            else f"legal evidence incomplete: {', '.join(missing) or 'numeric hard gate failed'}"
        ),
        identity=identity,
        evidence={
            "pnu": identity.pnu,
            "numeric_preflight": law,
            "assessment_scope": "supplied_numeric_preflight",
            "permit_compliance_verified": False,
            "neo4j": graph_status,
            "law_search": law_search,
            "articles": deepcopy(list(snapshot.get("articles") or ())),
            "search_results": deepcopy(
                list(snapshot.get("search_results") or ())
            ),
            "article_ids": article_ids,
            "search_result_ids": search_result_ids,
            "source_snapshot_hash": str(
                snapshot.get("source_snapshot_hash") or ""
            ),
            "missing_evidence": missing,
        },
    )
    if result.status == "passed":
        # The same contract applies before selection and after persistence.
        issues = validate_persisted_law_agent_evidence(
            result.to_dict(), canonical_agent_evidence_hash(result), expected_identity=identity,
        )
        if issues:
            result = replace(result, status="needs_evidence",
                summary="legal evidence incomplete: " + ", ".join(issues),
                evidence={**result.evidence, "missing_evidence": list(issues)})
    return result


def canonical_agent_evidence_hash(
    payload: AgentEvidence | Mapping[str, Any],
) -> str:
    """Hash the complete persisted AgentEvidence payload, including identity."""

    serialized = payload.to_dict() if isinstance(payload, AgentEvidence) else dict(payload)
    return _canonical_payload_hash(serialized)


def validate_persisted_law_agent_evidence(
    payload: Mapping[str, Any] | None,
    claimed_hash: str,
    *,
    expected_identity: ExecutionIdentity,
) -> tuple[str, ...]:
    """Validate persisted bytes and exact accepted identity continuity."""

    persisted = dict(payload) if isinstance(payload, Mapping) else {}
    issues: list[str] = []
    if not persisted:
        return ("law_agent_payload_missing",)
    if not str(claimed_hash or "").strip():
        issues.append("law_agent_payload_hash_missing")
    elif canonical_agent_evidence_hash(persisted) != str(claimed_hash):
        issues.append("law_agent_payload_hash_mismatch")
    if str(persisted.get("agent") or "") != "law_graph_agent":
        issues.append("law_agent_type_mismatch")
    if str(persisted.get("status") or "") != "passed":
        issues.append(
            f"law_agent_status_not_passed:{persisted.get('status') or 'missing'}"
        )
    identity = persisted.get("identity")
    identity = dict(identity) if isinstance(identity, Mapping) else {}
    expected = expected_identity.to_dict()
    for key, expected_value in expected.items():
        actual = str(identity.get(key) or "").strip()
        if not actual or "UNRESOLVED" in actual.upper():
            issues.append(f"law_agent_identity_unresolved:{key}")
        if actual != str(expected_value):
            issues.append(f"law_agent_identity_mismatch:{key}")
    evidence = persisted.get("evidence")
    evidence = dict(evidence) if isinstance(evidence, Mapping) else {}
    if str(evidence.get("pnu") or "") != str(identity.get("pnu") or ""):
        issues.append("law_agent_evidence_pnu_mismatch")
    numeric_preflight = evidence.get("numeric_preflight")
    numeric_preflight = (
        dict(numeric_preflight)
        if isinstance(numeric_preflight, Mapping)
        else {}
    )
    if numeric_verdict_status(numeric_preflight) != "passed":
        issues.append("law_agent_numeric_preflight_not_passed")
    neo4j = evidence.get("neo4j")
    neo4j = dict(neo4j) if isinstance(neo4j, Mapping) else {}
    if (
        neo4j.get("attempted") is not True
        or neo4j.get("available") is not True
    ):
        issues.append("law_agent_neo4j_unavailable")
    law_search = evidence.get("law_search")
    law_search = (
        dict(law_search)
        if isinstance(law_search, Mapping)
        else {}
    )
    if (
        law_search.get("attempted") is not True
        or law_search.get("available") is not True
    ):
        issues.append("law_agent_search_unavailable")
    if not [
        value
        for value in evidence.get("article_ids") or ()
        if str(value or "").strip()
    ]:
        issues.append("law_agent_article_ids_missing")
    if not [
        value
        for value in evidence.get("search_result_ids") or ()
        if str(value or "").strip()
    ]:
        issues.append("law_agent_search_result_ids_missing")
    missing_evidence = evidence.get("missing_evidence")
    if (
        not isinstance(missing_evidence, list)
        or bool(missing_evidence)
    ):
        issues.append("law_agent_missing_evidence_not_empty")
    return tuple(dict.fromkeys(issues))


def _canonical_payload_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _bounded_law_domain_search(query: str, limit: int) -> Mapping[str, Any]:
    """Use one explicitly configured Editor law search within the evidence budget."""
    from backend.app.modules.land.reference import config
    from backend.app.modules.land.reference.services.law_enricher import search_queries

    configured = bool(config.LAW_BACKEND_URL or config.AG_LIGHT_URL)
    result = search_queries([query], limit=max(1, min(3, int(limit))),
                            timeout=LAW_SEARCH_TIMEOUT_SECONDS, filter_results=False)
    errors = result['errors']
    response = {
        'attempted': configured,
        'available': configured and not errors,
        'source': 'editor-law-search',
        'query': query,
        'results': [record for article in result['articles'] for record in article['results']],
    }
    if errors:
        response['errors'] = list(errors)
        response['error_category'] = ('law_service_not_configured' if not configured else
            'law_service_timeout' if any('deadline exceeded' in error for error in errors) else
            'law_service_unavailable')
    return response


def _error_category(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "law_service_connect_timeout"
    if isinstance(exc, httpx.ConnectError):
        return "law_service_unavailable"
    if isinstance(exc, httpx.TimeoutException):
        return "law_service_timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "law_service_http_error"
    return "law_service_error"


def _fast_graph_projection() -> Mapping[str, Any]:
    """Avoid paying a driver routing timeout when the configured port is down."""

    if "test" in sys.argv:
        return build_law_provenance_projection()
    from backend.app.core.graph_config import neo4j_configured, neo4j_uri

    if not neo4j_configured():
        return build_law_provenance_projection()
    uri = neo4j_uri()
    parsed = urlparse(uri)
    host = parsed.hostname
    port = parsed.port or 7687
    if host:
        try:
            with socket.create_connection((host, port), timeout=0.6):
                pass
        except OSError:
            return {
                "graph_status": {
                    "attempted": True,
                    "available": False,
                    "uri": uri,
                    "error": "neo4j_tcp_preflight_failed",
                },
                "articles": [],
                "refs_by_check": {},
                "provenance_entities": [],
                "provenance_relations": [],
            }
    return build_law_provenance_projection()


__all__ = [
    "bind_law_agent_evidence",
    "canonical_agent_evidence_hash",
    "collect_law_agent_evidence",
    "collect_law_agent_evidence_batch",
    "collect_law_source_snapshot",
    "validate_persisted_law_agent_evidence",
]

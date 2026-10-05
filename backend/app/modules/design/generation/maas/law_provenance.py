"""Neo4j law-reference projection for MAAS evidence bundles.

This module enriches evidence with legal article references only. It must not
change compliance status or invent pass/fail conclusions.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

logger = logging.getLogger(__name__)


CHECK_ARTICLE_SEEDS: dict[str, list[str]] = {
    "bulk_and_density.bcr": ["국토의 계획 및 이용에 관한 법률_제77조"],
    "bulk_and_density.far": ["국토의 계획 및 이용에 관한 법률_제78조"],
    "bulk_and_density.height": ["건축법_제60조"],
    "building_line_and_setbacks.adjacent_setback": ["건축법_제58조"],
    "zoning_and_land_use.allowed_by_zone": ["국토의 계획 및 이용에 관한 법률_제76조"],
    "parking_loading_and_mobility.parking_required_count": ["주차장법_제19조"],
}


def _split_vectorize_id(vec_id: str) -> tuple[str, str] | None:
    parts = vec_id.split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _query_article(neo4j: Any, vec_id: str) -> dict[str, Any] | None:
    parsed = _split_vectorize_id(vec_id)
    if parsed is None:
        return None
    law_name, jo_number = parsed
    jo_num_bare = re.sub(r"^제", "", jo_number)
    suffix = "::" + jo_number
    rows = neo4j.execute_query(
        """
        MATCH (j:JO)
        WHERE j.law_name = $law
          AND (j.number = $num1 OR j.number = $num2 OR j.full_id ENDS WITH $suffix)
        RETURN j.full_id AS full_id,
               j.number AS number,
               j.title AS title,
               j.content AS content,
               j.law_name AS law_name,
               j.unit_path AS unit_path
        ORDER BY CASE
            WHEN j.full_id CONTAINS '(법률)' THEN 0
            WHEN j.full_id CONTAINS '(시행령)' THEN 1
            ELSE 2
        END
        LIMIT 1
        """,
        {"law": law_name, "num1": jo_number, "num2": jo_num_bare, "suffix": suffix},
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "ref_id": vec_id,
        "full_id": row.get("full_id"),
        "law_name": row.get("law_name") or law_name,
        "number": row.get("number"),
        "title": row.get("title"),
        "content": row.get("content"),
        "unit_path": row.get("unit_path"),
        "source": "neo4j",
    }


def build_law_provenance_projection() -> dict[str, Any]:
    """Resolve static MAAS check seeds to Neo4j article references.

    Returns a projection payload that can be merged into the evidence bundle.
    Failures are non-fatal and reported as graph_status only.
    """
    if "test" in sys.argv and os.environ.get("MAAS_EVIDENCE_ENABLE_LAW_GRAPH") != "1":
        return {
            "graph_status": {"available": False, "error": "law graph projection disabled during tests"},
            "articles": [],
            "refs_by_check": {},
            "provenance_entities": [],
            "provenance_relations": [],
        }
    if not os.environ.get("NEO4J_URI"):
        return {
            "graph_status": {"available": False, "error": "NEO4J_URI not configured"},
            "articles": [],
            "refs_by_check": {},
            "provenance_entities": [],
            "provenance_relations": [],
        }
    try:
        from backend.app.adapters.design_storage.neo4j_service import Neo4jService
    except Exception as exc:
        return {
            "graph_status": {"available": False, "error": f"neo4j driver unavailable: {exc}"},
            "articles": [],
            "refs_by_check": {},
            "provenance_entities": [],
            "provenance_relations": [],
        }

    neo4j = Neo4jService()
    try:
        if not neo4j.connect():
            return {
                "graph_status": {"available": False, "uri": neo4j.uri, "error": "connect returned false"},
                "articles": [],
                "refs_by_check": {},
                "provenance_entities": [],
                "provenance_relations": [],
            }
        articles_by_ref: dict[str, dict[str, Any]] = {}
        refs_by_check: dict[str, list[str]] = {}
        for check_key, seeds in CHECK_ARTICLE_SEEDS.items():
            for seed in seeds:
                article = _query_article(neo4j, seed)
                if article is None or not article.get("full_id"):
                    continue
                article_ref = f"law:{article['full_id']}"
                articles_by_ref[article_ref] = article
                refs_by_check.setdefault(check_key, []).append(article_ref)

        provenance_entities = [
            {
                "id": ref,
                "type": "LawArticle",
                "full_id": article.get("full_id"),
                "law_name": article.get("law_name"),
                "number": article.get("number"),
                "title": article.get("title"),
                "source": "neo4j",
            }
            for ref, article in articles_by_ref.items()
        ]
        provenance_relations = [
            {"type": "wasDerivedFrom", "entity": ref, "source": "neo4j:law_graph"}
            for ref in articles_by_ref
        ]
        return {
            "graph_status": {
                "available": True,
                "uri": neo4j.uri,
                "resolved_count": len(articles_by_ref),
                "missing_count": sum(len(v) for v in CHECK_ARTICLE_SEEDS.values()) - len(articles_by_ref),
            },
            "articles": list(articles_by_ref.values()),
            "refs_by_check": refs_by_check,
            "provenance_entities": provenance_entities,
            "provenance_relations": provenance_relations,
        }
    except Exception as exc:
        logger.warning("MAAS law provenance projection failed: %s", exc)
        return {
            "graph_status": {"available": False, "uri": getattr(neo4j, "uri", None), "error": str(exc)},
            "articles": [],
            "refs_by_check": {},
            "provenance_entities": [],
            "provenance_relations": [],
        }
    finally:
        neo4j.disconnect()


__all__ = ["CHECK_ARTICLE_SEEDS", "build_law_provenance_projection"]

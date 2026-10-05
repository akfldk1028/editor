"""Neo4j mirror for portable MAAS design-memory outcome graphs."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from backend.app.adapters.design_storage.neo4j_service import Neo4jService

from backend.app.modules.design.generation.maas.design_memory.config import DesignMemorySettings


_NODE_QUERY = """
UNWIND $nodes AS node
MERGE (n:MaasDesignNode {id: node.id})
SET n.kind = node.kind,
    n.identity = node.identity,
    n.payload_json = node.payload_json
""".strip()

_EDGE_QUERY = """
UNWIND $edges AS edge
MATCH (source:MaasDesignNode {id: edge.source})
MATCH (target:MaasDesignNode {id: edge.target})
MERGE (source)-[relation:MAAS_DESIGN_RELATION {id: edge.id}]->(target)
SET relation.kind = edge.kind,
    relation.payload_json = edge.payload_json
""".strip()


class DesignMemoryNeo4jAdapter:
    def __init__(
        self,
        *,
        settings: DesignMemorySettings | None = None,
        service_factory: Callable[..., Any] = Neo4jService,
    ) -> None:
        self.settings = settings or DesignMemorySettings.from_environment()
        self._service_factory = service_factory

    def mirror(self, graph: Any) -> dict[str, Any]:
        if not self.settings.enabled:
            return {
                "status": "disabled",
                "reason": self.settings.reason,
                "portable_graph_available": True,
            }

        service = None
        try:
            nodes, edges = _portable_records(graph)
            service = self._service_factory(
                uri=self.settings.uri,
                user=self.settings.user,
                password=self.settings.password,
                database=self.settings.database,
            )
            if not service.connect():
                return {
                    "status": "unavailable",
                    "reason": "connect_returned_false",
                    "portable_graph_available": True,
                }
            service.execute_write_query(
                _NODE_QUERY,
                parameters={"nodes": nodes},
            )
            service.execute_write_query(
                _EDGE_QUERY,
                parameters={"edges": edges},
            )
            return {
                "status": "mirrored",
                "node_count": len(nodes),
                "edge_count": len(edges),
                "database": self.settings.database,
                "portable_graph_available": True,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason": str(exc),
                "portable_graph_available": True,
            }
        finally:
            if service is not None:
                try:
                    service.disconnect()
                except Exception:
                    pass


def _portable_records(
    graph: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = graph.to_dict() if hasattr(graph, "to_dict") else graph
    if not isinstance(payload, Mapping):
        raise TypeError("design-memory graph must be a portable mapping")

    nodes = [
        {
            "id": str(node.get("id") or ""),
            "kind": str(node.get("kind") or ""),
            "identity": str(node.get("identity") or ""),
            "payload_json": json.dumps(
                node.get("attributes") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for node in payload.get("nodes") or ()
        if isinstance(node, Mapping) and node.get("id")
    ]
    edges = [
        {
            "id": str(edge.get("id") or ""),
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "kind": str(edge.get("kind") or ""),
            "payload_json": json.dumps(
                edge.get("attributes") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for edge in payload.get("edges") or ()
        if (
            isinstance(edge, Mapping)
            and edge.get("id")
            and edge.get("source")
            and edge.get("target")
        )
    ]
    return nodes, edges


__all__ = ["DesignMemoryNeo4jAdapter"]

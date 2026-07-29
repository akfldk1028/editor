from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import math

from backend.app.schemas.program import ProgramEdge, ProgramGraph

_RELATIONS = frozenset({"functional_adjacency", "service_adjacent"})


class TopologyContractError(ValueError):
    pass


@dataclass(frozen=True)
class TopologyAdjacency:
    source: str
    target: str
    relation: str
    weight: float


@dataclass(frozen=True)
class TopologyProposal:
    candidate_id: str
    sequence: tuple[str, ...]
    adjacencies: tuple[TopologyAdjacency, ...]


def parse_topology_proposals_json(
    payload: str,
    *,
    allowed_node_ids: tuple[str, ...],
    expected_count: int,
) -> tuple[TopologyProposal, ...]:
    try:
        document = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as error:
        raise TopologyContractError("model output must be valid JSON") from error
    if not isinstance(document, dict) or set(document) != {"candidates"}:
        raise TopologyContractError("model output must contain only candidates")
    candidates = document["candidates"]
    if not isinstance(candidates, list) or len(candidates) != expected_count:
        raise TopologyContractError(
            f"model output must contain exactly {expected_count} candidates"
        )
    if len(set(allowed_node_ids)) != len(allowed_node_ids) or not allowed_node_ids:
        raise ValueError("allowed_node_ids must be non-empty and unique")
    allowed = set(allowed_node_ids)
    proposals: list[TopologyProposal] = []
    seen_sequences: set[tuple[str, ...]] = set()
    for index, value in enumerate(candidates, start=1):
        label = f"candidates[{index - 1}]"
        if not isinstance(value, dict) or set(value) != {
            "candidate_id",
            "sequence",
            "adjacencies",
        }:
            raise TopologyContractError(f"{label} has invalid fields")
        candidate_id = value["candidate_id"]
        if candidate_id != f"topology-{index}":
            raise TopologyContractError(
                f"{label}.candidate_id must be topology-{index}"
            )
        sequence = value["sequence"]
        if (
            not isinstance(sequence, list)
            or len(sequence) != len(allowed_node_ids)
            or any(not isinstance(item, str) for item in sequence)
            or set(sequence) != allowed
        ):
            raise TopologyContractError(
                f"{label}.sequence must be an exact permutation of allowed node ids"
            )
        adjacencies = _parse_adjacencies(
            value["adjacencies"],
            allowed,
            label,
        )
        sequence_key = tuple(sequence)
        if sequence_key in seen_sequences:
            raise TopologyContractError(
                "topology candidate sequences must be distinct"
            )
        seen_sequences.add(sequence_key)
        proposals.append(
            TopologyProposal(
                candidate_id=candidate_id,
                sequence=tuple(sequence),
                adjacencies=adjacencies,
            )
        )
    return tuple(proposals)


def _parse_adjacencies(
    value: object,
    allowed: set[str],
    label: str,
) -> tuple[TopologyAdjacency, ...]:
    if not isinstance(value, list) or not value:
        raise TopologyContractError(f"{label}.adjacencies must not be empty")
    result: list[TopologyAdjacency] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(value):
        edge_label = f"{label}.adjacencies[{index}]"
        if not isinstance(item, dict) or set(item) != {
            "source",
            "target",
            "relation",
            "weight",
        }:
            raise TopologyContractError(f"{edge_label} has invalid fields")
        source = item["source"]
        target = item["target"]
        relation = item["relation"]
        weight = item["weight"]
        if source not in allowed or target not in allowed or source == target:
            raise TopologyContractError(f"{edge_label} has invalid endpoints")
        if relation not in _RELATIONS:
            raise TopologyContractError(f"{edge_label} has invalid relation")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or not 0 < weight <= 1
        ):
            raise TopologyContractError(
                f"{edge_label}.weight must be finite and in (0, 1]"
            )
        key = (min(source, target), max(source, target), relation)
        if key in seen:
            raise TopologyContractError(f"{edge_label} duplicates an adjacency")
        seen.add(key)
        result.append(
            TopologyAdjacency(
                source=source,
                target=target,
                relation=relation,
                weight=float(weight),
            )
        )
    return tuple(result)


def apply_topology_proposals(
    program: ProgramGraph,
    proposals: tuple[TopologyProposal, ...],
) -> tuple[ProgramGraph, ...]:
    nodes = {node.node_id: node for node in program.nodes}
    variants: list[ProgramGraph] = []
    for proposal in proposals:
        if set(proposal.sequence) != set(nodes):
            raise TopologyContractError(
                "proposal sequence does not match program nodes"
            )
        edges = list(program.edges)
        seen = {
            (min(edge.source, edge.target), max(edge.source, edge.target), edge.relation)
            for edge in edges
        }
        for adjacency in proposal.adjacencies:
            key = (
                min(adjacency.source, adjacency.target),
                max(adjacency.source, adjacency.target),
                adjacency.relation,
            )
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                ProgramEdge(
                    source=adjacency.source,
                    target=adjacency.target,
                    relation=adjacency.relation,
                    weight=adjacency.weight,
                )
            )
        variants.append(
            replace(
                program,
                nodes=[nodes[node_id] for node_id in proposal.sequence],
                edges=edges,
                source=f"local_qwen_topology:{proposal.candidate_id}",
            )
        )
    return tuple(variants)


def dump_topology_proposals_json(
    proposals: tuple[TopologyProposal, ...],
) -> str:
    return json.dumps(
        {"candidates": [asdict(proposal) for proposal in proposals]},
        ensure_ascii=False,
        separators=(",", ":"),
    )

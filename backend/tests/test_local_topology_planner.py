import json
import sys

import pytest

from backend.app.modules.local_topology_planner.contracts import (
    TopologyContractError,
    apply_topology_proposals,
    parse_topology_proposals_json,
)
from backend.app.modules.local_topology_planner.service import (
    LocalTopologyPlannerClient,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import MassInput


def _program():
    mass = MassInput(
        project_id="local-topology",
        floors=1,
        footprint_polygon=[(0, 0), (25, 0), (25, 20), (0, 20)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    return generate_program_graph(analyze_mass(mass), 1, "office")


def _payload():
    node_ids = [node.node_id for node in _program().nodes]
    return {
        "candidates": [
            {
                "candidate_id": "topology-1",
                "sequence": list(reversed(node_ids)),
                "adjacencies": [
                    {
                        "source": "reception",
                        "target": "open_work",
                        "relation": "functional_adjacency",
                        "weight": 0.8,
                    }
                ],
            },
            {
                "candidate_id": "topology-2",
                "sequence": node_ids,
                "adjacencies": [
                    {
                        "source": "core",
                        "target": "pantry",
                        "relation": "service_adjacent",
                        "weight": 1.0,
                    }
                ],
            },
        ]
    }


def test_parse_topology_proposals_requires_exact_node_permutation():
    payload = _payload()
    payload["candidates"][0]["sequence"].pop()

    with pytest.raises(TopologyContractError, match="exact permutation"):
        parse_topology_proposals_json(
            json.dumps(payload),
            allowed_node_ids=tuple(node.node_id for node in _program().nodes),
            expected_count=2,
        )


def test_parse_topology_proposals_wraps_unhashable_sequence_item():
    payload = _payload()
    payload["candidates"][0]["sequence"][0] = {}

    with pytest.raises(TopologyContractError, match="exact permutation"):
        parse_topology_proposals_json(
            json.dumps(payload),
            allowed_node_ids=tuple(node.node_id for node in _program().nodes),
            expected_count=2,
        )


def test_parse_topology_proposals_requires_distinct_sequences():
    payload = _payload()
    payload["candidates"][1]["sequence"] = payload["candidates"][0]["sequence"]

    with pytest.raises(TopologyContractError, match="sequences must be distinct"):
        parse_topology_proposals_json(
            json.dumps(payload),
            allowed_node_ids=tuple(node.node_id for node in _program().nodes),
            expected_count=2,
        )


def test_apply_topology_proposals_reorders_nodes_and_preserves_prior_edges():
    program = _program()
    proposals = parse_topology_proposals_json(
        json.dumps(_payload()),
        allowed_node_ids=tuple(node.node_id for node in program.nodes),
        expected_count=2,
    )

    variants = apply_topology_proposals(program, proposals)

    assert [node.node_id for node in variants[0].nodes] == list(
        reversed([node.node_id for node in program.nodes])
    )
    assert set(program.edges).issubset(set(variants[0].edges))
    assert any(
        edge.source == "reception"
        and edge.target == "open_work"
        and edge.relation == "functional_adjacency"
        for edge in variants[0].edges
    )
    assert variants[0].source == "local_qwen_topology:topology-1"


def test_local_topology_client_uses_json_subprocess_contract(tmp_path):
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps(_payload()), encoding="utf-8")
    script = (
        "import pathlib,sys;"
        "sys.stdin.read();"
        "sys.stdout.write(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))"
    )
    client = LocalTopologyPlannerClient(
        command=(sys.executable, "-c", script, str(response_path)),
        timeout_seconds=5,
    )

    proposals = client.propose(_program(), candidate_count=2)

    assert [proposal.candidate_id for proposal in proposals] == [
        "topology-1",
        "topology-2",
    ]


def test_local_topology_client_rejects_malformed_model_output():
    client = LocalTopologyPlannerClient(
        command=(sys.executable, "-c", "print('not-json')"),
        timeout_seconds=5,
    )

    with pytest.raises(TopologyContractError, match="valid JSON"):
        client.propose(_program(), candidate_count=2)

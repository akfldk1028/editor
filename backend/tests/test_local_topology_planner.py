import json
import sys

import pytest

from backend.app.modules.local_topology_planner.contracts import (
    TopologyContractError,
    apply_topology_proposals,
    parse_topology_proposals_json,
    require_distinct_layout_sequences,
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


def test_topology_candidates_must_vary_order_inside_solver_role_group():
    payload = _payload()
    first = payload["candidates"][0]["sequence"]
    second = list(first)
    focus_index = second.index("focus")
    pantry_index = second.index("pantry")
    second[focus_index], second[pantry_index] = (
        second[pantry_index],
        second[focus_index],
    )
    payload["candidates"][1]["sequence"] = second
    proposals = parse_topology_proposals_json(
        json.dumps(payload),
        allowed_node_ids=tuple(node.node_id for node in _program().nodes),
        expected_count=2,
    )

    with pytest.raises(TopologyContractError, match="layout-relevant"):
        require_distinct_layout_sequences(
            proposals,
            layout_node_groups=(
                ("pantry", "restroom", "it_storage"),
                ("meeting", "reception", "focus"),
            ),
        )


@pytest.mark.parametrize("field", ["source", "target", "relation"])
def test_parse_topology_proposals_wraps_unhashable_adjacency_fields(field):
    payload = _payload()
    payload["candidates"][0]["adjacencies"][0][field] = {}

    with pytest.raises(TopologyContractError, match=f"invalid {field}"):
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
    request_path = tmp_path / "request.json"
    script = (
        "import pathlib,sys;"
        "request=sys.stdin.read();"
        "pathlib.Path(sys.argv[2]).write_text(request,encoding='utf-8');"
        "sys.stdout.write(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))"
    )
    client = LocalTopologyPlannerClient(
        command=(
            sys.executable,
            "-c",
            script,
            str(response_path),
            str(request_path),
        ),
        timeout_seconds=5,
    )

    program = _program()
    proposals = client.propose(
        program,
        candidate_count=2,
        boundary=((0, 0), (25, 0), (25, 20), (0, 20)),
        access_candidates=({"edge_index": 0, "position": 0.5},),
        street_edge_indices=(0,),
        street_segments=(((0, 0), (25, 0)),),
    )

    assert [proposal.candidate_id for proposal in proposals] == [
        "topology-1",
        "topology-2",
    ]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["boundary"] == [[0.0, 0.0], [25.0, 0.0], [25.0, 20.0], [0.0, 20.0]]
    assert request["access_candidates"] == [{"edge_index": 0, "position": 0.5}]
    assert request["street_edge_indices"] == [0]
    assert request["street_segments"] == [[[0.0, 0.0], [25.0, 0.0]]]
    assert request["schema_version"] == 1
    assert request["core"]["geometry_status"] == "unresolved_pre_generation"
    assert request["nodes"][0] == {
        "node_id": program.nodes[0].node_id,
        "space_type": program.nodes[0].space_type,
        "zone": program.nodes[0].zone,
        "target_area": program.nodes[0].target_area,
        "min_area": program.nodes[0].min_area,
        "max_area": program.nodes[0].max_area,
        "frontage_required": program.nodes[0].frontage_required,
        "min_width": program.nodes[0].min_width,
        "max_aspect_ratio": program.nodes[0].max_aspect_ratio,
        "tenant_id": program.nodes[0].tenant_id,
    }
    assert request["edges"] == [
        {
            "source": edge.source,
            "target": edge.target,
            "relation": edge.relation,
            "weight": edge.weight,
        }
        for edge in program.edges
    ]


def test_local_topology_client_rejects_malformed_model_output():
    client = LocalTopologyPlannerClient(
        command=(sys.executable, "-c", "print('not-json')"),
        timeout_seconds=5,
    )

    with pytest.raises(TopologyContractError, match="valid JSON"):
        client.propose(
            _program(),
            candidate_count=2,
            boundary=((0, 0), (25, 0), (25, 20), (0, 20)),
        )


def test_local_topology_client_rejects_malformed_boundary_before_worker():
    client = LocalTopologyPlannerClient(
        command=(sys.executable, "-c", "raise SystemExit(99)"),
        timeout_seconds=5,
    )

    with pytest.raises(ValueError, match="coordinate pairs"):
        client.propose(
            _program(),
            candidate_count=2,
            boundary=((0, 0), (25, 0, 1), (25, 20), (0, 20)),
        )

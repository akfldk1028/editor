from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import MassAnalysis


def test_generate_program_graph_for_ground_floor_commercial_office_mix():
    analysis = MassAnalysis(
        project_id="mixed",
        area=300,
        floor_area=1500,
        floors=5,
        edge_count=4,
        street_edge_indices=[0],
        access_edge_indices=[0],
        bounds=(0, 0, 30, 10),
    )

    graph = generate_program_graph(
        analysis,
        floor_index=1,
        use_type="neighborhood_commercial",
    )

    node_types = {node.space_type for node in graph.nodes}
    assert {"shop_unit", "core", "restroom", "storage", "utility"}.issubset(node_types)
    assert sum(node.target_area for node in graph.nodes) == 300
    assert any(edge.relation == "public_access" for edge in graph.edges)
    assert graph.source == "baseline_prior"


def test_generate_program_graph_for_typical_office_floor():
    analysis = MassAnalysis(
        project_id="office",
        area=400,
        floor_area=3200,
        floors=8,
        edge_count=4,
        street_edge_indices=[0],
        access_edge_indices=[0],
        bounds=(0, 0, 20, 20),
    )

    graph = generate_program_graph(analysis, floor_index=3, use_type="office")

    areas = {node.space_type: node.target_area for node in graph.nodes}
    node_ids = {node.node_id for node in graph.nodes}
    assert areas["office_area"] > areas["core"]
    assert sum(areas.values()) == 400
    assert any(edge.relation == "service_adjacent" for edge in graph.edges)
    assert all(
        edge.source in node_ids
        and (edge.target in node_ids or edge.target == "street")
        for edge in graph.edges
    )

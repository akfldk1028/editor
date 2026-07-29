import math

import pytest

from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import FloorPlateAnalysis, MassAnalysis


OFFICE_PROFILE = {
    "open_work": (0.52, 6.0, 2.5, "workplace"),
    "meeting": (0.10, 2.7, 2.0, "public"),
    "reception": (0.05, 2.4, 2.5, "public"),
    "focus": (0.06, 1.8, 1.8, "workplace"),
    "pantry": (0.03, 1.8, 2.0, "service"),
    "restroom": (0.05, 1.8, 2.5, "service"),
    "core": (0.14, 3.0, 2.0, "core"),
    "it_storage": (0.05, 1.5, 2.5, "service"),
}

COMMERCIAL_PROFILE = {
    "sales_a": (0.285, 4.0, 3.0, "frontage"),
    "sales_b": (0.285, 4.0, 3.0, "frontage"),
    "checkout": (0.04, 2.4, 3.0, "public"),
    "stock": (0.10, 2.4, 2.5, "service"),
    "staff": (0.05, 2.4, 2.0, "service"),
    "restroom": (0.05, 1.8, 2.5, "service"),
    "core": (0.12, 3.0, 2.0, "core"),
    "utility": (0.07, 1.5, 2.5, "service"),
}


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
    assert {"sales", "core", "restroom", "stock", "utility"}.issubset(node_types)
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
    assert areas["open_work"] > areas["core"]
    assert sum(areas.values()) == 400
    assert any(edge.relation == "service_adjacent" for edge in graph.edges)
    assert all(
        edge.source in node_ids and (edge.target in node_ids or edge.target == "street")
        for edge in graph.edges
    )


def test_tiny_positive_mass_preserves_positive_coherent_program_areas():
    analysis = MassAnalysis(
        project_id="tiny-positive-mass",
        area=0.01,
        floor_area=0.01,
        floors=1,
        edge_count=4,
        street_edge_indices=[0],
        access_edge_indices=[],
        bounds=(0, 0, 0.1, 0.1),
    )

    graph = generate_program_graph(
        analysis,
        floor_index=1,
        use_type="neighborhood_commercial",
    )

    assert math.isclose(sum(node.target_area for node in graph.nodes), analysis.area)
    for node in graph.nodes:
        assert math.isfinite(node.target_area)
        assert math.isfinite(node.min_area)
        assert math.isfinite(node.max_area)
        assert 0 < node.min_area < node.target_area < node.max_area


@pytest.mark.parametrize(
    ("use_type", "expected_profile", "frontage_required"),
    [
        ("office", OFFICE_PROFILE, set()),
        ("neighborhood_commercial", COMMERCIAL_PROFILE, {"sales_a", "sales_b"}),
    ],
)
def test_program_profiles_emit_exact_ratios_and_form_metadata(
    use_type,
    expected_profile,
    frontage_required,
):
    analysis = MassAnalysis(
        project_id="profile-metadata",
        area=1000,
        floor_area=1000,
        floors=1,
        edge_count=4,
        street_edge_indices=[0],
        access_edge_indices=[0],
        bounds=(0, 0, 40, 25),
    )

    graph = generate_program_graph(analysis, floor_index=1, use_type=use_type)

    assert {
        node.node_id: (
            node.target_area / analysis.area,
            node.min_width,
            node.max_aspect_ratio,
            node.zone,
        )
        for node in graph.nodes
    } == expected_profile
    assert {
        node.node_id for node in graph.nodes if node.frontage_required
    } == frontage_required
    assert sum(node.target_area for node in graph.nodes) == analysis.area
    assert all(node.min_area == node.target_area * 0.85 for node in graph.nodes)
    assert all(node.max_area == node.target_area * 1.15 for node in graph.nodes)


def test_generate_program_graph_uses_floor_specific_plate_area():
    analysis = MassAnalysis(
        project_id="stepped-office",
        area=600,
        floor_area=1200,
        floors=3,
        edge_count=4,
        street_edge_indices=[0],
        access_edge_indices=[],
        bounds=(0, 0, 30, 20),
        floor_plates=(
            FloorPlateAnalysis(
                1,
                600,
                4,
                (0, 0, 30, 20),
                ((0, 0), (30, 0), (30, 20), (0, 20)),
                "explicit_floor_footprint",
            ),
            FloorPlateAnalysis(
                2,
                384,
                4,
                (0, 0, 24, 16),
                ((0, 0), (24, 0), (24, 16), (0, 16)),
                "explicit_floor_footprint",
            ),
            FloorPlateAnalysis(
                3,
                216,
                4,
                (0, 0, 18, 12),
                ((0, 0), (18, 0), (18, 12), (0, 12)),
                "explicit_floor_footprint",
            ),
        ),
    )

    graph = generate_program_graph(analysis, floor_index=2, use_type="office")

    assert sum(float(node.target_area) for node in graph.nodes) == 384


@pytest.mark.parametrize(
    ("use_type", "expected_edges"),
    [
        (
            "office",
            {
                ("reception", "meeting"),
                ("open_work", "focus"),
                ("open_work", "meeting"),
                ("core", "restroom"),
                ("core", "it_storage"),
                ("pantry", "open_work"),
            },
        ),
        (
            "neighborhood_commercial",
            {
                ("sales_a", "street"),
                ("sales_b", "street"),
                ("checkout", "sales_a"),
                ("checkout", "sales_b"),
                ("stock", "sales_a"),
                ("stock", "sales_b"),
                ("staff", "stock"),
                ("core", "restroom"),
                ("core", "utility"),
            },
        ),
    ],
)
def test_program_profiles_emit_exact_functional_relationships(use_type, expected_edges):
    analysis = MassAnalysis(
        project_id="profile-relationships",
        area=300,
        floor_area=300,
        floors=1,
        edge_count=4,
        street_edge_indices=[0],
        access_edge_indices=[0],
        bounds=(0, 0, 30, 10),
    )

    graph = generate_program_graph(analysis, floor_index=1, use_type=use_type)

    assert {(edge.source, edge.target) for edge in graph.edges} == expected_edges

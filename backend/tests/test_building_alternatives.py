import pytest

from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.schemas.mass import MassInput


@pytest.mark.parametrize("width,depth", [(20, 12), (30, 12), (30, 20)])
def test_building_alternatives_are_distinct_ranked_and_mostly_accepted(width, depth):
    mass = MassInput(
        project_id=f"alternatives-{width}x{depth}",
        floors=3,
        footprint_polygon=[(0, 0), (width, 0), (width, depth), (0, depth)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1 / 3, "office": 2 / 3},
    )

    result = run_building_alternatives(mass)

    assert len(result.alternatives) == 3
    assert sum(alternative.accepted for alternative in result.alternatives) >= 2
    assert [alternative.rank for alternative in result.alternatives] == [1, 2, 3]
    assert [alternative.score for alternative in result.alternatives] == sorted(
        (alternative.score for alternative in result.alternatives),
        reverse=True,
    )
    assert len(
        {
            tuple(layout_fingerprint(floor.layout) for floor in alternative.floor_results)
            for alternative in result.alternatives
        }
    ) == 3
    assert len({alternative.strategy for alternative in result.alternatives}) == 3
    assert len(result.comparisons) == 3
    assert all(comparison.semantic_distinct for comparison in result.comparisons)
    assert len({alternative.core_centroid for alternative in result.alternatives}) == 3
    assert all(alternative.circulation_graph_signature for alternative in result.alternatives)
    assert all(
        alternative.building.vertical_core_aligned
        and alternative.building.vertical_basic_design_aligned
        and alternative.building.vertical_structure_aligned
        for alternative in result.alternatives
    )

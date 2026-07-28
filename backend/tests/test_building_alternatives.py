import pytest

from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramAdjustment


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "reason": "",
            "original_targets": (("sales", 10.0),),
            "adjusted_targets": (("sales", 9.0),),
        },
        {
            "reason": "fit",
            "original_targets": (("sales", float("nan")),),
            "adjusted_targets": (("sales", 9.0),),
        },
        {
            "reason": "fit",
            "original_targets": (("sales", 10.0),),
            "adjusted_targets": (("office", 9.0),),
        },
        {
            "reason": "fit",
            "original_targets": (("sales", 10.0), ("sales", 9.0)),
            "adjusted_targets": (("sales", 8.0),),
        },
    ],
)
def test_program_adjustment_rejects_invalid_audit_evidence(kwargs):
    with pytest.raises(ValueError):
        ProgramAdjustment(**kwargs)


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
    assert [alternative.accepted for alternative in result.alternatives] == sorted(
        (alternative.accepted for alternative in result.alternatives),
        reverse=True,
    )
    for accepted in (True, False):
        scores = [
            alternative.score
            for alternative in result.alternatives
            if alternative.accepted is accepted
        ]
        assert scores == sorted(scores, reverse=True)
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
    by_id = {
        alternative.alternative_id: alternative
        for alternative in result.alternatives
    }
    min_x, min_y, max_x, max_y = result.mass.bounds
    normalized = {
        alternative_id: (
            (alternative.core_centroid[0] - min_x) / (max_x - min_x),
            (alternative.core_centroid[1] - min_y) / (max_y - min_y),
        )
        for alternative_id, alternative in by_id.items()
    }
    assert normalized["alternative-a"][0] > 0.65
    assert normalized["alternative-a"][1] > 0.65
    assert 0.35 < normalized["alternative-b"][0] < 0.65
    assert normalized["alternative-b"][1] > 0.65
    assert normalized["alternative-c"][0] > 0.65
    assert 0.35 < normalized["alternative-c"][1] < 0.65
    assert all("front" not in alternative.strategy for alternative in result.alternatives)
    assert all(
        alternative.tenant_count == 2
        and len(alternative.tenant_entrance_assignments) == 2
        and alternative.core_public_entrance
        for alternative in result.alternatives
    )
    for alternative in result.alternatives:
        footprints = {
            floor.layout.remote_stair_footprint
            for floor in alternative.floor_results
        }
        assert len(footprints) == 1
        assert None not in footprints
        assert all(floor.program.adjustments for floor in alternative.floor_results)

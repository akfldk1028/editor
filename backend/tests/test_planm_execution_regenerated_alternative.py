"""The loop's winner becomes a stage alternative that review and deliver can consume."""

from backend.app.modules.generation_loop.regeneration import regenerate
from backend.app.modules.generation_loop.repair import RuleRepairProposer
from backend.app.modules.planm_execution.service import (
    REGENERATED_ALTERNATIVE_ID,
    regenerated_alternative_record,
)
from backend.tests.test_generation_loop import _long_edge_fixture_inputs


def test_the_regenerated_building_is_rendered_and_recorded_like_an_alternative(tmp_path):
    mass, assignments, programs, core, circulation = _long_edge_fixture_inputs()
    outcome = regenerate(
        mass,
        proposer=RuleRepairProposer(),
        max_rounds=1,
        floor_assignments=assignments,
        baseline_programs_override=programs,
        layout_strategy="topology",
        core_override=core,
        circulation_overrides=circulation,
    )

    record, artifacts, fingerprint = regenerated_alternative_record(mass, outcome, tmp_path)

    assert record["alternative_id"] == REGENERATED_ALTERNATIVE_ID
    assert record["strategy"] == "regenerated:topology"
    assert record["regeneration_score"]["relaxations"] == 0
    assert len(record["preview_pngs"]) == len(outcome.building.floor_results)
    assert (tmp_path / record["report_path"]).exists()
    assert all((tmp_path / png).exists() for png in record["preview_pngs"])
    assert record["accepted"] == (
        outcome.score.accepted and record["internal_validation"] == "pass"
    )
    assert any(item["path"] == record["report_path"] for item in artifacts)
    assert len(fingerprint) == 64

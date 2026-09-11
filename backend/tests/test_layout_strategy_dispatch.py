"""run_building_generation dispatches on layout_strategy; topology carries no relaxations."""

import pytest

from backend.app.modules.generation_loop.service import run_building_generation
from backend.engine.geometry.polygon import polygon_area
from backend.tests.test_generation_loop import _long_edge_fixture_inputs


def _inputs():
    mass, assignments, programs, core, circulation = _long_edge_fixture_inputs()
    return mass, dict(floor_assignments=assignments, program_overrides=programs,
                      core_override=core, circulation_overrides=circulation)


def test_unknown_strategy_is_rejected_before_any_work():
    mass, kwargs = _inputs()

    with pytest.raises(ValueError, match="unknown layout strategy"):
        run_building_generation(mass, **kwargs, layout_strategy="diffusion")


def test_the_default_strategy_is_orthogonal_and_unchanged():
    mass, kwargs = _inputs()

    explicit = run_building_generation(mass, **kwargs, layout_strategy="orthogonal")
    implicit = run_building_generation(mass, **kwargs)

    assert explicit == implicit


def test_topology_strategy_produces_no_relaxations_on_the_sample_office():
    mass, kwargs = _inputs()

    building = run_building_generation(mass, **kwargs, layout_strategy="topology")

    for floor in building.floor_results:
        assert floor.program.form_relaxations == (), floor.program.floor_index
        assert floor.layout.candidate_id.endswith("-topology")


def test_topology_strategy_keeps_the_restroom_inside_its_band_on_every_floor():
    mass, kwargs = _inputs()

    building = run_building_generation(mass, **kwargs, layout_strategy="topology")

    for floor in building.floor_results:
        node = next(n for n in kwargs["program_overrides"][floor.program.floor_index].nodes if n.node_id == "restroom")
        got = polygon_area(next(r.polygon for r in floor.layout.rooms if r.room_id == "restroom"))
        assert float(node.min_area) - 1e-6 <= got <= float(node.max_area) + 1e-6, floor.program.floor_index


def test_topology_strategy_stacks_the_remote_stair_on_every_floor():
    """A stair is vertical: every floor takes the same remote stair box."""
    mass, kwargs = _inputs()

    building = run_building_generation(mass, **kwargs, layout_strategy="topology")

    footprints = {
        tuple(floor.layout.remote_stair_footprint) for floor in building.floor_results
    }
    assert len(footprints) == 1
    assert building.vertical_basic_design_aligned

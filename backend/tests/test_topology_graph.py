"""Topology first: which rooms must touch which, before any coordinates.

Spanning circulation (Shiksha et al. 2025) means every room opens directly
onto the corridor.  service_adjacent program edges are hard; functional ones
are soft.
"""

from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.topology_planner.graph import CORRIDOR, build_adjacency_graph
from backend.app.schemas.mass import MassAnalysis


def _office():
    analysis = MassAnalysis(project_id="t", area=900, floor_area=900, floors=1,
                            edge_count=4, street_edge_indices=[0], access_edge_indices=[0],
                            bounds=(0, 0, 37, 26))
    return generate_program_graph(analysis, floor_index=1, use_type="office")


def test_every_room_must_touch_the_corridor():
    graph = build_adjacency_graph(_office())

    for room in graph.nodes:
        if room == CORRIDOR:
            continue
        assert frozenset({room, CORRIDOR}) in graph.required, room


def test_the_restroom_touches_the_core():
    graph = build_adjacency_graph(_office())

    assert frozenset({"restroom", "core"}) in graph.required


def test_functional_adjacency_is_soft():
    graph = build_adjacency_graph(_office())

    assert frozenset({"open_work", "meeting"}) in graph.soft
    assert frozenset({"open_work", "meeting"}) not in graph.required


def test_external_endpoints_such_as_street_are_not_rooms():
    graph = build_adjacency_graph(_office())

    assert "street" not in graph.nodes
    assert all("street" not in pair for pair in graph.required | graph.soft)


def test_missing_required_reports_exactly_what_is_absent():
    graph = build_adjacency_graph(_office())
    present = [(room, CORRIDOR) for room in graph.nodes if room != CORRIDOR]
    present.append(("core", "it_storage"))  # the other service_adjacent edge
    present.remove(("restroom", CORRIDOR))

    missing = graph.missing_required(present)

    assert ("corridor", "restroom") in missing
    assert ("core", "restroom") in missing
    assert len(missing) == 2


def test_missing_required_is_order_insensitive_about_pairs():
    graph = build_adjacency_graph(_office())
    present = [(CORRIDOR, room) for room in graph.nodes if room != CORRIDOR]
    present.append(("core", "restroom"))
    present.append(("it_storage", "core"))

    assert graph.missing_required(present) == ()

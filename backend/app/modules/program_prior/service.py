from __future__ import annotations

from dataclasses import dataclass

from backend.app.modules.program_prior.assignable import assignable_area
from backend.app.modules.program_prior.sizing import (
    OFFICE_SIZING,
    SizingContext,
    SizingRule,
    size_space,
)
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.program import ProgramEdge, ProgramGraph, ProgramNode


@dataclass(frozen=True)
class SpaceProfile:
    space_type: str
    ratio: float
    min_width: float
    max_aspect_ratio: float
    zone: str
    frontage_required: bool = False


@dataclass(frozen=True)
class RelationshipProfile:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass(frozen=True)
class ProgramProfile:
    spaces: tuple[SpaceProfile, ...]
    relationships: tuple[RelationshipProfile, ...]
    # When present, areas come from the normative rules in ``sizing`` -- fixture
    # counts, headcount, fixed modules -- instead of ``SpaceProfile.ratio``.
    # A ratio makes a restroom grow with the building rather than with the
    # people using it; see modules/program_prior/sizing.py.
    sizing_rules: dict[str, SizingRule] | None = None


OFFICE_PROFILE = ProgramProfile(
    spaces=(
        SpaceProfile("open_work", 0.52, 6.0, 2.5, "workplace"),
        SpaceProfile("meeting", 0.10, 2.7, 2.0, "public"),
        SpaceProfile("reception", 0.05, 2.4, 2.5, "public"),
        SpaceProfile("focus", 0.06, 1.8, 1.8, "workplace"),
        SpaceProfile("pantry", 0.03, 1.8, 2.0, "service"),
        SpaceProfile("restroom", 0.05, 1.8, 2.5, "service"),
        SpaceProfile("core", 0.14, 3.0, 2.0, "core"),
        SpaceProfile("it_storage", 0.05, 1.5, 2.5, "service"),
    ),
    relationships=(
        RelationshipProfile("reception", "meeting", "functional_adjacency"),
        RelationshipProfile("open_work", "focus", "functional_adjacency"),
        RelationshipProfile("open_work", "meeting", "functional_adjacency"),
        RelationshipProfile("core", "restroom", "service_adjacent"),
        RelationshipProfile("core", "it_storage", "service_adjacent"),
        RelationshipProfile("pantry", "open_work", "functional_adjacency"),
    ),
    sizing_rules=OFFICE_SIZING,
)

COMMERCIAL_PROFILE = ProgramProfile(
    spaces=(
        SpaceProfile("sales", 0.57, 5.0, 3.0, "frontage", frontage_required=True),
        SpaceProfile("checkout", 0.04, 2.4, 3.0, "public"),
        SpaceProfile("stock", 0.10, 2.4, 2.5, "service"),
        SpaceProfile("staff", 0.05, 2.4, 2.0, "service"),
        SpaceProfile("restroom", 0.05, 1.8, 2.5, "service"),
        SpaceProfile("core", 0.12, 3.0, 2.0, "core"),
        SpaceProfile("utility", 0.07, 1.5, 2.5, "service"),
    ),
    relationships=(
        RelationshipProfile("sales", "street", "public_access"),
        RelationshipProfile("checkout", "sales", "functional_adjacency"),
        RelationshipProfile("stock", "sales", "functional_adjacency"),
        RelationshipProfile("staff", "stock", "functional_adjacency"),
        RelationshipProfile("core", "restroom", "service_adjacent"),
        RelationshipProfile("core", "utility", "service_adjacent"),
    ),
)


def generate_program_graph(
    analysis: MassAnalysis,
    floor_index: int,
    use_type: str,
) -> ProgramGraph:
    if floor_index < 1 or floor_index > analysis.floors:
        raise ValueError("floor_index must be inside analyzed floor range")

    profile = _profile_for(use_type)
    plate = analysis.floor_plate(floor_index)
    # Rooms are sized on what the plate can assign to rooms, not on its
    # gross area: the corridor and the un-rectangular corners come off first.
    assignable = assignable_area(
        plate.footprint_polygon, gross_m2=plate.area, bounds=plate.bounds
    )
    floor_area = assignable.assignable_m2
    if profile.sizing_rules is not None:
        nodes, unresolved, source = _nodes_from_sizing(floor_area, profile)
    else:
        nodes = _nodes_from_profile(floor_area, profile)
        unresolved, source = (), "baseline_prior"
    if use_type == "neighborhood_commercial":
        nodes = _split_commercial_tenants(nodes)

    return ProgramGraph(
        project_id=analysis.project_id,
        floor_index=floor_index,
        use_type=use_type,
        nodes=nodes,
        edges=_relationship_edges(profile, nodes),
        source=source,
        unresolved_facts=unresolved,
        net_area_allowance_m2=_clean_number(assignable.allowance_m2),
    )


def _profile_for(use_type: str) -> ProgramProfile:
    if use_type == "office":
        return OFFICE_PROFILE
    if use_type == "neighborhood_commercial":
        return COMMERCIAL_PROFILE
    raise ValueError(f"unsupported use_type: {use_type}")


def _nodes_from_profile(
    total_area: float, profile: ProgramProfile
) -> list[ProgramNode]:
    areas = [total_area * space.ratio for space in profile.spaces]
    areas[-1] = total_area - sum(areas[:-1])
    return [
        ProgramNode(
            node_id=space.space_type,
            space_type=space.space_type,
            target_area=_clean_number(area),
            min_area=_clean_number(area * 0.85),
            max_area=_clean_number(area * 1.15),
            frontage_required=space.frontage_required,
            min_width=space.min_width,
            max_aspect_ratio=space.max_aspect_ratio,
            zone=space.zone,
        )
        for space, area in zip(profile.spaces, areas)
    ]


def _nodes_from_sizing(
    total_area: float,
    profile: ProgramProfile,
) -> tuple[list[ProgramNode], tuple[str, ...], str]:
    """Size every space from its own driver, keeping the ratio path as fallback.

    A plate can be too small to hold the normative program -- the residual space
    goes negative.  That is a real finding about the mass, but the caller still
    needs a program, so we fall back to ratios and say so through the graph
    source rather than silently shrinking the restroom.
    """
    rules = profile.sizing_rules
    assert rules is not None
    context = SizingContext(net_area_m2=total_area)
    sized = {}
    unresolved: list[str] = []
    for space in profile.spaces:
        if space.space_type not in rules:
            return _nodes_from_profile(total_area, profile), (), "baseline_prior"
        try:
            item = size_space(space.space_type, context, rules)
        except ValueError as error:
            return (
                _nodes_from_profile(total_area, profile),
                (f"normative sizing did not fit the plate: {error}",),
                "baseline_prior:ratio_fallback",
            )
        sized[space.space_type] = item
        unresolved.extend(item.unresolved_facts)

    nodes = [
        ProgramNode(
            node_id=space.space_type,
            space_type=space.space_type,
            target_area=_clean_number(sized[space.space_type].area_m2),
            min_area=_clean_number(sized[space.space_type].area_m2 * 0.85),
            max_area=_clean_number(sized[space.space_type].area_m2 * 1.15),
            frontage_required=space.frontage_required,
            min_width=space.min_width,
            max_aspect_ratio=space.max_aspect_ratio,
            zone=space.zone,
        )
        for space in profile.spaces
    ]
    return nodes, tuple(dict.fromkeys(unresolved)), "baseline_prior:normative_sizing"


def _node_exists(node_id: str, nodes: list[ProgramNode]) -> bool:
    return any(node.node_id == node_id for node in nodes)


def _relationship_edges(
    profile: ProgramProfile,
    nodes: list[ProgramNode],
) -> list[ProgramEdge]:
    def ids(endpoint: str) -> list[str]:
        exact = [node.node_id for node in nodes if node.node_id == endpoint]
        if exact:
            return exact
        role_matches = [node.node_id for node in nodes if node.space_type == endpoint]
        return role_matches or ([endpoint] if endpoint == "street" else [])

    return [
        ProgramEdge(source, target, relationship.relation, relationship.weight)
        for relationship in profile.relationships
        for source in ids(relationship.source)
        for target in ids(relationship.target)
    ]


def _split_commercial_tenants(nodes: list[ProgramNode]) -> list[ProgramNode]:
    sales = next(node for node in nodes if node.node_id == "sales")
    tenant_target = float(sales.target_area) * 0.5
    tenants = [
        ProgramNode(
            node_id=f"sales_{suffix}",
            space_type="sales",
            target_area=_clean_number(tenant_target),
            min_area=_clean_number(tenant_target * 0.85),
            max_area=_clean_number(tenant_target * 1.15),
            frontage_required=True,
            min_width=4.0,
            max_aspect_ratio=sales.max_aspect_ratio,
            zone=sales.zone,
            tenant_id=f"tenant_{suffix}",
        )
        for suffix in ("a", "b")
    ]
    return [
        *tenants,
        *(node for node in nodes if node.node_id != "sales"),
    ]


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value

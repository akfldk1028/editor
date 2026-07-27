from __future__ import annotations

from dataclasses import dataclass

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
    nodes = _nodes_from_profile(analysis.area, profile)

    return ProgramGraph(
        project_id=analysis.project_id,
        floor_index=floor_index,
        use_type=use_type,
        nodes=nodes,
        edges=[
            ProgramEdge(
                source=relationship.source,
                target=relationship.target,
                relation=relationship.relation,
                weight=relationship.weight,
            )
            for relationship in profile.relationships
            if _node_exists(relationship.source, nodes)
            and (_node_exists(relationship.target, nodes) or relationship.target == "street")
        ],
        source="baseline_prior",
    )


def _profile_for(use_type: str) -> ProgramProfile:
    if use_type == "office":
        return OFFICE_PROFILE
    if use_type == "neighborhood_commercial":
        return COMMERCIAL_PROFILE
    raise ValueError(f"unsupported use_type: {use_type}")


def _nodes_from_profile(total_area: float, profile: ProgramProfile) -> list[ProgramNode]:
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


def _node_exists(node_id: str, nodes: list[ProgramNode]) -> bool:
    return any(node.node_id == node_id for node in nodes)


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value

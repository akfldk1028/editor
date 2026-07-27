from __future__ import annotations

from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.program import ProgramEdge, ProgramGraph, ProgramNode

COMMERCIAL_RATIOS = {
    "shop_unit": 0.72,
    "core": 0.12,
    "restroom": 0.05,
    "storage": 0.06,
    "utility": 0.05,
}

OFFICE_RATIOS = {
    "office_area": 0.78,
    "core": 0.14,
    "restroom": 0.04,
    "pantry": 0.02,
    "ps_eps": 0.02,
}


def generate_program_graph(
    analysis: MassAnalysis,
    floor_index: int,
    use_type: str,
) -> ProgramGraph:
    if floor_index < 1 or floor_index > analysis.floors:
        raise ValueError("floor_index must be inside analyzed floor range")

    ratios = _ratios_for(use_type)
    nodes = _nodes_from_ratios(analysis.area, ratios)

    edges = [
        ProgramEdge(source="core", target="restroom", relation="service_adjacent", weight=1.0),
        ProgramEdge(source="core", target="utility", relation="service_adjacent", weight=0.8),
    ]
    if use_type == "office":
        edges.append(ProgramEdge(source="core", target="office_area", relation="vertical_access", weight=1.0))
    else:
        edges.append(ProgramEdge(source="shop_unit", target="street", relation="public_access", weight=1.0))

    return ProgramGraph(
        project_id=analysis.project_id,
        floor_index=floor_index,
        use_type=use_type,
        nodes=nodes,
        edges=[
            edge
            for edge in edges
            if _node_exists(edge.source, nodes)
            and (_node_exists(edge.target, nodes) or edge.target == "street")
        ],
        source="baseline_prior",
    )


def _ratios_for(use_type: str) -> dict[str, float]:
    if use_type == "office":
        return OFFICE_RATIOS
    if use_type == "neighborhood_commercial":
        return COMMERCIAL_RATIOS
    raise ValueError(f"unsupported use_type: {use_type}")


def _nodes_from_ratios(total_area: float, ratios: dict[str, float]) -> list[ProgramNode]:
    names = list(ratios)
    areas = [total_area * ratios[name] for name in names]
    areas[-1] = total_area - sum(areas[:-1])
    return [
        ProgramNode(
            node_id=name,
            space_type=name,
            target_area=_clean_number(area),
            min_area=_clean_number(area * 0.85),
            max_area=_clean_number(area * 1.15),
            frontage_required=name == "shop_unit",
        )
        for name, area in zip(names, areas)
    ]


def _node_exists(node_id: str, nodes: list[ProgramNode]) -> bool:
    return any(node.node_id == node_id for node in nodes)


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value

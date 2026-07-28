from __future__ import annotations

from backend.app.schemas.mass import MassAnalysis, MassInput
from engine.geometry.polygon import bounds, polygon_area


def analyze_mass(mass: MassInput) -> MassAnalysis:
    if mass.floors < 1:
        raise ValueError("floors must be at least 1")
    if len(mass.footprint_polygon) < 3:
        raise ValueError("footprint polygon needs at least 3 points")

    area = polygon_area(mass.footprint_polygon)
    if area <= 0:
        raise ValueError("footprint polygon area must be greater than 0")

    street_edges = [
        int(edge["edge_index"])
        for edge in mass.site_edges
        if edge.get("kind") == "street" and "edge_index" in edge
    ]
    access_edges = [
        int(candidate["edge_index"])
        for candidate in mass.access_candidates
        if "edge_index" in candidate
    ]

    return MassAnalysis(
        project_id=mass.project_id,
        area=_clean_number(area),
        floor_area=_clean_number(area * mass.floors),
        floors=mass.floors,
        edge_count=len(mass.footprint_polygon),
        street_edge_indices=street_edges,
        access_edge_indices=access_edges,
        bounds=tuple(_clean_number(value) for value in bounds(mass.footprint_polygon)),
        building_code_context=mass.building_code_context,
    )


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value

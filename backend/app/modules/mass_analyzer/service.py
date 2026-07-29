from __future__ import annotations

from backend.app.schemas.mass import (
    FloorPlateAnalysis,
    MassAnalysis,
    MassInput,
)
from engine.geometry.polygon import bounds, contains_polygon, polygon_area


def analyze_mass(mass: MassInput) -> MassAnalysis:
    if mass.floors < 1:
        raise ValueError("floors must be at least 1")
    floor_plates = tuple(
        analyze_floor_mass(mass, floor_index)
        for floor_index in range(1, mass.floors + 1)
    )
    reference = floor_plates[0]

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
        area=reference.area,
        floor_area=_clean_number(sum(float(plate.area) for plate in floor_plates)),
        floors=mass.floors,
        edge_count=reference.edge_count,
        street_edge_indices=street_edges,
        access_edge_indices=access_edges,
        bounds=reference.bounds,
        building_code_context=mass.building_code_context,
        floor_plates=floor_plates,
    )


def analyze_floor_mass(
    mass: MassInput,
    floor_index: int,
) -> FloorPlateAnalysis:
    polygon = mass.footprint_for_floor(floor_index)
    if len(polygon) < 3:
        raise ValueError("footprint polygon needs at least 3 points")
    area = polygon_area(polygon)
    if area <= 0:
        raise ValueError("footprint polygon area must be greater than 0")
    if mass.floor_footprints and not contains_polygon(
        mass.footprint_polygon,
        polygon,
    ):
        raise ValueError(
            f"floor {floor_index} footprint must be covered by reference envelope"
        )
    return FloorPlateAnalysis(
        floor_index=floor_index,
        area=_clean_number(area),
        edge_count=len(polygon),
        bounds=tuple(_clean_number(value) for value in bounds(polygon)),
        footprint_polygon=polygon,
        source=(
            "explicit_floor_footprint" if mass.floor_footprints else "legacy_broadcast"
        ),
    )


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value

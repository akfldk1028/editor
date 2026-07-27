from __future__ import annotations

from backend.app.schemas.layout import LayoutCandidate
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph
from engine.geometry.polygon import bboxes_overlap, bounds, contains_bbox, polygon_area


def validate_layout(
    layout: LayoutCandidate,
    program: ProgramGraph,
    boundary: list[tuple[float, float]],
) -> ValidationReport:
    messages: list[str] = []
    boundary_ok = all(contains_bbox(boundary, room.polygon) for room in layout.rooms)
    if not boundary_ok:
        messages.append("room polygon escapes boundary")

    boxes = [bounds(room.polygon) for room in layout.rooms]
    overlap_ok = True
    for left_index, left in enumerate(boxes):
        for right in boxes[left_index + 1 :]:
            if bboxes_overlap(left, right):
                overlap_ok = False
    if not overlap_ok:
        messages.append("room polygons overlap")

    target_area = sum(node.target_area for node in program.nodes)
    actual_area = sum(polygon_area(room.polygon) for room in layout.rooms)
    area_error = abs(target_area - actual_area) / max(target_area, 1)
    area_score = 1.0 if area_error <= 0.01 else round(max(0.0, 1.0 - area_error), 4)
    if area_score < 1:
        messages.append("layout area differs from program target")

    boundary_score = 1.0 if boundary_ok else 0.0
    overlap_score = 1.0 if overlap_ok else 0.0
    circulation_score = 1.0
    efficiency_score = _efficiency_score(layout, program)
    total = round((area_score + boundary_score + overlap_score + circulation_score + efficiency_score) / 5, 4)

    return ValidationReport(
        is_valid=boundary_ok and overlap_ok and area_score == 1.0,
        area_score=area_score,
        overlap_score=overlap_score,
        boundary_score=boundary_score,
        circulation_score=circulation_score,
        efficiency_score=efficiency_score,
        total_score=total,
        messages=messages,
    )


def _efficiency_score(layout: LayoutCandidate, program: ProgramGraph) -> float:
    rentable_types = {"shop_unit", "office_area"}
    total = sum(polygon_area(room.polygon) for room in layout.rooms)
    rentable = sum(polygon_area(room.polygon) for room in layout.rooms if room.space_type in rentable_types)
    if total <= 0:
        return 0.0
    ratio = rentable / total
    target = 0.72 if program.use_type == "neighborhood_commercial" else 0.78
    return round(max(0.0, 1.0 - abs(target - ratio)), 4)

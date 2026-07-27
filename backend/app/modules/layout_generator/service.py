from __future__ import annotations

from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.program import ProgramGraph


def generate_baseline_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
) -> LayoutCandidate:
    min_x, min_y, max_x, max_y = analysis.bounds
    width = max_x - min_x
    height = max_y - min_y
    total = sum(node.target_area for node in program.nodes) or 1
    cursor = min_x
    rooms: list[RoomPolygon] = []

    for index, node in enumerate(program.nodes):
        if index == len(program.nodes) - 1:
            next_x = max_x
        else:
            next_x = cursor + width * (node.target_area / total)
        rooms.append(
            RoomPolygon(
                room_id=node.node_id,
                space_type=node.space_type,
                polygon=[
                    (_clean_number(cursor), _clean_number(min_y)),
                    (_clean_number(next_x), _clean_number(min_y)),
                    (_clean_number(next_x), _clean_number(max_y)),
                    (_clean_number(cursor), _clean_number(max_y)),
                ],
            )
        )
        cursor = next_x

    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-baseline",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[],
        score=0.0,
    )


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 4)

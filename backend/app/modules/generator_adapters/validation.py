from __future__ import annotations

from dataclasses import replace

from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.generator_adapter import (
    GeneratorRequest,
    GeneratorResponse,
    NormalizedCandidate,
)
from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    OpeningSegment,
    PlanElement,
    PlanLine,
    RoomPolygon,
    UsePlanningMetadata,
)
from backend.app.schemas.mass import BuildingCodeContext
from backend.app.schemas.program import ProgramEdge, ProgramGraph, ProgramNode


def normalized_candidate_to_layout(
    candidate: NormalizedCandidate,
) -> LayoutCandidate:
    basic_design = None
    if candidate.basic_design is not None:
        planning = candidate.basic_design.planning
        basic_design = BasicDesignFeatures(
            elements=tuple(
                PlanElement(
                    element.element_id,
                    element.category,
                    element.kind,
                    element.host_id,
                    element.label,
                    element.footprint,
                    element.stair_geometry,
                )
                for element in candidate.basic_design.elements
            ),
            lines=tuple(
                PlanLine(
                    line.line_id,
                    line.category,
                    line.kind,
                    line.points,
                    line.host_id,
                    line.target_id,
                    line.label,
                    line.measured_value,
                    line.clear_width,
                    line.door_swing,
                )
                for line in candidate.basic_design.lines
            ),
            policy_version=candidate.basic_design.policy_version,
            planning=(
                None
                if planning is None
                else UsePlanningMetadata(
                    planning.reception_to_lobby_route_line_id,
                    planning.support_room_ids,
                )
            ),
        )
    return LayoutCandidate(
        candidate_id=candidate.candidate_id,
        project_id=candidate.project_id,
        floor_index=candidate.floor_index,
        rooms=[
            RoomPolygon(room.polygon_id, room.kind, list(room.points))
            for room in candidate.rooms
        ],
        circulation=[
            RoomPolygon(path.polygon_id, path.kind, list(path.points))
            for path in candidate.circulation
        ],
        score=candidate.score,
        openings=[
            OpeningSegment(
                opening.opening_id,
                opening.kind,
                opening.connects,
                opening.start,
                opening.end,
                opening.clear_width,
            )
            for opening in candidate.openings
        ],
        basic_design=basic_design,
        remote_stair_footprint=candidate.remote_stair_footprint,
    )


def validate_normalized_response(
    request: GeneratorRequest,
    response: GeneratorResponse,
) -> GeneratorResponse:
    if response.status != "executed":
        return response
    candidate = response.normalized_candidate
    if candidate is None:
        return _failed(response, "executed response has no normalized candidate")
    if response.request_digest != request.digest:
        return _failed(response, "request digest does not match normalized response")
    if (
        candidate.project_id != request.project_id
        or candidate.floor_index != request.floor_index
    ):
        return _failed(response, "candidate identity does not match request")
    if candidate.boundary != request.boundary:
        return _failed(response, "candidate boundary does not match request")

    contract_error = _basic_design_contract_error(candidate)
    if contract_error is not None:
        return _failed(response, contract_error)

    try:
        layout = normalized_candidate_to_layout(candidate)
        program = ProgramGraph(
            project_id=request.project_id,
            floor_index=request.floor_index,
            use_type=request.use_type,
            nodes=[
                ProgramNode(
                    node.node_id,
                    node.space_type,
                    node.target_area,
                    node.min_area,
                    node.max_area,
                    node.frontage_required,
                    node.min_width,
                    node.max_aspect_ratio,
                    node.zone,
                    node.tenant_id,
                )
                for node in request.program_nodes
            ],
            edges=[
                ProgramEdge(edge.source, edge.target, edge.relation, edge.weight)
                for edge in request.program_edges
            ],
            source=f"generator-adapter:{response.backend_id}",
        )
        facts = {fact.name: fact.value for fact in request.project_facts}
        height = facts.get("floor_to_floor_height_m")
        report = validate_layout(
            layout,
            program,
            boundary=list(request.boundary),
            street_segments=_street_segments(request),
            require_openings=True,
            min_circulation_width=1.2,
            require_basic_design=True,
            building_code_context=BuildingCodeContext(
                floor_to_floor_height_m=height,
            ),
        )
    except Exception as error:
        return _failed(
            response,
            f"validator could not reconstruct normalized candidate: "
            f"{type(error).__name__}: {error}",
        )
    if report.accepted:
        return response
    codes = sorted({violation.code for violation in report.violations})
    detail = ", ".join(codes) if codes else "unknown violation"
    return _failed(
        response,
        f"validator rejected normalized candidate: {detail}",
    )


def _basic_design_contract_error(
    candidate: NormalizedCandidate,
) -> str | None:
    if candidate.basic_design is None:
        return "executed candidate requires normalized basic_design evidence"
    lines = candidate.basic_design.lines
    entrances = tuple(line for line in lines if line.kind == "entrance")
    routes = tuple(line for line in lines if line.category == "egress")
    if candidate.entrances != entrances:
        return "normalized entrances do not match basic_design lines"
    if candidate.routes != routes:
        return "normalized routes do not match basic_design lines"
    return None


def _street_segments(
    request: GeneratorRequest,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segments = []
    boundary = request.boundary
    for constraint in request.fixed_constraints:
        if constraint.kind != "street_edge":
            continue
        edge_index = constraint.value
        if (
            not isinstance(edge_index, int)
            or isinstance(edge_index, bool)
            or edge_index < 0
            or edge_index >= len(boundary)
        ):
            raise ValueError(
                f"street edge {constraint.constraint_id} is outside the boundary"
            )
        segments.append(
            (
                boundary[edge_index],
                boundary[(edge_index + 1) % len(boundary)],
            )
        )
    return segments


def _failed(
    response: GeneratorResponse,
    reason: str,
) -> GeneratorResponse:
    return replace(
        response,
        status="failed",
        normalized_candidate=None,
        reason=reason,
    )

from __future__ import annotations

from collections import Counter
from typing import Any, Protocol

from backend.app.modules.generation_loop.service import (
    assign_floors_from_use_mix,
    run_building_generation,
)
from backend.app.modules.llm_planner.contracts import (
    ContractValidationError,
    parse_building_floor_assignments_json,
)
from backend.app.schemas.llm import BuildingFloorAssignments
from backend.app.schemas.mass import MassInput
from backend.app.schemas.result import BuildingGenerationResult


class StructuredPlannerClient(Protocol):
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> str: ...


FLOOR_ASSIGNMENT_SYSTEM_PROMPT = """\
You are the program planner for a multi-floor building.
Assign exactly one supported use type to every floor.
Respect the requested use mix, put public commercial uses on lower floors when
access and frontage favor them, and keep the response limited to the JSON schema.
Do not generate room coordinates or geometry.
"""


def plan_floor_assignments(
    mass: MassInput,
    client: StructuredPlannerClient,
) -> BuildingFloorAssignments:
    payload = {
        "project_id": mass.project_id,
        "floors": mass.floors,
        "footprint_polygon": mass.footprint_polygon,
        "site_edges": mass.site_edges,
        "access_candidates": mass.access_candidates,
        "use_mix": mass.use_mix,
    }
    plan = parse_building_floor_assignments_json(
        client.complete_json(
            system_prompt=FLOOR_ASSIGNMENT_SYSTEM_PROMPT,
            user_payload=payload,
        )
    )
    if plan.project_id != mass.project_id:
        raise ContractValidationError(
            "project_id does not match the requested building"
        )
    indices = [assignment.floor_index for assignment in plan.assignments]
    if indices != list(range(1, mass.floors + 1)):
        raise ContractValidationError(
            "floor assignments must contain every floor exactly once"
        )
    expected_counts = Counter(
        assignment.use_type
        for assignment in assign_floors_from_use_mix(mass)
    )
    actual_counts = Counter(
        assignment.use_type for assignment in plan.assignments
    )
    if actual_counts != expected_counts:
        raise ContractValidationError(
            "floor assignments do not satisfy the requested use_mix"
        )
    commercial_floors = [
        assignment.floor_index
        for assignment in plan.assignments
        if assignment.use_type == "neighborhood_commercial"
    ]
    office_floors = [
        assignment.floor_index
        for assignment in plan.assignments
        if assignment.use_type == "office"
    ]
    if (
        commercial_floors
        and office_floors
        and max(commercial_floors) > min(office_floors)
    ):
        raise ContractValidationError(
            "neighborhood commercial use must occupy lower floors than office"
        )
    return plan


def run_llm_building_generation(
    mass: MassInput,
    client: StructuredPlannerClient,
) -> BuildingGenerationResult:
    plan = plan_floor_assignments(mass, client)
    return run_building_generation(
        mass,
        floor_assignments=plan.assignments,
    )

from __future__ import annotations

from backend.app.schemas.mass import (
    BuildingCodeContext,
    FloorCodeContext,
    FloorFootprint,
    MassInput,
)


def mass_input_from_payload(payload: dict) -> MassInput:
    context_payload = payload.get("building_code_context")
    context = None
    if context_payload is not None:
        if not isinstance(context_payload, dict):
            raise TypeError("building_code_context must be an object")
        floor_payloads = context_payload.get("floor_facts", [])
        if not isinstance(floor_payloads, list):
            raise TypeError("building_code_context.floor_facts must be a list")
        context = BuildingCodeContext(
            jurisdiction=context_payload.get("jurisdiction"),
            effective_date=context_payload.get("effective_date"),
            floor_to_floor_height_m=context_payload.get("floor_to_floor_height_m"),
            sprinklered=context_payload.get("sprinklered"),
            fire_resistant=context_payload.get("fire_resistant"),
            qualifying_sprinkler_protection=context_payload.get(
                "qualifying_sprinkler_protection"
            ),
            travel_construction_class=context_payload.get(
                "travel_construction_class"
            ),
            travel_limit_classification=context_payload.get(
                "travel_limit_classification"
            ),
            floor_facts=tuple(
                FloorCodeContext(
                    floor_index=fact["floor_index"],
                    occupancy=fact.get("occupancy"),
                    occupant_load=fact.get("occupant_load"),
                    above_grade=fact.get("above_grade"),
                    occupancy_category=fact.get("occupancy_category"),
                    story_number=fact.get("story_number"),
                    habitable_area_m2=fact.get("habitable_area_m2"),
                    is_evacuation_floor=fact.get("is_evacuation_floor"),
                )
                for fact in floor_payloads
            ),
        )
    floor_footprint_payloads = payload.get("floor_footprints", [])
    if not isinstance(floor_footprint_payloads, list):
        raise TypeError("floor_footprints must be a list")
    return MassInput(
        project_id=payload["project_id"],
        floors=int(payload["floors"]),
        footprint_polygon=[tuple(point) for point in payload["footprint_polygon"]],
        site_edges=list(payload.get("site_edges", [])),
        access_candidates=list(payload.get("access_candidates", [])),
        use_mix=dict(payload.get("use_mix", {})),
        building_code_context=context,
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=int(record["floor_index"]),
                footprint_polygon=tuple(
                    tuple(point) for point in record["footprint_polygon"]
                ),
            )
            for record in floor_footprint_payloads
        ),
    )


__all__ = ["mass_input_from_payload"]

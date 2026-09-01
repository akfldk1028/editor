from __future__ import annotations

from backend.app.modules.building_quality.contracts import QualityPolicy


DEFAULT_QUALITY_POLICY = QualityPolicy(
    version="building-quality/v1",
    minimum_floor_coverage=0.60,
    minimum_primary_daylight_ratio=0.70,
    minimum_room_form_pass_ratio=0.90,
    minimum_core_stack_ratio=0.95,
    minimum_shaft_stack_ratio=0.90,
    minimum_service_stack_ratio=0.70,
    minimum_pairwise_diversity=0.25,
    weights={
        "daylight": 0.25,
        "room_form": 0.20,
        "vertical_stacking": 0.20,
        "egress": 0.20,
        "coverage_efficiency": 0.15,
    },
)

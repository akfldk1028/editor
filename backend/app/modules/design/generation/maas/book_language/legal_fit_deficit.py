"""Typed, recipe-free feedback for failed whole-solid legal placement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


TARGET_FLOOR_AREA_DECIMAL_PLACES = 3
# Targets are serialized to three decimal square metres. Nearest rounding can
# place a target up to half one unit in the last reported place above the
# unrounded canonical legal section.
TARGET_FLOOR_AREA_ROUNDING_TOLERANCE_M2 = (
    0.5 * 10 ** -TARGET_FLOOR_AREA_DECIMAL_PLACES
)


@dataclass(frozen=True)
class LegalFitDeficit:
    stage: str
    authored_program_hash: str
    floor_capacity_plan_hash: str
    typed_reasons: tuple[str, ...]
    legal_section_indices: tuple[int, ...]
    measured_values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = "arr.maas.legal_fit_deficit.v1"
        payload["typed_reasons"] = list(self.typed_reasons)
        payload["legal_section_indices"] = list(self.legal_section_indices)
        return payload


def build_legal_fit_deficit(
    *,
    authored_program_hash: str,
    legal_sections: Iterable[Any],
    target_floor_areas_m2: Iterable[float],
    floor_capacity_plan_hash: str,
) -> LegalFitDeficit:
    sections = tuple(legal_sections)
    targets = tuple(float(value) for value in target_floor_areas_m2)
    legal_areas = tuple(float(section.area) for section in sections)
    exceeded = tuple(
        index
        for index, (target, legal_area) in enumerate(
            zip(targets, legal_areas)
        )
        if target > legal_area + TARGET_FLOOR_AREA_ROUNDING_TOLERANCE_M2
    )
    reasons: list[str] = []
    if not sections:
        reasons.append("legal_section_field_missing")
    if exceeded:
        reasons.append("target_exceeds_legal_section")
    if not reasons:
        reasons.append("whole_solid_affine_fit_infeasible")
    return LegalFitDeficit(
        stage="principal_frame_legal_fit",
        authored_program_hash=str(authored_program_hash),
        floor_capacity_plan_hash=str(floor_capacity_plan_hash),
        typed_reasons=tuple(reasons),
        legal_section_indices=exceeded,
        measured_values={
            "target_floor_areas_m2": list(targets),
            "legal_section_areas_m2": list(legal_areas),
            "target_total_m2": sum(targets),
            "legal_total_m2": sum(legal_areas),
            "target_floor_area_decimal_places": (
                TARGET_FLOOR_AREA_DECIMAL_PLACES
            ),
            "target_floor_area_rounding_tolerance_m2": (
                TARGET_FLOOR_AREA_ROUNDING_TOLERANCE_M2
            ),
        },
    )


__all__ = ["LegalFitDeficit", "build_legal_fit_deficit"]

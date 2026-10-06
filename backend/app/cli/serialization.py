from __future__ import annotations

from backend.app.core.serialization import to_jsonable
from backend.app.modules.building_quality import (
    AlternativeDiversityReport,
    BuildingQualityReport,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.mass_io import mass_input_from_payload


def _mass_input_from_payload(payload: dict) -> MassInput:
    return mass_input_from_payload(payload)


def _aggregate_review_status(records: list[dict], key: str) -> dict:
    statuses = [record[key]["status"] for record in records]
    if statuses and all(status == "pass" for status in statuses):
        status = "pass"
    elif any(status == "fail" for status in statuses):
        status = "fail"
    else:
        status = "not_checked"
    return {"status": status}


def _serialize_quality_evidence(
    report: BuildingQualityReport | AlternativeDiversityReport,
) -> dict:
    """Convert immutable quality reports into JSON-safe review evidence."""
    serialized = to_jsonable(report)
    if not isinstance(serialized, dict):
        raise TypeError("quality evidence must serialize to an object")
    return serialized


def _serialize_rejected_strategy(rejection) -> dict:
    serialized = {
        "strategy": rejection.strategy,
        "reason_type": rejection.reason_type,
        "reason": rejection.reason,
    }
    if rejection.quality_report is not None:
        serialized["quality_report"] = _serialize_quality_evidence(
            rejection.quality_report
        )
    if rejection.generator_repairs:
        serialized["generator_repairs"] = to_jsonable(rejection.generator_repairs)
    if rejection.generator_repair_attempt is not None:
        serialized["generator_repair_attempt"] = to_jsonable(
            rejection.generator_repair_attempt
        )
    return serialized

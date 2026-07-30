from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.app.modules.building_quality import BuildingQualityReport
from backend.app.schemas.result import BuildingGenerationResult


@dataclass(frozen=True)
class StructuralAlternative:
    strategy: str
    building: BuildingGenerationResult
    quality_report: BuildingQualityReport
    core_fingerprint: str
    circulation_fingerprint: str
    room_fingerprint: str
    structural_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise ValueError("structural alternative strategy must be non-empty")
        if not isinstance(self.building, BuildingGenerationResult):
            raise TypeError("structural alternative building is invalid")
        if not isinstance(self.quality_report, BuildingQualityReport):
            raise TypeError("structural alternative quality report is invalid")
        if not self.quality_report.hard_pass:
            raise ValueError("structural alternative quality report must hard-pass")
        components = (
            self.core_fingerprint,
            self.circulation_fingerprint,
            self.room_fingerprint,
        )
        if any(not _is_sha256(value) for value in components):
            raise ValueError("structural component fingerprints must be SHA-256")
        expected = hashlib.sha256(":".join(components).encode()).hexdigest()
        if self.structural_fingerprint != expected:
            raise ValueError("structural fingerprint must match its components")


@dataclass(frozen=True)
class StructuralAlternativeRejection:
    strategy: str
    reason_type: str
    reason: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.strategy, self.reason_type, self.reason)
        ):
            raise ValueError("structural rejection fields must be non-empty")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Mapping

from backend.app.modules.building_quality.constants import (
    DIVERSITY_COMPONENT_WEIGHTS,
    MATERIAL_DIVERSITY_DISTANCE,
)


QUALITY_COMPONENT_KEYS = frozenset(
    {
        "daylight",
        "room_form",
        "vertical_stacking",
        "egress",
        "coverage_efficiency",
    }
)


class _ImmutableJsonDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError(f"{type(self).__name__} is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _require_string(value: object, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must be non-empty")


def _require_integer(value: object, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    optional: bool = False,
) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")


def _immutable_scores(values: Mapping[str, float], name: str) -> _ImmutableJsonDict:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    result = dict(values)
    if not result:
        raise ValueError(f"{name} must not be empty")
    for key, value in result.items():
        _require_string(key, f"{name} key")
        _require_number(value, f"{name}[{key!r}]", minimum=0.0, maximum=1.0)
    return _ImmutableJsonDict(result)


@dataclass(frozen=True)
class QualityPolicy:
    version: str
    minimum_floor_coverage: float
    minimum_primary_daylight_ratio: float
    minimum_room_form_pass_ratio: float
    minimum_core_stack_ratio: float
    minimum_shaft_stack_ratio: float
    minimum_service_stack_ratio: float
    minimum_pairwise_diversity: float
    weights: Mapping[str, float]

    def __post_init__(self) -> None:
        _require_string(self.version, "version")
        for name in (
            "minimum_floor_coverage",
            "minimum_primary_daylight_ratio",
            "minimum_room_form_pass_ratio",
            "minimum_core_stack_ratio",
            "minimum_shaft_stack_ratio",
            "minimum_service_stack_ratio",
            "minimum_pairwise_diversity",
        ):
            _require_number(getattr(self, name), name, minimum=0.0, maximum=1.0)
        weights = _immutable_scores(self.weights, "weights")
        if set(weights) != QUALITY_COMPONENT_KEYS:
            raise ValueError("weights must contain exactly the quality components")
        if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("weights must sum to 1.0")
        object.__setattr__(self, "weights", weights)


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: Literal["hard", "soft", "unresolved"]
    floor_index: int | None
    subject_id: str | None
    measured_value: float | None
    threshold: float | None
    message: str

    def __post_init__(self) -> None:
        _require_string(self.code, "code")
        if self.severity not in {"hard", "soft", "unresolved"}:
            raise ValueError("severity must be hard, soft, or unresolved")
        _require_integer(self.floor_index, "floor_index", optional=True)
        _require_string(self.subject_id, "subject_id", optional=True)
        _require_number(self.measured_value, "measured_value", optional=True)
        _require_number(self.threshold, "threshold", optional=True)
        _require_string(self.message, "message")


@dataclass(frozen=True)
class FloorQualityMetrics:
    floor_index: int
    coverage: float
    primary_daylight_ratio: float
    room_form_pass_ratio: float
    worst_aspect_ratio: float | None
    narrowest_room_width_m: float | None
    egress_status: Literal["pass", "fail", "not_checked"]

    def __post_init__(self) -> None:
        _require_integer(self.floor_index, "floor_index")
        _require_number(self.coverage, "coverage", minimum=0.0, maximum=1.0)
        _require_number(
            self.primary_daylight_ratio,
            "primary_daylight_ratio",
            minimum=0.0,
            maximum=1.0,
        )
        _require_number(
            self.room_form_pass_ratio,
            "room_form_pass_ratio",
            minimum=0.0,
            maximum=1.0,
        )
        _require_number(
            self.worst_aspect_ratio,
            "worst_aspect_ratio",
            minimum=0.0,
            optional=True,
        )
        _require_number(
            self.narrowest_room_width_m,
            "narrowest_room_width_m",
            minimum=0.0,
            optional=True,
        )
        if self.egress_status not in {"pass", "fail", "not_checked"}:
            raise ValueError("egress_status must be pass, fail, or not_checked")


@dataclass(frozen=True)
class VerticalQualityMetrics:
    core_stack_ratio: float
    shaft_stack_ratio: float
    wet_service_stack_ratio: float
    maximum_service_centroid_shift_m: float | None

    def __post_init__(self) -> None:
        _require_number(
            self.core_stack_ratio, "core_stack_ratio", minimum=0.0, maximum=1.0
        )
        _require_number(
            self.shaft_stack_ratio, "shaft_stack_ratio", minimum=0.0, maximum=1.0
        )
        _require_number(
            self.wet_service_stack_ratio,
            "wet_service_stack_ratio",
            minimum=0.0,
            maximum=1.0,
        )
        _require_number(
            self.maximum_service_centroid_shift_m,
            "maximum_service_centroid_shift_m",
            minimum=0.0,
            optional=True,
        )


@dataclass(frozen=True)
class BuildingQualityReport:
    policy_version: str
    hard_pass: bool
    score: float
    component_scores: Mapping[str, float]
    floors: tuple[FloorQualityMetrics, ...]
    vertical: VerticalQualityMetrics
    issues: tuple[QualityIssue, ...]
    unresolved_facts: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_string(self.policy_version, "policy_version")
        if not isinstance(self.hard_pass, bool):
            raise TypeError("hard_pass must be a bool")
        _require_number(self.score, "score", minimum=0.0, maximum=1.0)
        object.__setattr__(
            self,
            "component_scores",
            _immutable_scores(self.component_scores, "component_scores"),
        )
        if not isinstance(self.floors, tuple) or not self.floors:
            raise TypeError("floors must be a non-empty tuple")
        if not all(isinstance(floor, FloorQualityMetrics) for floor in self.floors):
            raise TypeError("floors must contain FloorQualityMetrics")
        floor_indexes = tuple(floor.floor_index for floor in self.floors)
        if floor_indexes != tuple(sorted(floor_indexes)) or len(
            set(floor_indexes)
        ) != len(floor_indexes):
            raise ValueError("floors must be strictly ordered by floor_index")
        if not isinstance(self.vertical, VerticalQualityMetrics):
            raise TypeError("vertical must be VerticalQualityMetrics")
        if not isinstance(self.issues, tuple) or not all(
            isinstance(issue, QualityIssue) for issue in self.issues
        ):
            raise TypeError("issues must be a tuple of QualityIssue")
        if self.hard_pass and any(issue.severity == "hard" for issue in self.issues):
            raise ValueError("hard_pass cannot be true when a hard issue exists")
        if not isinstance(self.unresolved_facts, tuple):
            raise TypeError("unresolved_facts must be a tuple")
        for fact in self.unresolved_facts:
            _require_string(fact, "unresolved_facts member")


@dataclass(frozen=True)
class AlternativeDiversityReport:
    first_fingerprint: str
    second_fingerprint: str
    core_distance: float
    circulation_distance: float
    topology_distance: float
    area_distribution_distance: float
    total_distance: float
    nonzero_component_count: int
    quality_distinct: bool

    def __post_init__(self) -> None:
        _require_string(self.first_fingerprint, "first_fingerprint")
        _require_string(self.second_fingerprint, "second_fingerprint")
        components = (
            self.core_distance,
            self.circulation_distance,
            self.topology_distance,
            self.area_distribution_distance,
        )
        for name, value in zip(
            (
                "core_distance",
                "circulation_distance",
                "topology_distance",
                "area_distribution_distance",
            ),
            components,
            strict=True,
        ):
            _require_number(value, name, minimum=0.0, maximum=1.0)
        _require_number(self.total_distance, "total_distance", minimum=0.0, maximum=1.0)
        weighted_total = sum(
            weight * component
            for weight, component in zip(
                DIVERSITY_COMPONENT_WEIGHTS, components, strict=True
            )
        )
        if not math.isclose(
            self.total_distance, weighted_total, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError(
                "total_distance must equal the weighted component distance"
            )
        _require_integer(self.nonzero_component_count, "nonzero_component_count")
        nonzero_component_count = sum(component > 0.0 for component in components)
        if self.nonzero_component_count != nonzero_component_count:
            raise ValueError("nonzero_component_count must match component distances")
        if not isinstance(self.quality_distinct, bool):
            raise TypeError("quality_distinct must be a bool")
        material_component_count = sum(
            component > MATERIAL_DIVERSITY_DISTANCE for component in components
        )
        if self.quality_distinct and material_component_count < 2:
            raise ValueError(
                "quality_distinct requires two material component distances"
            )

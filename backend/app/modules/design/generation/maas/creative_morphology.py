"""Scale-invariant morphology evidence for creative MASS candidates."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from backend.app.modules.design.generation.maas.creative_morphology_geometry import extract_morphology_features


MORPHOLOGY_SCHEMA = "arr.maas.creative_morphology.v1"
GLOBAL_MORPHOLOGY_THRESHOLD = 0.015
WITHIN_FAMILY_MORPHOLOGY_THRESHOLD = 0.025
_EPSILON = 1e-12
_DISTANCE_WEIGHTS = {
    "component": 0.02,
    "axis": 0.12,
    "z_slice": 0.12,
    "floor": 0.12,
    "convexity": 0.08,
    "void": 0.08,
    "normal": 0.14,
    "radial": 0.12,
    "silhouette": 0.16,
    "contact": 0.04,
}


@dataclass(frozen=True)
class MorphologyDescriptor:
    axis_ratios: tuple[float, ...]
    z_slice_occupancies: tuple[float, ...]
    floor_area_profile: tuple[float, ...]
    convexity: float
    void_fraction: float
    normal_bins: tuple[float, ...]
    radial_bins: tuple[float, ...]
    silhouette_front: tuple[float, ...]
    silhouette_side: tuple[float, ...]
    silhouette_isometric: tuple[float, ...]
    component_count: int
    contact_topology: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MORPHOLOGY_SCHEMA,
            "axis_ratios": list(self.axis_ratios),
            "z_slice_occupancies": list(self.z_slice_occupancies),
            "floor_area_profile": list(self.floor_area_profile),
            "convexity": self.convexity,
            "void_fraction": self.void_fraction,
            "normal_bins": list(self.normal_bins),
            "radial_bins": list(self.radial_bins),
            "silhouette_front": list(self.silhouette_front),
            "silhouette_side": list(self.silhouette_side),
            "silhouette_isometric": list(self.silhouette_isometric),
            "component_count": self.component_count,
            "contact_topology": self.contact_topology,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MorphologyDescriptor:
        return cls(
            axis_ratios=_fixed_values(payload.get("axis_ratios"), 3),
            z_slice_occupancies=_fixed_values(
                payload.get("z_slice_occupancies"), 8
            ),
            floor_area_profile=_fixed_values(
                payload.get("floor_area_profile"), 8
            ),
            convexity=_unit_value(payload.get("convexity")),
            void_fraction=_unit_value(payload.get("void_fraction")),
            normal_bins=_fixed_values(payload.get("normal_bins"), 12),
            radial_bins=_fixed_values(payload.get("radial_bins"), 8),
            silhouette_front=_fixed_values(
                payload.get("silhouette_front"), 16
            ),
            silhouette_side=_fixed_values(
                payload.get("silhouette_side"), 16
            ),
            silhouette_isometric=_fixed_values(
                payload.get("silhouette_isometric"), 16
            ),
            component_count=max(0, int(payload.get("component_count") or 0)),
            contact_topology=str(payload.get("contact_topology") or "none"),
        )


class MorphologyDistance(float):
    """Numeric distance carrying its named raw and weighted evidence."""

    components: dict[str, float]
    weighted_components: dict[str, float]

    def __new__(
        cls,
        total: float,
        *,
        components: Mapping[str, float],
        weighted_components: Mapping[str, float],
    ) -> MorphologyDistance:
        instance = float.__new__(cls, _unit_value(total))
        instance.components = dict(components)
        instance.weighted_components = dict(weighted_components)
        return instance

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(float(self), 12),
            "components": dict(self.components),
            "weighted_components": dict(self.weighted_components),
        }


@dataclass(frozen=True)
class MorphologyDecision:
    accepted: bool
    nearest_distance: float
    nearest_within_family_distance: float | None
    threshold: float
    within_family_threshold: float
    closest_candidate_id: str | None
    closest_family_candidate_id: str | None
    failed_components: tuple[str, ...]
    distance: dict[str, Any] | None
    diagnostic: str

    def __bool__(self) -> bool:
        return self.accepted

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": "accepted" if self.accepted else "rejected",
            "accepted": self.accepted,
            "nearest_distance": round(self.nearest_distance, 12),
            "nearest_within_family_distance": (
                round(self.nearest_within_family_distance, 12)
                if self.nearest_within_family_distance is not None
                else None
            ),
            "threshold": self.threshold,
            "within_family_threshold": self.within_family_threshold,
            "closest_candidate_id": self.closest_candidate_id,
            "closest_family_candidate_id": (
                self.closest_family_candidate_id
            ),
            "failed_components": list(self.failed_components),
            "distance": self.distance,
            "diagnostic": self.diagnostic,
        }


def build_morphology_descriptor(
    *,
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    floor_areas: Sequence[float],
    component_count: int,
    contact_topology: str,
) -> MorphologyDescriptor:
    """Extract a deterministic descriptor after centroid/unit-diagonal fit."""

    features = extract_morphology_features(
        vertices=vertices,
        triangles=triangles,
        floor_areas=floor_areas,
    )
    return MorphologyDescriptor(
        **features,
        component_count=max(0, int(component_count)),
        contact_topology=str(contact_topology or "none"),
    )


def morphology_distance(
    left: MorphologyDescriptor | Mapping[str, Any],
    right: MorphologyDescriptor | Mapping[str, Any],
) -> MorphologyDistance:
    """Return a symmetric bounded distance with named weighted components."""

    a = _as_descriptor(left)
    b = _as_descriptor(right)
    components = {
        "component": min(
            1.0, abs(a.component_count - b.component_count) / 4.0
        ),
        "axis": _vector_distance(a.axis_ratios, b.axis_ratios),
        "z_slice": _distribution_distance(
            a.z_slice_occupancies, b.z_slice_occupancies
        ),
        "floor": _distribution_distance(
            a.floor_area_profile, b.floor_area_profile
        ),
        "convexity": abs(a.convexity - b.convexity),
        "void": abs(a.void_fraction - b.void_fraction),
        "normal": _distribution_distance(a.normal_bins, b.normal_bins),
        "radial": _distribution_distance(a.radial_bins, b.radial_bins),
        "silhouette": (
            _vector_distance(a.silhouette_front, b.silhouette_front)
            + _vector_distance(a.silhouette_side, b.silhouette_side)
            + _vector_distance(
                a.silhouette_isometric, b.silhouette_isometric
            )
        ) / 3.0,
        "contact": 0.0 if a.contact_topology == b.contact_topology else 1.0,
    }
    components = {
        name: round(_unit_value(value), 12)
        for name, value in components.items()
    }
    weighted = {
        name: round(components[name] * weight, 12)
        for name, weight in _DISTANCE_WEIGHTS.items()
    }
    return MorphologyDistance(
        sum(weighted.values()),
        components=components,
        weighted_components=weighted,
    )


def accept_morphology(
    candidate: Mapping[str, Any],
    accepted: Sequence[Mapping[str, Any]],
    *,
    global_threshold: float = GLOBAL_MORPHOLOGY_THRESHOLD,
    within_family_threshold: float = WITHIN_FAMILY_MORPHOLOGY_THRESHOLD,
) -> MorphologyDecision:
    """Evaluate global and same-family novelty without generating retries."""

    descriptor = _candidate_descriptor(candidate)
    family = str(candidate.get("family") or "")
    threshold = _threshold(global_threshold, "global_threshold")
    family_threshold = _threshold(
        within_family_threshold, "within_family_threshold"
    )
    if not accepted:
        return MorphologyDecision(
            accepted=True,
            nearest_distance=1.0,
            nearest_within_family_distance=None,
            threshold=threshold,
            within_family_threshold=family_threshold,
            closest_candidate_id=None,
            closest_family_candidate_id=None,
            failed_components=(),
            distance=None,
            diagnostic="accepted as the morphology portfolio seed",
        )

    measured = [
        (
            row,
            morphology_distance(descriptor, _candidate_descriptor(row)),
        )
        for row in accepted
    ]
    closest_row, closest_distance = min(
        measured,
        key=lambda item: (
            float(item[1]),
            str(item[0].get("candidate_id") or ""),
        ),
    )
    same_family = [
        item for item in measured if str(item[0].get("family") or "") == family
    ]
    closest_family_row: Mapping[str, Any] | None = None
    closest_family_distance: MorphologyDistance | None = None
    if same_family:
        closest_family_row, closest_family_distance = min(
            same_family,
            key=lambda item: (
                float(item[1]),
                str(item[0].get("candidate_id") or ""),
            ),
        )
    failed: list[str] = []
    if float(closest_distance) < threshold:
        failed.append("global")
    if (
        closest_family_distance is not None
        and float(closest_family_distance) < family_threshold
    ):
        failed.append("within_family")
    closest_id = str(closest_row.get("candidate_id") or "unknown")
    diagnostic = (
        f"morphology {'rejected' if failed else 'accepted'};"
        f" closest_candidate={closest_id};"
        f" distance={float(closest_distance):.6f};"
        f" failed_components={','.join(failed) if failed else 'none'}"
    )
    return MorphologyDecision(
        accepted=not failed,
        nearest_distance=float(closest_distance),
        nearest_within_family_distance=(
            float(closest_family_distance)
            if closest_family_distance is not None
            else None
        ),
        threshold=threshold,
        within_family_threshold=family_threshold,
        closest_candidate_id=closest_id,
        closest_family_candidate_id=(
            str(closest_family_row.get("candidate_id") or "unknown")
            if closest_family_row is not None
            else None
        ),
        failed_components=tuple(failed),
        distance=closest_distance.to_dict(),
        diagnostic=diagnostic,
    )


def audit_morphology_portfolio(
    candidates: Sequence[Mapping[str, Any]],
    *,
    global_threshold: float = GLOBAL_MORPHOLOGY_THRESHOLD,
    within_family_threshold: float = WITHIN_FAMILY_MORPHOLOGY_THRESHOLD,
) -> dict[str, Any]:
    """Audit a fixed schedule without changing, retrying, or filtering it."""

    preceding: list[Mapping[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = accept_morphology(
            candidate,
            preceding,
            global_threshold=global_threshold,
            within_family_threshold=within_family_threshold,
        )
        evidence = {
            "candidate_id": str(candidate.get("candidate_id") or "unknown"),
            "family": str(candidate.get("family") or ""),
            **decision.to_dict(),
        }
        decisions.append(evidence)
        preceding.append(candidate)
    rejections = [
        evidence for evidence in decisions if not evidence["accepted"]
    ]
    distances = [
        float(evidence["nearest_distance"])
        for evidence in decisions[1:]
    ]
    ordered = sorted(distances)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (
            (ordered[middle - 1] + ordered[middle]) / 2.0
            if ordered
            else None
        )
    )
    return {
        "schema_version": MORPHOLOGY_SCHEMA,
        "candidate_count": len(decisions),
        "accepted_count": len(decisions) - len(rejections),
        "rejected_count": len(rejections),
        "global_threshold": float(global_threshold),
        "within_family_threshold": float(within_family_threshold),
        "nearest_distance_distribution": {
            "count": len(ordered),
            "minimum": round(ordered[0], 12) if ordered else None,
            "median": round(median, 12) if median is not None else None,
            "maximum": round(ordered[-1], 12) if ordered else None,
        },
        "decisions": decisions,
        "rejections": rejections,
    }


def _candidate_descriptor(candidate: Mapping[str, Any]) -> MorphologyDescriptor:
    payload = candidate.get("morphology_descriptor")
    if payload is None:
        evidence = candidate.get("morphology_evidence")
        if isinstance(evidence, Mapping):
            payload = evidence.get("descriptor")
    if isinstance(payload, MorphologyDescriptor):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError("candidate requires morphology_descriptor evidence")
    return MorphologyDescriptor.from_dict(payload)


def _as_descriptor(
    value: MorphologyDescriptor | Mapping[str, Any],
) -> MorphologyDescriptor:
    if isinstance(value, MorphologyDescriptor):
        return value
    return MorphologyDescriptor.from_dict(value)


def _vector_distance(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("morphology vectors must have equal non-zero length")
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def _distribution_distance(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("morphology distributions must have equal length")
    return min(1.0, sum(abs(a - b) for a, b in zip(left, right)) / 2.0)


def _normalized_bins(values: Sequence[float]) -> tuple[float, ...]:
    total = sum(max(0.0, float(value)) for value in values)
    if total <= _EPSILON:
        return (0.0,) * len(values)
    return _rounded_tuple(max(0.0, float(value)) / total for value in values)


def _fixed_values(raw: Any, length: int) -> tuple[float, ...]:
    if not isinstance(raw, (list, tuple)) or len(raw) != length:
        raise ValueError(f"morphology vector must contain {length} values")
    return _rounded_tuple(_unit_value(value) for value in raw)


def _rounded_tuple(values: Iterable[float]) -> tuple[float, ...]:
    return tuple(round(float(value), 12) for value in values)


def _unit_value(value: Any) -> float:
    numeric = float(value or 0.0)
    if not isfinite(numeric):
        return 0.0
    return min(1.0, max(0.0, numeric))


def _rounded_unit(value: Any) -> float:
    return round(_unit_value(value), 12)


def _threshold(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return numeric


__all__ = [
    "GLOBAL_MORPHOLOGY_THRESHOLD",
    "MORPHOLOGY_SCHEMA",
    "WITHIN_FAMILY_MORPHOLOGY_THRESHOLD",
    "MorphologyDecision",
    "MorphologyDescriptor",
    "MorphologyDistance",
    "accept_morphology",
    "audit_morphology_portfolio",
    "build_morphology_descriptor",
    "morphology_distance",
]

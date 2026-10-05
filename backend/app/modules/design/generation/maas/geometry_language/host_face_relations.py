"""Normalized host/guest face relations for recursive architectural solids.

The author stores only dimensionless relations.  Absolute guest dimensions and
placement are resolved from the evaluated host and guest bounds at compile
time.  This keeps synthesis policy, face-frame math and geometry-kernel work in
separate modules and makes an Attach node reproducible on any Base Model size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ATTACH_PARAMETER_SPACE = "host_face_normalized.v1"


@dataclass(frozen=True)
class FaceAttachmentSamplingPolicy:
    faces: tuple[str, ...] = ("east", "north", "west", "south", "top")
    anchor_u_limit: float = 0.32
    anchor_v_limit: float = 0.24
    span_u_range: tuple[float, float] = (0.35, 0.68)
    span_v_range: tuple[float, float] = (0.32, 0.62)
    projection_range: tuple[float, float] = (0.18, 0.38)
    # Engagement is measured against the resolved guest projection, not the
    # whole host thickness. This keeps a guest visibly attached instead of
    # swallowing a small volume inside a deep Base Model.
    engagement_range: tuple[float, float] = (0.10, 0.22)
    rotations_degrees: tuple[float, ...] = (-12.0, 0.0, 12.0)


@dataclass(frozen=True)
class FaceAttachmentResolution:
    face: str
    normal_axis: int
    normal_sign: float
    u_axis: int
    v_axis: int
    target_span: tuple[float, float, float]
    target_center: tuple[float, float, float]
    rotation_degrees: float
    engagement_distance: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_space": ATTACH_PARAMETER_SPACE,
            "face": self.face,
            "normal_axis": self.normal_axis,
            "normal_sign": self.normal_sign,
            "u_axis": self.u_axis,
            "v_axis": self.v_axis,
            "target_span": list(self.target_span),
            "target_center": list(self.target_center),
            "rotation_degrees": self.rotation_degrees,
            "engagement_distance": self.engagement_distance,
        }


DEFAULT_FACE_ATTACHMENT_POLICY = FaceAttachmentSamplingPolicy()


_FACE_FRAMES: dict[str, tuple[int, float, int, int]] = {
    "east": (0, 1.0, 1, 2),
    "west": (0, -1.0, 1, 2),
    "north": (1, 1.0, 0, 2),
    "south": (1, -1.0, 0, 2),
    "top": (2, 1.0, 0, 1),
    "bottom": (2, -1.0, 0, 1),
}

HOST_FACES = frozenset(_FACE_FRAMES)


def sample_face_attachment_parameters(
    index: int,
    unit_u: float,
    unit_v: float,
    *,
    policy: FaceAttachmentSamplingPolicy = DEFAULT_FACE_ATTACHMENT_POLICY,
) -> dict[str, Any]:
    """Sample an explicit, dimensionless Attach program parameter set."""

    u = max(0.0, min(1.0, float(unit_u)))
    v = max(0.0, min(1.0, float(unit_v)))
    return {
        "parameter_space": ATTACH_PARAMETER_SPACE,
        "host_basis": "evaluated_input_0_bounds",
        "host_face": policy.faces[max(0, int(index)) % len(policy.faces)],
        "anchor": [
            round(-policy.anchor_u_limit + 2.0 * policy.anchor_u_limit * u, 3),
            round(-policy.anchor_v_limit + 2.0 * policy.anchor_v_limit * v, 3),
        ],
        # [normal projection, local-u coverage, local-v coverage].  These are
        # multiplied by the corresponding evaluated host-face spans.
        "guest_extent": [
            round(_lerp(policy.projection_range, u), 3),
            round(_lerp(policy.span_u_range, u), 3),
            round(_lerp(policy.span_v_range, v), 3),
        ],
        "engagement": round(_lerp(policy.engagement_range, v), 3),
        "rotation_degrees": policy.rotations_degrees[
            max(0, int(index)) % len(policy.rotations_degrees)
        ],
    }


def resolve_face_attachment(
    host_bounds: tuple[float, float, float, float, float, float],
    guest_bounds: tuple[float, float, float, float, float, float],
    parameters: dict[str, Any],
) -> FaceAttachmentResolution:
    """Resolve normalized Attach parameters against a live Base Model face."""

    face = str(parameters.get("host_face") or "east").lower()
    if face not in _FACE_FRAMES:
        raise ValueError(f"unsupported host face: {face}")
    normal_axis, sign, u_axis, v_axis = _FACE_FRAMES[face]
    host_min = [float(host_bounds[0]), float(host_bounds[1]), float(host_bounds[2])]
    host_max = [float(host_bounds[3]), float(host_bounds[4]), float(host_bounds[5])]
    host_span = [max(host_max[i] - host_min[i], 1e-7) for i in range(3)]
    host_center = [(host_min[i] + host_max[i]) / 2.0 for i in range(3)]
    guest_span = [
        max(float(guest_bounds[i + 3]) - float(guest_bounds[i]), 1e-7)
        for i in range(3)
    ]

    anchor = parameters.get("anchor") or (
        parameters.get("anchor_u", 0.0), parameters.get("anchor_v", 0.0)
    )
    if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
        raise ValueError("attach anchor must contain local u/v values")
    anchor_u = max(-0.9, min(0.9, float(anchor[0])))
    anchor_v = max(-0.9, min(0.9, float(anchor[1])))

    extent = parameters.get("guest_extent") or (
        parameters.get("depth_ratio", 0.18),
        parameters.get("width_ratio", 0.38),
        parameters.get("height_ratio", 0.38),
    )
    if not isinstance(extent, (list, tuple)) or len(extent) != 3:
        raise ValueError("attach guest_extent must contain normal/u/v ratios")
    projection = max(0.06, min(0.48, float(extent[0])))
    span_u = max(0.12, min(0.82, float(extent[1])))
    span_v = max(0.12, min(0.82, float(extent[2])))
    target_span = list(guest_span)
    target_span[normal_axis] = host_span[normal_axis] * projection
    target_span[u_axis] = host_span[u_axis] * span_u
    target_span[v_axis] = host_span[v_axis] * span_v

    target_center = list(host_center)
    target_center[u_axis] += anchor_u * max(0.0, host_span[u_axis] - target_span[u_axis]) / 2.0
    target_center[v_axis] += anchor_v * max(0.0, host_span[v_axis] - target_span[v_axis]) / 2.0
    engagement_ratio = max(0.015, min(0.24, float(
        parameters.get("engagement", parameters.get("embed_ratio", 0.10))
    )))
    engagement_distance = target_span[normal_axis] * engagement_ratio
    face_coordinate = host_max[normal_axis] if sign > 0 else host_min[normal_axis]
    target_center[normal_axis] = face_coordinate + sign * (
        target_span[normal_axis] / 2.0 - engagement_distance
    )
    return FaceAttachmentResolution(
        face=face,
        normal_axis=normal_axis,
        normal_sign=sign,
        u_axis=u_axis,
        v_axis=v_axis,
        target_span=tuple(target_span),
        target_center=tuple(target_center),
        rotation_degrees=max(
            -45.0,
            min(45.0, float(parameters.get("rotation_degrees", 0.0))),
        ),
        engagement_distance=engagement_distance,
    )


def _lerp(bounds: tuple[float, float], unit: float) -> float:
    return float(bounds[0]) + (float(bounds[1]) - float(bounds[0])) * unit


__all__ = [
    "ATTACH_PARAMETER_SPACE",
    "HOST_FACES",
    "DEFAULT_FACE_ATTACHMENT_POLICY",
    "FaceAttachmentResolution",
    "FaceAttachmentSamplingPolicy",
    "resolve_face_attachment",
    "sample_face_attachment_parameters",
]

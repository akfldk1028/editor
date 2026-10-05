"""Turn the lawful field's band relations into generic seed proportions.

The deterministic form supply picks BaseVolume proportions without ever seeing
the lawful field, so a constant-section seed is routinely authored into a
field that narrows with height.  Downstream it cannot reach its capacity
target at any pose, gets pushed into floorwise repair, and comes back wearing
the envelope's own silhouette — which is how a portfolio collapses onto one
shape.

This module publishes what a seed needs in order to be *proportionally*
plausible in that field: how the lawful plan is proportioned, how much lawful
area survives with height, and which way the field retreats.  It never selects
a form, names a typology, or emits a parcel coordinate — a consumer is free to
ignore every value here and still produce lawful geometry.
"""

from __future__ import annotations

from math import isfinite
from typing import Any


SCHEMA_VERSION = "arr.maas.legal_envelope_seed_conditioning.v1"

AUTHORITY = "proportion_guidance_only_not_form_selection"


def envelope_seed_conditioning(
    design_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive generic seed proportions from one normalized lawful field.

    Returns an empty dict when the lawful field is absent or unusable, so a
    consumer can treat "no guidance" as "carry on unconditioned".
    """

    context = design_context if isinstance(design_context, dict) else {}
    bands = context.get("bands")
    if not isinstance(bands, list) or not bands:
        return {}
    ratios = _band_area_ratios(bands)
    if ratios is None:
        return {}
    plan_aspect = _positive_float(context.get("ground_long_to_short_aspect"))
    if plan_aspect is None:
        return {}
    retreat = _axis_retreat(bands)
    if retreat is None:
        return {}
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "plan_aspect": plan_aspect,
        "band_area_ratios": ratios,
        **retreat,
        # A constant-section prism standing on the lawful ground can only ever
        # occupy the mean of the band ratios.  When a capacity target exceeds
        # this share of the lawful volume, no straight prism can satisfy it and
        # the seed has to taper, step or shrink in plan instead.
        "prism_efficiency_ceiling": round(sum(ratios) / len(ratios), 6),
        "taper_ratio": round(ratios[-1], 6),
    }


# A real parcel boundary is not axis-aligned, so its principal-frame extents
# carry sub-percent noise. Judging contraction at float tolerance reports a
# 0.003% wobble as a setback and tells a seed to taper in a direction the law
# never asked for. One percent of an axis is the smallest change that can mean
# a real legal setback at building scale.
_RETENTION_EPSILON = 0.01

# Sides are compared to each other rather than to the axis length, so they keep
# a tighter tolerance: the question is only which end moved further.
_SIDE_EPSILON = 1e-6


def _axis_retreat(bands: list[Any]) -> dict[str, Any] | None:
    """Report how much of each plan axis survives to the topmost lawful band.

    Naming the retreating axis and end is what lets a seed lean, notch or taper
    *towards* the lawful field instead of being trimmed by it afterwards.
    """

    ground = _axis_extents(bands[0])
    top = _axis_extents(bands[-1])
    if ground is None or top is None:
        return None
    (long_min, long_max), (short_min, short_max) = ground
    (top_long_min, top_long_max), (top_short_min, top_short_max) = top
    long_span = long_max - long_min
    short_span = short_max - short_min
    if long_span <= _SIDE_EPSILON or short_span <= _SIDE_EPSILON:
        return None
    long_retention = (top_long_max - top_long_min) / long_span
    short_retention = (top_short_max - top_short_min) / short_span
    long_contracts = long_retention < 1.0 - _RETENTION_EPSILON
    short_contracts = short_retention < 1.0 - _RETENTION_EPSILON
    if long_contracts and short_contracts:
        axis = "both"
    elif long_contracts:
        axis = "long"
    elif short_contracts:
        axis = "short"
    else:
        axis = "none"
    if axis == "long":
        side = _retreating_side(long_min, long_max, top_long_min, top_long_max)
    elif axis == "short":
        side = _retreating_side(
            short_min, short_max, top_short_min, top_short_max
        )
    elif axis == "both":
        side = "both"
    else:
        side = "none"
    ground_centroids = _centroids(bands[0])
    top_centroids = _centroids(bands[-1])
    if ground_centroids is None or top_centroids is None:
        return None
    return {
        "long_axis_retention": round(long_retention, 6),
        "short_axis_retention": round(short_retention, 6),
        "contraction_axis": axis,
        "contraction_side": side,
        "centroid_drift_long": round(
            top_centroids[0] - ground_centroids[0], 6
        ),
        "centroid_drift_short": round(
            top_centroids[1] - ground_centroids[1], 6
        ),
    }


def _retreating_side(
    ground_min: float,
    ground_max: float,
    top_min: float,
    top_max: float,
) -> str:
    advanced = top_min - ground_min
    receded = ground_max - top_max
    if advanced - receded > _SIDE_EPSILON:
        return "min"
    if receded - advanced > _SIDE_EPSILON:
        return "max"
    return "both"


def _axis_extents(
    band: Any,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if not isinstance(band, dict):
        return None
    values = [
        _finite_float(band.get(key))
        for key in (
            "long_axis_min",
            "long_axis_max",
            "short_axis_min",
            "short_axis_max",
        )
    ]
    if any(value is None for value in values):
        return None
    long_min, long_max, short_min, short_max = values  # type: ignore[misc]
    if long_max < long_min or short_max < short_min:
        return None
    return (long_min, long_max), (short_min, short_max)


def _centroids(band: Any) -> tuple[float, float] | None:
    if not isinstance(band, dict):
        return None
    long_centroid = _finite_float(band.get("centroid_long_axis"))
    short_centroid = _finite_float(band.get("centroid_short_axis"))
    if long_centroid is None or short_centroid is None:
        return None
    return long_centroid, short_centroid


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _band_area_ratios(bands: list[Any]) -> tuple[float, ...] | None:
    ratios: list[float] = []
    for band in bands:
        if not isinstance(band, dict):
            return None
        ratio = _positive_float(band.get("area_ratio_to_ground"))
        if ratio is None:
            return None
        ratios.append(ratio)
    return tuple(ratios)


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not isfinite(number) or number <= 0.0:
        return None
    return round(number, 6)


__all__ = [
    "AUTHORITY",
    "SCHEMA_VERSION",
    "envelope_seed_conditioning",
]

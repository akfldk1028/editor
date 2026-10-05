"""Immutable PNU legal-floor field independent of any candidate stack."""

from __future__ import annotations

import hashlib
import json
from math import floor, isfinite
from typing import Any, Mapping

from shapely.geometry import Polygon, mapping, shape

from backend.app.modules.design.generation.maas.floor_viability import evaluate_floor_section_viability

from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import LegalGenerationContext, generation_site_at_height


SCHEMA_VERSION = "arr.maas.legal_floor_field.v1"
AUTHORITY = "pnu_legal_height_x_live_floor_sections_x_bcr_x_far"
MAX_TERMINAL_REASON_LENGTH = 256
TERMINAL_FLOOR_EXCLUSION_REASONS = frozenset({
    "missing_legal_floor_section",
    "insufficient_floor_area",
    "insufficient_clear_floor_depth",
})
LEGAL_FLOOR_FIELD_KEYS = frozenset({
    "schema_version",
    "status",
    "authority",
    "pnu",
    "typical_floor_height_m",
    "legal_height_cap_m",
    "parcel_area_m2",
    "bcr_limit_pct",
    "bcr_footprint_capacity_m2",
    "far_limit_pct",
    "statutory_far_capacity_m2",
    "legal_floor_top_heights_m",
    "legal_floor_section_areas_m2",
    "bcr_adjusted_floor_capacities_m2",
    "legal_floor_sections",
    "measured_usable_floor_count",
    "height_field_capacity_m2",
    "feasible_maximum_gfa_m2",
    "statutory_far_reachable",
    "terminal_floor_exclusion_reasons",
    "candidate_floor_count",
    "candidate_target_gfa_m2",
    "candidate_identity",
    "legal_floor_field_hash",
})
GEOJSON_POLYGON_KEYS = frozenset({"type", "coordinates"})


def materialize_legal_floor_field(
    context: LegalGenerationContext,
    *,
    site_local_utm: Polygon,
    pnu: str = "",
) -> dict[str, Any]:
    """Measure every viable legal floor section through the PNU height field."""

    envelope = context.envelope
    floor_height = max(0.1, float(envelope.floor_height))
    height_cap = max(0.0, float(envelope.height_limit))
    legal_floor_count = int(height_cap / floor_height)
    parcel_area = max(float(site_local_utm.area), 1e-9)
    sections: list[Polygon] = []
    areas: list[float] = []
    tops: list[float] = []
    terminal_reasons: list[str] = []

    for floor_number in range(1, legal_floor_count + 1):
        top_height = floor_number * floor_height
        section = generation_site_at_height(context, top_height)
        if section is None or section.is_empty:
            terminal_reasons = ["missing_legal_floor_section"]
            break
        viability = evaluate_floor_section_viability(
            section,
            parcel_area_m2=parcel_area,
        )
        if viability["hard_pass"] is not True:
            terminal_reasons = list(viability["failure_reasons"])
            break
        sections.append(section)
        areas.append(float(section.area))
        tops.append(top_height)

    bcr_limit = max(0.0, float(envelope.bcr_limit))
    far_limit = max(0.0, float(envelope.far_limit))
    bcr_cap = parcel_area * bcr_limit / 100.0
    far_cap = parcel_area * far_limit / 100.0
    # Coverage is the building's horizontal projection (건축법 시행령 제119조
    # 제1항 제2호), so an overhanging upper plate governs it. Every plate is
    # bounded, not just the ground one - see the note in floor_capacity_plan.
    # The aggregate is summed from the *stored* per-floor capacities, not from
    # the raw ones. The validator recomputes it from what the payload carries,
    # so summing unrounded values and storing the rounded total leaves the
    # payload inconsistent with itself by up to n x half an ulp of the stored
    # precision. That stayed inside the 0.002 tolerance only while the plates
    # differed and their rounding errors cancelled; with coverage bounding
    # every plate, sixteen identical 499.938 capacities put the error at
    # 0.0020000000004 - just over - and the whole run was rejected as
    # `authoritative_run_legal_floor_field_invalid`.
    floor_caps = [_round(min(area, bcr_cap)) for area in areas]
    height_field_capacity = sum(floor_caps)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "materialized" if sections else "infeasible",
        "authority": AUTHORITY,
        "pnu": pnu if type(pnu) is str else "PNU_INVALID",
        "typical_floor_height_m": _round(floor_height),
        "legal_height_cap_m": _round(height_cap),
        "parcel_area_m2": _round(parcel_area),
        "bcr_limit_pct": _round(bcr_limit),
        "bcr_footprint_capacity_m2": _round(bcr_cap),
        "far_limit_pct": _round(far_limit),
        "statutory_far_capacity_m2": _round(far_cap),
        "legal_floor_top_heights_m": [_round(value) for value in tops],
        "legal_floor_section_areas_m2": [_round(value) for value in areas],
        "bcr_adjusted_floor_capacities_m2": list(floor_caps),
        "legal_floor_sections": [mapping(section) for section in sections],
        "measured_usable_floor_count": len(sections),
        "height_field_capacity_m2": _round(height_field_capacity),
        "feasible_maximum_gfa_m2": _round(
            min(height_field_capacity, far_cap)
        ),
        "statutory_far_reachable": bool(
            height_field_capacity + 1e-9 >= far_cap
        ),
        "terminal_floor_exclusion_reasons": terminal_reasons,
        "candidate_floor_count": None,
        "candidate_target_gfa_m2": None,
        "candidate_identity": None,
    }
    payload["legal_floor_field_hash"] = _payload_hash(payload)
    return payload


def validate_legal_floor_field(payload: Mapping[str, Any] | None) -> bool:
    """Verify structure, geometry measurements and the content-addressed seal."""

    try:
        return _validate_legal_floor_field(payload)
    except Exception:
        # This is a trust-boundary validator. Malformed or adversarial JSON
        # must be rejected rather than escaping as a conversion/GEOS error.
        return False


def _validate_legal_floor_field(payload: Mapping[str, Any] | None) -> bool:
    if not _valid_legal_floor_field_boundary_shape(payload):
        return False
    expected_hash = payload.get("legal_floor_field_hash")
    canonical = dict(payload)
    canonical.pop("legal_floor_field_hash", None)
    if _payload_hash(canonical) != expected_hash:
        return False

    sections = payload.get("legal_floor_sections")
    areas = payload.get("legal_floor_section_areas_m2")
    caps = payload.get("bcr_adjusted_floor_capacities_m2")
    tops = payload.get("legal_floor_top_heights_m")
    terminal_reasons = payload.get("terminal_floor_exclusion_reasons")
    raw_count = payload.get("measured_usable_floor_count")
    if type(raw_count) is not int:
        return False
    count = raw_count
    if (
        count <= 0
        or type(sections) is not list
        or type(areas) is not list
        or type(caps) is not list
        or type(tops) is not list
        or not all(len(values) == count for values in (sections, areas, caps, tops))
        or type(terminal_reasons) is not list
        or any(
            type(reason) is not str
            or not reason.strip()
            or len(reason) > MAX_TERMINAL_REASON_LENGTH
            or reason not in TERMINAL_FLOOR_EXCLUSION_REASONS
            for reason in terminal_reasons
        )
    ):
        return False

    previous_top = 0.0
    normalized_areas: list[float] = []
    normalized_caps: list[float] = []
    normalized_tops: list[float] = []
    raw_scalars = (
        payload.get("typical_floor_height_m"),
        payload.get("legal_height_cap_m"),
        payload.get("parcel_area_m2"),
        payload.get("bcr_limit_pct"),
        payload.get("bcr_footprint_capacity_m2"),
        payload.get("far_limit_pct"),
        payload.get("statutory_far_capacity_m2"),
        payload.get("height_field_capacity_m2"),
        payload.get("feasible_maximum_gfa_m2"),
    )
    if not all(_is_json_number(value) for value in raw_scalars):
        return False
    try:
        floor_height = float(payload.get("typical_floor_height_m"))
        height_cap = float(payload.get("legal_height_cap_m"))
        parcel_area = float(payload.get("parcel_area_m2"))
        bcr_limit = float(payload.get("bcr_limit_pct"))
        bcr_cap = float(payload.get("bcr_footprint_capacity_m2"))
        far_limit = float(payload.get("far_limit_pct"))
        far_cap = float(payload.get("statutory_far_capacity_m2"))
        stored_height_capacity = float(payload.get("height_field_capacity_m2"))
        stored_feasible = float(payload.get("feasible_maximum_gfa_m2"))
    except (TypeError, ValueError):
        return False
    legal_max = int(floor(height_cap / floor_height))
    if (
        not all(isfinite(value) for value in (
            floor_height,
            height_cap,
            parcel_area,
            bcr_limit,
            bcr_cap,
            far_limit,
            far_cap,
            stored_height_capacity,
            stored_feasible,
        ))
        or floor_height <= 0.0
        or height_cap < floor_height
        or parcel_area <= 0.0
        or min(bcr_limit, bcr_cap, far_limit, far_cap) < 0.0
        or abs(bcr_cap - parcel_area * bcr_limit / 100.0) > 0.002
        or abs(far_cap - parcel_area * far_limit / 100.0) > 0.002
        or count > legal_max
        or (count == legal_max and bool(terminal_reasons))
        or (count < legal_max and not terminal_reasons)
    ):
        return False

    for index, (raw_section, raw_area, raw_cap, raw_top) in enumerate(zip(
        sections,
        areas,
        caps,
        tops,
    )):
        if type(raw_section) is not dict:
            return False
        if not all(
            _is_json_number(value)
            for value in (raw_area, raw_cap, raw_top)
        ):
            return False
        try:
            section = shape(raw_section)
            area = float(raw_area)
            cap = float(raw_cap)
            top = float(raw_top)
        except (TypeError, ValueError):
            return False
        if (
            not isinstance(section, Polygon)
            or section.is_empty
            or not section.is_valid
            or not all(isfinite(value) for value in (area, cap, top))
            or area <= 0.0
            or cap < 0.0
            or cap > area + 0.002
            or abs(float(section.area) - area) > 0.002
            or top <= previous_top
            or abs(top - floor_height * (index + 1)) > 0.002
            or top > height_cap + 0.002
        ):
            return False
        # Coverage bounds every plate, since it is the building's horizontal
        # projection (건축법 시행령 제119조 제1항 제2호) - see the note where these
        # capacities are produced.
        expected_cap = min(area, bcr_cap)
        if abs(cap - expected_cap) > 0.002:
            return False
        normalized_areas.append(area)
        normalized_caps.append(cap)
        normalized_tops.append(top)
        previous_top = top
    height_capacity = sum(normalized_caps)
    feasible = min(height_capacity, far_cap)
    if (
        abs(stored_height_capacity - height_capacity) > 0.002
        or abs(stored_feasible - feasible) > 0.002
        or payload.get("statutory_far_reachable")
        is not bool(height_capacity + 1e-9 >= far_cap)
    ):
        return False
    return True


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _valid_legal_floor_field_boundary_shape(payload: Any) -> bool:
    """Reject non-plain or open-ended evidence before hashing/arithmetic."""

    if (
        type(payload) is not dict
        or frozenset(payload) != LEGAL_FLOOR_FIELD_KEYS
        or type(payload.get("schema_version")) is not str
        or payload.get("schema_version") != SCHEMA_VERSION
        or type(payload.get("status")) is not str
        or payload.get("status") != "materialized"
        or type(payload.get("authority")) is not str
        or payload.get("authority") != AUTHORITY
        or not _is_canonical_pnu(payload.get("pnu"))
        or not _is_canonical_sha256(
            payload.get("legal_floor_field_hash")
        )
        or type(payload.get("measured_usable_floor_count")) is not int
        or type(payload.get("statutory_far_reachable")) is not bool
        or payload.get("candidate_floor_count") is not None
        or payload.get("candidate_target_gfa_m2") is not None
        or payload.get("candidate_identity") is not None
    ):
        return False

    scalar_keys = (
        "typical_floor_height_m",
        "legal_height_cap_m",
        "parcel_area_m2",
        "bcr_limit_pct",
        "bcr_footprint_capacity_m2",
        "far_limit_pct",
        "statutory_far_capacity_m2",
        "height_field_capacity_m2",
        "feasible_maximum_gfa_m2",
    )
    if not all(_is_json_number(payload.get(key)) for key in scalar_keys):
        return False

    list_keys = (
        "legal_floor_top_heights_m",
        "legal_floor_section_areas_m2",
        "bcr_adjusted_floor_capacities_m2",
        "legal_floor_sections",
        "terminal_floor_exclusion_reasons",
    )
    if any(type(payload.get(key)) is not list for key in list_keys):
        return False
    if not all(
        _is_json_number(value)
        for key in (
            "legal_floor_top_heights_m",
            "legal_floor_section_areas_m2",
            "bcr_adjusted_floor_capacities_m2",
        )
        for value in payload[key]
    ):
        return False
    if not all(
        _valid_geojson_polygon_boundary_shape(section)
        for section in payload["legal_floor_sections"]
    ):
        return False
    return all(
        type(reason) is str
        and bool(reason.strip())
        and len(reason) <= MAX_TERMINAL_REASON_LENGTH
        and reason in TERMINAL_FLOOR_EXCLUSION_REASONS
        for reason in payload["terminal_floor_exclusion_reasons"]
    )


def _valid_geojson_polygon_boundary_shape(value: Any) -> bool:
    if (
        type(value) is not dict
        or frozenset(value) != GEOJSON_POLYGON_KEYS
        or type(value.get("type")) is not str
        or value.get("type") != "Polygon"
    ):
        return False
    coordinates = value.get("coordinates")
    if type(coordinates) not in (list, tuple) or not coordinates:
        return False
    for ring in coordinates:
        if type(ring) not in (list, tuple) or len(ring) < 4:
            return False
        for point in ring:
            if (
                type(point) not in (list, tuple)
                or len(point) != 2
                or not all(_is_json_number(value) for value in point)
            ):
                return False
    return True


def _is_canonical_sha256(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_json_number(value: Any) -> bool:
    return bool(
        type(value) in (int, float)
        and isfinite(float(value))
    )


def _is_canonical_pnu(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 19
        and all("0" <= character <= "9" for character in value)
    )


def _round(value: float) -> float:
    return round(float(value), 3)


__all__ = [
    "SCHEMA_VERSION",
    "materialize_legal_floor_field",
    "validate_legal_floor_field",
]

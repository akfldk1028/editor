"""Fail-closed candidate-specific floor-count and actual-GFA certificate."""

from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field


SCHEMA_VERSION = "arr.maas.candidate_actual_gfa_stop.v1"
GFA_TOLERANCE_M2 = 1e-6
AREA_SERIALIZATION_QUANTUM_M2 = 1e-6
GFA_MESH_OVERLAY_TOLERANCE_M2 = 1e-5
IDENTITY_KEYS = (
    "program_hash",
    "final_geometry_hash",
    "visual_hash",
)
IDENTITY_KEY_SET = frozenset(IDENTITY_KEYS)
CERTIFICATE_IDENTITY_KEYS = frozenset({
    *IDENTITY_KEYS,
    "pnu",
})
CONTAINMENT_KEYS = frozenset({
    "floor_number",
    "contained",
    "actual_area_m2",
    "legal_floor_field_hash",
    *IDENTITY_KEYS,
})
CERTIFICATE_KEYS = frozenset({
    "schema_version",
    "status",
    "hard_pass",
    "legal_floor_field_hash",
    "identity",
    "program_hash",
    "final_geometry_hash",
    "visual_hash",
    "pnu",
    "target_gfa_m2",
    "actual_floor_areas_m2",
    "containment_evidence",
    "selected_floor_count",
    "terminal_floor_number",
    "achieved_gfa_m2",
    "terminal_residual_area_m2",
    "terminal_actual_area_m2",
    "terminal_overshoot_area_m2",
    "terminal_handling",
    "geometry_was_mutated",
    "failure_reasons",
    "candidate_actual_gfa_stop_hash",
})
CERTIFICATE_STATUSES = frozenset({
    "certified",
    "rejected",
    "target_unreachable",
})
TERMINAL_HANDLING_VALUES = frozenset({
    "not_applicable",
    "reject_nonminimal_floor_count",
    "reject_unauthored_terminal_adjustment",
    "exact_stop",
})


def certify_candidate_actual_gfa_stop(
    *,
    legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    expected_pnu: str,
    expected_identity: Mapping[str, Any],
    measured_identity: Mapping[str, Any],
    actual_floor_areas_m2: Sequence[float],
    containment_evidence: Sequence[Mapping[str, Any]],
    target_gfa_m2: float,
    tolerance_m2: Any = GFA_TOLERANCE_M2,
) -> dict[str, Any]:
    """Total fail-closed boundary for one candidate's actual-GFA stop."""

    try:
        return _certify_candidate_actual_gfa_stop(
            legal_floor_field=legal_floor_field,
            expected_legal_floor_field_hash=(
                expected_legal_floor_field_hash
            ),
            expected_pnu=expected_pnu,
            expected_identity=expected_identity,
            measured_identity=measured_identity,
            actual_floor_areas_m2=actual_floor_areas_m2,
            containment_evidence=containment_evidence,
            target_gfa_m2=target_gfa_m2,
            tolerance_m2=tolerance_m2,
        )
    except Exception:
        return _boundary_rejection_certificate()


def _certify_candidate_actual_gfa_stop(
    *,
    legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    expected_pnu: str,
    expected_identity: Mapping[str, Any],
    measured_identity: Mapping[str, Any],
    actual_floor_areas_m2: Sequence[float],
    containment_evidence: Sequence[Mapping[str, Any]],
    target_gfa_m2: float,
    tolerance_m2: Any,
) -> dict[str, Any]:
    """Certify the first actual floor where one bound candidate reaches GFA.

    This function never changes geometry.  Any uncorrected terminal overshoot
    or positive floor above the first target hit fails closed.
    """

    field = legal_floor_field if type(legal_floor_field) is dict else {}
    expected_identity_valid = _valid_identity_input(expected_identity)
    measured_identity_valid = _valid_identity_input(measured_identity)
    expected_source = expected_identity if expected_identity_valid else {}
    measured_source = measured_identity if measured_identity_valid else {}
    raw_field_hash = field.get("legal_floor_field_hash")
    raw_field_pnu = field.get("pnu")
    field_hash = raw_field_hash if type(raw_field_hash) is str else ""
    field_pnu = (
        raw_field_pnu
        if _is_canonical_pnu(raw_field_pnu)
        else ""
    )
    identity = {
        key: (
            measured_source.get(key)
            if type(measured_source.get(key)) is str
            else ""
        )
        for key in IDENTITY_KEYS
    }
    identity["pnu"] = field_pnu
    failures: list[str] = []
    if not _valid_sha256(expected_legal_floor_field_hash):
        failures.append("invalid_expected_legal_floor_field_hash")
    elif (
        not field_hash
        or field_hash != expected_legal_floor_field_hash
    ):
        failures.append("legal_floor_field_identity_mismatch")
    if failures:
        return _certificate(
            status="rejected",
            hard_pass=False,
            legal_floor_field_hash=field_hash,
            identity=identity,
            target_gfa_m2=target_gfa_m2,
            actual_floor_areas_m2=(),
            containment_evidence=(),
            failures=failures,
        )
    if not validate_legal_floor_field(field):
        failures.append("invalid_legal_floor_field")
    expected = {
        key: (
            expected_source.get(key)
            if type(expected_source.get(key)) is str
            else ""
        )
        for key in IDENTITY_KEYS
    }
    expected_pnu_valid = _is_canonical_pnu(expected_pnu)
    if not expected_pnu_valid:
        failures.append("invalid_expected_pnu")
    if (
        not field_pnu
        or not expected_pnu_valid
        or field_pnu != expected_pnu
    ):
        failures.append("pnu_identity_mismatch")
    if (
        not expected_identity_valid
        or not measured_identity_valid
        or any(
            not _valid_sha256(value)
            for key in IDENTITY_KEYS
            for value in (expected[key], identity[key])
        )
        or any(identity[key] != expected[key] for key in IDENTITY_KEYS)
    ):
        failures.append("candidate_identity_mismatch")

    if (
        not _is_json_number(tolerance_m2)
        or float(tolerance_m2) != GFA_TOLERANCE_M2
    ):
        failures.append("invalid_tolerance_m2")
    tolerance = GFA_TOLERANCE_M2

    raw_field_count = field.get("measured_usable_floor_count")
    if type(raw_field_count) is int:
        field_count = raw_field_count
    else:
        field_count = 0
        failures.append("invalid_legal_floor_count")
    raw_areas = _sequence_items(actual_floor_areas_m2)
    if raw_areas is None or not all(
        _is_json_number(value) for value in raw_areas
    ):
        areas = ()
        failures.append("invalid_actual_floor_area")
        if raw_areas is not None and any(
            type(value) in (int, float) and not isfinite(float(value))
            for value in raw_areas
        ):
            failures.append("nonfinite_actual_floor_area")
    else:
        areas = tuple(float(value) for value in raw_areas)
    if len(areas) != field_count:
        failures.append("actual_floor_area_count_mismatch")
    if any(value < 0.0 for value in areas if isfinite(value)):
        failures.append("negative_actual_floor_area")

    rows = _canonical_containment_rows(containment_evidence)
    if rows is None:
        rows = ()
        failures.append("invalid_containment_evidence")
    if len(rows) != field_count:
        failures.append("containment_evidence_count_mismatch")
    raw_caps = field.get("bcr_adjusted_floor_capacities_m2")
    if (
        type(raw_caps) is list
        and all(_is_json_number(value) for value in raw_caps)
    ):
        caps = tuple(float(value) for value in raw_caps)
    else:
        caps = ()
        failures.append("invalid_legal_floor_capacity")
    if len(caps) != field_count:
        failures.append("legal_floor_capacity_count_mismatch")

    if (
        len(rows) == field_count
        and len(areas) == field_count
        and len(caps) == field_count
    ):
        for index, (row, area, cap) in enumerate(zip(rows, areas, caps)):
            if not isinstance(row, Mapping):
                failures.append("invalid_containment_evidence")
                continue
            evidence_area = float(row["actual_area_m2"])
            floor_number = row["floor_number"]
            if (
                floor_number != index + 1
                or row.get("contained") is not True
                or str(row.get("legal_floor_field_hash") or "") != field_hash
                or any(
                    str(row.get(key) or "") != identity[key]
                    for key in IDENTITY_KEYS
                )
                or not isfinite(evidence_area)
                or not isfinite(area)
                or abs(evidence_area - area) > tolerance
            ):
                failures.append("invalid_containment_evidence")
            if isfinite(area) and area > cap + tolerance:
                failures.append("actual_floor_area_exceeds_legal_capacity")

    if _is_json_number(target_gfa_m2):
        target = float(target_gfa_m2)
    else:
        target = float("nan")
    if not isfinite(target) or target <= 0.0:
        failures.append("invalid_target_gfa")
    try:
        feasible_capacity = float(
            field.get("feasible_maximum_gfa_m2")
        )
        statutory_far_capacity = float(
            field.get("statutory_far_capacity_m2")
        )
        legal_capacity = min(
            feasible_capacity,
            statutory_far_capacity,
        )
    except (TypeError, ValueError):
        legal_capacity = float("nan")
    if (
        not isfinite(legal_capacity)
        or legal_capacity < 0.0
    ):
        failures.append("invalid_legal_gfa_capacity")
    else:
        if isfinite(target) and target > legal_capacity + tolerance:
            failures.append("target_gfa_exceeds_legal_capacity")
        if (
            len(areas) == field_count
            and all(isfinite(value) for value in areas)
            and sum(areas) > legal_capacity + _summed_area_tolerance(
                len(areas),
                base_tolerance=tolerance,
            )
        ):
            failures.append("actual_gfa_exceeds_legal_capacity")
    if failures:
        return _certificate(
            status="rejected",
            hard_pass=False,
            legal_floor_field_hash=field_hash,
            identity=identity,
            target_gfa_m2=target,
            actual_floor_areas_m2=areas,
            containment_evidence=rows,
            failures=failures,
        )

    cumulative = 0.0
    selected_index: int | None = None
    cumulative_before = 0.0
    for index, area in enumerate(areas):
        before = cumulative
        cumulative += area
        cumulative_tolerance = _summed_area_tolerance(
            index + 1,
            base_tolerance=tolerance,
        )
        if (
            selected_index is None
            and cumulative + cumulative_tolerance >= target
        ):
            selected_index = index
            cumulative_before = before

    if selected_index is None:
        return _certificate(
            status="target_unreachable",
            hard_pass=False,
            legal_floor_field_hash=field_hash,
            identity=identity,
            target_gfa_m2=target,
            actual_floor_areas_m2=areas,
            containment_evidence=rows,
            achieved_gfa_m2=cumulative,
            failures=("legal_floor_field_exhausted_before_target",),
        )

    selected_count = selected_index + 1
    terminal_area = areas[selected_index]
    residual = max(0.0, target - cumulative_before)
    overshoot = max(0.0, terminal_area - residual)
    positive_above = any(
        area > tolerance
        for area in areas[selected_count:]
    )
    if positive_above:
        return _certificate(
            status="rejected",
            hard_pass=False,
            legal_floor_field_hash=field_hash,
            identity=identity,
            target_gfa_m2=target,
            actual_floor_areas_m2=areas,
            containment_evidence=rows,
            selected_floor_count=selected_count,
            achieved_gfa_m2=cumulative_before + terminal_area,
            terminal_residual_area_m2=residual,
            terminal_actual_area_m2=terminal_area,
            terminal_overshoot_area_m2=overshoot,
            terminal_handling="reject_nonminimal_floor_count",
            failures=("nonminimal_floor_count",),
        )

    if overshoot > _summed_area_tolerance(
        selected_count,
        base_tolerance=tolerance,
    ):
        return _certificate(
            status="rejected",
            hard_pass=False,
            legal_floor_field_hash=field_hash,
            identity=identity,
            target_gfa_m2=target,
            actual_floor_areas_m2=areas,
            containment_evidence=rows,
            selected_floor_count=selected_count,
            achieved_gfa_m2=cumulative_before + terminal_area,
            terminal_residual_area_m2=residual,
            terminal_actual_area_m2=terminal_area,
            terminal_overshoot_area_m2=overshoot,
            terminal_handling="reject_unauthored_terminal_adjustment",
            failures=("uncorrected_gfa_overshoot",),
        )

    return _certificate(
        status="certified",
        hard_pass=True,
        legal_floor_field_hash=field_hash,
        identity=identity,
        target_gfa_m2=target,
        actual_floor_areas_m2=areas,
        containment_evidence=rows,
        selected_floor_count=selected_count,
        achieved_gfa_m2=cumulative_before + terminal_area,
        terminal_residual_area_m2=residual,
        terminal_actual_area_m2=terminal_area,
        terminal_overshoot_area_m2=overshoot,
        terminal_handling="exact_stop",
        failures=(),
    )


def _sequence_items(value: Any) -> tuple[Any, ...] | None:
    if type(value) not in (list, tuple):
        return None
    return tuple(value)


def _summed_area_tolerance(
    term_count: int,
    *,
    base_tolerance: float,
) -> float:
    """Bound summed serialization and certified mesh-overlay area error."""

    quantization_bound = (
        max(int(term_count), 0)
        * AREA_SERIALIZATION_QUANTUM_M2
        / 2.0
    )
    return max(
        base_tolerance,
        GFA_MESH_OVERLAY_TOLERANCE_M2 + 1e-12,
        quantization_bound + 1e-12,
    )


def _canonical_containment_rows(
    value: Any,
) -> tuple[dict[str, Any], ...] | None:
    raw_rows = _sequence_items(value)
    if raw_rows is None:
        return None
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        if (
            type(raw_row) is not dict
            or frozenset(raw_row) != CONTAINMENT_KEYS
            or type(raw_row.get("floor_number")) is not int
            or raw_row.get("contained") is not True
            or not _is_json_number(raw_row.get("actual_area_m2"))
            or type(raw_row.get("legal_floor_field_hash")) is not str
            or any(
                type(raw_row.get(key)) is not str
                for key in IDENTITY_KEYS
            )
        ):
            return None
        rows.append({
            "floor_number": raw_row["floor_number"],
            "contained": True,
            "actual_area_m2": float(raw_row["actual_area_m2"]),
            "legal_floor_field_hash": raw_row["legal_floor_field_hash"],
            **{
                key: raw_row[key]
                for key in IDENTITY_KEYS
            },
        })
    return tuple(rows)


def _boundary_rejection_certificate() -> dict[str, Any]:
    identity = {
        key: ""
        for key in IDENTITY_KEYS
    }
    identity["pnu"] = ""
    return _certificate(
        status="rejected",
        hard_pass=False,
        legal_floor_field_hash="",
        identity=identity,
        target_gfa_m2=float("nan"),
        actual_floor_areas_m2=(),
        containment_evidence=(),
        failures=("invalid_certificate_input",),
    )


def _certificate(
    *,
    status: str,
    hard_pass: bool,
    legal_floor_field_hash: str,
    identity: Mapping[str, str],
    target_gfa_m2: float,
    actual_floor_areas_m2: Sequence[float],
    containment_evidence: Sequence[Mapping[str, Any]],
    failures: Sequence[str],
    selected_floor_count: int = 0,
    achieved_gfa_m2: float = 0.0,
    terminal_residual_area_m2: float = 0.0,
    terminal_actual_area_m2: float = 0.0,
    terminal_overshoot_area_m2: float = 0.0,
    terminal_handling: str = "not_applicable",
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "hard_pass": bool(hard_pass),
        "legal_floor_field_hash": legal_floor_field_hash,
        "identity": dict(identity),
        "program_hash": str(identity.get("program_hash") or ""),
        "final_geometry_hash": str(identity.get("final_geometry_hash") or ""),
        "visual_hash": str(identity.get("visual_hash") or ""),
        "pnu": str(identity.get("pnu") or ""),
        "target_gfa_m2": _finite_round(target_gfa_m2),
        "actual_floor_areas_m2": [
            _finite_round(value) for value in actual_floor_areas_m2
        ],
        "containment_evidence": [
            dict(row) if isinstance(row, Mapping) else row
            for row in containment_evidence
        ],
        "selected_floor_count": int(selected_floor_count),
        "terminal_floor_number": int(selected_floor_count),
        "achieved_gfa_m2": _finite_round(achieved_gfa_m2),
        "terminal_residual_area_m2": _finite_round(
            terminal_residual_area_m2
        ),
        "terminal_actual_area_m2": _finite_round(terminal_actual_area_m2),
        "terminal_overshoot_area_m2": _finite_round(
            terminal_overshoot_area_m2
        ),
        "terminal_handling": terminal_handling,
        "geometry_was_mutated": False,
        "failure_reasons": list(dict.fromkeys(failures)),
    }
    payload["candidate_actual_gfa_stop_hash"] = _payload_hash(payload)
    return payload


def validate_candidate_actual_gfa_stop_certificate(
    payload: Mapping[str, Any] | None,
    *,
    legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    expected_pnu: Any = None,
    expected_identity: Mapping[str, Any],
    expected_target: float,
) -> bool:
    """Independently recompute a candidate stop certificate and its seal."""

    try:
        return _validate_candidate_actual_gfa_stop_certificate(
            payload,
            legal_floor_field=legal_floor_field,
            expected_legal_floor_field_hash=(
                expected_legal_floor_field_hash
            ),
            expected_pnu=expected_pnu,
            expected_identity=expected_identity,
            expected_target=expected_target,
        )
    except Exception:
        return False


def _validate_candidate_actual_gfa_stop_certificate(
    payload: Mapping[str, Any] | None,
    *,
    legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    expected_pnu: Any,
    expected_identity: Mapping[str, Any],
    expected_target: float,
) -> bool:
    if (
        not _valid_candidate_certificate_boundary_shape(payload)
        or type(legal_floor_field) is not dict
        or not _valid_sha256(expected_legal_floor_field_hash)
        or legal_floor_field.get("legal_floor_field_hash")
        != expected_legal_floor_field_hash
        or not validate_legal_floor_field(legal_floor_field)
        or not _is_canonical_pnu(expected_pnu)
        or legal_floor_field.get("pnu") != expected_pnu
        or not _valid_identity_input(expected_identity)
        or not _is_json_number(expected_target)
        or float(expected_target) <= 0.0
    ):
        return False
    stored_hash = payload.get("candidate_actual_gfa_stop_hash")
    if not _valid_sha256(stored_hash):
        return False
    canonical = dict(payload)
    canonical.pop("candidate_actual_gfa_stop_hash", None)
    if _payload_hash(canonical) != stored_hash:
        return False
    measured_identity = payload.get("identity")
    actual_floor_areas = payload.get("actual_floor_areas_m2")
    containment = payload.get("containment_evidence")
    if (
        type(measured_identity) is not dict
        or type(actual_floor_areas) is not list
        or type(containment) is not list
    ):
        return False
    try:
        recomputed = certify_candidate_actual_gfa_stop(
            legal_floor_field=legal_floor_field,
            expected_legal_floor_field_hash=(
                expected_legal_floor_field_hash
            ),
            expected_pnu=expected_pnu,
            expected_identity=expected_identity,
            measured_identity={
                key: measured_identity[key]
                for key in IDENTITY_KEYS
            },
            actual_floor_areas_m2=actual_floor_areas,
            containment_evidence=containment,
            target_gfa_m2=expected_target,
        )
    except Exception:
        return False
    return dict(payload) == recomputed


def _valid_identity_input(value: Any) -> bool:
    return bool(
        type(value) is dict
        and frozenset(value) == IDENTITY_KEY_SET
        and all(_valid_sha256(value.get(key)) for key in IDENTITY_KEYS)
    )


def _valid_candidate_certificate_boundary_shape(value: Any) -> bool:
    """Reject open/non-plain certificate evidence before hashing."""

    if (
        type(value) is not dict
        or frozenset(value) != CERTIFICATE_KEYS
        or type(value.get("schema_version")) is not str
        or value.get("schema_version") != SCHEMA_VERSION
        or type(value.get("status")) is not str
        or value.get("status") not in CERTIFICATE_STATUSES
        or type(value.get("hard_pass")) is not bool
        or not _valid_sha256(value.get("legal_floor_field_hash"))
        or type(value.get("program_hash")) is not str
        or type(value.get("final_geometry_hash")) is not str
        or type(value.get("visual_hash")) is not str
        or not _is_canonical_pnu(value.get("pnu"))
        or not _is_json_number(value.get("target_gfa_m2"))
        or type(value.get("actual_floor_areas_m2")) is not list
        or type(value.get("containment_evidence")) is not list
        or type(value.get("selected_floor_count")) is not int
        or type(value.get("terminal_floor_number")) is not int
        or not _is_json_number(value.get("achieved_gfa_m2"))
        or not _is_json_number(value.get("terminal_residual_area_m2"))
        or not _is_json_number(value.get("terminal_actual_area_m2"))
        or not _is_json_number(value.get("terminal_overshoot_area_m2"))
        or type(value.get("terminal_handling")) is not str
        or value.get("terminal_handling") not in TERMINAL_HANDLING_VALUES
        or value.get("geometry_was_mutated") is not False
        or type(value.get("failure_reasons")) is not list
        or not _valid_sha256(value.get("candidate_actual_gfa_stop_hash"))
    ):
        return False
    identity = value.get("identity")
    if (
        type(identity) is not dict
        or frozenset(identity) != CERTIFICATE_IDENTITY_KEYS
        or not all(
            _valid_sha256(identity.get(key))
            for key in IDENTITY_KEYS
        )
        or not _is_canonical_pnu(identity.get("pnu"))
        or any(value.get(key) != identity.get(key) for key in IDENTITY_KEYS)
        or value.get("pnu") != identity.get("pnu")
    ):
        return False
    if (
        not all(
            _is_json_number(item)
            for item in value["actual_floor_areas_m2"]
        )
        or _canonical_containment_rows(
            value["containment_evidence"]
        ) is None
        or any(
            type(reason) is not str or not reason
            for reason in value["failure_reasons"]
        )
    ):
        return False
    return True


def _valid_sha256(value: str) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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


def _finite_round(value: float) -> float | None:
    if not _is_json_number(value):
        return None
    return round(float(value), 6)


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


__all__ = [
    "IDENTITY_KEYS",
    "GFA_TOLERANCE_M2",
    "SCHEMA_VERSION",
    "certify_candidate_actual_gfa_stop",
    "validate_candidate_actual_gfa_stop_certificate",
]

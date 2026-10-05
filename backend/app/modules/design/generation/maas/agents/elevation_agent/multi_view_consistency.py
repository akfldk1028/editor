"""Deterministic consistency checks for creative facade artifacts."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_contract import FACADE_VIEWS, proposal_identity

MIN_SILHOUETTE_IOU = 0.99


def evaluate_multi_view_consistency(
    bundle: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Reject facade artifacts that are not registered to their locked sources."""

    expected_identity = proposal_identity(bundle)
    source_views = {
        str(row.get("view") or ""): row
        for row in bundle.get("views") or ()
        if isinstance(row, Mapping)
    }
    checks: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, str]] = []
    failed: set[str] = set()

    for view in FACADE_VIEWS:
        artifact = artifacts.get(view)
        source = source_views.get(view)
        if not isinstance(artifact, Mapping) or not isinstance(source, Mapping):
            failed.add(view)
            issues.append(_issue("missing_required_view", view, f"{view} facade artifact is missing"))
            continue
        check, view_issues = _evaluate_view(
            view,
            expected_identity,
            source,
            artifact,
        )
        checks[view] = check
        if view_issues:
            failed.add(view)
            issues.extend(view_issues)

    corner_checks = _corner_checks(checks)
    for corner in corner_checks:
        if corner["status"] == "failed":
            for view in corner["views"]:
                failed.add(view)
                issues.append(
                    _issue(
                        "corner_datum_mismatch",
                        view,
                        f"{'/'.join(corner['views'])} corner datum drift exceeds 2 px",
                    )
                )

    return {
        "schema_version": "arr.elevation_agent.multi_view_gate.v1",
        "status": "failed" if failed else "passed",
        "required_views": list(FACADE_VIEWS),
        "failed_views": [view for view in FACADE_VIEWS if view in failed],
        "checks": checks,
        "corner_checks": corner_checks,
        "issues": issues,
    }


def _evaluate_view(
    view: str,
    expected_identity: Mapping[str, str],
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    identity = artifact.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    expected_view_identity = {**expected_identity, "view": view}
    identity_match = all(
        str(identity.get(key) or "") == value
        for key, value in expected_view_identity.items()
    )
    if not identity_match:
        issues.append(_issue("identity_mismatch", view, f"{view} identity does not match the elevation bundle"))

    source_record = artifact.get("source")
    source_record = source_record if isinstance(source_record, Mapping) else {}
    output_record = artifact.get("artifact")
    output_record = output_record if isinstance(output_record, Mapping) else {}
    source_path = Path(str(source.get("path") or "")).resolve()
    declared_source_path = Path(str(source_record.get("path") or "")).resolve()
    output_path = Path(str(output_record.get("path") or "")).resolve()
    expected_source_hash = str(source.get("sha256") or "")
    source_sha256_match = (
        source_path.is_file()
        and declared_source_path == source_path
        and str(source_record.get("sha256") or "") == expected_source_hash
        and _sha256(source_path) == expected_source_hash
    )
    if not source_sha256_match:
        issues.append(_issue("source_hash_mismatch", view, f"{view} source hash or path changed"))

    output_hash_match = (
        output_path.is_file()
        and str(output_record.get("sha256") or "") == _sha256(output_path)
    )
    if not output_hash_match:
        issues.append(_issue("output_hash_mismatch", view, f"{view} output hash does not match its manifest"))

    dimensions_match = False
    outside_changed = -1
    silhouette_iou = 0.0
    floor_alignment = float("inf")
    facade_extent_match = False
    source_bbox: tuple[int, int, int, int] | None = None
    output_bbox: tuple[int, int, int, int] | None = None
    if source_path.is_file() and output_path.is_file():
        with Image.open(source_path) as source_image, Image.open(output_path) as output_image:
            source_rgba = source_image.convert("RGBA")
            output_rgba = output_image.convert("RGBA")
            dimensions_match = source_rgba.size == output_rgba.size
            if dimensions_match:
                source_mask = _largest_foreground_component(source_rgba)
                output_mask = _largest_foreground_component(output_rgba)
                outside_changed = _outside_change_count(
                    source_rgba,
                    output_rgba,
                    source_mask,
                )
                silhouette_iou = _intersection_over_union(source_mask, output_mask)
                source_bbox = _mask_bbox(source_mask, source_rgba.size)
                output_bbox = _mask_bbox(output_mask, output_rgba.size)
                floor_alignment = _bbox_drift(source_bbox, output_bbox)
                facade_extent_match = floor_alignment <= 2.0
    if not dimensions_match:
        issues.append(_issue("dimension_mismatch", view, f"{view} output dimensions changed"))
    if outside_changed != 0:
        issues.append(
            _issue(
                "outside_mask_changed",
                view,
                f"{view} changed {max(0, outside_changed)} pixels outside the locked silhouette",
            )
        )
    if silhouette_iou < MIN_SILHOUETTE_IOU:
        issues.append(
            _issue(
                "silhouette_registration_failed",
                view,
                f"{view} silhouette IoU {silhouette_iou:.6f} "
                f"is below {MIN_SILHOUETTE_IOU:.2f}",
            )
        )
    if floor_alignment > 2.0:
        issues.append(
            _issue(
                "floor_guide_misaligned",
                view,
                f"{view} vertical datum drift {floor_alignment:.3f}px exceeds 2px",
            )
        )
    if not facade_extent_match:
        issues.append(_issue("facade_extent_mismatch", view, f"{view} facade extent changed"))

    return {
        "identity_match": identity_match,
        "source_sha256_match": source_sha256_match,
        "output_sha256_match": output_hash_match,
        "dimensions_match": dimensions_match,
        "outside_mask_changed_pixels": outside_changed,
        "silhouette_registration_iou": round(silhouette_iou, 6),
        "floor_guide_alignment_px": (
            round(floor_alignment, 6)
            if floor_alignment != float("inf")
            else None
        ),
        "facade_extent_match": facade_extent_match,
        "source_bbox_px": list(source_bbox) if source_bbox else [],
        "output_bbox_px": list(output_bbox) if output_bbox else [],
    }, issues


def _largest_foreground_component(image: Image.Image) -> set[tuple[int, int]]:
    width, height = image.size
    border = [
        image.getpixel((x, y))
        for x, y in (
            *((x, 0) for x in range(width)),
            *((x, height - 1) for x in range(width)),
            *((0, y) for y in range(height)),
            *((width - 1, y) for y in range(height)),
        )
    ]
    background = Counter(border).most_common(1)[0][0]
    candidates = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if _color_distance(image.getpixel((x, y)), background) > 12
    }
    largest: set[tuple[int, int]] = set()
    while candidates:
        seed = candidates.pop()
        component = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for adjacent in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if adjacent in candidates:
                    candidates.remove(adjacent)
                    component.add(adjacent)
                    stack.append(adjacent)
        if len(component) > len(largest):
            largest = component
    return largest


def _color_distance(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    return max(abs(int(left[index]) - int(right[index])) for index in range(3))


def _outside_change_count(
    source: Image.Image,
    output: Image.Image,
    silhouette: set[tuple[int, int]],
) -> int:
    return sum(
        source.getpixel((x, y)) != output.getpixel((x, y))
        for y in range(source.height)
        for x in range(source.width)
        if (x, y) not in silhouette
    )


def _intersection_over_union(
    left: set[tuple[int, int]],
    right: set[tuple[int, int]],
) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _mask_bbox(
    mask: set[tuple[int, int]],
    _size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    if not mask:
        return None
    xs = [point[0] for point in mask]
    ys = [point[1] for point in mask]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_drift(
    source: tuple[int, int, int, int] | None,
    output: tuple[int, int, int, int] | None,
) -> float:
    if source is None or output is None:
        return float("inf")
    return float(max(abs(left - right) for left, right in zip(source, output)))


def _corner_checks(checks: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for left, right in (
        ("front", "right"),
        ("right", "back"),
        ("back", "left"),
        ("left", "front"),
    ):
        left_drift = checks.get(left, {}).get("floor_guide_alignment_px")
        right_drift = checks.get(right, {}).get("floor_guide_alignment_px")
        if isinstance(left_drift, (int, float)) and isinstance(right_drift, (int, float)):
            delta = int(round(max(float(left_drift), float(right_drift))))
            status = "passed" if delta <= 2 else "failed"
        else:
            delta = None
            status = "not_evaluated"
        result.append({
            "views": [left, right],
            "height_delta_px": delta,
            "status": status,
        })
    return result


def _issue(code: str, view: str, message: str) -> dict[str, str]:
    return {"code": code, "view": view, "message": message}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["evaluate_multi_view_consistency"]

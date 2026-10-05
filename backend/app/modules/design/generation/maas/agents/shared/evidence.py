"""Shared evidence helpers for deterministic MAAS agents."""

from __future__ import annotations

from typing import Any


def feature_properties(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    return props if isinstance(props, dict) else {}


def parking_precheck(props: dict[str, Any]) -> dict[str, Any]:
    precheck = props.get("parking_precheck")
    return precheck if isinstance(precheck, dict) else {}


def parking_layout_candidate(precheck: dict[str, Any]) -> dict[str, Any]:
    layout = precheck.get("layout_candidate")
    return layout if isinstance(layout, dict) else {}


def parking_required_spaces(precheck: dict[str, Any], layout: dict[str, Any]) -> Any:
    if layout.get("required_spaces") is not None:
        return layout.get("required_spaces")
    required_count = precheck.get("required_count")
    if isinstance(required_count, dict):
        return required_count.get("required_spaces")
    return required_count


__all__ = [
    "feature_properties",
    "parking_layout_candidate",
    "parking_precheck",
    "parking_required_spaces",
]

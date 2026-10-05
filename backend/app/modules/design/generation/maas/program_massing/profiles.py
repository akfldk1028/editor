"""Data-backed building-program massing profiles."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


PROFILE_PATH = _design_paths.package_root('design/maas/program_massing') / "data" / "program_profiles.v1.json"


@lru_cache(maxsize=1)
def load_program_profiles() -> tuple[dict[str, Any], ...]:
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "arr.maas.program_profiles.v1":
        raise ValueError("unsupported program massing profile schema")
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("program massing profiles are empty")
    ids = [str(item.get("id") or "") for item in profiles]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("program massing profile ids must be unique and non-empty")
    return tuple(dict(item) for item in profiles)


def resolve_program_profile(building_type: str) -> dict[str, Any]:
    text = str(building_type or "").strip().lower()
    for profile in load_program_profiles():
        profile_id = str(profile.get("id") or "").strip().lower()
        if text == profile_id or any(str(alias).lower() in text for alias in profile.get("aliases") or []):
            return profile
    return {
        "id": "generic",
        "aliases": [],
        "design_intent": "clear dominant public mass with restrained supporting volumes",
        "target_volume_range": [1, 4],
        "target_floor_range": [1, 40],
        "preferred_families": [],
        "sequences": [],
    }


def program_reference_contract(building_type: str) -> dict[str, Any]:
    """Return the AI/retrieval contract for one building program.

    This contract contains program relationships and search vocabulary, not a
    completed mass template.  Geometry agents may change every solid node as
    long as the compiler and downstream program gates preserve these relations.
    """
    profile = resolve_program_profile(building_type)
    search = profile.get("reference_search") if isinstance(profile.get("reference_search"), dict) else {}
    invariants = [
        {
            "id": str(item.get("id") or ""),
            "subject_role": str(item.get("subject_role") or ""),
            "relation": str(item.get("relation") or ""),
            "object_role": str(item.get("object_role") or ""),
            "description": str(item.get("description") or ""),
        }
        for item in profile.get("semantic_invariants") or ()
        if isinstance(item, dict) and item.get("id")
    ]
    return {
        "schema_version": "arr.maas.program_reference_contract.v1",
        "program_id": str(profile.get("id") or "generic"),
        "building_type": str(building_type or ""),
        "design_intent": str(profile.get("design_intent") or ""),
        "preferred_collections": [str(value) for value in search.get("preferred_collections") or ()],
        "required_any_terms": [str(value) for value in search.get("required_any_terms") or ()],
        "supporting_terms": [str(value) for value in search.get("supporting_terms") or ()],
        "excluded_terms": [str(value) for value in search.get("excluded_terms") or ()],
        "excluded_scale_typologies": [str(value) for value in search.get("excluded_scale_typologies") or ()],
        "preferred_primary_typologies": [str(value) for value in search.get("preferred_primary_typologies") or ()],
        "minimum_program_specific_images": max(0, min(5, int(search.get("minimum_program_specific_images") or 0))),
        "semantic_invariants": invariants,
        "target_volume_range": list(profile.get("target_volume_range") or [1, 4]),
        "target_floor_range": list(profile.get("target_floor_range") or [1, 40]),
        "dimensional_requirements": dict(profile.get("dimensional_requirements") or {}),
        "geometry_language_contract": dict(profile.get("geometry_language_contract") or {}),
        "geometry_template": None,
        "parcel_coordinates_allowed": False,
    }


__all__ = ["PROFILE_PATH", "load_program_profiles", "program_reference_contract", "resolve_program_profile"]

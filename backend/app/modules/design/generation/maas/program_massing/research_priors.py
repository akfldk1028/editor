"""Research-backed search bounds for program-conditioned component graphs."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile


PRIOR_PATH = _design_paths.package_root('design/maas/program_massing') / "data" / "research_search_priors.v1.json"


@lru_cache(maxsize=1)
def load_research_search_priors() -> dict[str, Any]:
    payload = json.loads(PRIOR_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "arr.maas.research_search_priors.v1":
        raise ValueError("unsupported research search prior schema")
    return payload


def program_search_prior(building_type: str) -> dict[str, Any]:
    payload = load_research_search_priors()
    profile_id = resolve_program_profile(building_type)["id"]
    profiles = payload.get("profiles") or {}
    prior = dict(profiles.get(profile_id) or profiles["generic"])
    prior.update({
        "schema_version": payload["schema_version"],
        "profile_id": profile_id,
        "source_ids": [item["id"] for item in payload.get("sources") or []],
        "hard_constraint_order": ["grammar_validity", "law", "parking", "clean_mass", "program_fit"],
    })
    return prior


__all__ = ["PRIOR_PATH", "load_research_search_priors", "program_search_prior"]

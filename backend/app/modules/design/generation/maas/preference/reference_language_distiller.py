"""Distill reference images into executable, coordinate-free MassDSL briefs.

Reference images must influence topology before candidate generation.  This
module is deliberately separate from candidate scoring: it reads a diverse
program-relevant image set once, extracts architectural rules, and gives the
LLM architect typed operation recipes.  Geometry, law, parking and capacity
remain deterministic downstream gates.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import base64
import json
import mimetypes
import os
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS

from backend.app.modules.design.generation.maas.preference.reference_corpus import ReferenceItem


REFERENCE_LANGUAGE_SCHEMA_VERSION = "arr.maas.reference_language_distillation.v4"

REQUIRED_LANGUAGE_CLASSES = {
    "continuous_field": 1,
    "carved_void": 1,
    "bridge_interlock": 1,
    "folded_section": 1,
    "cluster_field": 2,
    "stepped_capacity": 2,
    "hybrid_civic": 2,
}


def distill_reference_languages_with_openai(
    references: Iterable[ReferenceItem],
    *,
    building_type: str,
    model: str = "gpt-5.4-mini",
    cache_path: Path | None = None,
    image_limit: int = 12,
    language_count: int = 10,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Return image-derived graph recipes, using a stable cache when present."""
    if cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("schema_version") == REFERENCE_LANGUAGE_SCHEMA_VERSION:
            return cached
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    language_count = sum(REQUIRED_LANGUAGE_CLASSES.values())
    selected = _select_reference_images(
        list(references),
        building_type=building_type,
        limit=max(4, int(image_limit)),
    )
    if len(selected) < 4:
        raise RuntimeError("fewer than four image-backed architecture references are available")
    content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": _prompt(building_type=building_type, language_count=language_count),
    }]
    used: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        image_url = _reference_image_url(item)
        if not image_url:
            continue
        content.append({
            "type": "input_text",
            "text": f"Reference {index}: {item.title}; tags={list(item.tags)}; source={item.source}",
        })
        content.append({"type": "input_image", "image_url": image_url})
        used.append({
            "source": item.source,
            "source_id": item.source_id,
            "title": item.title,
            "page_url": item.page_url,
            "local_path": item.local_path,
            "tags": list(item.tags),
        })
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "You are an architectural precedent analyst and procedural-grammar author. "
                        "Extract transferable massing rules from images, never facade style and never exact coordinates."
                    ),
                }],
            },
            {"role": "user", "content": content},
        ],
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "maas_reference_language_distillation",
                "strict": True,
                "schema": _response_schema(language_count),
            },
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = json.loads(response.read().decode("utf-8"))
    parsed = json.loads(_extract_text(raw))
    languages = _validate_languages(parsed.get("languages") or [])
    result = {
        "schema_version": REFERENCE_LANGUAGE_SCHEMA_VERSION,
        "status": "distilled",
        "model": model,
        "response_id": raw.get("id"),
        "building_type": building_type,
        "reference_count": len(used),
        "references": used,
        "languages": languages,
        "anti_copy_rule": str(parsed.get("anti_copy_rule") or "transfer rules, never copy a building"),
    }
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def language_briefs_for_generation(distillation: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact the audit artifact into the author-agent feedback contract."""
    briefs: list[dict[str, Any]] = []
    for item in distillation.get("languages") or []:
        language_class = str(item.get("language_class") or "")
        recipe = _normalize_primary_recipe(language_class, item.get("operation_recipe") or [])
        briefs.append({
            "name": item.get("name"),
            "language_class": language_class,
            "primary_operation": recipe[1] if len(recipe) > 1 else "",
            "dominant_gesture": item.get("dominant_gesture"),
            "spatial_rule": item.get("spatial_rule"),
            "operation_recipe": recipe,
            "capacity_strategy": item.get("capacity_strategy"),
            "ground_strategy": item.get("ground_strategy"),
            "avoid": item.get("avoid"),
        })
    return briefs


def _normalize_primary_recipe(language_class: str, recipe: list[Any]) -> list[str]:
    verbs = [str(verb) for verb in recipe if str(verb) in SUPPORTED_VERBS and str(verb) != "base"]
    preferred = {
        "continuous_field": ("bend", "branch"),
        "carved_void": ("courtyard", "cave", "notch", "embed"),
        "bridge_interlock": ("split", "interlock", "diagonal_connect"),
        "folded_section": ("sloped_roof_mass",),
        "cluster_field": ("array", "branch", "reflect"),
        "stepped_capacity": ("stack",),
        "hybrid_civic": ("offset", "overlap", "courtyard"),
    }.get(language_class, ())
    primary = next(
        (verb for verb in preferred if verb in verbs),
        preferred[0] if preferred else (verbs[0] if verbs else "bar"),
    )
    verbs = [verb for verb in verbs if verb != primary]
    if language_class == "stepped_capacity" and "step_envelope" not in verbs:
        verbs.append("step_envelope")
    return ["base", primary, *verbs][:5]


def _select_reference_images(
    references: list[ReferenceItem],
    *,
    building_type: str,
    limit: int,
) -> list[ReferenceItem]:
    program_tokens = set(str(building_type).casefold().replace("-", " ").split())
    program_tokens.update({"community", "commercial", "retail", "civic", "cultural", "sports", "pavilion"})
    family_tokens = {
        "courtyard", "atrium", "terrace", "stepped", "ribbon", "bridge", "split",
        "folded", "sloped", "cluster", "campus", "stacked", "shifted", "void", "undercut",
    }
    image_backed = [item for item in references if _reference_image_url(item)]
    def rank(item: ReferenceItem) -> tuple[Any, ...]:
        terms = set(item.tags) | set(item.title.casefold().split())
        return (
            -len(terms & program_tokens),
            -len(set(item.tags) & family_tokens),
            item.source,
            item.title,
        )

    ranked = sorted(image_backed, key=rank)
    by_collection: dict[str, list[ReferenceItem]] = {}
    for item in ranked:
        by_collection.setdefault(_reference_collection(item), []).append(item)

    # The old ranker selected six sports projects out of twelve images even
    # though the local DB already held twelve collections and 338 files. That
    # is a retrieval failure, not a data shortage. Start with the strongest
    # representative from each independent collection, explicitly preserving
    # user/curated iconic and massing-diversity collections.
    collection_representatives = [items[0] for items in by_collection.values() if items]
    collection_representatives.sort(key=lambda item: (
        0 if _reference_collection(item) in {"iconic_precedents", "massing_diversity_20260711"} else 1,
        *rank(item),
    ))
    selected: list[ReferenceItem] = collection_representatives[:limit]
    collection_counts = {
        collection: sum(1 for item in selected if _reference_collection(item) == collection)
        for collection in by_collection
    }
    if len(selected) < limit:
        for item in ranked:
            collection = _reference_collection(item)
            if item in selected or collection_counts.get(collection, 0) >= 2:
                continue
            selected.append(item)
            collection_counts[collection] = collection_counts.get(collection, 0) + 1
            if len(selected) >= limit:
                break
    return selected


def _reference_collection(item: ReferenceItem) -> str:
    normalized = str(item.local_path or item.page_url or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    try:
        archdaily_index = parts.index("archdaily")
    except ValueError:
        return str(item.source or "unknown")
    tail = parts[archdaily_index + 1:]
    if len(tail) >= 2 and tail[0] in {"api", "seeded"}:
        return tail[1]
    return tail[0] if tail else str(item.source or "archdaily")


def _prompt(*, building_type: str, language_count: int) -> str:
    verbs = ", ".join(sorted(SUPPORTED_VERBS))
    return (
        f"Study the following architecture images for a {building_type} early massing population. "
        f"Produce exactly {language_count} visibly different transferable architectural languages. "
        "Include continuous/curved, carved void/courtyard, bridge/interlock, folded section, cluster/field, "
        "Use this exact class distribution: one continuous_field, one carved_void, one bridge_interlock, "
        "one folded_section, exactly two cluster_field, exactly two stepped_capacity, and exactly two hybrid_civic. "
        "A stepped_capacity language must "
        "use occupiable floor plates and one continuous sectional rule; do not describe a generic cake tier. "
        "Each operation_recipe must use 2-5 supported MassDSL verbs, start conceptually from base, and contain "
        "no coordinates, dimensions copied from the image, facade/material instructions, or proper-name mimicry. "
        f"Supported verbs: {verbs}. Explain the spatial and capacity consequence of every language."
    )


def _response_schema(language_count: int) -> dict[str, Any]:
    string = {"type": "string"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["languages", "anti_copy_rule"],
        "properties": {
            "languages": {
                "type": "array",
                "minItems": language_count,
                "maxItems": language_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name", "language_class", "dominant_gesture", "spatial_rule", "operation_recipe",
                        "capacity_strategy", "ground_strategy", "avoid",
                    ],
                    "properties": {
                        "name": string,
                        "language_class": {
                            "type": "string",
                            "enum": sorted(REQUIRED_LANGUAGE_CLASSES),
                        },
                        "dominant_gesture": string,
                        "spatial_rule": string,
                        "operation_recipe": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 5,
                            "items": {"type": "string", "enum": sorted(SUPPORTED_VERBS)},
                        },
                        "capacity_strategy": string,
                        "ground_strategy": string,
                        "avoid": string,
                    },
                },
            },
            "anti_copy_rule": string,
        },
    }


def _validate_languages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for item in items:
        recipe = [str(verb) for verb in item.get("operation_recipe") or [] if str(verb) in SUPPORTED_VERBS]
        if len(recipe) < 2:
            continue
        valid.append({**item, "operation_recipe": recipe})
    if len(valid) < 6:
        raise RuntimeError(f"reference distillation returned only {len(valid)} valid language recipes")
    counts = {key: 0 for key in REQUIRED_LANGUAGE_CLASSES}
    for item in valid:
        language_class = str(item.get("language_class") or "")
        if language_class in counts:
            counts[language_class] += 1
    if any(counts[key] != expected for key, expected in REQUIRED_LANGUAGE_CLASSES.items()):
        raise RuntimeError(f"reference language class distribution invalid: {counts}")
    return valid


def _reference_image_url(item: ReferenceItem) -> str:
    if item.local_path:
        raw = Path(item.local_path)
        candidates = [raw] if raw.is_absolute() else [Path.cwd() / raw, _design_paths.workspace_root() / raw]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is not None:
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    return item.image_url if item.image_url.startswith(("https://", "http://", "data:")) else ""


def _extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    return "".join(
        str(content.get("text") or "")
        for item in response.get("output") or []
        if isinstance(item, dict)
        for content in item.get("content") or []
        if isinstance(content, dict)
    )


__all__ = [
    "REFERENCE_LANGUAGE_SCHEMA_VERSION",
    "distill_reference_languages_with_openai",
    "language_briefs_for_generation",
]

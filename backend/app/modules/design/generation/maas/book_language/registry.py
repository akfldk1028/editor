"""Canonical, traceable registry for the architect-supplied 69-page BOOK.

The scanned pages are evidence.  Operative principles are typed concepts that
may cite one or more pages.  Keeping those identities separate prevents the
debug UI from presenting a page count or a coarse strategy bucket as if it
were an executable architectural language.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.book_language.corpus_contract import AGGREGATIONS, BASE_OPERATIVES, BOOK_ORIENTATIONS, BOOK_VARIATION_COUNT, BaseOperative, CASE_STUDIES, CASE_STUDY_CONTRACTS, COMBINATIONS, page_section
from backend.app.modules.design.generation.maas.book_language.semantics import BASE_VOLUME_FRACTIONS, semantics_for


SCHEMA_VERSION = "arr.maas.book_language_registry.v1"
CORPUS_ID = "architect-book-69"
_OCR_PATH = _design_paths.package_root('design/maas') / "grammar" / "data" / "book_operative_languages.v1.ocr.json"


@lru_cache(maxsize=1)
def _ocr_document() -> dict[str, Any]:
    data = json.loads(_OCR_PATH.read_text(encoding="utf-8"))
    if data.get("page_count") != 69 or len(data.get("pages") or ()) != 69:
        raise ValueError("BOOK OCR contract requires exactly 69 pages")
    return data


def _principle_refs_by_page() -> dict[int, list[str]]:
    refs: dict[int, list[str]] = {page: [] for page in range(1, 70)}
    refs[3].extend(f"book:base-volume:{label.replace('/', '-') }" for label, _fraction in BASE_VOLUME_FRACTIONS)
    for item in BASE_OPERATIVES:
        refs[item.page].append(item.principle_id)
    for index, (page, left, right) in enumerate(COMBINATIONS, start=1):
        refs[page].append(f"book:combination:{index:02d}:{left}+{right}")
    for page, methods, verb in AGGREGATIONS:
        refs[page].append(f"book:aggregation:{'+'.join(methods)}:{verb}")
    for page, _label, verbs in CASE_STUDIES:
        refs[page].append(f"book:case:{page}:{'+'.join(verbs)}")
    return refs


def _status(principle_id: str, compile_evidence: dict[str, dict[str, Any]]) -> str:
    evidence = compile_evidence.get(principle_id) or {}
    if evidence.get("hard_pass") and evidence.get("geometry_delta", 0) > 0:
        return "active"
    if evidence.get("compile_passed"):
        return "compile_tested"
    return "typed"


def build_book_language_registry(
    compile_evidence: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one reconciled manifest for provenance, typing and execution."""
    evidence = compile_evidence or {}
    ocr = _ocr_document()
    refs = _principle_refs_by_page()
    pages = []
    for page in ocr["pages"]:
        number = int(page["page"])
        pages.append({
            "page": number,
            "source_path": page.get("source_path"),
            "sha256": page.get("sha256"),
            "section": page_section(number),
            "ocr_status": "extracted",
            "ocr_lines": page.get("ocr_lines") or [],
            "principle_ids": refs[number],
        })

    principles: list[dict[str, Any]] = []
    for item in BASE_OPERATIVES:
        semantics = semantics_for(item.verb)
        principles.append({
            "principle_id": item.principle_id,
            "kind": "base_operative",
            "label": item.verb,
            "verbs": [item.verb],
            "execution_verbs": [item.verb],
            "generation_stage": "base",
            "generation_stage_order": 1,
            "lineage_base_operative_id": item.principle_id,
            "lineage_parent_principle_id": None,
            "page_refs": [item.page],
            "transformation": item.transformation,
            "cardinality": item.cardinality,
            "semantics": semantics.to_dict(),
            "source_diagram_contract": {
                "procedure_step_count": 3,
                "base_volume_choices": [label for label, _fraction in BASE_VOLUME_FRACTIONS],
                "orientations": list(BOOK_ORIENTATIONS),
                "variation_count": BOOK_VARIATION_COUNT,
            },
            "status": _status(item.principle_id, evidence),
            "compile_evidence": evidence.get(item.principle_id),
        })
    for index, (page, left, right) in enumerate(COMBINATIONS, start=1):
        principle_id = f"book:combination:{index:02d}:{left}+{right}"
        base_operative_id = f"book:operative:{left}"
        principles.append({
            "principle_id": principle_id,
            "kind": "combination",
            "label": f"{left} + {right}",
            "verbs": [left, right],
            "execution_verbs": [left, right],
            "generation_stage": "combination",
            "generation_stage_order": 2,
            "lineage_base_operative_id": base_operative_id,
            "lineage_parent_principle_id": base_operative_id,
            "page_refs": [page],
            "status": _status(principle_id, evidence),
            "compile_evidence": evidence.get(principle_id),
        })
    for page, methods, verb in AGGREGATIONS:
        principle_id = f"book:aggregation:{'+'.join(methods)}:{verb}"
        base_operative_id = f"book:operative:{verb}"
        principles.append({
            "principle_id": principle_id,
            "kind": "aggregation",
            "label": f"{' + '.join(methods)} · {verb}",
            "verbs": [*methods, verb],
            # The BOOK title presents aggregation method first (Reflect |
            # Expand), while its procedure applies the operation before the
            # aggregation method (Base -> Expand -> Reflect).
            "execution_verbs": [verb, *methods],
            "generation_stage": "aggregation",
            "generation_stage_order": 3,
            "lineage_base_operative_id": base_operative_id,
            "lineage_parent_principle_id": base_operative_id,
            "aggregation_methods": list(methods),
            "page_refs": [page],
            "status": _status(principle_id, evidence),
            "compile_evidence": evidence.get(principle_id),
        })
    case_studies: list[dict[str, Any]] = []
    for case in CASE_STUDY_CONTRACTS:
        principle_id = f"book:case:{case.page}:{'+'.join(case.verbs)}"
        base_operative_id = f"book:operative:{case.verbs[0]}"
        record = {
            "principle_id": principle_id,
            "kind": "case_study",
            "label": case.label,
            "project": case.project,
            "verbs": list(case.verbs),
            "execution_verbs": list(case.verbs),
            "implementation_elements": list(case.implementation_elements),
            "generation_stage": "case_study",
            "generation_stage_order": 4,
            "lineage_base_operative_id": base_operative_id,
            "lineage_parent_principle_id": base_operative_id,
            "page_refs": [case.page],
            "status": _status(principle_id, evidence),
            "compile_evidence": evidence.get(principle_id),
        }
        principles.append(record)
        case_studies.append(dict(record))

    status_counts: dict[str, int] = {}
    for principle in principles:
        status_counts[principle["status"]] = status_counts.get(principle["status"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "source": ocr.get("source"),
        "page_count": len(pages),
        "base_volume_count": len(BASE_VOLUME_FRACTIONS),
        "base_volumes": [
            {
                "base_volume_id": f"book:base-volume:{label.replace('/', '-')}",
                "label": f"{label} Base Volume",
                "fraction": fraction,
                "page_refs": [3],
                "status": "typed",
            }
            for label, fraction in BASE_VOLUME_FRACTIONS
        ],
        "base_operative_count": len(BASE_OPERATIVES),
        "combination_count": len(COMBINATIONS),
        "aggregation_recipe_count": len(AGGREGATIONS),
        "case_study_count": len(CASE_STUDIES),
        "executable_principle_count": len(principles),
        "operative_page_variation_count": BOOK_VARIATION_COUNT,
        "operative_orientation_count": len(BOOK_ORIENTATIONS),
        "aggregation_methods": sorted({method for _, methods, _ in AGGREGATIONS for method in methods}),
        "taxonomy": {
            "base_volumes": [f"book:base-volume:{label.replace('/', '-')}" for label, _fraction in BASE_VOLUME_FRACTIONS],
            "operations": {
                transformation: {
                    cardinality: [
                        item.principle_id for item in BASE_OPERATIVES
                        if item.transformation == transformation and item.cardinality == cardinality
                    ]
                    for cardinality in ("single", "multiple")
                }
                for transformation in ("add", "displace", "subtract")
            },
            "combinations": [
                f"book:combination:{index:02d}:{left}+{right}"
                for index, (_page, left, right) in enumerate(COMBINATIONS, start=1)
            ],
            "aggregations": [
                f"book:aggregation:{'+'.join(methods)}:{verb}"
                for _page, methods, verb in AGGREGATIONS
            ],
            "case_studies": [
                f"book:case:{page}:{'+'.join(verbs)}"
                for page, _label, verbs in CASE_STUDIES
            ],
        },
        "status_counts": status_counts,
        "pages": pages,
        "principles": principles,
        "case_studies": case_studies,
    }


def book_base_verbs() -> frozenset[str]:
    return frozenset(item.verb for item in BASE_OPERATIVES)


def principles_for_verbs(verbs: Iterable[str]) -> tuple[str, ...]:
    requested = tuple(str(verb) for verb in verbs)
    manifest = build_book_language_registry()
    return tuple(
        item["principle_id"] for item in manifest["principles"]
        if tuple(item["verbs"]) == requested
    )


def book_composition_registry_summary() -> dict[str, Any]:
    """Expose the complete path-space contract without embedding all paths."""

    from backend.app.modules.design.generation.maas.book_language.composition_lattice import book_composition_lattice_summary

    return book_composition_lattice_summary()


__all__ = [
    "AGGREGATIONS",
    "BASE_OPERATIVES",
    "CASE_STUDIES",
    "COMBINATIONS",
    "CORPUS_ID",
    "SCHEMA_VERSION",
    "book_base_verbs",
    "book_composition_registry_summary",
    "build_book_language_registry",
    "principles_for_verbs",
]

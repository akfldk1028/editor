"""Executable evidence audit for BOOK operations, sentences, aggregations and cases.

An operation is active only when it compiles, changes the 2.5D source mass and
stays inside the same clean-mass budget used by final visual selection.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from shapely.geometry import Polygon, box

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass

from backend.app.modules.design.generation.maas.book_language.registry import AGGREGATIONS, BASE_OPERATIVES, CASE_STUDIES, COMBINATIONS


def _canonical_sites() -> tuple[tuple[str, Polygon], ...]:
    return (
        ("rect", box(0, 0, 60, 40)),
        ("narrow", box(0, 0, 90, 24)),
        ("trapezoid", Polygon(((0, 0), (72, 7), (61, 45), (8, 38)))),
        ("concave", Polygon(((0, 0), (64, 0), (64, 24), (38, 24), (38, 48), (0, 48)))),
    )


def _delta(source, base: Polygon) -> dict[str, float]:
    area = max(float(base.area), 1e-9)
    plan = float(base.symmetric_difference(source.footprint).area) / area
    upper = (
        float(source.footprint.symmetric_difference(source.upper_footprint).area) / area
        if source.upper_footprint is not None else 0.0
    )
    volume = 0.0
    for item in source.volumes:
        height = max(0.0, float(item.top_fraction) - float(item.bottom_fraction))
        volume += float(item.footprint.area) * height
    # The comparison base is one full-height extrusion.  This detects section,
    # layer and field mutations even when their ground silhouette is retained.
    volume = abs(volume / area - 1.0)
    return {
        "plan": round(plan, 5),
        "section": round(upper, 5),
        "volume": round(volume, 5),
        "effective": round(max(plan, upper, volume), 5),
    }


def _audit_sequence(principle_id: str, label: str, verbs: tuple[str, ...]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for site_name, site in _canonical_sites():
        sequence = VerbSequence(
            f"book_audit_{label}_{site_name}",
            label,
            (VerbCall("base", {}), *(VerbCall(verb, {}) for verb in verbs)),
            (f"book_principle_id={principle_id}",),
        )
        source = compile_sequence_to_source_mass(site, sequence)
        if source is None:
            cases.append({"site": site_name, "compile_passed": False, "hard_pass": False})
            continue
        signature = source.signature()
        delta = _delta(source, site)
        clean = bool(
            int(signature.get("effective_surface_count") or 0) <= 48
            and int(signature.get("volume_count") or 0) <= 5
            and delta["effective"] >= 0.025
            and source.footprint.difference(site).area <= 1e-6
        )
        cases.append({
            "site": site_name,
            "compile_passed": True,
            "geometry_delta": delta,
            "volume_count": int(signature.get("volume_count") or 0),
            "surface_count": int(signature.get("effective_surface_count") or 0),
            "inside_site": source.footprint.difference(site).area <= 1e-6,
            "hard_pass": clean,
        })
    compiled = [case for case in cases if case.get("compile_passed")]
    hard = [case for case in cases if case.get("hard_pass")]
    minimum_delta = min(
        (float((case.get("geometry_delta") or {}).get("effective") or 0.0) for case in compiled),
        default=0.0,
    )
    return {
        "schema_version": "arr.maas.book_compile_evidence.v1",
        "compile_passed": len(compiled) == len(cases),
        "compile_pass_count": len(compiled),
        "case_count": len(cases),
        "clean_pass_count": len(hard),
        "geometry_delta": round(minimum_delta, 5),
        "hard_pass": len(hard) == len(cases),
        "execution_verbs": list(verbs),
        "cases": cases,
    }


@lru_cache(maxsize=1)
def audit_book_principles() -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for operative in BASE_OPERATIVES:
        evidence[operative.principle_id] = _audit_sequence(operative.principle_id, operative.verb, (operative.verb,))
    for index, (_page, left, right) in enumerate(COMBINATIONS, start=1):
        principle_id = f"book:combination:{index:02d}:{left}+{right}"
        evidence[principle_id] = _audit_sequence(principle_id, f"{left}_{right}", (left, right))
    for _page, methods, verb in AGGREGATIONS:
        principle_id = f"book:aggregation:{'+'.join(methods)}:{verb}"
        evidence[principle_id] = _audit_sequence(principle_id, f"{verb}_{'_'.join(methods)}", (verb, *methods))
    for page, _label, verbs in CASE_STUDIES:
        principle_id = f"book:case:{page}:{'+'.join(verbs)}"
        evidence[principle_id] = _audit_sequence(principle_id, f"case_{page}_{'_'.join(verbs)}", verbs)
    return evidence


def audit_book_base_operatives() -> dict[str, dict[str, Any]]:
    """Compatibility view retained for callers that only need base verbs."""
    evidence = audit_book_principles()
    return {item.principle_id: evidence[item.principle_id] for item in BASE_OPERATIVES}


__all__ = ["audit_book_base_operatives", "audit_book_principles"]

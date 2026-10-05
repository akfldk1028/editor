"""Pairwise visual/precedent similarity for final MAAS projection.

The VLM scores candidates independently.  This module turns its concept
vectors and ArchDaily retrieval evidence into a set-level anti-duplication
signal without pretending that metadata matching is an image embedding.
"""

from __future__ import annotations

from math import sqrt
from typing import Any

from shapely.geometry import shape
from shapely.ops import unary_union


Feature = dict[str, Any]


def visual_precedent_signature(feature: Feature) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    concepts = preference.get("concept_scores") if isinstance(preference.get("concept_scores"), dict) else {}
    references = preference.get("reference_matches") if isinstance(preference.get("reference_matches"), list) else []
    reference_ids = tuple(sorted({
        str(item.get("source_id"))
        for item in references[:5]
        if isinstance(item, dict) and item.get("source") == "archdaily_api" and item.get("source_id")
    }))
    roles = source.get("source_volume_roles") if isinstance(source.get("source_volume_roles"), list) else []
    volume_count = int(source.get("visible_volume_count") or len(source.get("source_volumes") or roles) or 0)
    polygons = []
    for item in props.get("mass_volumes") or []:
        if not isinstance(item, dict) or not isinstance(item.get("geometry"), dict):
            continue
        try:
            geometry = shape(item["geometry"])
        except Exception:
            continue
        if not geometry.is_empty and geometry.area > 0:
            polygons.append(geometry)
    aspect_ratio = 1.0
    plan_signature: tuple[float, ...] = ()
    if polygons:
        footprint = unary_union(polygons)
        minx, miny, maxx, maxy = footprint.bounds
        width, depth = maxx - minx, maxy - miny
        aspect_ratio = max(width, depth) / max(min(width, depth), 1e-6)
        largest = max(polygon.area for polygon in polygons)
        signature_values: list[float] = []
        for polygon in sorted(polygons, key=lambda item: item.area, reverse=True)[:4]:
            signature_values.extend((
                polygon.area / largest,
                (polygon.centroid.x - minx) / max(width, 1e-6),
                (polygon.centroid.y - miny) / max(depth, 1e-6),
            ))
        plan_signature = tuple(signature_values)
    return {
        "references": reference_ids,
        "concepts": tuple(float(concepts.get(key) or 0.0) for key in (
            "gesture_clarity", "hierarchy", "non_stair_silhouette",
            "void_publicness", "repair_integrity", "precedent_resonance",
        )),
        "surface_count": int(source.get("surface_count") or 0),
        "volume_count": volume_count,
        "height": float(props.get("height") or 0.0),
        "visual_vector": (
            float(source.get("surface_count") or 0),
            float(volume_count),
            float(props.get("height") or 0.0),
            float(aspect_ratio),
            *plan_signature,
        ),
    }


def pairwise_visual_similarity(left: Any, right: Any) -> float:
    """Return a conservative 0..1 duplicate likelihood for two descriptors."""
    score = 0.0
    score += 0.18 if left.family and left.family == right.family else 0.0
    score += 0.18 if left.language and left.language == right.language else 0.0
    score += 0.14 if left.formal_principle and left.formal_principle == right.formal_principle else 0.0
    score += 0.16 if left.role_pattern and left.role_pattern == right.role_pattern else 0.0
    lv, rv = left.visual_vector, right.visual_vector
    if len(lv) >= 3 and len(rv) >= 3:
        score += 0.08 * max(0.0, 1.0 - abs(lv[0] - rv[0]) / 12.0)
        score += 0.08 * max(0.0, 1.0 - abs(lv[1] - rv[1]) / 2.0)
        score += 0.04 * max(0.0, 1.0 - abs(lv[2] - rv[2]) / 5.6)
    if len(lv) >= 4 and len(rv) >= 4:
        score += 0.04 * max(0.0, 1.0 - abs(lv[3] - rv[3]) / 1.5)
    lc, rc = left.concept_vector, right.concept_vector
    if lc and rc and len(lc) == len(rc):
        norm = sqrt(sum(value * value for value in lc)) * sqrt(sum(value * value for value in rc))
        if norm:
            score += 0.10 * max(0.0, min(1.0, sum(a * b for a, b in zip(lc, rc)) / norm))
    lrefs, rrefs = set(left.reference_ids), set(right.reference_ids)
    if lrefs and rrefs:
        score += 0.04 * (len(lrefs & rrefs) / len(lrefs | rrefs))
    # Labels such as family/formal principle can legitimately differ while the
    # compiled silhouette is effectively the same. Do not let metadata evade
    # the duplicate gate when language, role topology, and coarse geometry all
    # coincide.
    if (
        left.language
        and left.language == right.language
        and len(lv) >= 3
        and len(rv) >= 3
        and abs(lv[0] - rv[0]) <= 4.0
        and abs(lv[1] - rv[1]) <= 0.5
        and abs(lv[2] - rv[2]) <= 0.2
        and len(lv) >= 4
        and len(rv) >= 4
        and abs(lv[3] - rv[3]) <= 0.25
        and _tail_distance(lv[4:], rv[4:]) <= 0.10
    ):
        # A geometry-equivalent duplicate is a true hard conflict and must not
        # disappear when soft similarity thresholds relax in later profiles.
        score = 1.0
    return round(min(1.0, score), 4)


def _tail_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    size = max(len(left), len(right), 1)
    padded_left = (*left, *((0.0,) * (size - len(left))))
    padded_right = (*right, *((0.0,) * (size - len(right))))
    return sum(abs(a - b) for a, b in zip(padded_left, padded_right)) / size


def duplicate_conflict_pairs(descriptors: list[Any], *, threshold: float = 0.82) -> list[tuple[int, int, float]]:
    return [
        (left_index, right_index, similarity)
        for left_index, left in enumerate(descriptors)
        for right_index, right in enumerate(descriptors[left_index + 1:], start=left_index + 1)
        if (similarity := pairwise_visual_similarity(left, right)) >= threshold
    ]


__all__ = ["duplicate_conflict_pairs", "pairwise_visual_similarity", "visual_precedent_signature"]

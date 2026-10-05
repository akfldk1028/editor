"""Immutable, portable events for reference, VLM, and preference memory."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping


EVENT_SCHEMA_VERSION = "arr.maas.design_memory_event.v1"
EVENT_TYPES = frozenset({
    "reference_retrieved",
    "reference_submitted_to_vlm",
    "vlm_judgement",
    "typed_edit_proposed",
    "human_pairwise_choice",
})


def build_reference_review_events(
    *,
    retrieved_references: Iterable[Mapping[str, Any]],
    vlm_result: Mapping[str, Any],
    program_hash: str,
    geometry_hash: str,
    require_exact_truth_policy: bool = False,
) -> tuple[MappingProxyType, ...]:
    """Bind retrieval and exact visual inputs without conflating the two."""

    retrieved = [dict(item) for item in retrieved_references]
    image_inputs = vlm_result.get("vlm_image_inputs")
    image_inputs = image_inputs if isinstance(image_inputs, Mapping) else {}
    submitted = [
        dict(item)
        for item in image_inputs.get("references") or ()
        if isinstance(item, Mapping) and item.get("used_by_vlm")
    ]
    if require_exact_truth_policy:
        if len(retrieved) != 5:
            raise ValueError("truth policy requires exactly five retrieved references")
        if len(submitted) != 2:
            raise ValueError("truth policy requires exactly two submitted references")

    response_id = str(vlm_result.get("response_id") or "")
    retrieved_by_id = {
        _reference_identity(item, index): item
        for index, item in enumerate(retrieved, start=1)
    }
    events: list[MappingProxyType] = []
    for order, reference in enumerate(retrieved, start=1):
        identity = _reference_identity(reference, order)
        events.append(_event(
            "reference_retrieved",
            program_hash=program_hash,
            geometry_hash=geometry_hash,
            source_id=identity,
            title=str(reference.get("title") or ""),
            retrieval_order=int(reference.get("retrieval_order") or order),
            used_by_vlm=False,
            **_reference_metadata(reference),
        ))

    for order, reference in enumerate(submitted, start=1):
        identity = _reference_identity(reference, order)
        merged = {
            **retrieved_by_id.get(identity, {}),
            **reference,
        }
        metadata = _reference_metadata(merged)
        input_order = int(merged.get("input_order") or order)
        if not response_id:
            raise ValueError("submitted reference requires a VLM response ID")
        if not program_hash or not geometry_hash:
            raise ValueError("submitted reference requires program and geometry hashes")
        if not metadata["sha256"]:
            raise ValueError(f"submitted reference {identity} requires SHA-256")
        if not metadata["local_path"] and not metadata["image_uri"]:
            raise ValueError(
                f"submitted reference {identity} requires local or remote identity"
            )
        events.append(_event(
            "reference_submitted_to_vlm",
            program_hash=program_hash,
            geometry_hash=geometry_hash,
            response_id=response_id,
            source_id=identity,
            title=str(merged.get("title") or ""),
            input_order=input_order,
            used_by_vlm=True,
            **metadata,
        ))

    events.append(_event(
        "vlm_judgement",
        program_hash=program_hash,
        geometry_hash=geometry_hash,
        response_id=response_id,
        model=str(vlm_result.get("model") or ""),
        hard_pass=bool(vlm_result.get(
            "hard_pass",
            vlm_result.get("program_fit_hard_pass", False),
        )),
        concept_scores=dict(vlm_result.get("concept_scores") or {}),
        critic_actions=[
            str(item) for item in vlm_result.get("critic_actions") or ()
        ],
        used_by_vlm=False,
    ))
    edits = [
        *(
            item for item in vlm_result.get("graph_edits") or ()
            if isinstance(item, Mapping)
        ),
        *(
            item for item in vlm_result.get("geometry_edits") or ()
            if isinstance(item, Mapping)
        ),
    ]
    for edit_order, edit in enumerate(edits, start=1):
        events.append(_event(
            "typed_edit_proposed",
            program_hash=program_hash,
            geometry_hash=geometry_hash,
            response_id=response_id,
            edit_order=edit_order,
            edit=dict(edit),
            used_by_vlm=False,
        ))
    return tuple(events)


def human_pairwise_choice_event(
    *,
    preferred_candidate_id: str,
    rejected_candidate_id: str,
    reviewer_id: str,
    session_id: str,
    reason: str,
    preferred_geometry_hash: str,
    rejected_geometry_hash: str,
) -> MappingProxyType:
    if not preferred_geometry_hash or not rejected_geometry_hash:
        raise ValueError("human pairwise choice requires both geometry hashes")
    return _event(
        "human_pairwise_choice",
        preferred_candidate_id=str(preferred_candidate_id),
        rejected_candidate_id=str(rejected_candidate_id),
        reviewer_id=str(reviewer_id),
        session_id=str(session_id),
        reason=str(reason),
        preferred_geometry_hash=str(preferred_geometry_hash),
        rejected_geometry_hash=str(rejected_geometry_hash),
        used_by_vlm=False,
    )


def mutable_event(value: Any) -> Any:
    """Recursively thaw an event for JSON serialization and persistence."""

    if isinstance(value, Mapping):
        return {
            str(key): mutable_event(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [mutable_event(item) for item in value]
    if isinstance(value, list):
        return [mutable_event(item) for item in value]
    return value


def _event(event_type: str, **payload: Any) -> MappingProxyType:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported design-memory event: {event_type}")
    body = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_type": event_type,
        **payload,
    }
    canonical = json.dumps(
        body,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _freeze({
        **body,
        "event_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    })


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _reference_identity(reference: Mapping[str, Any], order: int) -> str:
    return str(
        reference.get("source_id")
        or reference.get("input_id")
        or reference.get("sha256")
        or f"reference-{order}"
    )


def _reference_metadata(reference: Mapping[str, Any]) -> dict[str, Any]:
    provenance = reference.get("provenance")
    if isinstance(provenance, Mapping):
        provenance_record = dict(provenance)
    elif provenance:
        provenance_record = {"note": str(provenance)}
    else:
        provenance_record = {}
    return {
        "local_path": str(reference.get("local_path") or ""),
        "image_uri": str(
            reference.get("image_uri")
            or reference.get("image_url")
            or reference.get("preview_url")
            or ""
        ),
        "sha256": str(reference.get("sha256") or ""),
        "source_url": str(
            reference.get("source_url")
            or reference.get("page_url")
            or ""
        ),
        "reference_collection": str(
            reference.get("reference_collection") or ""
        ),
        "rights": str(
            reference.get("rights")
            or reference.get("license")
            or ""
        ),
        "provenance": provenance_record,
    }


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "EVENT_TYPES",
    "build_reference_review_events",
    "human_pairwise_choice_event",
    "mutable_event",
]

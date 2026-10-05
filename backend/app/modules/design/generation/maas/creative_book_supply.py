"""Canonical BOOK-language assignments for creative MASS production."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable
import hashlib
import json

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence

from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.affine_normalization import normalize_affine_basevolume_program
from backend.app.modules.design.generation.maas.geometry_language.book_adapter import apply_book_projection_to_geometry_program
from backend.app.modules.design.generation.maas.program_massing.book_projection import book_sentence_variants, compose_program_with_book_operations


_SCOPE_LABELS = ("1/1", "3/8", "1/2", "1/4", "1/8", "1/16")
_SCOPE_ORIENTATIONS = {
    "1/1": "long_axis",
    "3/8": "short_axis",
    "1/2": "long_axis",
    "1/4": "short_axis",
    "1/8": "vertical",
    "1/16": "vertical",
}
_SCHEDULED_KINDS = frozenset({
    "base_operative",
    "combination",
    "aggregation",
})
AUTHORED_SCHEDULE_POLICY = "source_set_rotated_kind_interleave.v1"


def authored_book_schedule_key(source_ids: Iterable[str]) -> str:
    """A set identity, independent of input ordering and candidate positions."""
    identities = list(source_ids)
    if any(not isinstance(identity, str) or not identity for identity in identities):
        raise ValueError("authored source identities must be nonempty strings")
    identities = sorted(set(identities))
    return hashlib.sha256(json.dumps(identities, separators=(",", ":")).encode("utf8")).hexdigest()


@dataclass(frozen=True)
class CreativeBookAssignment:
    principle_id: str
    principle_kind: str
    execution_verbs: tuple[str, ...]
    aggregation_methods: tuple[str, ...]
    scope_label: str
    orientation: str

    def evidence(self) -> dict[str, Any]:
        return {
            "principle_id": self.principle_id,
            "principle_kind": self.principle_kind,
            "execution_verbs": list(self.execution_verbs),
            "aggregation_methods": list(self.aggregation_methods),
            "scope_label": self.scope_label,
            "orientation": self.orientation,
        }


def creative_book_schedule(
    count: int,
    *,
    authored_source_ids: Iterable[str] | None = None,
) -> tuple[CreativeBookAssignment, ...]:
    """Return exhaustive assignments; optional authored mode avoids a prefix.

    The default fixture ordering is unchanged. Authored mode rotates each kind
    by source-set identity and interleaves kinds until every principle has been
    offered once. Offering is not a materialization or feasibility claim.
    """

    requested = int(count)
    if requested < 0:
        raise ValueError("count must be non-negative")
    principles = tuple(
        item
        for item in build_book_language_registry()["principles"]
        if str(item.get("kind") or "") in _SCHEDULED_KINDS
    )
    if len(principles) != 59:
        raise RuntimeError(
            "canonical BOOK schedule requires exactly 59 principles"
        )
    if authored_source_ids is not None:
        key = authored_book_schedule_key(authored_source_ids)
        groups = []
        for kind in ("base_operative", "combination", "aggregation"):
            group = [item for item in principles if item["kind"] == kind]
            offset = int(hashlib.sha256(f"{key}:{kind}".encode("utf8")).hexdigest(), 16) % len(group)
            groups.append(group[offset:] + group[:offset])
        principles = tuple(group[index] for index in range(max(map(len, groups)))
                           for group in groups if index < len(group))
    result: list[CreativeBookAssignment] = []
    for index in range(requested):
        principle = principles[index % len(principles)]
        scope_label = _SCOPE_LABELS[index % len(_SCOPE_LABELS)]
        result.append(CreativeBookAssignment(
            principle_id=str(principle["principle_id"]),
            principle_kind=str(principle["kind"]),
            execution_verbs=tuple(
                str(verb)
                for verb in principle.get("execution_verbs") or ()
            ),
            aggregation_methods=tuple(
                str(method)
                for method in principle.get("aggregation_methods") or ()
            ),
            scope_label=scope_label,
            orientation=_SCOPE_ORIENTATIONS[scope_label],
        ))
    return tuple(result)


def project_creative_book_program(
    program: GeometryProgram,
    assignment: CreativeBookAssignment,
) -> GeometryProgram:
    """Materialize one scheduled BOOK scope and principle in the AST."""

    operations = book_sentence_variants(
        assignment.execution_verbs,
        count=1,
    )[0]
    sequence = compose_program_with_book_operations(
        VerbSequence(
            name=f"creative-{program.name}-source",
            label=program.name,
            calls=(VerbCall("base", {}),),
        ),
        operations,
        name_suffix=assignment.principle_id.replace(":", "-")
        .replace("+", "-"),
        base_volume_label=assignment.scope_label,
        orientation=assignment.orientation,
    )
    projected = apply_book_projection_to_geometry_program(program, sequence)
    assigned = replace(
        projected,
        metadata={
            **projected.metadata,
            "creative_book_assignment": assignment.evidence(),
        },
    )
    return normalize_affine_basevolume_program(assigned)


def creative_book_evidence(
    program: GeometryProgram,
) -> dict[str, Any]:
    """Return assignment evidence only when executable AST witnesses exist."""

    assignment = program.metadata.get("creative_book_assignment")
    projection = program.metadata.get("book_recursive_projection")
    if not isinstance(assignment, dict):
        return {}
    if not isinstance(projection, dict) or not projection.get("active"):
        return {}
    book_nodes = [
        node
        for node in program.topological_nodes()
        if str((node.provenance or {}).get("source") or "")
        == "book_recursive_projection"
    ]
    selector = next((
        node
        for node in book_nodes
        if node.operator == "book_base_volume"
        and str((node.provenance or {}).get("book_verb") or "")
        == "select_book_scope"
    ), None)
    projected_nodes = [
        node.id
        for node in book_nodes
        if node is not selector
    ]
    if selector is None or not projected_nodes:
        return {}
    return {
        "schema_version": "arr.maas.creative_book_evidence.v1",
        "materialized": True,
        "principle_id": str(assignment.get("principle_id") or ""),
        "principle_kind": str(assignment.get("principle_kind") or ""),
        "execution_verbs": list(
            assignment.get("execution_verbs") or ()
        ),
        "aggregation_methods": list(
            assignment.get("aggregation_methods") or ()
        ),
        "scope_label": str(assignment.get("scope_label") or ""),
        "orientation": str(assignment.get("orientation") or ""),
        "selector_node_id": selector.id,
        "projected_node_ids": projected_nodes,
    }


__all__ = [
    "CreativeBookAssignment",
    "creative_book_evidence",
    "creative_book_schedule",
    "authored_book_schedule_key",
    "AUTHORED_SCHEDULE_POLICY",
    "project_creative_book_program",
]

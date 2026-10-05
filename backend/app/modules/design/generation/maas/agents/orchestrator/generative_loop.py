"""Executable A2A generate-compile-critic-revise archive loop.

Agent cards and post-hoc reviews are not a generative multi-agent system.  This
module provides the typed closed loop.  It owns no architectural templates:
the language-author and critic/reviser are injected agents, while the geometry
and hard-gate callbacks remain deterministic ARR services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence


Feature = dict[str, Any]


@dataclass(frozen=True)
class GraphEditDirective:
    operation: str
    target_node_id: str = ""
    parent_node_id: str = ""
    node_id: str = ""
    role: str = ""
    verb: str = ""
    parameter_name: str = ""
    numeric_value: float = 0.0
    string_value: str = ""
    control_point_index: int = 0
    control_point_u: float = 0.0
    control_point_v: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class GeometryEditDirective:
    operation: str
    target_node_id: str = ""
    node_id: str = ""
    node_kind: str = ""
    operator: str = ""
    input_ids: tuple[str, ...] = ()
    input_index: int = 0
    input_node_id: str = ""
    parameter_name: str = ""
    numeric_value: float = 0.0
    string_value: str = ""
    vector_value: tuple[float, ...] = ()
    semantic_role: str = ""
    rationale: str = ""


@dataclass(frozen=True)
class CriticDirective:
    actions: tuple[str, ...] = ()
    graph_edits: tuple[GraphEditDirective, ...] = ()
    geometry_edits: tuple[GeometryEditDirective, ...] = ()
    scores: dict[str, float] = field(default_factory=dict)
    reference_evidence: tuple[dict[str, Any], ...] = ()
    provider: str = ""

    @property
    def actionable(self) -> bool:
        return bool(self.actions or self.graph_edits or self.geometry_edits)


@dataclass(frozen=True)
class GenerativeLoopResult:
    archive: tuple[Feature, ...]
    trace: dict[str, Any]


AuthorPopulation = Callable[[dict[str, Any]], Iterable[VerbSequence]]
CompileCandidate = Callable[[VerbSequence], Feature | None]
HardGate = Callable[[Feature], bool]
CriticAgent = Callable[[Feature], CriticDirective]
ReviseGraph = Callable[[VerbSequence, CriticDirective], Iterable[VerbSequence]]
QualityKey = Callable[[Feature], tuple[Any, ...]]
SelectArchive = Callable[[list[Feature], int], list[Feature]]


def run_generative_a2a_loop(
    *,
    context: dict[str, Any],
    target_count: int,
    author_population: AuthorPopulation,
    compile_candidate: CompileCandidate,
    hard_gate: HardGate,
    critic_agent: CriticAgent,
    revise_graph: ReviseGraph,
    quality_key: QualityKey,
    select_archive: SelectArchive,
    max_generations: int = 3,
) -> GenerativeLoopResult:
    frontier = list(author_population(context))
    accepted: list[Feature] = []
    seen_sequences: set[tuple[Any, ...]] = set()
    trace: dict[str, Any] = {
        "schema_version": "arr.maas.generative_a2a_loop.v1",
        "status": "running",
        "target_count": target_count,
        "max_generations": max_generations,
        "generations": [],
    }
    for generation in range(max(1, max_generations)):
        records: list[dict[str, Any]] = []
        revised: list[VerbSequence] = []
        for sequence in frontier:
            signature = tuple(
                (call.verb, tuple(sorted((str(key), str(value)) for key, value in call.params.items())))
                for call in sequence.calls
            )
            if signature in seen_sequences:
                continue
            seen_sequences.add(signature)
            record: dict[str, Any] = {
                "sequence": sequence.name,
                "generation": generation,
                "verbs": [call.verb for call in sequence.calls],
            }
            feature = compile_candidate(sequence)
            if feature is None:
                record["status"] = "compile_rejected"
                records.append(record)
                continue
            if not hard_gate(feature):
                record["status"] = "hard_gate_rejected"
                records.append(record)
                continue
            directive = critic_agent(feature)
            record.update({
                "status": "critic_reviewed",
                "critic_provider": directive.provider,
                "critic_actions": list(directive.actions),
                "graph_edits": [edit.__dict__ for edit in directive.graph_edits],
                "critic_scores": directive.scores,
            })
            accepted.append(feature)
            if generation + 1 < max_generations and directive.actionable:
                revised.extend(revise_graph(sequence, directive))
            records.append(record)
        # Keep one best copy per variant identity before the archive agent runs.
        best: dict[str, Feature] = {}
        for feature in accepted:
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            identity = str(props.get("variant_id") or props.get("mass_shape") or id(feature))
            if identity not in best or quality_key(feature) > quality_key(best[identity]):
                best[identity] = feature
        accepted = list(best.values())
        trace["generations"].append({
            "generation": generation,
            "input_count": len(frontier),
            "revision_count": len(revised),
            "records": records,
        })
        frontier = revised
        if not frontier:
            break
    archive = select_archive(accepted, max(1, target_count))
    trace.update({
        "status": "completed" if len(archive) >= target_count else "insufficient_verified_archive",
        "evaluated_sequence_count": len(seen_sequences),
        "verified_candidate_count": len(accepted),
        "archive_count": len(archive),
    })
    return GenerativeLoopResult(tuple(archive), trace)


def critic_directive_from_feature(feature: Feature) -> CriticDirective:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    edits = tuple(
        GraphEditDirective(
            operation=str(item.get("operation") or ""),
            target_node_id=str(item.get("target_node_id") or ""),
            parent_node_id=str(item.get("parent_node_id") or ""),
            node_id=str(item.get("node_id") or ""),
            role=str(item.get("role") or ""),
            verb=str(item.get("verb") or ""),
            parameter_name=str(item.get("parameter_name") or ""),
            numeric_value=float(item.get("numeric_value") or 0.0),
            string_value=str(item.get("string_value") or ""),
            control_point_index=int(item.get("control_point_index") or 0),
            control_point_u=float(item.get("control_point_u") or 0.0),
            control_point_v=float(item.get("control_point_v") or 0.0),
            rationale=str(item.get("rationale") or ""),
        )
        for item in preference.get("graph_edits") or [] if isinstance(item, dict)
    )
    geometry_edits = tuple(
        GeometryEditDirective(
            operation=str(item.get("operation") or ""),
            target_node_id=str(item.get("target_node_id") or ""),
            node_id=str(item.get("node_id") or ""),
            node_kind=str(item.get("node_kind") or ""),
            operator=str(item.get("operator") or ""),
            input_ids=tuple(str(value) for value in item.get("input_ids") or ()),
            input_index=int(item.get("input_index") or 0),
            input_node_id=str(item.get("input_node_id") or ""),
            parameter_name=str(item.get("parameter_name") or ""),
            numeric_value=float(item.get("numeric_value") or 0.0),
            string_value=str(item.get("string_value") or ""),
            vector_value=tuple(float(value) for value in item.get("vector_value") or ()),
            semantic_role=str(item.get("semantic_role") or ""),
            rationale=str(item.get("rationale") or ""),
        )
        for item in preference.get("geometry_edits") or [] if isinstance(item, dict)
    )
    scores = preference.get("concept_scores") if isinstance(preference.get("concept_scores"), dict) else {}
    return CriticDirective(
        actions=tuple(str(item) for item in preference.get("critic_actions") or []),
        graph_edits=edits,
        geometry_edits=geometry_edits,
        scores={str(key): float(value) for key, value in scores.items() if isinstance(value, int | float)},
        reference_evidence=tuple(item for item in preference.get("reference_matches") or [] if isinstance(item, dict)),
        provider=str(preference.get("vlm_model") or preference.get("mode") or ""),
    )


__all__ = [
    "CriticDirective",
    "GenerativeLoopResult",
    "GraphEditDirective",
    "GeometryEditDirective",
    "critic_directive_from_feature",
    "run_generative_a2a_loop",
]

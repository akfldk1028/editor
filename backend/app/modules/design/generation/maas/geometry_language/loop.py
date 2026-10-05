"""LLM author -> solid compiler -> VLM critic -> typed AST revision loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.mutation import GeometryEdit, apply_geometry_edits_compiler_safe
from backend.app.modules.design.generation.maas.geometry_language.render import render_compilation_preview


@dataclass(frozen=True)
class GeometryLoopCandidate:
    program: GeometryProgram
    compilation: CompilationResult
    generation: int
    critic_score: float
    critic_payload: dict[str, Any] = field(default_factory=dict)
    preview_path: str = ""


@dataclass(frozen=True)
class GeometryLoopResult:
    archive: tuple[GeometryLoopCandidate, ...]
    trace: dict[str, Any]


AuthorPrograms = Callable[[dict[str, Any]], Iterable[GeometryProgram]]
CriticProgram = Callable[[GeometryProgram, CompilationResult, Path], dict[str, Any]]
SelectPrograms = Callable[[list[GeometryLoopCandidate], int], list[GeometryLoopCandidate]]
PreviewRenderer = Callable[[GeometryProgram, CompilationResult, Path], Path]


def run_geometry_program_a2a_loop(
    *,
    context: dict[str, Any],
    target_count: int,
    author_programs: AuthorPrograms,
    critic_program: CriticProgram,
    max_generations: int = 3,
    gate_policy: GeometryGatePolicy | None = None,
    select_programs: SelectPrograms | None = None,
    preview_dir: str | Path | None = None,
    author_provider: str = "injected_callback",
    critic_provider: str = "injected_callback",
    preview_renderer: PreviewRenderer | None = None,
) -> GeometryLoopResult:
    """Run a real closed loop whose critic edits are recompiled solids.

    The author may be an LLM adapter, but it only returns validated programs.
    The critic may be the OpenAI VLM scorer or a deterministic test critic.  A
    revision is archived only after its AST hash and resulting mesh hash both
    change and the complete solid hard gate passes again.
    """
    policy = gate_policy or GeometryGatePolicy()
    selector = select_programs or _default_selector
    frontier = list(author_programs(context))
    archive_by_geometry: dict[str, GeometryLoopCandidate] = {}
    seen_programs: set[str] = set()
    trace: dict[str, Any] = {
        "schema_version": "arr.maas.geometry_program_a2a_loop.v1",
        "status": "running",
        "target_count": max(1, int(target_count)),
        "max_generations": max(1, int(max_generations)),
        "generations": [],
        "author_provider": author_provider,
        "critic_provider": critic_provider,
        "llm_author_active": author_provider.lower() in {
            "openai", "llm", "openai_llm", "openai_llm_geometry_author",
            "bounded_procedural_plus_openai_llm",
        },
        "vlm_geometry_critic_active": critic_provider.lower() in {"openai", "vlm", "openai_vlm"},
        "author_callback_active": True,
        "critic_callback_active": True,
        "typed_ast_revision_active": True,
    }
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if preview_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="maas-geometry-program-loop-")
        root = Path(temporary.name)
    else:
        root = Path(preview_dir)
        root.mkdir(parents=True, exist_ok=True)
    try:
        for generation in range(max(1, int(max_generations))):
            next_frontier: list[GeometryProgram] = []
            records: list[dict[str, Any]] = []
            for program_index, program in enumerate(frontier):
                program_hash = program.program_hash() if not [i for i in program.validate() if i.severity == "error"] else ""
                if program_hash and program_hash in seen_programs:
                    records.append({"program": program.name, "status": "duplicate_program_skipped"})
                    continue
                if program_hash:
                    seen_programs.add(program_hash)
                compilation = compile_geometry_program(program)
                gate_issues = compilation_gate(compilation, policy)
                record: dict[str, Any] = {
                    "generation": generation,
                    "program": program.name,
                    "program_hash": program_hash,
                    "compile_status": compilation.status,
                    "geometry_hash": compilation.geometry_hash,
                    "gate_issues": [issue.to_dict() for issue in gate_issues],
                }
                if compilation.status != "compiled" or gate_issues:
                    record["status"] = "compile_or_gate_rejected"
                    records.append(record)
                    continue
                preview_output = root / f"g{generation:02d}_{program_index:03d}_{program_hash[:10]}.png"
                preview = (
                    preview_renderer(program, compilation, preview_output)
                    if preview_renderer is not None
                    else render_compilation_preview(
                        compilation,
                        preview_output,
                        title=program.name,
                    )
                )
                payload = critic_program(program, compilation, preview)
                if not isinstance(payload, dict):
                    payload = {}
                score = _critic_score(payload)
                candidate = GeometryLoopCandidate(program, compilation, generation, score, payload, str(preview))
                # A VLM-rejected form is still useful as a causal parent for a
                # typed repair, but it must never enter the accepted archive.
                # Injected deterministic critics predate this contract, so an
                # absent field remains backward-compatible; the live scorer
                # always returns the explicit boolean.
                program_fit_hard_pass = bool(payload.get("program_fit_hard_pass", True))
                if program_fit_hard_pass:
                    incumbent = archive_by_geometry.get(compilation.geometry_hash)
                    if incumbent is None or candidate.critic_score > incumbent.critic_score:
                        archive_by_geometry[compilation.geometry_hash] = candidate
                raw_edits = payload.get("geometry_edits") or []
                edits = tuple(GeometryEdit.from_dict(item) for item in raw_edits if isinstance(item, dict))
                safe_mutation = apply_geometry_edits_compiler_safe(program, edits)
                mutation = safe_mutation.mutation
                record.update({
                    "status": (
                        "critic_reviewed"
                        if program_fit_hard_pass
                        else "critic_program_fit_rejected"
                    ),
                    "critic_score": round(score, 6),
                    "program_fit_hard_pass": program_fit_hard_pass,
                    "program_appropriateness": float(
                        (payload.get("concept_scores") or {}).get("program_appropriateness") or 0.0
                    ),
                    "section_program_fit": float(
                        (payload.get("concept_scores") or {}).get("section_program_fit") or 0.0
                    ),
                    "reference_assessments": list(payload.get("reference_assessments") or ()),
                    "critic_model": str(payload.get("model") or ""),
                    "critic_response_id": str(payload.get("response_id") or ""),
                    "critic_actions": [str(item) for item in payload.get("critic_actions") or []],
                    "geometry_edits": [edit.to_dict() for edit in edits],
                    "mutation_status": mutation.status,
                    "mutation_issues": [issue.to_dict() for issue in mutation.issues],
                    "compiler_safe_recovery_mode": safe_mutation.recovery_mode,
                    "compiler_safe_rejected_groups": list(safe_mutation.rejected_groups),
                    "preview_path": str(preview),
                    "vlm_causal_context": (
                        payload.get("maas_causal_context")
                        if isinstance(payload.get("maas_causal_context"), dict)
                        else {}
                    ),
                    "mass_execution_agent_context": (
                        payload.get("mass_execution_agent_context")
                        if isinstance(payload.get("mass_execution_agent_context"), dict)
                        else {}
                    ),
                })
                if mutation.program is not None and generation + 1 < max_generations:
                    child_compilation = (
                        safe_mutation.compilation
                        if safe_mutation.compilation is not None
                        else compile_geometry_program(mutation.program)
                    )
                    child_gate_issues = compilation_gate(child_compilation, policy)
                    geometry_changed = (
                        child_compilation.status == "compiled"
                        and child_compilation.geometry_hash
                        and child_compilation.geometry_hash != compilation.geometry_hash
                    )
                    record["revision_proof"] = {
                        "parent_program_hash": program_hash,
                        "child_program_hash": mutation.program.program_hash(),
                        "parent_geometry_hash": compilation.geometry_hash,
                        "child_geometry_hash": child_compilation.geometry_hash,
                        "program_changed": mutation.program.program_hash() != program_hash,
                        "geometry_changed": geometry_changed,
                        "child_gate_issues": [issue.to_dict() for issue in child_gate_issues],
                    }
                    if geometry_changed and not child_gate_issues:
                        next_frontier.append(mutation.program)
                    else:
                        record["mutation_status"] = "revision_geometry_or_gate_rejected"
                records.append(record)
            trace["generations"].append({
                "generation": generation,
                "frontier_count": len(frontier),
                "revised_frontier_count": len(next_frontier),
                "records": records,
            })
            frontier = next_frontier
            if not frontier:
                break
        selected = selector(list(archive_by_geometry.values()), max(1, int(target_count)))
        trace.update({
            "status": "completed" if len(selected) >= target_count else "insufficient_verified_archive",
            "unique_program_count": len(seen_programs),
            "unique_geometry_count": len(archive_by_geometry),
            "archive_count": len(selected),
            "geometry_revision_count": sum(
                1
                for generation in trace["generations"]
                for record in generation["records"]
                if (record.get("revision_proof") or {}).get("geometry_changed")
            ),
        })
        return GeometryLoopResult(tuple(selected), trace)
    finally:
        if temporary is not None:
            temporary.cleanup()


def _critic_score(payload: dict[str, Any]) -> float:
    scores = payload.get("concept_scores") if isinstance(payload.get("concept_scores"), dict) else {}
    values = [float(value) for value in scores.values() if isinstance(value, (int, float))]
    score = sum(values) / len(values) if values else float(payload.get("score") or 0.0)
    actions = {str(item) for item in payload.get("critic_actions") or []}
    score -= 0.12 if "too_box_like" in actions else 0.0
    score -= 0.08 if "weak_form_continuity" in actions else 0.0
    score -= 0.08 if "overlapping_volumes" in actions else 0.0
    score -= 0.25 if "wrong_program_typology" in actions else 0.0
    score -= 0.18 if "missing_program_section" in actions else 0.0
    return max(0.0, min(1.0, score))


def _default_selector(candidates: list[GeometryLoopCandidate], count: int) -> list[GeometryLoopCandidate]:
    def selection_key(item: GeometryLoopCandidate) -> tuple[float, float, int]:
        context = item.critic_payload.get("mass_execution_agent_context")
        context = context if isinstance(context, dict) else {}
        failed_count = len(context.get("failed_stages") or ())
        return (
            -float(failed_count),
            item.critic_score,
            -int(item.compilation.metrics.get("triangle_count") or 0),
        )

    return sorted(
        candidates,
        key=selection_key,
        reverse=True,
    )[:count]


__all__ = [
    "GeometryLoopCandidate",
    "GeometryLoopResult",
    "PreviewRenderer",
    "run_geometry_program_a2a_loop",
]

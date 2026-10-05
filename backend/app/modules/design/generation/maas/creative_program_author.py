"""Source-neutral contracts for LLM-authored creative GeometryPrograms."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.dimensional_intent import KEY, program_intent, validate_intent
from backend.app.modules.design.generation.maas.creative_family_contract import CreativeRecipeResult
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.affine_normalization import normalize_affine_basevolume_program
from backend.app.modules.design.generation.maas.geometry_language.llm_adapter import geometry_programs_from_author_payload


AUTHOR_EVIDENCE_SCHEMA = "arr.maas.creative_author_evidence.v1"


@dataclass(frozen=True)
class CreativeAuthoredProgram:
    program: GeometryProgram
    author_evidence: dict[str, Any]


def normalize_authored_programs(
    programs: Iterable[GeometryProgram | CreativeAuthoredProgram],
) -> tuple[CreativeAuthoredProgram, ...]:
    result: list[CreativeAuthoredProgram] = []
    for item in programs:
        program_intent(item.program if isinstance(item, CreativeAuthoredProgram) else item)
        if isinstance(item, CreativeAuthoredProgram):
            result.append(CreativeAuthoredProgram(
                program=normalize_affine_basevolume_program(item.program),
                author_evidence=dict(item.author_evidence),
            ))
        elif isinstance(item, GeometryProgram):
            normalized = normalize_affine_basevolume_program(item)
            result.append(CreativeAuthoredProgram(
                program=normalized,
                author_evidence=author_evidence_from_program(normalized),
            ))
        else:
            raise TypeError(
                "authored_programs must contain GeometryProgram values"
            )
    return tuple(result)


def authored_programs_from_payload(
    payload: dict[str, Any],
    *,
    expected_count: int,
    program_context: dict[str, Any] | None = None,
) -> tuple[CreativeAuthoredProgram, ...]:
    for item in payload.get("programs", []):
        if isinstance(item, dict) and item.get(KEY) is not None:
            validate_intent(item[KEY])
    exact_programs = payload.get("geometry_programs")
    if isinstance(payload.get("sentences"), list):
        # BOOK sentences: the grammar builds the geometry; the author chose,
        # sized and faced. See book_language/sentence_author.py.
        import os
        from backend.app.modules.design.generation.maas.book_language.sentence_author import realize_sentence_payload
        programs = realize_sentence_payload(
            payload, expected_count=expected_count,
            building_type=os.environ.get("BUILDING_TYPE") or None)
    elif isinstance(exact_programs, list):
        programs = tuple(
            GeometryProgram.from_dict(item)
            for item in exact_programs
            if isinstance(item, dict)
        )
        if len(programs) < max(1, int(expected_count)):
            raise ValueError(
                "author payload contains fewer exact programs than requested"
            )
    elif isinstance(payload.get("nodes"), list) and payload.get("root_id"):
        programs = (GeometryProgram.from_dict(payload),)
    else:
        programs = geometry_programs_from_author_payload(
            payload,
            expected_count=expected_count,
            program_context=program_context,
        )
    return normalize_authored_programs(programs)


def authored_programs_from_cache_pool(
    cache_root: Path,
    *,
    expected_count: int,
) -> tuple[CreativeAuthoredProgram, ...]:
    """Load a deterministic unique prefix of accepted exact LLM programs."""

    requested = max(1, int(expected_count))
    selected = cached_authored_programs(cache_root, limit=requested)
    if len(selected) < requested:
        raise ValueError(
            "accepted geometry author cache pool contains fewer unique exact "
            f"programs than requested: {len(selected)}/{requested}"
        )
    return selected


def cached_authored_programs(
    cache_root: Path,
    *,
    limit: int,
) -> tuple[CreativeAuthoredProgram, ...]:
    """Return up to limit unique compiler-clean accepted cached programs."""

    root = Path(cache_root).resolve()
    requested = max(0, int(limit))
    if not root.is_dir():
        raise ValueError(f"geometry author cache directory is missing: {root}")
    if requested == 0:
        return ()
    selected: list[CreativeAuthoredProgram] = []
    seen_hashes: set[str] = set()
    seen_geometry_hashes: set[str] = set()
    connected_policy = GeometryGatePolicy(maximum_components=1)
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if (
            not isinstance(payload, dict)
            or payload.get("cache_schema_version")
            != "arr.maas.geometry_llm_author_cache.v3"
            or payload.get("validation_status") != "accepted"
            or not isinstance(payload.get("compiled_programs"), list)
        ):
            continue
        for raw_program in payload["compiled_programs"]:
            if not isinstance(raw_program, dict):
                continue
            try:
                program = GeometryProgram.from_dict(raw_program)
            except (TypeError, ValueError):
                continue
            decorated = replace(
                program,
                metadata={
                    **program.metadata,
                    "author_provider": (
                        program.metadata.get("author_provider")
                        or "openai_llm_geometry_author"
                    ),
                    "author_model": (
                        program.metadata.get("author_model")
                        or str(payload.get("model") or "")
                    ),
                    "author_response_id": (
                        program.metadata.get("author_response_id")
                        or str(payload.get("response_id") or "")
                    ),
                    "author_cache_hit": True,
                    "author_cache_path": str(path),
                },
            )
            try:
                authored = normalize_authored_programs((decorated,))[0]
            except (RuntimeError, TypeError, ValueError):
                # Accepted legacy cache records can predate the strict
                # UnitBox/Matrix4 authority. They are not production supply,
                # but one stale record must not abort scanning later valid
                # cached programs.
                continue
            canonical_bases = tuple(
                node
                for node in authored.program.nodes
                if (
                    node.kind == "primitive"
                    and node.operator == "box"
                    and node.parameters
                    == {"width": 1.0, "depth": 1.0, "height": 1.0}
                )
            )
            if len(canonical_bases) != 1:
                continue
            program_hash = authored.program.program_hash()
            if program_hash in seen_hashes:
                continue
            try:
                compilation = compile_geometry_program(authored.program)
            except (RuntimeError, TypeError, ValueError):
                continue
            if (
                compilation_gate(compilation, connected_policy)
                or int(compilation.metrics.get("component_count") or 0) != 1
                or compilation.metrics.get("watertight") is not True
                or compilation.metrics.get("manifold") is not True
                or compilation.geometry_hash in seen_geometry_hashes
            ):
                continue
            seen_hashes.add(program_hash)
            seen_geometry_hashes.add(compilation.geometry_hash)
            selected.append(authored)
            if len(selected) >= requested:
                return tuple(selected)
    return tuple(selected)


def author_evidence_from_program(
    program: GeometryProgram,
) -> dict[str, Any]:
    metadata = program.metadata
    return {
        "schema_version": AUTHOR_EVIDENCE_SCHEMA,
        "source_kind": "llm_authored_geometry_program",
        "provider": str(metadata.get("author_provider") or "unknown"),
        "model": str(metadata.get("author_model") or ""),
        "response_id": str(metadata.get("author_response_id") or ""),
        "cache_hit": bool(metadata.get("author_cache_hit")),
        "prompt_contract": str(
            metadata.get("author_prompt_contract") or ""
        ),
    }


def authored_program_result(
    authored: CreativeAuthoredProgram,
) -> CreativeRecipeResult:
    program = authored.program
    return CreativeRecipeResult(
        program=program,
        contact_type="compiled_connected_solid",
        contact_node_id=program.root_id,
        form_class="posthoc_morphology",
        recipe_parameters={
            "source_family": "llm_authored",
            "author_evidence": dict(authored.author_evidence),
        },
    )


def posthoc_family_label(
    program: GeometryProgram,
    compilation: CompilationResult,
) -> str:
    """Classify compiled morphology without selecting a form builder."""

    bounds = compilation.metrics.get("bounds") or ()
    if len(bounds) != 2:
        raise ValueError("post-hoc family classification requires bounds")
    minimum, maximum = bounds
    spans = tuple(
        max(
            1e-9,
            float(maximum[index]) - float(minimum[index]),
        )
        for index in range(3)
    )
    if not all(isfinite(value) for value in spans):
        raise ValueError("post-hoc family classification requires finite bounds")
    operators = {
        node.operator
        for node in program.topological_nodes()
        if node.kind != "primitive"
    }
    matrices = [
        node.parameters.get("matrix4")
        for node in program.topological_nodes()
        if node.operator == "matrix4"
    ]
    oblique = any(
        isinstance(matrix, (list, tuple))
        and len(matrix) >= 3
        and any(
            abs(float(matrix[row][column])) > 1e-8
            for row, column in (
                (0, 1), (0, 2), (1, 0),
                (1, 2), (2, 0), (2, 1),
            )
        )
        for matrix in matrices
    )
    if "bridge" in operators:
        gesture = "bridge"
    elif operators.intersection({"circularize", "twist", "bend"}):
        gesture = "curved"
    elif operators.intersection({"array_linear", "array_radial"}):
        gesture = "repeated"
    elif "difference" in operators:
        gesture = "voided"
    elif oblique:
        gesture = "oblique"
    else:
        plan_ratio = max(spans[0], spans[1]) / min(spans[0], spans[1])
        gesture = "linear" if plan_ratio >= 2.4 else "compact"
    height_ratio = spans[2] / max(spans[0], spans[1])
    vertical = (
        "tall"
        if height_ratio >= 1.4
        else "low"
        if height_ratio <= 0.55
        else "mid"
    )
    return f"morph-{gesture}-{vertical}"


__all__ = [
    "AUTHOR_EVIDENCE_SCHEMA",
    "CreativeAuthoredProgram",
    "authored_program_result",
    "cached_authored_programs",
    "authored_programs_from_payload",
    "authored_programs_from_cache_pool",
    "author_evidence_from_program",
    "normalize_authored_programs",
    "posthoc_family_label",
]

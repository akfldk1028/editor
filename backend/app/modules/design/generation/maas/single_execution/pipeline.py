"""Execute one explicit GeometryProgram without entering portfolio search.

Generation, retrieval, paid VLM critique, and portfolio selection intentionally
live outside this boundary.  Any of those agents can hand this module one AST;
the same compiler, hard geometry gate, renderer, passport, and causal graph then
run deterministically for that one MASS.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any
import uuid

from backend.app.modules.design.generation.maas.agents.elevation_agent import generate_elevation_bundle, generate_elevation_image_proposal, select_facade_strategy
from backend.app.modules.design.generation.maas.aesthetic.contracts import AestheticProvider
from backend.app.modules.design.generation.maas.agents.orchestrator.execution_collaboration import AgentExecutor, build_default_execution_executors, run_execution_collaboration
from backend.app.modules.design.generation.maas.agents.shared.types import ExecutionIdentity
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.execution_persistence import passport_path_for_preview, write_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import AUTHORED_COORDINATE_SPACE, COORDINATE_SPACE
from backend.app.modules.design.generation.maas.geometry_language.render import render_compilation_preview
from backend.app.modules.design.generation.maas.geometry_language.unitbox_normalization import normalize_unitbox_program
from backend.app.modules.design.generation.maas.mass_product_evidence import resolve_floor_capacity_plan_identity

from backend.app.modules.design.generation.maas.single_execution.contracts import SingleMassExecutionResult
from backend.app.modules.design.generation.maas.single_execution.catalog import single_execution_id, single_execution_passport, single_execution_program
from backend.app.modules.design.generation.maas.single_execution.persistence import write_json_atomic


_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")


def execute_single_mass(
    program: GeometryProgram | Mapping[str, Any],
    *,
    output_root: str | Path,
    execution_id: str = "",
    title: str = "",
    downstream_evidence: Mapping[str, Any] | None = None,
    vlm_result: Mapping[str, Any] | None = None,
    geometry_graph_snapshot: Mapping[str, Any] | None = None,
    collaboration_executors: Mapping[str, AgentExecutor] | None = None,
    execution_mode: str = "explicit_program",
    source_run_id: str = "",
    source_mass_index: int = 0,
    elevation_image_adapter: AestheticProvider | None = None,
    validated_compilation: CompilationResult | None = None,
) -> SingleMassExecutionResult:
    """Compile, gate, render, and persist exactly one MASS with stage timings."""

    started = perf_counter()
    timings: dict[str, float] = {}

    stage_started = perf_counter()
    resolved_program = (
        program if isinstance(program, GeometryProgram) else GeometryProgram.from_dict(dict(program))
    )
    if validated_compilation is None:
        resolved_program = normalize_unitbox_program(resolved_program)
    validation_issues = tuple(resolved_program.validate())
    timings["parse_validate"] = _elapsed_ms(stage_started)

    program_hash = ""
    if not validation_issues:
        program_hash = resolved_program.program_hash()
    resolved_id = _execution_id(execution_id, resolved_program.name, program_hash)
    directory = Path(output_root).resolve() / resolved_id
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(f"single MASS execution already exists: {resolved_id}") from exc
    program_path = directory / "program.json"
    preview_path = directory / "mass.png"
    passport_path = passport_path_for_preview(preview_path)
    manifest_path = directory / "execution.json"

    normalized_downstream = dict(downstream_evidence or {})
    shared_floor_contract = (
        normalized_downstream.get("shared_floor_contract")
        if isinstance(normalized_downstream.get("shared_floor_contract"), Mapping)
        else None
    )
    stage_started = perf_counter()
    if validated_compilation is not None:
        compilation = _physical_visual_compilation(
            _validated_replay_compilation(
                validated_compilation,
                resolved_program,
            ),
            physical_z_bounds=_shared_floor_vertical_bounds(
                shared_floor_contract,
            ),
        )
    else:
        compilation = compile_geometry_program(resolved_program)
    timings["compile"] = _elapsed_ms(stage_started)
    final_legal_geometry_hash = str(compilation.geometry_hash or "")

    stage_started = perf_counter()
    gate_issues = tuple(compilation_gate(compilation))
    timings["geometry_gate"] = _elapsed_ms(stage_started)
    geometry_ready = compilation.status == "compiled" and not gate_issues
    capacity_evidence = normalized_downstream.get("capacity")
    capacity_evidence = (
        capacity_evidence if isinstance(capacity_evidence, Mapping) else {}
    )
    floor_capacity_plan_hash = resolve_floor_capacity_plan_identity(
        program=resolved_program,
        capacity=capacity_evidence,
        shared_floor_contract=(
            normalized_downstream.get("shared_floor_contract")
            if isinstance(
                normalized_downstream.get("shared_floor_contract"),
                Mapping,
            )
            else None
        ),
        require_shared_contract=(
            str(execution_mode or "") == "exact_replay"
            and bool(str(source_run_id or "").strip())
        ),
        unresolved="FLOOR_CAPACITY_PLAN_HASH_UNRESOLVED",
    )

    stage_started = perf_counter()
    if geometry_ready:
        render_compilation_preview(
            compilation,
            preview_path,
            title=title or resolved_program.name,
        )
    timings["render"] = _elapsed_ms(stage_started)

    stage_started = perf_counter()
    elevation_evidence: dict[str, Any] = {}
    elevation_handoff_accepted = (
        shared_floor_contract is None
        or _accepted_elevation_handoff(normalized_downstream)
    )
    if geometry_ready and elevation_handoff_accepted:
        try:
            elevation_evidence = generate_elevation_bundle(
                compilation,
                directory / "elevation",
                execution_id=resolved_id,
                shared_floor_contract=(
                    dict(shared_floor_contract)
                    if shared_floor_contract is not None
                    else None
                ),
                floor_capacity_plan_hash=floor_capacity_plan_hash,
            )
        except Exception as exc:
            elevation_evidence = {
                "schema_version": "arr.elevation_agent.bundle.v1",
                "status": "failed",
                "execution_id": resolved_id,
                "program_hash": program_hash,
                "geometry_hash": str(compilation.geometry_hash or ""),
                "final_legal_geometry_hash": final_legal_geometry_hash,
                "error": f"{type(exc).__name__}: {exc}",
                "views": [],
            }
        if elevation_evidence.get("status") == "generated":
            facade_strategy = select_facade_strategy(resolved_program, compilation)
            elevation_evidence["facade_strategy"] = facade_strategy
            proposal_identity = {
                "execution_id": resolved_id,
                "program_hash": program_hash,
                "geometry_hash": str(compilation.geometry_hash or ""),
                "final_legal_geometry_hash": final_legal_geometry_hash,
                "floor_capacity_plan_hash": str(
                    floor_capacity_plan_hash
                ),
            }
            if elevation_image_adapter is not None:
                try:
                    elevation_evidence["image_proposal"] = (
                        generate_elevation_image_proposal(
                            elevation_evidence,
                            preview_path,
                            adapter=elevation_image_adapter,
                            strategy=facade_strategy,
                        )
                    )
                except Exception as exc:
                    elevation_evidence["image_proposal"] = {
                        "schema_version": "arr.elevation_agent.image_proposal.v1",
                        "status": "failed",
                        "identity": proposal_identity,
                        "strategy": facade_strategy,
                        "provider": str(getattr(elevation_image_adapter, "name", "")),
                        "provider_metadata": {},
                        "issues": [{
                            "code": "provider_error",
                            "message": f"{type(exc).__name__}: {exc}",
                        }],
                        "request_count": 1,
                        "retry_count": 0,
                        "artifact": {},
                    }
            else:
                elevation_evidence["image_proposal"] = (
                    {
                        "schema_version": "arr.elevation_agent.image_proposal.v1",
                        "status": "not_evaluated",
                        "identity": proposal_identity,
                        "strategy": facade_strategy,
                        "provider": "",
                        "provider_metadata": {},
                        "issues": [],
                        "request_count": 0,
                        "retry_count": 0,
                        "artifact": {},
                    }
                )
    elif geometry_ready:
        elevation_evidence = {
            "schema_version": "arr.elevation_agent.bundle.v1",
            "status": "blocked",
            "execution_id": resolved_id,
            "program_hash": program_hash,
            "geometry_hash": str(compilation.geometry_hash or ""),
            "final_legal_geometry_hash": final_legal_geometry_hash,
            "floor_contract_hash": str(
                (shared_floor_contract or {}).get("floor_contract_hash") or ""
            ),
            "floor_capacity_plan_hash": str(
                floor_capacity_plan_hash
            ),
            "reason": "accepted_mass_handoff_required",
            "views": [],
        }
    timings["elevation_agent"] = _elapsed_ms(stage_started)

    stage_started = perf_counter()
    identity = ExecutionIdentity(
        execution_id=resolved_id,
        program_hash=program_hash or "PROGRAM_HASH_UNRESOLVED",
        geometry_hash=str(compilation.geometry_hash or "GEOMETRY_HASH_UNRESOLVED"),
        floor_capacity_plan_hash=floor_capacity_plan_hash,
        pnu=_resolve_pnu(resolved_program.metadata or {}, normalized_downstream),
    )
    executors = dict(collaboration_executors or build_default_execution_executors(
        compilation=compilation,
        geometry_gate_issues=gate_issues,
        downstream_evidence=normalized_downstream,
        program_metadata=resolved_program.metadata or {},
    ))
    collaboration = run_execution_collaboration(identity, executors=executors)
    timings["agent_collaboration"] = _elapsed_ms(stage_started)

    stage_started = perf_counter()
    passport_path = write_mass_execution_passport(
        compilation,
        preview_path,
        downstream_evidence=downstream_evidence,
        vlm_result=vlm_result,
        geometry_graph_snapshot=geometry_graph_snapshot,
        agent_collaboration=collaboration.to_dict(),
        elevation_evidence=elevation_evidence,
    )
    passport = json.loads(passport_path.read_text(encoding="utf-8"))
    passport["final_legal_geometry_hash"] = final_legal_geometry_hash
    for passport_stage in passport.get("stages") or ():
        if (
            isinstance(passport_stage, dict)
            and passport_stage.get("id") == "render"
            and isinstance(passport_stage.get("evidence"), dict)
        ):
            passport_stage["evidence"][
                "final_legal_geometry_hash"
            ] = final_legal_geometry_hash
            break
    write_json_atomic(passport_path, passport)
    timings["passport"] = _elapsed_ms(stage_started)

    stage_started = perf_counter()
    write_json_atomic(program_path, resolved_program.to_dict())
    timings["persist"] = _elapsed_ms(stage_started)
    timings["total"] = _elapsed_ms(started)

    status = (
        "geometry_ready"
        if geometry_ready
        else "geometry_gate_failed"
        if compilation.status == "compiled" and gate_issues
        else compilation.status
    )
    result = SingleMassExecutionResult(
        execution_id=resolved_id,
        execution_mode=str(execution_mode or "explicit_program"),
        source_run_id=str(source_run_id or ""),
        source_mass_index=max(0, int(source_mass_index or 0)),
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        geometry_ready=geometry_ready,
        full_flow_status=str(passport.get("status") or "in_progress"),
        program_hash=program_hash,
        geometry_hash=str(compilation.geometry_hash or ""),
        floor_capacity_plan_hash=floor_capacity_plan_hash,
        timings_ms={key: round(value, 3) for key, value in timings.items()},
        gate_issues=tuple(issue.to_dict() for issue in gate_issues),
        output_directory=directory,
        program_path=program_path,
        preview_path=preview_path,
        passport_path=passport_path,
        manifest_path=manifest_path,
        passport=passport,
    )
    manifest = result.to_dict()
    manifest["final_legal_geometry_hash"] = final_legal_geometry_hash
    write_json_atomic(manifest_path, manifest)
    return result


def _execution_id(requested: str, name: str, program_hash: str) -> str:
    raw = requested.strip() or (
        f"mass-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    )
    resolved = _SAFE_ID.sub("-", raw).strip("-_")[:96]
    return resolved or f"mass-{program_hash[:12] or 'invalid'}"


def _elapsed_ms(started: float) -> float:
    return max(0.0, (perf_counter() - started) * 1000.0)


def _resolve_pnu(metadata: Mapping[str, Any], downstream: Mapping[str, Any]) -> str:
    site = downstream.get("site")
    site = site if isinstance(site, Mapping) else {}
    metadata_site = metadata.get("site")
    metadata_site = metadata_site if isinstance(metadata_site, Mapping) else {}
    return str(
        site.get("pnu")
        or downstream.get("pnu")
        or metadata.get("pnu")
        or metadata_site.get("pnu")
        or "PNU_UNRESOLVED"
    )


def _accepted_elevation_handoff(downstream: Mapping[str, Any]) -> bool:
    floor_contract = downstream.get("shared_floor_contract")
    if not isinstance(floor_contract, Mapping) or floor_contract.get("hard_pass") is not True:
        return False
    site = downstream.get("site")
    if not isinstance(site, Mapping) or str(site.get("status") or "") != "passed":
        return False
    for stage_name in ("law", "parking", "program_fit", "selector"):
        stage = downstream.get(stage_name)
        if not isinstance(stage, Mapping) or stage.get("hard_pass") is not True:
            return False
    capacity = downstream.get("capacity")
    if not isinstance(capacity, Mapping):
        return False
    if not (
        capacity.get("hard_pass") is True
        or (
            capacity.get("evaluated") is True
            and capacity.get("hard_gates_remain_downstream") is True
        )
    ):
        return False
    expected_plan_hash = str(
        capacity.get("floor_capacity_plan_hash")
        or ""
    )
    actual_plan_hash = str(
        floor_contract.get("floor_capacity_plan_hash")
        or (
            floor_contract.get("identity", {})
            if isinstance(floor_contract.get("identity"), Mapping)
            else {}
        ).get("floor_capacity_plan_hash")
        or ""
    )
    if expected_plan_hash and actual_plan_hash != expected_plan_hash:
        return False
    return True


def _validated_replay_compilation(
    compilation: CompilationResult,
    program: GeometryProgram,
) -> CompilationResult:
    if compilation.program.program_hash() != program.program_hash():
        raise ValueError("validated compilation program identity mismatch")
    metrics = dict(compilation.metrics or {})
    if (
        compilation.status != "compiled"
        or compilation.issues
        or not compilation.vertices
        or not compilation.triangles
        or metrics.get("geometry_authority") != "certified_projected_visual_mesh"
        or metrics.get("coordinate_space")
        not in {COORDINATE_SPACE, AUTHORED_COORDINATE_SPACE}
        or not re.fullmatch(r"[0-9a-f]{64}", str(compilation.geometry_hash or ""))
        or not re.fullmatch(r"[0-9a-f]{64}", str(metrics.get("exact_payload_hash") or ""))
    ):
        raise ValueError("validated compilation is not a certified projected visual mesh")
    capacity_metrics = metrics.get("capacity_replay_metrics")
    if isinstance(capacity_metrics, Mapping):
        metrics = {
            **dict(capacity_metrics),
            **metrics,
            "vertex_count": len(compilation.vertices),
            "triangle_count": len(compilation.triangles),
        }
    return replace(compilation, program=program, metrics=metrics)


def _physical_visual_compilation(
    compilation: CompilationResult,
    *,
    physical_z_bounds: tuple[float, float] | None = None,
) -> CompilationResult:
    metrics = dict(compilation.metrics or {})
    capacity_metrics = metrics.get("capacity_replay_metrics")
    capacity_metrics = (
        dict(capacity_metrics)
        if isinstance(capacity_metrics, Mapping)
        else metrics
    )
    bounds = capacity_metrics.get("bounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 2
        or not all(isinstance(row, list) and len(row) == 3 for row in bounds)
    ):
        raise ValueError("certified visual replay requires trusted capacity bounds")
    if physical_z_bounds is None:
        minimum_z = float(bounds[0][2])
        maximum_z = float(bounds[1][2])
    else:
        minimum_z, maximum_z = physical_z_bounds
    height = maximum_z - minimum_z
    if height <= 0.0:
        raise ValueError("certified visual replay requires positive physical height")
    normalized_z = [float(vertex[2]) for vertex in compilation.vertices]
    if (
        min(normalized_z) < -1e-8
        or max(normalized_z) > 1.0 + 1e-8
        or max(normalized_z) - min(normalized_z) <= 1e-8
    ):
        raise ValueError("certified visual mesh has invalid normalized z coordinates")
    vertices = tuple(
        (
            float(x),
            float(y),
            minimum_z + float(z) * height,
        )
        for x, y, z in compilation.vertices
    )
    physical_bounds = [
        [min(vertex[axis] for vertex in vertices) for axis in range(3)],
        [max(vertex[axis] for vertex in vertices) for axis in range(3)],
    ]
    identity_coordinate_space = str(metrics.get("coordinate_space") or "")
    physical_coordinate_space = {
        COORDINATE_SPACE: "capacity_source_centroid_local_xy_physical_z_m",
        AUTHORED_COORDINATE_SPACE: (
            "source_footprint_centroid_local_xy_physical_z_m"
        ),
    }.get(identity_coordinate_space)
    if not physical_coordinate_space:
        raise ValueError("certified visual replay coordinate space is unsupported")
    return replace(
        compilation,
        vertices=vertices,
        metrics={
            **metrics,
            "bounds": physical_bounds,
            "coordinate_space": physical_coordinate_space,
            "identity_coordinate_space": identity_coordinate_space,
            "certified_visual_geometry_hash": compilation.geometry_hash,
            "physical_z_scale_m": height,
            "physical_z_origin_m": minimum_z,
        },
    )


def _shared_floor_vertical_bounds(
    contract: Mapping[str, Any] | None,
) -> tuple[float, float] | None:
    if contract is None:
        return None
    plates = contract.get("plates")
    accepted = [
        plate
        for plate in (plates if isinstance(plates, list) else ())
        if isinstance(plate, Mapping) and plate.get("hard_pass") is True
    ]
    if not accepted:
        return None
    try:
        minimum_z = min(float(plate["bottom_height_m"]) for plate in accepted)
        maximum_z = max(float(plate["top_height_m"]) for plate in accepted)
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "certified visual replay requires trusted shared-floor heights"
        ) from None
    if maximum_z <= minimum_z:
        raise ValueError(
            "certified visual replay requires positive shared-floor height"
        )
    return minimum_z, maximum_z


def resolve_single_execution_replay(
    *,
    root: str | Path,
    run_id: str,
    compile_archive: Callable[
        [int, str],
        tuple[CompilationResult, dict[str, Any], dict[str, Any], Path],
    ],
) -> tuple[GeometryProgram, dict[str, Any], CompilationResult | None]:
    """Resolve one single-execution chain without trusting intermediate files."""

    resolved_root = Path(root).resolve()
    current_run_id = str(run_id)
    visited: set[str] = set()
    requested_program: GeometryProgram | None = None
    requested_passport: dict[str, Any] | None = None
    requested_program_hash = ""
    requested_geometry_hash = ""
    requested_floor_capacity_plan_hash = ""
    for _depth in range(32):
        if current_run_id in visited:
            raise ValueError("single execution replay provenance cycle")
        visited.add(current_run_id)
        execution_id = single_execution_id(current_run_id)
        program = single_execution_program(resolved_root, current_run_id)
        passport = single_execution_passport(resolved_root, current_run_id)
        manifest_path = (resolved_root / execution_id / "execution.json").resolve()
        if not manifest_path.is_relative_to(resolved_root) or not manifest_path.is_file():
            raise ValueError("single execution replay manifest is unavailable")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        program_hash = program.program_hash()
        geometry_hash = str(passport.get("geometry_hash") or "")
        passport_floor_capacity_plan_hash = str(
            passport.get("floor_capacity_plan_hash") or ""
        )
        manifest_floor_capacity_plan_hash = str(
            manifest.get("floor_capacity_plan_hash") or ""
        )
        if (
            str(manifest.get("execution_id") or "") != execution_id
            or str(manifest.get("program_hash") or "") != program_hash
            or str(passport.get("program_hash") or "") != program_hash
        ):
            raise ValueError("single execution replay program identity mismatch")
        if (
            not geometry_hash
            or str(manifest.get("geometry_hash") or "") != geometry_hash
        ):
            raise ValueError("single execution replay geometry identity mismatch")
        if (
            not passport_floor_capacity_plan_hash
            or manifest_floor_capacity_plan_hash
            != passport_floor_capacity_plan_hash
        ):
            raise ValueError(
                "single execution replay floor capacity plan identity mismatch"
            )
        if requested_program is None:
            requested_program = program
            requested_passport = passport
            requested_program_hash = program_hash
            requested_geometry_hash = geometry_hash
            requested_floor_capacity_plan_hash = (
                passport_floor_capacity_plan_hash
            )
        elif (
            program_hash != requested_program_hash
            or geometry_hash != requested_geometry_hash
            or passport_floor_capacity_plan_hash
            != requested_floor_capacity_plan_hash
        ):
            raise ValueError("single execution replay intermediate identity mismatch")

        origin_run_id = str(manifest.get("source_run_id") or "")
        origin_mass_index = int(manifest.get("source_mass_index") or 0)
        if not origin_run_id:
            if origin_mass_index != 0:
                raise ValueError(
                    "single execution terminal source mass index must equal 0"
                )
            capacity = compile_geometry_program(program)
            if capacity.geometry_hash == geometry_hash:
                return requested_program, requested_passport, None
            raise ValueError(
                "original certified archive is unavailable for exact replay"
            )
        if origin_mass_index < 1:
            raise ValueError("single execution replay source identity is incomplete")
        if origin_run_id.startswith("single-execution:"):
            if origin_mass_index != 1:
                raise ValueError(
                    "single execution source mass index must equal 1"
                )
            current_run_id = origin_run_id
            continue
        compilation, source_artifact, source_row, _ = compile_archive(
            origin_mass_index,
            origin_run_id,
        )
        if (
            compilation.program.program_hash() != requested_program_hash
            or compilation.geometry_hash != requested_geometry_hash
        ):
            raise ValueError("single execution certified compilation identity mismatch")
        artifact_identity = (
            source_artifact.get("identity")
            if isinstance(source_artifact, Mapping)
            and isinstance(source_artifact.get("identity"), Mapping)
            else {}
        )
        artifact_passport = (
            source_artifact.get("executionPassport")
            if isinstance(source_artifact, Mapping)
            and isinstance(source_artifact.get("executionPassport"), Mapping)
            else {}
        )
        source_floor_capacity_plan_hash = resolve_floor_capacity_plan_identity(
            program=compilation.program,
            additional_hashes=(
                artifact_identity.get("floorCapacityPlanHash"),
                artifact_identity.get("floor_capacity_plan_hash"),
                artifact_passport.get("floor_capacity_plan_hash"),
                (
                    source_artifact.get("floor_capacity_plan_hash")
                    if isinstance(source_artifact, Mapping)
                    else ""
                ),
                (
                    source_row.get("floor_capacity_plan_hash")
                    if isinstance(source_row, Mapping)
                    else ""
                ),
            ),
        )
        if not source_floor_capacity_plan_hash:
            raise ValueError(
                "single execution certified floor capacity plan identity is unavailable"
            )
        if (
            source_floor_capacity_plan_hash
            != requested_floor_capacity_plan_hash
        ):
            raise ValueError(
                "single execution certified floor capacity plan identity mismatch"
            )
        return requested_program, requested_passport, compilation
    raise ValueError("single execution replay provenance depth exceeded")


__all__ = ["execute_single_mass", "resolve_single_execution_replay"]

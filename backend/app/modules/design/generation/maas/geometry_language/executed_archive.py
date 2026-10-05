"""Read and materialize the newest real MAAS portfolio execution archive."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import hashlib
from functools import lru_cache
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.dsl import program_to_dsl
from backend.app.modules.design.generation.maas.geometry_language.execution_persistence import write_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import semantic_audit_payload_hash, validate_projected_visual_artifact
from backend.app.modules.design.generation.maas.geometry_language.run_state import RUN_STATE_FILENAME
from backend.app.modules.design.generation.maas.geometry_language.vlm_adapter import retrieve_geometry_reference_matches
from backend.app.modules.design.generation.maas.preference.reference_paths import resolve_reference_image_path
from backend.app.modules.design.generation.maas.book_language.archive_layout import archive_card_crop_box
from backend.app.modules.design.generation.maas.book_language.mass_passport_bridge import resolve_capacity_band_evidence, resolve_shared_floor_contract_hard_gate
from backend.app.modules.design.generation.maas.mass_product_evidence import floor_capacity_plan_hash, serialize_mass_product_evidence


ARCHIVE_SCHEMA = "arr.maas.executed_mass_archive.v1"


def workspace_root() -> Path:
    return _design_paths.workspace_root()


def _archive_paths() -> list[Path]:
    root = workspace_root() / "docs" / "playwright" / "design-route-live-verify"
    return sorted(
        root.glob("book-program-portfolios-*/maas-book-exact-geometry-artifacts.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.parent.name),
    )


def _run_directories() -> list[Path]:
    root = workspace_root() / "docs" / "playwright" / "design-route-live-verify"
    directories = {
        path.parent
        for path in root.glob("book-program-portfolios-*/maas-book-exact-geometry-artifacts.json")
    }
    directories.update(
        path.parent for path in root.glob(f"book-program-portfolios-*/{RUN_STATE_FILENAME}")
    )
    return sorted(directories, key=lambda path: path.name)


def latest_archive_path() -> Path:
    for candidate in reversed(_archive_paths()):
        summary = candidate.with_name("maas-book-programs-summary.json")
        if not summary.is_file():
            continue
        payload = _read_json(str(candidate), candidate.stat().st_mtime_ns)
        if int(payload.get("record_count") or 0) > 0 and isinstance(payload.get("records"), list):
            return candidate
    raise FileNotFoundError("no completed MAAS geometry artifact archive found")


def _archive_path_for_run(run_id: str | None) -> Path:
    if not run_id:
        return latest_archive_path()
    requested = str(run_id).strip()
    match = next((path for path in _run_directories() if path.name == requested), None)
    if match is None:
        raise FileNotFoundError(f"unknown MAAS run: {requested}")
    return match / "maas-book-exact-geometry-artifacts.json"


@lru_cache(maxsize=8)
def _read_json(path: str, _mtime_ns: int) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _bundle(run_id: str | None = None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    archive_path = _archive_path_for_run(run_id)
    summary_path = archive_path.with_name("maas-book-programs-summary.json")
    state_path = archive_path.with_name(RUN_STATE_FILENAME)
    archive = (
        _read_json(str(archive_path), archive_path.stat().st_mtime_ns)
        if archive_path.is_file()
        else {"records": [], "record_count": 0}
    )
    if summary_path.is_file():
        summary = _read_json(str(summary_path), summary_path.stat().st_mtime_ns)
    elif state_path.is_file():
        summary = _read_json(str(state_path), state_path.stat().st_mtime_ns)
    else:
        raise FileNotFoundError(f"no state or summary for MAAS run: {archive_path.parent.name}")
    return archive_path, archive, summary


@lru_cache(maxsize=4)
def _run_catalog_cached(
    signature: tuple[tuple[str, int, int, int, int, int], ...],
) -> tuple[dict[str, Any], ...]:
    """Materialize a catalog only when an archive file signature changes."""
    rows: list[dict[str, Any]] = []
    for path, archive_mtime_ns, _archive_size, summary_mtime_ns, state_mtime_ns, _state_size in signature:
        run_directory = Path(path)
        archive_path = run_directory / "maas-book-exact-geometry-artifacts.json"
        summary_path = archive_path.with_name("maas-book-programs-summary.json")
        state_path = archive_path.with_name(RUN_STATE_FILENAME)
        archive: dict[str, Any] = {}
        state: dict[str, Any] = {}
        if archive_mtime_ns:
            try:
                archive = _read_json(str(archive_path), archive_mtime_ns)
            except (OSError, ValueError, json.JSONDecodeError):
                archive = {}
        if state_mtime_ns:
            try:
                state = _read_json(str(state_path), state_mtime_ns)
            except (OSError, ValueError, json.JSONDecodeError):
                state = {}
        modified_ns = max(archive_mtime_ns, summary_mtime_ns, state_mtime_ns)
        record_count = len([
            item for item in archive.get("records") or () if isinstance(item, dict)
        ])
        lifecycle_status = str(state.get("status") or "")
        status = (
            "selected_mass_ready"
            if record_count
            else lifecycle_status
            if lifecycle_status and lifecycle_status != "completed"
            else "completed_without_selected_mass"
            if archive_mtime_ns
            else lifecycle_status or "unknown"
        )
        rows.append({
            "run_id": run_directory.name,
            "created_at": str(state.get("created_at") or datetime.fromtimestamp(
                modified_ns / 1_000_000_000, tz=timezone.utc
            ).isoformat()),
            "pnu": str(archive.get("pnu") or state.get("pnu") or ""),
            "site_context_status": (
                "site_bound"
                if record_count and str(archive.get("pnu") or state.get("pnu") or "").strip()
                else "unresolved"
            ),
            "selected_mass_count": record_count,
            "status": status,
            "replayable": bool(record_count),
            "floor_capacity_plan_hash": _archive_floor_capacity_plan_hash(archive),
        })
    return tuple(sorted(rows, key=lambda item: (item["created_at"], item["run_id"])))


def _run_catalog() -> list[dict[str, Any]]:
    """Return the immutable run timeline without reparsing 90 runs per click."""
    signature: list[tuple[str, int, int, int, int, int]] = []
    for run_directory in _run_directories():
        archive_path = run_directory / "maas-book-exact-geometry-artifacts.json"
        summary_path = archive_path.with_name("maas-book-programs-summary.json")
        state_path = archive_path.with_name(RUN_STATE_FILENAME)
        archive_stat = archive_path.stat() if archive_path.is_file() else None
        summary_stat = summary_path.stat() if summary_path.is_file() else None
        state_stat = state_path.stat() if state_path.is_file() else None
        signature.append((
            str(run_directory),
            archive_stat.st_mtime_ns if archive_stat else 0,
            archive_stat.st_size if archive_stat else 0,
            summary_stat.st_mtime_ns if summary_stat else 0,
            state_stat.st_mtime_ns if state_stat else 0,
            state_stat.st_size if state_stat else 0,
        ))
    return [dict(item) for item in _run_catalog_cached(tuple(signature))]


def executed_mass_manifest(run_id: str | None = None) -> dict[str, Any]:
    archive_path, archive, summary = _bundle(run_id)
    rows = _summary_rows(summary)
    masses = [
        _manifest_row(index, record, rows.get(_source_sequence(record), {}), archive_path)
        for index, record in enumerate(archive.get("records") or (), start=1)
        if isinstance(record, dict)
    ]
    runs = _run_catalog()
    summary_path = archive_path.with_name("maas-book-programs-summary.json")
    revision = ":".join((
        max((str(item["created_at"]) for item in runs), default=""),
        str(archive_path.stat().st_mtime_ns if archive_path.is_file() else 0),
        str(summary_path.stat().st_mtime_ns if summary_path.is_file() else 0),
    ))
    program_summary = next((
        item for item in summary.get("programs") or () if isinstance(item, dict)
    ), {})
    portfolio_vlm_audit = _mapping(program_summary.get("portfolio_vlm_audit"))
    return {
        "schema_version": ARCHIVE_SCHEMA,
        "run_id": archive_path.parent.name,
        "pnu": str(archive.get("pnu") or summary.get("pnu") or ""),
        "run_status": str(summary.get("status") or "unknown"),
        "numeric_status": str(summary.get("book_program_numeric_status") or "unknown"),
        "source_archive": str(archive_path),
        "mass_count": len(masses),
        "selected_run_id": archive_path.parent.name,
        "run_count": len(runs),
        "archive_revision": revision,
        "publishable_20": summary.get("publishable_20") is True,
        "publishable_target_count": int(
            summary.get("publishable_target_count") or 0
        ),
        "publishable_20_manifest": _mapping(
            summary.get("publishable_20_manifest")
        ),
        "runs": runs,
        "book_images_included": False,
        "image_authority": "actual archived candidate render tied to exact executed GeometryProgram",
        "portfolio_vlm_audit": portfolio_vlm_audit,
        "masses": masses,
    }


def executed_mass_record(
    index: int,
    run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    archive_path, archive, summary = _bundle(run_id)
    records = [record for record in archive.get("records") or () if isinstance(record, dict)]
    if not 1 <= int(index) <= len(records):
        raise IndexError(index)
    record = records[int(index) - 1]
    row = _summary_rows(summary).get(_source_sequence(record), {})
    return record, row, archive_path


def compile_executed_mass(
    index: int,
    run_id: str | None = None,
) -> tuple[CompilationResult, dict[str, Any], dict[str, Any], Path]:
    record, row, archive_path = executed_mass_record(index, run_id)
    artifact = _artifact(record)
    program = GeometryProgram.from_dict(artifact["geometryProgram"])
    projected_visual = _validated_projected_visual_compilation(
        artifact,
        program,
        expected_semantic_anchor=_summary_semantic_anchor(row),
    )
    if projected_visual is not None:
        return projected_visual, artifact, row, archive_path
    compilation = compile_geometry_program(program)
    expected_hash = str((artifact.get("identity") or {}).get("geometryHash") or "")
    if compilation.status != "compiled" or compilation.geometry_hash != expected_hash:
        raise ValueError(
            f"executed MASS replay mismatch at {index}: expected={expected_hash} actual={compilation.geometry_hash}"
        )
    return compilation, artifact, row, archive_path


def archived_compilation(
    index: int,
    run_id: str | None = None,
) -> tuple[CompilationResult, dict[str, Any], dict[str, Any], Path]:
    """Rehydrate the compilation evidence recorded by the original run without mutating it."""

    record, row, archive_path = executed_mass_record(index, run_id)
    artifact = _artifact(record)
    program = GeometryProgram.from_dict(artifact["geometryProgram"])
    projected_visual = _validated_projected_visual_compilation(
        artifact,
        program,
        expected_semantic_anchor=_summary_semantic_anchor(row),
    )
    if projected_visual is not None:
        return projected_visual, artifact, row, archive_path
    stored = _mapping(artifact.get("compilation"))
    trace = tuple({
        "node_id": node.id,
        "operator": node.operator,
        "status": "archived_compiled",
        "evidence_authority": "original_execution_archive",
    } for node in program.topological_nodes())
    result = CompilationResult(
        program=program,
        status=str(stored.get("status") or "compiled"),
        metrics=_mapping(stored.get("metrics")),
        trace=trace,
        issues=(),
        geometry_hash=str((artifact.get("identity") or {}).get("geometryHash") or stored.get("geometry_hash") or ""),
    )
    return result, artifact, row, archive_path


def _validated_projected_visual_compilation(
    artifact: dict[str, Any],
    program: GeometryProgram,
    *,
    expected_semantic_anchor: dict[str, Any] | None = None,
) -> CompilationResult | None:
    """Hydrate a certified archived triangle skin, rejecting partial or altered data."""

    semantic_anchor = (
        expected_semantic_anchor
        if isinstance(expected_semantic_anchor, dict)
        else {}
    )
    validated = validate_projected_visual_artifact(
        artifact,
        expected_semantic_context=semantic_anchor.get(
            "expected_semantic_context"
        ),
        expected_semantic_projection_hash=str(
            semantic_anchor.get("expected_semantic_projection_hash") or ""
        ),
        expected_semantic_audit_payload_hash=str(
            semantic_anchor.get(
                "expected_semantic_audit_payload_hash"
            )
            or ""
        ),
        expected_section_geometry_binding_hash=str(
            semantic_anchor.get(
                "expected_section_geometry_binding_hash"
            ) or ""
        ),
    )
    if validated is None:
        return None
    identity = _mapping(artifact.get("identity"))
    expected_program_hash = str(identity.get("programHash") or "")
    if expected_program_hash and program.program_hash() != expected_program_hash:
        raise ValueError("capacity replay GeometryProgram identity mismatch")

    stored = _mapping(artifact.get("compilation"))
    fresh_capacity = compile_geometry_program(program)
    if (
        fresh_capacity.status != "compiled"
        or str(stored.get("geometry_hash") or "")
        != fresh_capacity.geometry_hash
    ):
        raise ValueError("capacity replay compilation identity mismatch")
    stored_metrics = _mapping(stored.get("metrics"))
    for key in (
        "bounds",
        "volume",
        "watertight",
        "manifold",
        "closed_solid",
        "self_intersection_checked_by_kernel",
        "outward_normals",
        "vertex_count",
        "triangle_count",
        "component_count",
    ):
        if stored_metrics.get(key) != fresh_capacity.metrics.get(key):
            raise ValueError(
                f"capacity replay compilation metrics mismatch: {key}"
            )
    metrics = {
        "vertex_count": len(validated.vertices),
        "triangle_count": len(validated.triangles),
        "coordinate_space": validated.coordinate_space,
        "geometry_authority": "certified_projected_visual_mesh",
        "exact_payload_hash": validated.exact_payload_hash,
        "capacity_geometry_hash": fresh_capacity.geometry_hash,
        "capacity_replay_metrics": dict(fresh_capacity.metrics),
    }
    trace = tuple({
        "node_id": node.id,
        "operator": node.operator,
        "status": "capacity_replay_metadata",
        "evidence_authority": "archived_floorwise_capacity_program",
    } for node in program.topological_nodes())
    return CompilationResult(
        program=program,
        status="compiled",
        vertices=validated.vertices,
        triangles=validated.triangles,
        metrics=metrics,
        trace=trace,
        issues=(),
        geometry_hash=validated.visual_hash,
    )


def _summary_semantic_anchor(row: dict[str, Any]) -> dict[str, Any]:
    """Build the final-visual anchor from the separately stored summary row."""

    audit = _mapping(row.get("semantic_projection_hard_gate"))
    return {
        "expected_semantic_context": audit.get("audited_context"),
        "expected_semantic_projection_hash": str(
            audit.get("semantic_projection_hash") or ""
        ),
        "expected_semantic_audit_payload_hash": (
            semantic_audit_payload_hash(audit)
            if audit
            else ""
        ),
        "expected_section_geometry_binding_hash": str(
            row.get(
                "projected_visual_section_geometry_binding_hash"
            ) or ""
        ),
    }


def materialize_executed_mass_preview(index: int, run_id: str | None = None) -> Path:
    record, row, archive_path = executed_mass_record(index, run_id)
    artifact = _artifact(record)
    geometry_hash = str((artifact.get("identity") or {}).get("geometryHash") or "")
    evidence = row.get("archive_render_evidence") if isinstance(row.get("archive_render_evidence"), dict) else {}
    board = Path(str(evidence.get("board_png") or archive_path.with_name("maas-book-neighborhood-20.png"))).resolve()
    crop_box = tuple(int(value) for value in evidence.get("crop_box") or ())
    if len(crop_box) != 4:
        card_index = int(evidence.get("card_index") or index)
        if card_index >= 1:
            crop_box = archive_card_crop_box(card_index)
    root = workspace_root().resolve()
    if not board.is_relative_to(root) or not board.is_file() or len(crop_box) != 4:
        raise FileNotFoundError("actual archived MASS render is unavailable")
    output = (
        root / "docs" / "ai-session-memory" / "maas-service-cache" / "executed-masses"
        / archive_path.parent.name / f"mass-{int(index):02d}-{geometry_hash[:16]}.png"
    )
    if not output.is_file():
        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(board) as image:
            image.crop(crop_box).save(output, format="PNG", optimize=True)
    return output


def _archived_capacity_evidence(artifact: dict[str, Any]) -> dict[str, Any]:
    """Recover the complete selected capacity stage, including floor contract."""

    alternative = _mapping(artifact.get("capacityAlternative"))
    archived_passport = _mapping(artifact.get("executionPassport"))
    archived_stage = next(
        (
            _mapping(stage.get("evidence"))
            for stage in archived_passport.get("stages") or ()
            if isinstance(stage, dict) and stage.get("id") == "capacity"
        ),
        {},
    )
    capacity = {**alternative, **archived_stage}
    measurement = _mapping(capacity.get("measurement"))
    shared_floor_contract = _mapping(capacity.get("shared_floor_contract"))
    resolution = resolve_capacity_band_evidence(
        capacity,
        capacity_measurement=measurement,
        fallback_requested_hard_pass=bool(capacity.get("target_hard_pass")),
    )
    shared_floor_gate = resolve_shared_floor_contract_hard_gate(
        shared_floor_contract
    )
    hard_pass = bool(
        resolution["resolved_capacity_hard_pass"]
        and shared_floor_gate["hard_pass"]
    )
    return {
        **capacity,
        "measurement": measurement,
        "shared_floor_contract": shared_floor_contract,
        "shared_floor_contract_hard_pass": shared_floor_gate["hard_pass"],
        "shared_floor_contract_failure_reasons": list(
            shared_floor_gate["failure_reasons"]
        ),
        "evaluated": bool(alternative or archived_stage),
        **resolution,
        "hard_pass": hard_pass,
        "status": "passed" if hard_pass else "failed",
    }


def materialize_executed_mass_passport(
    index: int,
    run_id: str | None = None,
) -> dict[str, Any]:
    compilation, artifact, row, archive_path = archived_compilation(index, run_id)
    preview = materialize_executed_mass_preview(index, run_id)
    hard_gates = artifact.get("hardGates") if isinstance(artifact.get("hardGates"), dict) else {}
    capacity = _archived_capacity_evidence(artifact)
    program_gate = hard_gates.get("program") if isinstance(hard_gates.get("program"), dict) else {}
    downstream = {
        "site": {
            "evaluated": True,
            "hard_pass": bool(row.get("inside_site")),
            "inside_site": bool(row.get("inside_site")),
            "pnu": str(executed_mass_manifest(archive_path.parent.name).get("pnu") or ""),
            "generation_context": row.get("legal_generation_context_evidence") or {},
        },
        "capacity": capacity,
        "law": {**_mapping(hard_gates.get("legal")), "evaluated": True},
        "parking": {**_mapping(hard_gates.get("parking")), "evaluated": True},
        "program_fit": {
            **_mapping(program_gate.get("evidence")),
            "evaluated": True,
            "hard_pass": bool(program_gate.get("hard_pass")),
        },
        "selector": {
            "evaluated": True,
            "selected": True,
            "variant_id": str(row.get("variant_id") or f"maas_{int(index):02d}"),
            "archive_run_id": archive_path.parent.name,
            "score": row.get("score"),
        },
    }
    vlm = artifact.get("vlmAudit") if isinstance(artifact.get("vlmAudit"), dict) and artifact.get("vlmAudit") else None
    sidecar = write_mass_execution_passport(
        compilation,
        preview,
        downstream_evidence=downstream,
        vlm_result=vlm,
        geometry_graph_snapshot=_mapping(artifact.get("geometryGraphSnapshot")),
        geometry_gate_evidence={
            "hard_pass": bool(hard_gates.get("combinedHardPass")),
            "authority": "original_execution_archive",
            "original_clean_mass_gate": _mapping(hard_gates.get("cleanMass")),
            "note": "current-only metrics absent from the archive are not retroactively fabricated",
        },
    )
    passport = json.loads(sidecar.read_text(encoding="utf-8"))
    actual_vlm_source_ids = {
        str((_mapping(node.get("evidence"))).get("source_id") or "")
        for node in ((_mapping(passport.get("activation_graph"))).get("nodes") or ())
        if isinstance(node, dict) and node.get("kind") == "vlm_reference_image"
    }
    passport["retrieved_references"] = [
        {**record, "used_by_vlm": record["source_id"] in actual_vlm_source_ids}
        for record in _retrieved_reference_records(compilation.program)
    ]
    passport["reference_truth_policy"] = {
        "retrieved_is_not_vlm_input": True,
        "active_visual_reference_edge_requires_recorded_vlm_submission": True,
        "retrieval_launches_paid_vlm": False,
    }
    passport["reference_retrieval"] = _reference_corpus_summary(compilation.program)
    passport["executed_mass"] = _manifest_row(index, {"geometry_artifact": artifact}, row, archive_path)
    passport["executed_mass"]["compilation_authority"] = "original_execution_archive"
    return passport


def _retrieved_reference_records(program: GeometryProgram) -> list[dict[str, Any]]:
    """Expose deterministic ArchDaily retrieval without pretending it was a VLM call."""

    projection = _mapping(program.metadata.get("program_projection"))
    building_type = str(projection.get("program_id") or program.metadata.get("family") or "generic")
    try:
        matches = retrieve_geometry_reference_matches(
            program,
            building_type=building_type,
            limit=5,
        )
    except (OSError, ValueError, TypeError):
        return []
    corpus_root = (workspace_root() / "docs" / "ai-session-memory" / "reference-corpus").resolve()
    result: list[dict[str, Any]] = []
    for order, match in enumerate(matches, start=1):
        if not isinstance(match, dict):
            continue
        local_path = resolve_reference_image_path(str(match.get("local_path") or ""))
        preview_url = ""
        if local_path is not None:
            try:
                relative = local_path.relative_to(corpus_root)
            except ValueError:
                relative = None
            if relative is not None:
                preview_url = f"/design/maas/reference-assets/{quote(relative.as_posix(), safe='/')}"
        if not preview_url:
            remote = str(match.get("image_url") or "")
            if remote.startswith(("http://", "https://", "data:")):
                preview_url = remote
        source_id = str(match.get("source_id") or f"retrieved-{order}")
        result.append({
            "id": f"retrieved:{source_id}",
            "source_id": source_id,
            "title": str(match.get("title") or source_id),
            "source": str(match.get("source") or "archdaily"),
            "source_url": str(match.get("source_url") or match.get("page_url") or ""),
            "image_url": str(match.get("image_url") or ""),
            "local_path": str(local_path) if local_path is not None else "",
            "sha256": (
                hashlib.sha256(local_path.read_bytes()).hexdigest()
                if local_path is not None
                else str(match.get("sha256") or "")
            ),
            "preview_url": preview_url,
            "selection_role": str(match.get("selection_role") or "similar"),
            "matched_tags": list(match.get("matched_tags") or ()),
            "program_match_tier": str(match.get("program_match_tier") or ""),
            "reference_collection": str(match.get("reference_collection") or ""),
            "rights": str(match.get("rights") or match.get("license") or ""),
            "provenance": (
                dict(match.get("provenance") or {})
                if isinstance(match.get("provenance"), dict)
                else (
                    {"note": str(match.get("provenance"))}
                    if match.get("provenance")
                    else {}
                )
            ),
            "score": match.get("score"),
            "retrieval_order": order,
            "used_by_vlm": False,
        })
    return result


def _reference_corpus_summary(program: GeometryProgram) -> dict[str, Any]:
    manifest_path = (
        workspace_root() / "docs" / "ai-session-memory" / "reference-corpus"
        / "archdaily" / "DB_MANIFEST.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        manifest = {}
    projection = _mapping(program.metadata.get("program_projection"))
    return {
        "source": "archdaily",
        "collection_count": int(manifest.get("collection_count") or 0),
        "image_count": int(manifest.get("image_file_count") or 0),
        "project_count": int(manifest.get("unique_item_count") or 0),
        "program_id": str(projection.get("program_id") or "generic"),
        "building_type": str(projection.get("building_type") or ""),
        "geometry_family": str(program.metadata.get("family") or ""),
        "intent_tags": [str(value) for value in program.metadata.get("intent_tags") or ()],
        "query_role": "deterministic program-and-geometry retrieval",
        "current_mass_causality": "posthoc_match_unless_recorded_as_actual_vlm_input",
    }


def _summary_rows(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for program in summary.get("programs") or ():
        if not isinstance(program, dict):
            continue
        for row in program.get("rows") or ():
            if isinstance(row, dict) and row.get("source_sequence"):
                result[str(row["source_sequence"])] = row
    return result


def _source_sequence(record: dict[str, Any]) -> str:
    return str(_artifact(record).get("sourceSequence") or record.get("trace_sequence_name") or "")


def _artifact(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("geometry_artifact")
    if not isinstance(value, dict):
        raise ValueError("invalid executed geometry artifact")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _manifest_row(
    index: int,
    record: dict[str, Any],
    row: dict[str, Any],
    archive_path: Path,
) -> dict[str, Any]:
    artifact = _artifact(record)
    identity = _mapping(artifact.get("identity"))
    projected_visual_hash = str(
        artifact.get("projectedVisualGeometryHash") or ""
    )
    projected_visual_certificate = _mapping(
        artifact.get("projectedVisualCertificate")
    )
    passport = _mapping(artifact.get("executionPassport"))
    visual_hash = (
        projected_visual_hash
        if (
            projected_visual_hash
            and str(
                projected_visual_certificate.get("visual_hash") or ""
            )
            == projected_visual_hash
            and str(identity.get("geometryHash") or "")
            == projected_visual_hash
            and str(passport.get("geometry_hash") or "")
            == projected_visual_hash
            and str(passport.get("visual_hash") or "")
            == projected_visual_hash
        )
        else ""
    )
    compilation = _mapping(artifact.get("compilation"))
    capacity = _mapping(artifact.get("capacityAlternative"))
    hard_gates = _mapping(artifact.get("hardGates"))
    phenotype = str(row.get("body_phenotype") or row.get("solid_phenotype") or "mass")
    operation = str(row.get("book_operation") or record.get("trace_sequence_label") or "executed geometry")
    program = GeometryProgram.from_dict(artifact["geometryProgram"])
    program_hash = str(
        identity.get("programHash")
        or compilation.get("program_hash")
        or ""
    )
    passport_program_hash = str(
        passport.get("program_hash") or ""
    )
    if (
        not program_hash
        or program_hash != program.program_hash()
        or (
            passport_program_hash
            and passport_program_hash != program_hash
        )
    ):
        program_hash = ""
    geometry_hash = str(
        identity.get("geometryHash")
        or compilation.get("geometry_hash")
        or ""
    )
    final_geometry_hash = str(
        artifact.get("finalLegalGeometryHash") or ""
    )
    legal_floor_field_hash = str(
        artifact.get("legalFloorFieldHash") or ""
    )
    candidate_stop_hash = str(
        artifact.get("candidateActualGfaStopHash") or ""
    )
    candidate_stop_certificate = _mapping(
        artifact.get("candidateActualGfaStopCertificate")
    )
    passport_stop_certificate = _mapping(
        passport.get("candidate_actual_gfa_stop_certificate")
    )
    row_stop_certificate = _mapping(
        row.get("candidate_actual_gfa_stop_certificate")
    )
    phase_b2_identity_hard_pass = bool(
        final_geometry_hash
        and final_geometry_hash
        == str(passport.get("final_legal_geometry_hash") or "")
        and legal_floor_field_hash
        == str(passport.get("legal_floor_field_hash") or "")
        and candidate_stop_hash
        == str(passport.get("candidate_actual_gfa_stop_hash") or "")
        and candidate_stop_hash
        == str(
            candidate_stop_certificate.get(
                "candidate_actual_gfa_stop_hash"
            )
            or ""
        )
        and candidate_stop_certificate == passport_stop_certificate
        and candidate_stop_certificate == row_stop_certificate
        and legal_floor_field_hash
        == str(
            candidate_stop_certificate.get(
                "legal_floor_field_hash"
            )
            or ""
        )
        and program_hash
        == str(candidate_stop_certificate.get("program_hash") or "")
        and final_geometry_hash
        == str(
            candidate_stop_certificate.get("final_geometry_hash") or ""
        )
        and visual_hash
        == str(candidate_stop_certificate.get("visual_hash") or "")
        and str(row.get("floor_capacity_plan_hash") or "")
        == str(passport.get("floor_capacity_plan_hash") or "")
    )
    authored_program_payload = artifact.get("authoredGeometryProgram")
    authored_program = (
        GeometryProgram.from_dict(authored_program_payload)
        if isinstance(authored_program_payload, dict)
        else program
    )
    mass_product = serialize_mass_product_evidence(
        program=program,
        capacity=capacity,
        hard_gates=hard_gates,
        passport=passport,
        compilation=compilation,
    )
    book_base_node = next((
        node for node in authored_program.topological_nodes()
        if node.operator == "book_base_volume"
    ), None)
    return {
        "index": int(index),
        "variant_id": str(row.get("variant_id") or f"maas_{int(index):02d}"),
        "label": f"MASS {int(index):02d} · {phenotype}",
        "operation_label": operation,
        "source_sequence": _source_sequence(record),
        "run_id": archive_path.parent.name,
        "program_type": str(artifact.get("programType") or ""),
        "program_label": str(artifact.get("programLabel") or ""),
        "program_hash": program_hash,
        "geometry_hash": geometry_hash,
        "visual_hash": visual_hash,
        "final_geometry_hash": (
            final_geometry_hash if phase_b2_identity_hard_pass else ""
        ),
        "legal_floor_field_hash": (
            legal_floor_field_hash
            if phase_b2_identity_hard_pass
            else ""
        ),
        "candidate_actual_gfa_stop_hash": (
            candidate_stop_hash if phase_b2_identity_hard_pass else ""
        ),
        "candidate_actual_gfa_stop_certificate": (
            deepcopy(candidate_stop_certificate)
            if phase_b2_identity_hard_pass
            else {}
        ),
        "candidate_floor_count": (
            candidate_stop_certificate.get("selected_floor_count")
            if phase_b2_identity_hard_pass
            else None
        ),
        "candidate_target_gfa_m2": (
            candidate_stop_certificate.get("target_gfa_m2")
            if phase_b2_identity_hard_pass
            else None
        ),
        "achieved_gfa_m2": (
            candidate_stop_certificate.get("achieved_gfa_m2")
            if phase_b2_identity_hard_pass
            else None
        ),
        "phase_b2_identity_hard_pass": phase_b2_identity_hard_pass,
        "dsl": program_to_dsl(program),
        "node_count": len(program.nodes),
        "operator_path": [node.operator for node in program.topological_nodes()],
        "book_principle_id": str(artifact.get("bookPrincipleId") or ""),
        "book_scope": str(artifact.get("bookScope") or ""),
        "book_orientation": str(
            (book_base_node.parameters or {}).get("orientation")
            if book_base_node is not None
            else ""
        ),
        "capacity_alternative_id": str(capacity.get("alternative_id") or row.get("capacity_alternative_id") or ""),
        "capacity_target_utilization": capacity.get("target_utilization"),
        "capacity_achieved_utilization": capacity.get("achieved_utilization"),
        **mass_product,
        "far_pct": (
            mass_product["far_pct"]
            if mass_product["far_pct"] is not None
            else row.get("far_pct")
        ),
        "score": row.get("score"),
        "hard_pass": bool(hard_gates.get("combinedHardPass")),
        "vlm_evaluated": bool(artifact.get("vlmAudit")),
        "archive_key": f"{archive_path.parent.name}:{int(index)}:{str(identity.get('geometryHash') or '')[:16]}",
        "preview_url": (
            f"/design/maas/executed-masses/{int(index)}/"
            f"?run_id={quote(archive_path.parent.name, safe='')}"
        ),
        "passport_url": (
            f"/design/maas/executed-masses/{int(index)}/passport/"
            f"?run_id={quote(archive_path.parent.name, safe='')}"
        ),
        "image_role": "actual_run_candidate_render",
    }


def _archive_floor_capacity_plan_hash(archive: dict[str, Any]) -> str:
    for record in archive.get("records") or ():
        if not isinstance(record, dict):
            continue
        artifact = record.get("geometry_artifact")
        if not isinstance(artifact, dict):
            continue
        program_payload = artifact.get("geometryProgram")
        if not isinstance(program_payload, dict):
            continue
        try:
            return floor_capacity_plan_hash(
                program=GeometryProgram.from_dict(program_payload),
                capacity=_mapping(artifact.get("capacityAlternative")),
                passport=_mapping(artifact.get("executionPassport")),
            )
        except (TypeError, ValueError):
            continue
    return ""


__all__ = [
    "ARCHIVE_SCHEMA",
    "archived_compilation",
    "compile_executed_mass",
    "executed_mass_manifest",
    "executed_mass_record",
    "latest_archive_path",
    "materialize_executed_mass_passport",
    "materialize_executed_mass_preview",
]

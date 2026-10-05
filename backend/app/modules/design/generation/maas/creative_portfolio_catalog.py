"""Validated read model for complete pre-legal creative MASS portfolios."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, compile_geometry_program


CATALOG_SCHEMA_VERSION = "arr.maas.creative_portfolio_catalog.v1"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PORTFOLIO_FILENAME = "maas-creative-portfolio.json"


def creative_portfolio_manifest(
    root: str | Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    resolved_root = Path(root).resolve()
    selected_run = str(run_id or "").strip()
    if not selected_run:
        runs = creative_portfolio_runs(resolved_root)
        if not runs:
            raise FileNotFoundError("no creative portfolio run")
        selected_run = str(runs[-1]["run_id"])
    run_directory = _run_directory(resolved_root, selected_run)
    portfolio_path = run_directory / _PORTFOLIO_FILENAME
    portfolio = _read_object(portfolio_path)
    if str(portfolio.get("run_id") or "") != selected_run:
        raise ValueError("creative portfolio run ID mismatch")
    if portfolio.get("legal_review_status") != "not_evaluated":
        raise ValueError("creative portfolio must remain legally not_evaluated")
    board_path = _inside_existing_file(
        run_directory,
        "maas-creative-board.png",
    )
    summaries = portfolio.get("candidates")
    if not isinstance(summaries, list):
        raise ValueError("creative portfolio candidates must be an array")
    candidates = [
        _validated_candidate(
            run_directory,
            selected_run,
            summary,
        )
        for summary in summaries
    ]
    candidate_ids = [candidate["candidate_id"] for candidate in candidates]
    identity_tuples = [
        (
            candidate["candidate_id"],
            candidate["program_hash"],
            candidate["geometry_hash"],
        )
        for candidate in candidates
    ]
    if (
        len(set(candidate_ids)) != len(candidate_ids)
        or len(set(identity_tuples)) != len(identity_tuples)
    ):
        raise ValueError("creative portfolio member identities must be unique")
    if int(portfolio.get("candidate_count") or 0) != len(candidates):
        raise ValueError("creative portfolio candidate count mismatch")
    graph = _catalog_graph(
        selected_run,
        str(portfolio.get("pnu") or ""),
        candidates,
    )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "run_type": "creative_portfolio",
        "run_id": selected_run,
        "pnu": str(portfolio.get("pnu") or ""),
        "created_at": str(portfolio.get("created_at") or ""),
        "status": str(portfolio.get("status") or "materialized"),
        "choice_pool": portfolio.get("choice_pool") is True,
        "candidate_count": len(candidates),
        "legal_review_status": "not_evaluated",
        "paid_vlm_request_count": int(
            portfolio.get("paid_vlm_request_count") or 0
        ),
        "board": deepcopy(portfolio.get("board") or {}),
        "board_png": board_path.relative_to(run_directory).as_posix(),
        "filter_facets": deepcopy(portfolio.get("filter_facets") or {}),
        "morphology_evidence": deepcopy(
            portfolio.get("morphology_evidence") or {}
        ),
        "candidates": candidates,
        "graph": graph,
        "runs": creative_portfolio_runs(resolved_root),
        "contracts": {
            "executed_mass_manifest_coercion": False,
            "law_evidence_fabricated": False,
            "parking_evidence_fabricated": False,
            "elevation_evidence_fabricated": False,
            "certified_capacity_fabricated": False,
            "asset_root": "configured_docs_mass_root",
        },
    }


def creative_portfolio_runs(root: str | Path) -> list[dict[str, Any]]:
    resolved_root = Path(root).resolve()
    if not resolved_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in resolved_root.glob(f"*/{_PORTFOLIO_FILENAME}"):
        try:
            run_id = path.parent.name
            _validate_opaque_id(run_id, "run ID", _RUN_ID_PATTERN)
            payload = _read_object(path)
            if str(payload.get("run_id") or "") != run_id:
                continue
            created_at = str(payload.get("created_at") or datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat())
            rows.append({
                "run_id": run_id,
                "run_type": "creative_portfolio",
                "created_at": created_at,
                "candidate_count": int(payload.get("candidate_count") or 0),
                "pnu": str(payload.get("pnu") or ""),
                "legal_review_status": str(
                    payload.get("legal_review_status") or ""
                ),
            })
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: (row["created_at"], row["run_id"]))


def creative_portfolio_render(
    root: str | Path,
    run_id: str,
    candidate_id: str,
) -> Path:
    selected_candidate = str(candidate_id or "")
    _validate_opaque_id(
        selected_candidate,
        "candidate ID",
        _CANDIDATE_ID_PATTERN,
    )
    resolved_root = Path(root).resolve()
    run_directory = _run_directory(resolved_root, str(run_id))
    portfolio = _read_object(run_directory / _PORTFOLIO_FILENAME)
    if str(portfolio.get("run_id") or "") != str(run_id):
        raise ValueError("creative portfolio run ID mismatch")
    summary = next(
        (
            candidate for candidate in portfolio.get("candidates") or ()
            if isinstance(candidate, dict)
            and str(candidate.get("candidate_id") or "") == selected_candidate
        ),
        None,
    )
    if summary is None:
        raise FileNotFoundError(selected_candidate)
    row = _validated_candidate(
        run_directory,
        str(run_id),
        summary,
    )
    return _inside_existing_file(run_directory, str(row["render_png"]))


def _validated_candidate(
    run_directory: Path,
    run_id: str,
    summary: Any,
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        raise ValueError("creative portfolio member must be an object")
    candidate_id = str(summary.get("candidate_id") or "")
    _validate_opaque_id(
        candidate_id,
        "candidate ID",
        _CANDIDATE_ID_PATTERN,
    )
    candidate_path = _inside_existing_file(
        run_directory,
        str(summary.get("candidate_json") or ""),
    )
    render_path = _inside_existing_file(
        run_directory,
        str(summary.get("render_png") or ""),
    )
    if render_path.suffix.lower() != ".png":
        raise ValueError("creative candidate render must be PNG")
    candidate = _read_object(candidate_path)
    if str(candidate.get("candidate_id") or "") != candidate_id:
        raise ValueError("creative candidate ID mismatch")
    if str(candidate.get("run_id") or "") != run_id:
        raise ValueError("creative candidate run ID mismatch")
    if (
        str(candidate.get("candidate_json") or "")
        != candidate_path.relative_to(run_directory).as_posix()
        or str(candidate.get("render_png") or "")
        != render_path.relative_to(run_directory).as_posix()
    ):
        raise ValueError("creative candidate artifact path mismatch")
    program_hash = str(summary.get("program_hash") or "")
    geometry_hash = str(summary.get("geometry_hash") or "")
    if not _HEX64_PATTERN.fullmatch(program_hash):
        raise ValueError("creative candidate program hash is invalid")
    if not _HEX64_PATTERN.fullmatch(geometry_hash):
        raise ValueError("creative candidate geometry hash is invalid")
    if str(candidate.get("program_hash") or "") != program_hash:
        raise ValueError("creative candidate program hash mismatch")
    if str(candidate.get("geometry_hash") or "") != geometry_hash:
        raise ValueError("creative candidate geometry hash mismatch")
    identity = candidate.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    if (
        str(identity.get("candidate_id") or "") != candidate_id
        or str(identity.get("program_hash") or "") != program_hash
        or str(identity.get("geometry_hash") or "") != geometry_hash
    ):
        raise ValueError("creative candidate identity tuple mismatch")
    program_payload = candidate.get("geometry_program")
    if not isinstance(program_payload, dict):
        raise ValueError("creative candidate requires full GeometryProgram")
    program = GeometryProgram.from_dict(program_payload)
    if program.program_hash() != program_hash:
        raise ValueError("creative candidate program hash replay mismatch")
    compilation = compile_geometry_program(program)
    if (
        compilation.status != "compiled"
        or compilation.geometry_hash != geometry_hash
    ):
        raise ValueError("creative candidate geometry hash replay mismatch")
    matrix_trace = candidate.get("matrix4_trace")
    mesh = candidate.get("mesh")
    mesh = mesh if isinstance(mesh, dict) else {}
    if (
        not isinstance(matrix_trace, list)
        or not matrix_trace
        or not isinstance(mesh.get("vertices"), list)
        or not mesh["vertices"]
        or not isinstance(mesh.get("triangles"), list)
        or not mesh["triangles"]
    ):
        raise ValueError("creative candidate material evidence is incomplete")
    try:
        vertices = tuple(
            tuple(float(value) for value in vertex)
            for vertex in mesh["vertices"]
        )
        triangles = tuple(
            tuple(int(value) for value in triangle)
            for triangle in mesh["triangles"]
        )
        stored_mesh_hash = _mesh_hash(vertices, triangles)
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("creative candidate mesh is invalid") from exc
    if stored_mesh_hash != geometry_hash:
        raise ValueError("creative candidate stored mesh geometry hash mismatch")
    mass_directory_relative = str(
        candidate.get("mass_directory") or ""
    )
    mass_directory = (run_directory / mass_directory_relative).resolve()
    if (
        not mass_directory_relative
        or not mass_directory.is_relative_to(run_directory)
        or not mass_directory.is_dir()
    ):
        raise ValueError("creative candidate MASS directory is invalid")
    mass_manifest = _inside_existing_file(
        run_directory,
        str(candidate.get("mass_manifest") or ""),
    )
    elevation_handoff = _inside_existing_file(
        run_directory,
        str(candidate.get("elevation_research_handoff") or ""),
    )
    for field, resolved in (
        ("mass_manifest", mass_manifest),
        ("elevation_research_handoff", elevation_handoff),
    ):
        if (
            str(summary.get(field) or "")
            != resolved.relative_to(run_directory).as_posix()
        ):
            raise ValueError(
                f"creative candidate {field} path mismatch"
            )
    legal = candidate.get("legal_review")
    legal = legal if isinstance(legal, dict) else {}
    if legal.get("status") != "not_evaluated" or legal.get("hard_pass") is not False:
        raise ValueError("creative candidate must remain legally not_evaluated")
    morphology = candidate.get("morphology_evidence")
    morphology = morphology if isinstance(morphology, dict) else {}
    morphology_decision = morphology.get("decision")
    morphology_decision = (
        morphology_decision
        if isinstance(morphology_decision, dict)
        else {}
    )
    return {
        "run_id": run_id,
        "candidate_id": candidate_id,
        "program_hash": program_hash,
        "geometry_hash": geometry_hash,
        "render_png": render_path.relative_to(run_directory).as_posix(),
        "candidate_json": candidate_path.relative_to(run_directory).as_posix(),
        "mass_directory": mass_directory.relative_to(
            run_directory
        ).as_posix(),
        "mass_manifest": mass_manifest.relative_to(
            run_directory
        ).as_posix(),
        "elevation_research_handoff": elevation_handoff.relative_to(
            run_directory
        ).as_posix(),
        "render_url": (
            f"/design/maas/creative-portfolios/{quote(run_id, safe='')}/"
            f"candidates/{quote(candidate_id, safe='')}/render/"
        ),
        "family": str(candidate.get("family") or ""),
        "form_class": str(candidate.get("form_class") or ""),
        "capacity_band": str(candidate.get("capacity_band") or ""),
        "storeys": int(
            (candidate.get("storey_evidence") or {}).get("storey_count") or 0
        ),
        "legal_status": "not_evaluated",
        "morphology_distance": float(
            morphology_decision.get("nearest_distance") or 0.0
        ),
    }


def _catalog_graph(
    run_id: str,
    pnu: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    portfolio_id = f"creative:portfolio:{run_id}"
    nodes = [{
        "id": portfolio_id,
        "kind": "geometry_portfolio",
        "identity": run_id,
        "attributes": {
            "run_id": run_id,
            "pnu": pnu,
            "candidate_count": len(candidates),
            "legal_status": "not_evaluated",
        },
    }]
    edges = []
    for candidate in candidates:
        node_id = f"creative:candidate:{candidate['candidate_id']}"
        nodes.append({
            "id": node_id,
            "kind": "creative_mass_candidate",
            "identity": candidate["geometry_hash"],
            "attributes": deepcopy(candidate),
        })
        edges.append({
            "id": f"creative:member:{candidate['candidate_id']}",
            "source": node_id,
            "target": portfolio_id,
            "kind": "member_of",
        })
    return {
        "schema_version": "arr.maas.creative_frontend_graph.v1",
        "root_node_ids": [portfolio_id],
        "nodes": nodes,
        "edges": edges,
    }


def _run_directory(root: Path, run_id: str) -> Path:
    selected_run = str(run_id or "")
    _validate_opaque_id(selected_run, "run ID", _RUN_ID_PATTERN)
    directory = (root / selected_run).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise FileNotFoundError(directory)
    return directory


def _inside_existing_file(run_directory: Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("creative candidate path is missing")
    target = (run_directory / relative_path).resolve()
    if not target.is_relative_to(run_directory):
        raise ValueError("creative candidate path must stay inside run directory")
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def _validate_opaque_id(value: str, label: str, pattern: re.Pattern) -> None:
    if (
        not pattern.fullmatch(value)
        or value in {".", ".."}
    ):
        raise ValueError(f"invalid creative portfolio {label}")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _mesh_hash(
    vertices: tuple[tuple[float, ...], ...],
    triangles: tuple[tuple[int, ...], ...],
) -> str:
    canonical = []
    for face in triangles:
        points = sorted(
            tuple(round(value, 5) for value in vertices[index])
            for index in face
        )
        canonical.append(points)
    canonical.sort()
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "creative_portfolio_manifest",
    "creative_portfolio_render",
    "creative_portfolio_runs",
]

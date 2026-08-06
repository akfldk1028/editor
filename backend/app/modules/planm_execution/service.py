from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

from PIL import Image, ImageChops


from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.visual_review.service import create_building_visual_review_artifacts
from backend.app.schemas.mass_io import mass_input_from_payload


EXIT_CODES = {"success": 0, "needs_input": 2, "retryable": 3, "blocked": 4}
STAGE_SKILLS = {
    "normalize": "normalize-plan-request",
    "analyze": "analyze-building-mass",
    "alternatives": "generate-plan-alternatives",
    "review": "review-floorplan",
    "deliver": "deliver-planm-package",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _portable_path(path: Path, output_dir: Path) -> str:
    try:
        return path.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _artifact(path: Path, output_dir: Path) -> dict[str, Any]:
    suffixes = {".json": "application/json", ".png": "image/png", ".html": "text/html"}
    resolved = path.resolve()
    return {
        "path": _portable_path(resolved, output_dir),
        "media_type": suffixes.get(path.suffix.lower(), "application/octet-stream"),
        "sha256": _file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _load_mass(input_path: Path):
    return mass_input_from_payload(_read_json(input_path))


def _load_state(state_path: Path, expected_stage: str) -> dict:
    state = _read_json(state_path)
    if state.get("contract_version") != "planm-state/v1":
        raise ValueError("unsupported PLANM state contract")
    if state.get("stage") != expected_stage:
        raise ValueError(f"expected state stage {expected_stage}, got {state.get('stage')}")
    return state


def _unresolved_facts(mass) -> list[str]:
    context = mass.building_code_context
    unresolved = []
    if context is None or not context.jurisdiction:
        unresolved.append("jurisdiction")
    if context is None or not context.effective_date:
        unresolved.append("effective_date")
    if context is None or len(context.floor_facts) != mass.floors:
        unresolved.append("floor_code_context")
    if context is None or not context.travel_limit_classification:
        unresolved.append("travel_limit_classification")
    return unresolved


def _result(*, skill_name: str, status: str, started_at: str, input_sha256: str,
            outputs: dict | None = None, violations: list[dict] | None = None,
            artifacts: list[dict] | None = None, attempt: int = 1) -> dict:
    value = {
        "contract_version": "skill-result/v1",
        "skill_name": skill_name,
        "status": status,
        "outputs": outputs or {},
        "violations": violations or [],
        "artifacts": artifacts or [],
        "provenance": {
            "started_at": started_at,
            "finished_at": _now(),
            "attempt": attempt,
            "input_sha256": input_sha256,
            "output_sha256": None,
        },
    }
    value["provenance"]["output_sha256"] = _sha256(value["outputs"])
    return value


def _violation(code: str, message: str, *, retryable: bool = False) -> dict:
    return {"code": code, "message": message, "severity": "hard", "retryable": retryable}


def _advance(state_path: Path, state: dict, *, skill: str, stage: str,
             artifacts: list[dict], accepted_ids: list[str] | None = None,
             fingerprints: list[str] | None = None) -> int:
    attempt = int(state["attempts"].get(skill, 0)) + 1
    state["stage"] = stage
    state["status"] = "success"
    state["attempts"][skill] = attempt
    state["artifacts"].extend(artifacts)
    if accepted_ids is not None:
        state["accepted_alternative_ids"] = accepted_ids
    if fingerprints is not None:
        state["candidate_fingerprints"] = fingerprints
    state["history"].append({"skill_name": skill, "status": "success", "attempt": attempt, "finished_at": _now()})
    _atomic_write(state_path, state)
    return attempt


def normalize(input_path: Path, state_path: Path, output_dir: Path) -> dict:
    started_at = _now()
    try:
        payload = _read_json(input_path)
        mass = mass_input_from_payload(payload)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return _result(skill_name=STAGE_SKILLS["normalize"], status="needs_input", started_at=started_at,
                       input_sha256=_sha256({"path": str(input_path)}),
                       violations=[_violation("invalid_mass_input", f"{type(error).__name__}: {error}")])

    state = {
        "contract_version": "planm-state/v1", "project_id": mass.project_id,
        "stage": "normalized", "status": "success", "input_path": input_path.name,
        "output_dir": ".", "attempts": {STAGE_SKILLS["normalize"]: 1},
        "candidate_fingerprints": [], "accepted_alternative_ids": [],
        "unresolved_facts": _unresolved_facts(mass), "violations": [], "artifacts": [],
        "history": [{"skill_name": STAGE_SKILLS["normalize"], "status": "success", "attempt": 1, "finished_at": _now()}],
    }
    _atomic_write(state_path, state)
    return _result(skill_name=STAGE_SKILLS["normalize"], status="success", started_at=started_at,
                   input_sha256=_sha256(payload), outputs={"state_path": _portable_path(state_path, output_dir),
                   "project_id": mass.project_id, "unresolved_facts": state["unresolved_facts"]})


def analyze(input_path: Path, state_path: Path, output_dir: Path) -> dict:
    started_at, skill = _now(), STAGE_SKILLS["analyze"]
    state = _load_state(state_path, "normalized")
    analysis_path = output_dir / "mass-analysis.json"
    _atomic_write(analysis_path, to_jsonable(analyze_mass(_load_mass(input_path))))
    artifacts = [_artifact(analysis_path, output_dir)]
    attempt = _advance(state_path, state, skill=skill, stage="analyzed", artifacts=artifacts)
    return _result(skill_name=skill, status="success", started_at=started_at,
                   input_sha256=_file_sha256(input_path), outputs={"analysis_path": _portable_path(analysis_path, output_dir)},
                   artifacts=artifacts, attempt=attempt)


def alternatives(input_path: Path, state_path: Path, output_dir: Path) -> dict:
    started_at, skill = _now(), STAGE_SKILLS["alternatives"]
    state = _load_state(state_path, "analyzed")
    mass = _load_mass(input_path)
    generated = run_building_alternatives(mass)
    records, artifacts, accepted_ids, fingerprints = [], [], [], []
    for alternative in generated.alternatives:
        alt_dir = output_dir / "alternatives" / alternative.alternative_id
        create_building_visual_review_artifacts(
            alternative.building, boundary=list(mass.footprint_polygon), output_dir=alt_dir,
            render_style="architectural",
        )
        report_path = alt_dir / "building.review.json"
        report = _read_json(report_path)
        png_paths = sorted(alt_dir.rglob("*.png"))
        alt_fingerprint = _sha256(to_jsonable(alternative.fingerprints))
        fingerprints.append(alt_fingerprint)
        accepted = bool(alternative.accepted and report.get("accepted") and png_paths)
        if accepted:
            accepted_ids.append(alternative.alternative_id)
        alt_artifacts = [_artifact(report_path, output_dir), _artifact(alt_dir / "index.html", output_dir)]
        alt_artifacts.extend(_artifact(path, output_dir) for path in png_paths)
        artifacts.extend(alt_artifacts)
        records.append({
            "alternative_id": alternative.alternative_id, "strategy": alternative.strategy,
            "rank": alternative.rank, "score": alternative.score, "accepted": accepted,
            "fingerprint": alt_fingerprint, "report_path": _portable_path(report_path, output_dir),
            "preview_pngs": [_portable_path(path, output_dir) for path in png_paths],
            "internal_validation": report.get("internal_validation", {}).get("status"),
            "render_validation": report.get("render_validation", {}).get("status"),
            "regulatory_screening": report.get("regulatory_screening", {}).get("status", "not_checked"),
        })

    summary_path = output_dir / "alternatives.json"
    summary = {"project_id": mass.project_id, "accepted_count": len(accepted_ids),
               "accepted_alternative_ids": accepted_ids, "alternatives": records,
               "comparisons": to_jsonable(generated.comparisons),
               "rejected_families": to_jsonable(generated.rejected_families)}
    _atomic_write(summary_path, summary)
    artifacts.insert(0, _artifact(summary_path, output_dir))
    if len(accepted_ids) < 2:
        status = "retryable" if len(accepted_ids) == 1 else "blocked"
        return _result(skill_name=skill, status=status, started_at=started_at,
                       input_sha256=_file_sha256(input_path), outputs={"alternatives_path": _portable_path(summary_path, output_dir),
                       "accepted_count": len(accepted_ids)}, artifacts=artifacts,
                       violations=[_violation("insufficient_accepted_alternatives", "at least two accepted alternatives are required", retryable=status == "retryable")])
    attempt = _advance(state_path, state, skill=skill, stage="alternatives_generated", artifacts=artifacts,
                       accepted_ids=accepted_ids, fingerprints=fingerprints)
    return _result(skill_name=skill, status="success", started_at=started_at,
                   input_sha256=_file_sha256(input_path), outputs={"alternatives_path": _portable_path(summary_path, output_dir),
                   "accepted_count": len(accepted_ids), "accepted_alternative_ids": accepted_ids},
                   artifacts=artifacts, attempt=attempt)


def _png_has_content(path: Path) -> bool:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        white = Image.new("RGB", rgb.size, "white")
        return ImageChops.difference(rgb, white).getbbox() is not None


def review(input_path: Path, state_path: Path, output_dir: Path) -> dict:
    started_at, skill = _now(), STAGE_SKILLS["review"]
    state = _load_state(state_path, "alternatives_generated")
    summary = _read_json(output_dir / "alternatives.json")
    failures, preview_hashes = [], {}
    accepted = [item for item in summary["alternatives"] if item.get("accepted")]
    for item in accepted:
        report_path = output_dir / item["report_path"]
        if not report_path.is_file():
            failures.append(f"missing report: {report_path}")
            continue
        report = _read_json(report_path)
        if report.get("internal_validation", {}).get("status") != "pass":
            failures.append(f"internal validation failed: {item['alternative_id']}")
        if report.get("render_validation", {}).get("status") != "pass":
            failures.append(f"render validation failed: {item['alternative_id']}")
        pngs = [output_dir / path for path in item.get("preview_pngs", [])]
        if not pngs or any(not path.is_file() or not _png_has_content(path) for path in pngs):
            failures.append(f"blank or missing preview: {item['alternative_id']}")
        elif pngs:
            preview_hashes[item["alternative_id"]] = _file_sha256(pngs[0])
    if len(accepted) < 2:
        failures.append("fewer than two accepted alternatives")
    if len(set(preview_hashes.values())) < 2:
        failures.append("accepted alternatives do not have distinct previews")

    review_path = output_dir / "review-summary.json"
    review_value = {"project_id": state["project_id"], "status": "pass" if not failures else "fail",
                    "accepted_alternative_ids": [item["alternative_id"] for item in accepted],
                    "preview_sha256": preview_hashes, "failures": failures}
    _atomic_write(review_path, review_value)
    artifacts = [_artifact(review_path, output_dir)]
    if failures:
        return _result(skill_name=skill, status="blocked", started_at=started_at,
                       input_sha256=_file_sha256(output_dir / "alternatives.json"),
                       outputs={"review_path": _portable_path(review_path, output_dir)}, artifacts=artifacts,
                       violations=[_violation("visual_review_failed", "; ".join(failures))])
    attempt = _advance(state_path, state, skill=skill, stage="reviewed", artifacts=artifacts)
    return _result(skill_name=skill, status="success", started_at=started_at,
                   input_sha256=_file_sha256(output_dir / "alternatives.json"),
                   outputs={"review_path": _portable_path(review_path, output_dir), "preview_sha256": preview_hashes},
                   artifacts=artifacts, attempt=attempt)


def deliver(input_path: Path, state_path: Path, output_dir: Path) -> dict:
    started_at, skill = _now(), STAGE_SKILLS["deliver"]
    state = _load_state(state_path, "reviewed")
    review_value = _read_json(output_dir / "review-summary.json")
    missing_or_changed = [item["path"] for item in state["artifacts"]
                          if not (output_dir / item["path"]).is_file()
                          or _file_sha256(output_dir / item["path"]) != item["sha256"]]
    if missing_or_changed:
        return _result(skill_name=skill, status="blocked", started_at=started_at,
                       input_sha256=_file_sha256(state_path),
                       violations=[_violation("artifact_integrity_failed", "; ".join(missing_or_changed))])
    alternatives_value = _read_json(output_dir / "alternatives.json")
    regulatory = {item.get("regulatory_screening", "not_checked") for item in alternatives_value["alternatives"] if item.get("accepted")}
    regulatory_status = "fail" if "fail" in regulatory else ("pass" if regulatory == {"pass"} else "not_checked")
    manifest_path = output_dir / "planm-manifest.json"
    manifest = {
        "contract_version": "planm-delivery/v1", "project_id": state["project_id"], "status": "success",
        "accepted_alternative_ids": state["accepted_alternative_ids"], "internal_validation": "pass",
        "render_validation": "pass", "regulatory_screening": regulatory_status,
        "unresolved_facts": state["unresolved_facts"], "preview_sha256": review_value["preview_sha256"],
        "artifacts": state["artifacts"],
    }
    _atomic_write(manifest_path, manifest)
    artifacts = [_artifact(manifest_path, output_dir)]
    attempt = _advance(state_path, state, skill=skill, stage="delivered", artifacts=artifacts)
    return _result(skill_name=skill, status="success", started_at=started_at,
                   input_sha256=_file_sha256(output_dir / "review-summary.json"),
                   outputs={"manifest_path": _portable_path(manifest_path, output_dir), "accepted_count": len(state["accepted_alternative_ids"])},
                   artifacts=artifacts, attempt=attempt)


def main() -> int:
    request = json.load(sys.stdin)
    if not isinstance(request, dict) or request.get("contract_version") != "planm-stage-request/v1":
        raise SystemExit("unsupported PLANM stage request contract")
    stage = request.get("stage")
    if stage not in STAGE_SKILLS:
        raise SystemExit(f"unsupported PLANM stage: {stage}")
    input_path = Path(request["input_path"])
    state_path = Path(request["state_path"])
    output_dir = Path(request["output_dir"])
    handlers: dict[str, Callable[[Path, Path, Path], dict]] = {
        "normalize": normalize, "analyze": analyze, "alternatives": alternatives,
        "review": review, "deliver": deliver,
    }
    try:
        result = handlers[stage](input_path, state_path, output_dir)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        result = _result(skill_name=STAGE_SKILLS[stage], status="blocked", started_at=_now(),
                         input_sha256=_sha256({"input": input_path.name, "state": state_path.name}),
                         violations=[_violation("stage_execution_failed", f"{type(error).__name__}: {error}")])
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())

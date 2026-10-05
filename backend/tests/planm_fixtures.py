"""A stand-in for the Plan Agent's plan_stage, writing the artifact tree the run service reads.

It pins the file contract between this product and the agent (planm-state.json,
alternatives.json, alternatives/<id>/building.review.json, preview PNGs, planm-manifest.json)
without running the engine. Tests that need real geometry use the live agent instead.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

STAGE_SKILLS = {
    "normalize": "normalize-plan-request", "analyze": "analyze-building-mass",
    "alternatives": "generate-plan-alternatives", "review": "review-floorplan",
    "deliver": "deliver-planm-package",
}
NEXT_STAGE = {"normalize": "normalized", "analyze": "analyzed", "alternatives": "alternatives_generated",
              "review": "reviewed", "deliver": "delivered"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _artifact(path: Path, output_dir: Path) -> dict:
    data = path.read_bytes()
    return {"path": path.relative_to(output_dir).as_posix(),
            "media_type": {".json": "application/json", ".png": "image/png"}.get(path.suffix, "application/octet-stream"),
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def unresolved_facts(mass: dict) -> list[str]:
    context = mass.get("building_code_context") or {}
    facts = []
    if not context.get("jurisdiction"):
        facts.append("jurisdiction")
    if not context.get("effective_date"):
        facts.append("effective_date")
    if len(context.get("floor_facts") or []) != mass.get("floors"):
        facts.append("floor_code_context")
    if not context.get("travel_limit_classification"):
        facts.append("travel_limit_classification")
    return facts


def _result(stage: str, outputs: dict, artifacts: list[dict], attempt: int = 1) -> dict:
    now = _now()
    return {"contract_version": "skill-result/v1", "skill_name": STAGE_SKILLS[stage], "status": "success",
            "outputs": outputs, "violations": [], "artifacts": artifacts,
            "provenance": {"started_at": now, "finished_at": now, "attempt": attempt,
                           "input_sha256": _sha256(stage), "output_sha256": _sha256(outputs)}}


def _preview(path: Path, seed: int) -> None:
    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10 + seed * 7, 10, 200, 140), outline="black", width=3)
    draw.rectangle((30, 30 + seed * 9, 120, 100), fill="lightgray")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def fake_planm_stage(*, stage: str, input_path: Path, state_path: Path, output_dir: Path, run_root: Path,
                     timeout_seconds: float = 300, client=None) -> dict:
    """Same signature as backend.app.adapters.planm_agent.run_planm_stage."""
    mass = json.loads(input_path.read_text(encoding="utf-8"))
    if stage == "normalize":
        state = {"contract_version": "planm-state/v1", "project_id": mass["project_id"], "stage": "normalized",
                 "status": "success", "input_path": input_path.name, "output_dir": ".",
                 "attempts": {STAGE_SKILLS["normalize"]: 1}, "candidate_fingerprints": [],
                 "accepted_alternative_ids": [], "unresolved_facts": unresolved_facts(mass), "violations": [],
                 "artifacts": [], "history": [{"skill_name": STAGE_SKILLS["normalize"], "status": "success",
                                                "attempt": 1, "finished_at": _now()}]}
        _write(state_path, state)
        return _result(stage, {"state_path": state_path.name, "project_id": mass["project_id"],
                               "unresolved_facts": state["unresolved_facts"]}, [])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    artifacts, outputs = [], {}
    if stage == "analyze":
        path = output_dir / "mass-analysis.json"
        _write(path, {"floors": mass["floors"], "footprint_area": 360.0})
        artifacts = [_artifact(path, output_dir)]
    elif stage == "alternatives":
        records = []
        for index in (1, 2):
            alt = f"alt-{index:02d}"
            alt_dir = output_dir / "alternatives" / alt
            floors = []
            for floor in range(mass["floors"]):
                png = alt_dir / f"floor_{floor + 1:03d}" / "plan.png"
                _preview(png, index + floor)
                _write(alt_dir / f"floor_{floor + 1:03d}" / "f.geometry.json",
                       {"contract_version": "planm-floor-geometry/v1", "floor_index": floor, "rooms": []})
                floors.append({"floor_index": floor, "accepted": True, "artifacts": {"png": png.relative_to(alt_dir).as_posix()}})
            report = alt_dir / "building.review.json"
            _write(report, {"schema_version": 1, "project_id": mass["project_id"], "accepted": True,
                            "internal_validation": {"status": "pass"}, "render_validation": {"status": "pass"},
                            "regulatory_screening": {"status": "not_checked"}, "floors": floors})
            (alt_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            pngs = sorted(alt_dir.rglob("*.png"))
            records.append({"alternative_id": alt, "strategy": f"strategy-{index}", "rank": index, "score": 1.0 / index,
                            "accepted": True, "fingerprint": _sha256(alt),
                            "report_path": report.relative_to(output_dir).as_posix(),
                            "preview_pngs": [p.relative_to(output_dir).as_posix() for p in pngs],
                            "internal_validation": "pass", "render_validation": "pass",
                            "regulatory_screening": "not_checked"})
            artifacts.extend(_artifact(p, output_dir) for p in [report, *pngs])
        summary = output_dir / "alternatives.json"
        _write(summary, {"project_id": mass["project_id"], "accepted_count": 2,
                         "accepted_alternative_ids": [r["alternative_id"] for r in records],
                         "alternatives": records, "comparisons": [], "rejected_families": []})
        artifacts.insert(0, _artifact(summary, output_dir))
        state["accepted_alternative_ids"] = [r["alternative_id"] for r in records]
        state["candidate_fingerprints"] = [r["fingerprint"] for r in records]
        outputs = {"accepted_count": 2, "accepted_alternative_ids": state["accepted_alternative_ids"]}
    elif stage == "review":
        path = output_dir / "review-summary.json"
        _write(path, {"project_id": mass["project_id"], "status": "pass",
                      "accepted_alternative_ids": state["accepted_alternative_ids"], "preview_sha256": {}, "failures": []})
        artifacts = [_artifact(path, output_dir)]
    elif stage == "deliver":
        path = output_dir / "planm-manifest.json"
        _write(path, {"contract_version": "planm-delivery/v1", "project_id": mass["project_id"], "status": "success",
                      "accepted_alternative_ids": state["accepted_alternative_ids"], "internal_validation": "pass",
                      "render_validation": "pass", "regulatory_screening": "not_checked",
                      "unresolved_facts": state["unresolved_facts"], "preview_sha256": {}, "artifacts": state["artifacts"]})
        artifacts = [_artifact(path, output_dir)]
    attempt = int(state["attempts"].get(STAGE_SKILLS[stage], 0)) + 1
    state["attempts"][STAGE_SKILLS[stage]] = attempt
    state["stage"] = NEXT_STAGE[stage]
    state["artifacts"].extend(artifacts)
    state["history"].append({"skill_name": STAGE_SKILLS[stage], "status": "success", "attempt": attempt, "finished_at": _now()})
    _write(state_path, state)
    return _result(stage, outputs, artifacts, attempt)

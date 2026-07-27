from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import (
    run_candidate_search,
    run_generation_loop,
)
from backend.app.schemas.loop import CandidateRecord, LoopConfig
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.result import GenerationResult
from backend.app.schemas.visual import VisualReviewArtifacts, VisualReviewLoopResult
from engine.geometry.polygon import bounds
from engine.io.png import SimplePngCanvas

PALETTE = {
    "shop_unit": "#d9ead3",
    "office_area": "#cfe2f3",
    "core": "#f4cccc",
    "restroom": "#d9d2e9",
    "storage": "#fff2cc",
    "utility": "#ead1dc",
    "pantry": "#d0e0e3",
    "ps_eps": "#fce5cd",
}

PNG_PALETTE = {
    "shop_unit": (217, 234, 211),
    "office_area": (207, 226, 243),
    "core": (244, 204, 204),
    "restroom": (217, 210, 233),
    "storage": (255, 242, 204),
    "utility": (234, 209, 220),
    "pantry": (208, 224, 227),
    "ps_eps": (252, 229, 205),
}


def create_visual_review_artifacts(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
    output_dir: str | Path,
    width: int = 960,
    height: int = 540,
    *,
    candidate: CandidateRecord | None = None,
    iteration_number: int | None = None,
    previous_validation: ValidationReport | None = None,
    run_root: str | Path | None = None,
) -> VisualReviewArtifacts:
    if width <= 0 or height <= 0:
        raise ValueError("viewport width and height must be positive")

    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    stem = f"{_slug(result.mass.project_id)}-f{result.program.floor_index}"
    svg_path = target / f"{stem}.svg"
    png_path = target / f"{stem}.png"
    html_path = target / f"{stem}.html"
    report_path = target / f"{stem}.review.json"
    artifact_root = Path(run_root).resolve() if run_root is not None else target
    if not target.is_relative_to(artifact_root):
        raise ValueError("artifact output directory escapes run root")
    artifact_links = {
        "svg": _relative_link(artifact_root, svg_path),
        "png": _relative_link(artifact_root, png_path),
        "html": _relative_link(artifact_root, html_path),
        "review_json": _relative_link(artifact_root, report_path),
    }
    _ensure_within_target(target, svg_path, png_path, html_path, report_path)

    svg_path.write_text(_render_svg(result, boundary, width, height), encoding="utf-8")
    png_path.write_bytes(_render_png(result, boundary, width, height))

    checks = _hard_validation_checks(result.validation)
    needs_iteration = not result.validation.accepted
    scores = _validation_scores(result.validation)
    previous_total_score = (
        previous_validation.total_score if previous_validation is not None else None
    )
    previous_hard_failures = (
        previous_validation.hard_violation_count
        if previous_validation is not None
        else None
    )
    report = {
        "schema_version": 1,
        "project_id": result.mass.project_id,
        "floor_index": result.program.floor_index,
        "use_type": result.program.use_type,
        "iteration": (
            iteration_number
            if iteration_number is not None
            else candidate.iteration if candidate is not None else None
        ),
        "candidate_id": result.layout.candidate_id,
        "fingerprint": candidate.fingerprint if candidate is not None else None,
        "parent_id": candidate.parent_id if candidate is not None else None,
        "operator": candidate.operator if candidate is not None else None,
        "operator_params": (
            to_jsonable(candidate.operator_params) if candidate is not None else {}
        ),
        "accepted": result.validation.accepted,
        "needs_iteration": needs_iteration,
        "hard_failure_count": result.validation.hard_violation_count,
        "violations": to_jsonable(result.validation.violations),
        "scores": scores,
        "total_score_delta": (
            None
            if previous_total_score is None
            else round(result.validation.total_score - previous_total_score, 10)
        ),
        "hard_failure_count_delta": (
            None
            if previous_hard_failures is None
            else result.validation.hard_violation_count - previous_hard_failures
        ),
        "checks": checks,
        "validation": to_jsonable(result.validation),
        "artifacts": artifact_links,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    html_path.write_text(
        _render_html(
            result,
            svg_name=svg_path.name,
            png_name=png_path.name,
            report_name=report_path.name,
            report=report,
        ),
        encoding="utf-8",
    )

    return VisualReviewArtifacts(
        svg_path=svg_path,
        png_path=png_path,
        html_path=html_path,
        report_path=report_path,
        artifact_links=artifact_links,
        needs_iteration=needs_iteration,
        checks=checks,
    )


def run_visual_review_loop(
    mass: MassInput,
    floor_index: int,
    use_type: str,
    output_dir: str | Path,
    max_iterations: int = 3,
) -> VisualReviewLoopResult:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")

    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    search = run_candidate_search(
        mass,
        floor_index=floor_index,
        use_type=use_type,
        config=LoopConfig(max_iterations=max_iterations),
    )
    artifacts: list[VisualReviewArtifacts] = []
    previous_validation: ValidationReport | None = None
    reports: list[dict] = []
    for iteration in search.iterations:
        candidate = iteration.best_so_far
        result = GenerationResult(
            mass=search.mass,
            program=search.program,
            layout=candidate.layout,
            validation=candidate.validation,
        )
        iteration_dir = target / f"iteration_{iteration.iteration:03d}"
        review = create_visual_review_artifacts(
            result,
            boundary=mass.footprint_polygon,
            output_dir=iteration_dir,
            candidate=candidate,
            iteration_number=iteration.iteration,
            previous_validation=previous_validation,
            run_root=target,
        )
        artifacts.append(review)
        reports.append(
            json.loads(review.report_path.read_text(encoding="utf-8"))
        )
        previous_validation = candidate.validation

    index = _review_index(search, reports)
    index_json_path = target / "review.index.json"
    index_html_path = target / "index.html"
    _ensure_within_target(target, index_json_path, index_html_path)
    index_json_path.write_text(
        json.dumps(
            index,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    index_html_path.write_text(_render_index_html(index), encoding="utf-8")

    return VisualReviewLoopResult(
        iterations_run=len(artifacts),
        final_needs_iteration=not search.accepted,
        artifacts=artifacts,
        index_json_path=index_json_path,
        index_html_path=index_html_path,
        termination_reason=search.termination_reason,
        evaluation_count=search.evaluation_count,
        accepted=search.accepted,
    )


def _review_index(search, reports: list[dict]) -> dict:
    iterations = [
        {
            "iteration": report["iteration"],
            "candidate_id": report["candidate_id"],
            "fingerprint": report["fingerprint"],
            "parent_id": report["parent_id"],
            "operator": report["operator"],
            "operator_params": report["operator_params"],
            "accepted": report["accepted"],
            "needs_iteration": report["needs_iteration"],
            "hard_failure_count": report["hard_failure_count"],
            "violations": report["violations"],
            "scores": report["scores"],
            "total_score_delta": report["total_score_delta"],
            "hard_failure_count_delta": report["hard_failure_count_delta"],
            "artifacts": report["artifacts"],
        }
        for report in reports
    ]
    return {
        "schema_version": 1,
        "project_id": search.mass.project_id,
        "floor_index": search.program.floor_index,
        "use_type": search.program.use_type,
        "accepted": search.accepted,
        "needs_iteration": not search.accepted,
        "termination_reason": search.termination_reason,
        "evaluation_count": search.evaluation_count,
        "iterations": iterations,
        "score_trend": [entry["scores"]["total_score"] for entry in iterations],
        "hard_failure_trend": [
            entry["hard_failure_count"] for entry in iterations
        ],
        "lineage": [
            {
                "candidate_id": entry["candidate_id"],
                "parent_id": entry["parent_id"],
                "operator": entry["operator"],
                "operator_params": entry["operator_params"],
            }
            for entry in iterations
        ],
    }


def _render_index_html(index: dict) -> str:
    rows = []
    for entry in index["iterations"]:
        operator_params = json.dumps(
            entry["operator_params"],
            ensure_ascii=False,
            sort_keys=True,
        )
        artifact_links = " ".join(
            f'<a href="{html.escape(path, quote=True)}">{html.escape(kind)}</a>'
            for kind, path in entry["artifacts"].items()
        )
        rows.append(
            "<tr>"
            f'<th scope="row">{entry["iteration"]}</th>'
            f"<td>{html.escape(entry['candidate_id'])}</td>"
            f"<td>{html.escape(entry['fingerprint'])}</td>"
            f"<td>{html.escape(entry['parent_id'] or '')}</td>"
            f"<td>{html.escape(entry['operator'])}</td>"
            f"<td>{html.escape(operator_params)}</td>"
            f"<td>{entry['hard_failure_count']}</td>"
            f"<td>{entry['scores']['total_score']}</td>"
            f"<td>{html.escape('accepted' if entry['accepted'] else 'rejected')}</td>"
            f"<td>{artifact_links}</td>"
            "</tr>"
        )
    status = "accepted" if index["accepted"] else "needs iteration"
    project_id = html.escape(index["project_id"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{project_id} review history</title>
  <style>
    body {{ margin: 24px; font-family: Arial, sans-serif; background: white; color: #111; }}
    main {{ max-width: 1280px; margin: 0 auto; }}
    h1 {{ font-size: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }}
    thead th {{ background: #f4f4f4; }}
    a {{ color: #0645ad; }}
  </style>
</head>
<body>
  <main>
    <h1>Review History: {project_id} F{index["floor_index"]}</h1>
    <section aria-labelledby="run-summary">
      <h2 id="run-summary">Run Summary</h2>
      <p>Status: {html.escape(status)}. Termination: {html.escape(index["termination_reason"])}.
      Evaluations: {index["evaluation_count"]}.</p>
    </section>
    <section aria-labelledby="iteration-history">
      <h2 id="iteration-history">Iteration History</h2>
      <table>
        <thead><tr><th scope="col">Iteration</th><th scope="col">Candidate</th>
        <th scope="col">Fingerprint</th><th scope="col">Parent</th>
        <th scope="col">Operator</th><th scope="col">Operator parameters</th>
        <th scope="col">Hard failures</th>
        <th scope="col">Total score</th><th scope="col">Status</th>
        <th scope="col">Artifacts</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _render_svg(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
) -> str:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(min_x, min_y, max_x, max_y, width, height)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for room in result.layout.rooms:
        points = " ".join(
            f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}" for x, y in room.polygon
        )
        fill = PALETTE.get(room.space_type, "#eeeeee")
        parts.append(f'<polygon points="{points}" fill="{fill}" stroke="#111111" stroke-width="2"/>')
        cx, cy = _centroid(room.polygon)
        parts.append(
            f'<text x="{_sx(cx, min_x, scale, pad_x)}" y="{_sy(cy, min_y, scale, pad_y, height)}" '
            f'font-family="Arial" font-size="14" text-anchor="middle">{html.escape(room.space_type)}</text>'
        )
    boundary_points = " ".join(
        f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}" for x, y in boundary
    )
    parts.append(f'<polygon points="{boundary_points}" fill="none" stroke="#000000" stroke-width="4"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_png(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
) -> bytes:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(min_x, min_y, max_x, max_y, width, height)
    canvas = SimplePngCanvas(width, height)
    for room in result.layout.rooms:
        points = _raster_points(room.polygon, min_x, min_y, scale, pad_x, pad_y, height)
        color = PNG_PALETTE.get(room.space_type, (238, 238, 238))
        canvas.fill_polygon(points, color)
        canvas.stroke_polygon(points, (17, 17, 17), thickness=2)
    canvas.stroke_polygon(
        _raster_points(boundary, min_x, min_y, scale, pad_x, pad_y, height), (0, 0, 0), thickness=4
    )
    return canvas.to_bytes()


def _render_html(
    result: GenerationResult,
    svg_name: str,
    png_name: str,
    report_name: str,
    report: dict,
) -> str:
    status = (
        "needs iteration"
        if report["needs_iteration"]
        else "passes hard validation"
    )
    checks = "".join(
        f'<tr><th scope="row">{html.escape(name)}</th>'
        f"<td>{html.escape(value)}</td></tr>"
        for name, value in report["checks"].items()
    )
    advisory_scores = "".join(
        f'<tr><th scope="row">{html.escape(name)}</th><td>{value}</td></tr>'
        for name, value in report["scores"].items()
    )
    project_id = html.escape(result.mass.project_id)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{project_id} floor visual review</title>
  <style>
    body {{ margin: 24px; font-family: Arial, sans-serif; background: white; color: #111; }}
    main {{ max-width: 1180px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .status {{ margin-bottom: 18px; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; align-items: start; }}
    iframe {{ width: 100%; height: 620px; border: 1px solid #ccc; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td {{ border-bottom: 1px solid #ddd; padding: 8px 6px; }}
    a {{ color: #0645ad; }}
  </style>
</head>
<body>
  <main>
    <h1>Visual Review: {project_id} F{result.program.floor_index}</h1>
    <div class="status">{html.escape(status)}</div>
    <div class="grid">
      <iframe src="{html.escape(svg_name, quote=True)}" title="floor plan svg"></iframe>
      <section>
        <h2>Hard Validation Checks</h2>
        <table>
          <thead><tr><th scope="col">Hard gate</th><th scope="col">Status</th></tr></thead>
          <tbody>{checks}</tbody>
        </table>
        <h2>Advisory Scores</h2>
        <table>
          <thead><tr><th scope="col">Metric</th><th scope="col">Score</th></tr></thead>
          <tbody>{advisory_scores}</tbody>
        </table>
        <p><a href="{html.escape(png_name, quote=True)}">PNG</a></p>
        <p><a href="{html.escape(report_name, quote=True)}">Review JSON</a></p>
      </section>
    </div>
  </main>
</body>
</html>
"""


def _fit_transform(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    width: int,
    height: int,
) -> tuple[float, float, float]:
    drawing_width = max_x - min_x
    drawing_height = max_y - min_y
    scale = min((width * 0.86) / drawing_width, (height * 0.82) / drawing_height)
    pad_x = (width - drawing_width * scale) / 2
    pad_y = (height - drawing_height * scale) / 2
    return scale, pad_x, pad_y


def _sx(x: float, min_x: float, scale: float, pad_x: float) -> float:
    return round((x - min_x) * scale + pad_x, 2)


def _sy(y: float, min_y: float, scale: float, pad_y: float, height: int) -> float:
    return round(height - ((y - min_y) * scale + pad_y), 2)


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _raster_points(
    points: list[tuple[float, float]],
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    height: int,
) -> list[tuple[int, int]]:
    return [
        (round(_sx(x, min_x, scale, pad_x)), round(_sy(y, min_y, scale, pad_y, height))) for x, y in points
    ]


def _slug(value: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "project"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{readable[:63]}-{digest}"


def _validation_scores(validation: ValidationReport) -> dict[str, float]:
    payload = to_jsonable(validation)
    return {
        name: value
        for name, value in payload.items()
        if name.endswith("_score")
    }


def _hard_validation_checks(validation: ValidationReport) -> dict[str, str]:
    violation_codes = {violation.code for violation in validation.violations}
    hard_gate_codes = {
        "boundary": {"invalid_geometry", "boundary"},
        "overlap": {"overlap"},
        "area": {"room_identity", "room_area"},
        "circulation_access": {
            "circulation_missing",
            "circulation_disconnected",
            "room_inaccessible",
        },
    }
    return {
        name: "fail" if violation_codes & codes else "pass"
        for name, codes in hard_gate_codes.items()
    }


def _relative_link(root: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("artifact path escapes output root")
    return resolved.relative_to(root).as_posix()


def _ensure_within_target(target: Path, *paths: Path) -> None:
    for path in paths:
        if not path.resolve().is_relative_to(target):
            raise ValueError("artifact path escapes output root")

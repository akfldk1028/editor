from __future__ import annotations

import hashlib
import html
import json
import math
import re
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import (
    run_candidate_search,
)
from backend.app.schemas.loop import CandidateRecord, LoopConfig
from backend.app.schemas.layout import OpeningSegment
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.result import BuildingGenerationResult, GenerationResult
from backend.app.schemas.visual import (
    BuildingVisualReviewArtifacts,
    VisualReviewArtifacts,
    VisualReviewLoopResult,
)
from engine.geometry import orthogonal_min_width
from engine.geometry.polygon import bounds
from engine.geometry.polygon import polygon_area
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
    "open_work": "#b8d8f0",
    "meeting": "#f6c6a8",
    "reception": "#f9df8a",
    "focus": "#c7dfb1",
    "it_storage": "#d7c4e8",
    "sales": "#f3b6b8",
    "checkout": "#f6d5a6",
    "stock": "#c6d9b8",
    "staff": "#b9d7cf",
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
    "open_work": (184, 216, 240),
    "meeting": (246, 198, 168),
    "reception": (249, 223, 138),
    "focus": (199, 223, 177),
    "it_storage": (215, 196, 232),
    "sales": (243, 182, 184),
    "checkout": (246, 213, 166),
    "stock": (198, 217, 184),
    "staff": (185, 215, 207),
}

CIRCULATION_FILL = "#d9d9d9"
CIRCULATION_STROKE = "#38761d"
PNG_CIRCULATION_FILL = (217, 217, 217)
PNG_CIRCULATION_STROKE = (56, 118, 29)
DOOR_STROKE = "#0056b3"
PNG_DOOR_STROKE = (0, 86, 179)


def create_building_visual_review_artifacts(
    result: BuildingGenerationResult,
    boundary: list[tuple[float, float]],
    output_dir: str | Path,
    width: int = 960,
    height: int = 540,
) -> BuildingVisualReviewArtifacts:
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    floor_artifacts = []
    floor_reports = []
    for floor in result.floor_results:
        floor_dir = target / f"floor_{floor.program.floor_index:03d}"
        artifacts = create_visual_review_artifacts(
            floor,
            boundary=boundary,
            output_dir=floor_dir,
            width=width,
            height=height,
            run_root=target,
        )
        floor_artifacts.append(artifacts)
        floor_reports.append(
            {
                "floor_index": floor.program.floor_index,
                "use_type": floor.program.use_type,
                "accepted": floor.validation.accepted,
                "room_count": len(floor.layout.rooms),
                "artifacts": artifacts.artifact_links,
            }
        )

    report_path = target / "building.review.json"
    index_html_path = target / "index.html"
    report = {
        "schema_version": 1,
        "project_id": result.mass.project_id,
        "accepted": result.accepted,
        "assignment_source": result.assignment_source,
        "vertical_core_aligned": result.vertical_core_aligned,
        "total_area": result.total_area,
        "use_type_areas": result.use_type_areas,
        "floors": floor_reports,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    index_html_path.write_text(
        _render_building_index(result, floor_reports),
        encoding="utf-8",
    )
    return BuildingVisualReviewArtifacts(
        index_html_path=index_html_path,
        report_path=report_path,
        floor_artifacts=tuple(floor_artifacts),
        accepted=result.accepted,
    )


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

    checks = _hard_validation_checks(
        result.validation,
    )
    measurements = _layout_measurements(result)
    room_shapes = to_jsonable(result.validation.room_shapes)
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
        "measurements": measurements,
        "room_shapes": room_shapes,
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


def _render_building_index(
    result: BuildingGenerationResult,
    floors: list[dict],
) -> str:
    floor_sections = []
    for floor in floors:
        title = (
            f"F{floor['floor_index']} · "
            f"{html.escape(str(floor['use_type']))}"
        )
        png = html.escape(floor["artifacts"]["png"], quote=True)
        review = html.escape(floor["artifacts"]["html"], quote=True)
        status = "accepted" if floor["accepted"] else "needs review"
        floor_sections.append(
            f"""
            <section>
              <header><h2>{title}</h2><span>{status} | {floor['room_count']} rooms</span></header>
              <a href="{review}"><img src="{png}" alt="{title} floor plan"></a>
            </section>
            """
        )
    status = "accepted" if result.accepted else "needs review"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{html.escape(result.mass.project_id)} building review</title>
  <style>
    :root {{ font-family: Inter, Segoe UI, sans-serif; color: #17232f; background: #f4f6f8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 48px; }}
    .summary {{ display: flex; align-items: baseline; justify-content: space-between; gap: 20px; border-bottom: 1px solid #ccd5dc; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    p {{ margin: 0 0 20px; color: #63717e; }}
    .status {{ color: #217a55; font-weight: 700; }}
    section {{ margin-top: 22px; padding-bottom: 22px; border-bottom: 1px solid #d8dfe5; }}
    section header {{ display: flex; align-items: center; justify-content: space-between; }}
    h2 {{ margin: 0 0 10px; font-size: 15px; }}
    section span {{ color: #217a55; font-size: 12px; }}
    img {{ display: block; width: 100%; height: auto; border: 1px solid #cad3da; background: white; }}
  </style>
</head>
<body>
  <main>
    <div class="summary">
      <div><h1>{html.escape(result.mass.project_id)}</h1><p>{len(floors)} floors · {result.total_area:g} total area</p></div>
      <span class="status">{status}</span>
    </div>
    {''.join(floor_sections)}
  </main>
</body>
</html>
"""


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
        error=search.error,
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
        "error": search.error,
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
  <link rel="icon" href="data:,">
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
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    parts.append('<g data-layer="rooms">')
    for room in result.layout.rooms:
        points = " ".join(
            f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}" for x, y in room.polygon
        )
        fill = PALETTE.get(room.space_type, "#eeeeee")
        parts.append(f'<polygon points="{points}" fill="{fill}" stroke="#111111" stroke-width="2"/>')
    parts.append("</g>")
    parts.append('<g data-layer="text-labels">')
    for room in result.layout.rooms:
        cx, cy = _centroid(room.polygon)
        label_x = _sx(cx, min_x, scale, pad_x)
        label_y = _sy(cy, min_y, scale, pad_y, height)
        area = _format_measurement(polygon_area(room.polygon))
        parts.append(
            f'<text data-kind="room-label" x="{label_x}" y="{label_y}" '
            'font-family="Arial" font-size="12" text-anchor="middle">'
            f'<tspan x="{label_x}" dy="-0.6em">{html.escape(room.room_id)}</tspan>'
            f'<tspan x="{label_x}" dy="1.2em">{html.escape(room.space_type)}</tspan>'
            f'<tspan x="{label_x}" dy="1.2em">{area} m2</tspan></text>'
        )
    parts.append("</g>")
    parts.append('<g data-layer="circulation">')
    for path in result.layout.circulation:
        points = " ".join(
            f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}"
            for x, y in path.polygon
        )
        parts.append(
            f'<polygon data-kind="circulation" points="{points}" '
            f'fill="{CIRCULATION_FILL}" stroke="{CIRCULATION_STROKE}" stroke-width="2"/>'
        )
        cx, cy = _centroid(path.polygon)
        parts.append(
            f'<text data-kind="circulation" x="{_sx(cx, min_x, scale, pad_x)}" '
            f'y="{_sy(cy, min_y, scale, pad_y, height)}" font-family="Arial" '
            f'font-size="14" text-anchor="middle">{html.escape(path.space_type)}</text>'
        )
    parts.append("</g>")
    boundary_points = " ".join(
        f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}" for x, y in boundary
    )
    parts.append(f'<polygon points="{boundary_points}" fill="none" stroke="#000000" stroke-width="4"/>')
    parts.append('<g data-layer="door-openings">')
    for opening in result.layout.openings:
        if not _is_renderable_opening(opening):
            continue
        start_x = _sx(opening.start[0], min_x, scale, pad_x)
        start_y = _sy(opening.start[1], min_y, scale, pad_y, height)
        end_x = _sx(opening.end[0], min_x, scale, pad_x)
        end_y = _sy(opening.end[1], min_y, scale, pad_y, height)
        midpoint_x = round((start_x + end_x) / 2, 2)
        midpoint_y = round((start_y + end_y) / 2, 2)
        clear_width = _format_measurement(opening.clear_width)
        accessible_label = html.escape(
            f"{opening.connects[0]} door clear width {clear_width} m",
            quote=True,
        )
        parts.append(
            f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" '
            'stroke="white" stroke-width="8"/>'
        )
        parts.append(
            f'<line data-kind="door-opening" aria-label="{accessible_label}" '
            f'x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" '
            f'stroke="{DOOR_STROKE}" stroke-width="4"/>'
        )
        parts.append(
            f'<text data-kind="door-width" x="{midpoint_x + 7}" y="{midpoint_y - 4}" '
            f'font-family="Arial" font-size="11">{clear_width} m</text>'
        )
    parts.append("</g>")
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
    for path in result.layout.circulation:
        points = _raster_points(path.polygon, min_x, min_y, scale, pad_x, pad_y, height)
        canvas.fill_polygon(points, PNG_CIRCULATION_FILL)
        canvas.stroke_polygon(points, PNG_CIRCULATION_STROKE, thickness=2)
    canvas.stroke_polygon(
        _raster_points(boundary, min_x, min_y, scale, pad_x, pad_y, height), (0, 0, 0), thickness=4
    )
    for opening in result.layout.openings:
        if not _is_renderable_opening(opening):
            continue
        start, end = _raster_points(
            [opening.start, opening.end],
            min_x,
            min_y,
            scale,
            pad_x,
            pad_y,
            height,
        )
        canvas.stroke_line(start, end, (255, 255, 255), thickness=8)
        canvas.stroke_line(start, end, PNG_DOOR_STROKE, thickness=4)
        _draw_door_jambs(canvas, start, end)
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
    room_form_rows = "".join(
        "<tr>"
        f'<th scope="row">{html.escape(shape["room_id"])}</th>'
        f"<td>{_display_measurement(shape['measured_min_width'])}</td>"
        f"<td>{_display_measurement(shape['measured_aspect_ratio'])}</td>"
        f"<td>{_display_measurement(shape['required_min_width'])}</td>"
        f"<td>{_display_measurement(shape['maximum_aspect_ratio'])}</td>"
        "</tr>"
        for shape in report["room_shapes"]
    )
    project_id = html.escape(result.mass.project_id)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="icon" href="data:,">
  <title>{project_id} floor visual review</title>
  <style>
    body {{ margin: 24px; font-family: Arial, sans-serif; background: white; color: #111; }}
    main {{ max-width: 1180px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .status {{ margin-bottom: 18px; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); gap: 20px; align-items: start; }}
    .plan {{ min-width: 0; }}
    iframe {{ width: 100%; aspect-ratio: 16 / 9; height: auto; border: 1px solid #ccc; }}
    #working-layer-controls {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 12px; }}
    #working-layer-controls button {{ min-width: 78px; min-height: 32px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td {{ border-bottom: 1px solid #ddd; padding: 8px 6px; }}
    a {{ color: #0645ad; }}
    @media (max-width: 680px) {{ body {{ margin: 14px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Visual Review: {project_id} F{result.program.floor_index}</h1>
    <div class="status">{html.escape(status)}</div>
    <div class="grid">
      <section class="plan">
        <div id="working-layer-controls" aria-label="Working layers">
          <button type="button" data-layer="rooms" aria-pressed="true">Rooms</button>
          <button type="button" data-layer="circulation" aria-pressed="true">Circulation</button>
          <button type="button" data-layer="door-openings" aria-pressed="true">Doors</button>
          <button type="button" data-layer="text-labels" aria-pressed="true">Labels</button>
        </div>
        <iframe id="floor-plan" src="{html.escape(svg_name, quote=True)}" title="floor plan svg"></iframe>
      </section>
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
        <h2>Room Program and Form</h2>
        <table id="room-form-report">
          <thead><tr><th scope="col">Room</th><th scope="col">Width m</th><th scope="col">Aspect</th><th scope="col">Min width</th><th scope="col">Max aspect</th></tr></thead>
          <tbody>{room_form_rows}</tbody>
        </table>
        <p><a href="{html.escape(png_name, quote=True)}">PNG</a></p>
        <p><a href="{html.escape(report_name, quote=True)}">Review JSON</a></p>
      </section>
    </div>
  </main>
  <script>
    const frame = document.getElementById("floor-plan");
    document.querySelectorAll("#working-layer-controls button").forEach((button) => {{
      button.addEventListener("click", () => {{
        const pressed = button.getAttribute("aria-pressed") === "true";
        frame.contentDocument?.querySelectorAll(`[data-layer="${{button.dataset.layer}}"]`).forEach((node) => {{ node.style.display = pressed ? "none" : ""; }});
        button.setAttribute("aria-pressed", String(!pressed));
      }});
    }});
  </script>
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


def _hard_validation_checks(
    validation: ValidationReport,
) -> dict[str, str]:
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
        "openings": {
            "opening_identity",
            "opening_reference",
            "door_geometry",
            "door_width",
            "door_missing",
        },
        "corridor_width": {"circulation_too_narrow"},
        "room_form": {"room_min_width", "room_aspect_ratio"},
    }
    checks = {
        name: "fail" if violation_codes & codes else "pass"
        for name, codes in hard_gate_codes.items()
    }
    if not validation.openings_checked:
        checks["openings"] = "not_checked"
    if not validation.corridor_width_checked:
        checks["corridor_width"] = "not_checked"
    return checks


def _layout_measurements(result: GenerationResult) -> dict[str, int | float | list[str] | None]:
    door_widths = [
        float(opening.clear_width)
        for opening in result.layout.openings
        if (
            opening.kind == "door"
            and isinstance(opening.clear_width, (int, float))
            and math.isfinite(opening.clear_width)
        )
    ]
    room_widths = [
        shape.measured_min_width
        for shape in result.validation.room_shapes
        if shape.measured_min_width is not None
    ]
    room_aspects = [
        shape.measured_aspect_ratio
        for shape in result.validation.room_shapes
        if shape.measured_aspect_ratio is not None
    ]
    failed_room_ids = sorted(
        {
            violation.subject
            for violation in result.validation.violations
            if violation.code in {"room_min_width", "room_aspect_ratio"}
        }
    )
    corridor_widths = []
    for path in result.layout.circulation:
        try:
            corridor_widths.append(orthogonal_min_width(path.polygon))
        except ValueError:
            continue
    return {
        "door_count": len(result.layout.openings),
        "min_door_width": min(door_widths) if door_widths else None,
        "min_corridor_width": min(corridor_widths) if corridor_widths else None,
        "min_room_width": min(room_widths) if room_widths else None,
        "max_room_aspect_ratio": max(room_aspects) if room_aspects else None,
        "failed_room_ids": failed_room_ids,
    }


def _is_renderable_opening(opening: OpeningSegment) -> bool:
    values = (*opening.start, *opening.end, opening.clear_width)
    return all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)


def _format_measurement(value: float) -> str:
    return f"{round(value, 3):g}"


def _display_measurement(value: float | None) -> str:
    return "-" if value is None else _format_measurement(value)


def _draw_door_jambs(
    canvas: SimplePngCanvas,
    start: tuple[int, int],
    end: tuple[int, int],
) -> None:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = max((delta_x**2 + delta_y**2) ** 0.5, 1)
    offset_x = round(-delta_y / length * 4)
    offset_y = round(delta_x / length * 4)
    for x, y in (start, end):
        canvas.stroke_line(
            (x - offset_x, y - offset_y),
            (x + offset_x, y + offset_y),
            (0, 0, 0),
            thickness=2,
        )


def _relative_link(root: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("artifact path escapes output root")
    return resolved.relative_to(root).as_posix()


def _ensure_within_target(target: Path, *paths: Path) -> None:
    for path in paths:
        if not path.resolve().is_relative_to(target):
            raise ValueError("artifact path escapes output root")

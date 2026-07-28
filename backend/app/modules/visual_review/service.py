from __future__ import annotations

import hashlib
import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import (
    run_candidate_search,
)
from backend.app.schemas.loop import CandidateRecord, LoopConfig
from backend.app.schemas.layout import OpeningSegment, PlanElement, PlanLine
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

LAYER_ORDER = (
    "grid",
    "rooms",
    "circulation",
    "core",
    "structure",
    "envelope",
    "door-openings",
    "furniture",
    "fixtures",
    "egress",
    "dimensions",
    "text-labels",
)
_BASIC_DESIGN_LAYERS = {
    "grid",
    "core",
    "structure",
    "envelope",
    "furniture",
    "fixtures",
    "egress",
    "dimensions",
}
_BASIC_DESIGN_VIOLATION_CODES = {
    "basic_design_missing",
    "basic_design_identity",
    "basic_design_reference",
    "basic_design_geometry",
    "core_geometry",
    "core_subspace_containment",
    "core_subspace_overlap",
    "vertical_missing",
    "protected_exit_count",
    "protected_exit_reference",
    "protected_exit_geometry",
    "protected_exit_width",
    "protected_exit_separation",
    "egress_route_missing",
    "egress_route_reference",
    "egress_route_geometry",
    "column_boundary",
    "column_conflict",
    "structure_missing",
    "window_reference",
    "window_geometry",
    "window_conflict",
    "window_missing",
    "entrance_missing",
    "entrance_geometry",
    "placed_object_reference",
    "placed_object_containment",
    "placed_object_overlap",
    "placed_object_missing",
    "dimension_reference",
    "dimension_value",
    "dimension_missing",
    "site_missing",
    "site_geometry",
}


@dataclass(frozen=True)
class _RenderFeature:
    feature_id: str
    layer: str
    kind: str
    geometry: str
    points: tuple[tuple[float, float], ...]
    label: str = ""
    style_key: str = ""
    invalid_reason: str = ""


@dataclass(frozen=True)
class _RenderedOutput:
    payload: str | bytes
    rendered: tuple[_RenderFeature, ...]
    skipped: tuple[dict[str, str], ...]


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

    features = _normalize_render_features(result, boundary)
    svg_output = _render_svg(features, boundary, width, height)
    png_output = _render_png(features, boundary, width, height)
    svg_path.write_text(str(svg_output.payload), encoding="utf-8")
    png_path.write_bytes(bytes(png_output.payload))

    render_evidence = _render_evidence(features, svg_output, png_output)
    missing_basic_design = _missing_basic_design_ids(result, render_evidence)
    checks = _hard_validation_checks(result.validation)
    if result.validation.basic_design_checked and missing_basic_design:
        checks["basic_design"] = "fail"
    measurements = _layout_measurements(result)
    room_shapes = to_jsonable(result.validation.room_shapes)
    room_areas = to_jsonable(result.validation.room_areas)
    accepted = result.validation.accepted and not missing_basic_design
    needs_iteration = not accepted
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
        "accepted": accepted,
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
        "room_areas": room_areas,
        "validation": to_jsonable(result.validation),
        "render_evidence": render_evidence,
        "layer_completeness": _layer_completeness(render_evidence),
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
            f"F{floor['floor_index']} | "
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
      <div><h1>{html.escape(result.mass.project_id)}</h1><p>{len(floors)} floors | {result.total_area:g} total area</p></div>
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


def _normalize_render_features(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
) -> tuple[_RenderFeature, ...]:
    features: list[_RenderFeature] = []
    labels: list[_RenderFeature] = []
    basic_design = result.layout.basic_design
    if basic_design is not None:
        for line in basic_design.lines:
            layer = _line_layer(line)
            features.append(
                _RenderFeature(
                    line.line_id,
                    layer,
                    line.kind,
                    "polyline",
                    tuple(line.points),
                    _line_label(line),
                    line.category,
                )
            )
    for room in result.layout.rooms:
        points = tuple(room.polygon)
        features.append(
            _RenderFeature(
                room.room_id,
                "rooms",
                "room",
                "polygon",
                points,
                style_key=room.space_type,
            )
        )
        if _finite_points(points, minimum=3):
            area = _format_measurement(polygon_area(room.polygon))
            room_label = (
                f"{room.room_id}|{area} m2"
                if room.room_id == room.space_type
                else f"{room.room_id}|{room.space_type}|{area} m2"
            )
            labels.append(
                _RenderFeature(
                    f"{room.room_id}-label",
                    "text-labels",
                    "room-label",
                    "label",
                    (_centroid(points),),
                    room_label,
                )
            )
    labeled_circulation = (
        max(
            (
                path
                for path in result.layout.circulation
                if _finite_points(path.polygon, minimum=3)
            ),
            key=lambda path: polygon_area(path.polygon),
            default=None,
        )
    )
    for path in result.layout.circulation:
        points = tuple(path.polygon)
        features.append(
            _RenderFeature(
                path.room_id,
                "circulation",
                "circulation",
                "polygon",
                points,
                style_key=path.space_type,
            )
        )
        if path is labeled_circulation:
            labels.append(
                _RenderFeature(
                    f"{path.room_id}-label",
                    "text-labels",
                    "circulation",
                    "label",
                    (_circulation_label_point(points),),
                    path.space_type,
                )
            )
    features.append(
        _RenderFeature(
            "floor-boundary",
            "rooms",
            "boundary",
            "polygon",
            tuple(boundary),
        )
    )
    for opening in result.layout.openings:
        label = ""
        if isinstance(opening.clear_width, (int, float)) and math.isfinite(
            opening.clear_width
        ):
            label = f"{_format_measurement(opening.clear_width)} m"
        features.append(
            _RenderFeature(
                opening.opening_id,
                "door-openings",
                "door-opening",
                "polyline",
                (opening.start, opening.end),
                label,
                opening.connects[0] if opening.connects else "",
                "" if _is_renderable_opening(opening) else "non_finite_geometry",
            )
        )
        if _finite_points((opening.start, opening.end), minimum=2) and label:
            midpoint = (
                (opening.start[0] + opening.end[0]) / 2,
                (opening.start[1] + opening.end[1]) / 2,
            )
            host = next(
                (
                    room
                    for room in result.layout.rooms
                    if room.room_id == opening.connects[0]
                ),
                None,
            )
            label_point = (
                _offset_toward(midpoint, _centroid(host.polygon), 0.3)
                if host is not None and _finite_points(host.polygon, minimum=3)
                else midpoint
            )
            labels.append(
                _RenderFeature(
                    f"{opening.opening_id}-width-label",
                    "text-labels",
                    "door-width",
                    "label",
                    (label_point,),
                    label,
                )
            )
    if basic_design is not None:
        for element in basic_design.elements:
            layer = _element_layer(element)
            features.append(
                _RenderFeature(
                    element.element_id,
                    layer,
                    element.kind,
                    "polygon",
                    tuple(element.footprint),
                    style_key=element.category,
                )
            )
            if layer == "core" and _finite_points(element.footprint, minimum=3):
                labels.append(
                    _RenderFeature(
                        f"{element.element_id}-label",
                        "text-labels",
                        "core-label",
                        "label",
                        (_centroid(element.footprint),),
                        element.label or element.kind.upper(),
                    )
                )
    return tuple(
        feature
        for layer in LAYER_ORDER
        for feature in (*features, *labels)
        if feature.layer == layer
    )


def _element_layer(element: PlanElement) -> str:
    return {
        "vertical": "core",
        "structure": "structure",
        "furniture": "furniture",
        "fixture": "fixtures",
    }.get(element.category, element.category)


def _line_layer(line: PlanLine) -> str:
    if line.category == "structure":
        return "grid"
    if line.category == "envelope":
        return "envelope"
    if line.category == "egress":
        return "door-openings" if line.kind == "protected_exit" else "egress"
    if line.category in {"dimension", "site"}:
        return "dimensions"
    return line.category


def _line_label(line: PlanLine) -> str:
    if line.kind in {"egress_route", "window"}:
        return ""
    if line.kind == "protected_exit":
        suffix = line.line_id.rsplit("-", 1)[-1]
        width = (
            f" {_format_measurement(line.clear_width)}m"
            if line.clear_width is not None
            else ""
        )
        return f"EXIT {suffix}{width}"
    if line.kind == "scale_line" and line.measured_value is not None:
        return f"SCALE {_format_measurement(line.measured_value)}m"
    parts = [line.label] if line.label else []
    if line.measured_value is not None:
        parts.append(f"{_format_measurement(line.measured_value)} m")
    elif line.clear_width is not None:
        parts.append(f"{_format_measurement(line.clear_width)} m")
    return " ".join(parts)


def _render_svg(
    features: tuple[_RenderFeature, ...],
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
) -> _RenderedOutput:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(min_x, min_y, max_x, max_y, width, height)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    rendered: list[_RenderFeature] = []
    skipped: list[dict[str, str]] = []
    for layer in LAYER_ORDER:
        deferred_boundary = (
            next(
                (
                    feature
                    for feature in features
                    if feature.layer == "rooms" and feature.kind == "boundary"
                ),
                None,
            )
            if layer == "rooms"
            else None
        )
        layer_features = [
            feature
            for feature in features
            if feature.layer == layer and feature is not deferred_boundary
        ]
        if not layer_features:
            continue
        parts.append(f'<g data-layer="{html.escape(layer, quote=True)}">')
        for feature in layer_features:
            reason = _feature_skip_reason(feature)
            if reason is not None:
                skipped.append(_skip_record(feature, reason))
                continue
            try:
                parts.append(
                    _svg_feature(
                        feature,
                        min_x,
                        min_y,
                        scale,
                        pad_x,
                        pad_y,
                        height,
                    )
                )
            except (TypeError, ValueError, OverflowError):
                skipped.append(_skip_record(feature, "render_error"))
                continue
            rendered.append(feature)
        parts.append("</g>")
        if deferred_boundary is not None:
            reason = _feature_skip_reason(deferred_boundary)
            if reason is None:
                try:
                    parts.append(
                        _svg_feature(
                            deferred_boundary,
                            min_x,
                            min_y,
                            scale,
                            pad_x,
                            pad_y,
                            height,
                        )
                    )
                except (TypeError, ValueError, OverflowError):
                    skipped.append(_skip_record(deferred_boundary, "render_error"))
                else:
                    rendered.append(deferred_boundary)
            else:
                skipped.append(_skip_record(deferred_boundary, reason))
    parts.append("</svg>")
    return _RenderedOutput("\n".join(parts), tuple(rendered), tuple(skipped))


def _svg_feature(
    feature: _RenderFeature,
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    height: int,
) -> str:
    metadata = (
        f'data-id="{html.escape(feature.feature_id, quote=True)}" '
        f'data-kind="{html.escape(feature.kind, quote=True)}" '
        f'data-layer="{html.escape(feature.layer, quote=True)}"'
    )
    raster = [
        (
            _sx(x, min_x, scale, pad_x),
            _sy(y, min_y, scale, pad_y, height),
        )
        for x, y in feature.points
    ]
    if feature.geometry == "label":
        x, y = raster[0]
        rows = feature.label.split("|")
        if len(rows) == 1:
            return (
                f"<text {metadata} x=\"{x}\" y=\"{y}\" font-family=\"Arial\" "
                f'font-size="10" text-anchor="middle">'
                f"{html.escape(rows[0])}</text>"
            )
        tspans = "".join(
            f'<tspan x="{x}" dy="{0 if index == 0 else 12}">'
            f"{html.escape(row)}</tspan>"
            for index, row in enumerate(rows)
        )
        return (
            f"<text {metadata} x=\"{x}\" y=\"{y}\" font-family=\"Arial\" "
            f'font-size="10" text-anchor="middle">{tspans}</text>'
        )
    if feature.geometry == "polygon":
        points = " ".join(f"{x},{y}" for x, y in raster)
        fill, stroke, stroke_width = _svg_polygon_style(feature)
        return (
            f'<polygon {metadata} points="{points}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
    points = " ".join(f"{x},{y}" for x, y in raster)
    stroke, stroke_width, dash = _svg_line_style(feature)
    line = (
        f'<polyline points="{points}" fill="none" stroke="{stroke}" '
        f'stroke-width="{stroke_width}"{dash}/>'
    )
    label = ""
    if feature.label and feature.kind != "door-opening":
        x, y = _line_label_position(feature, raster)
        label = (
            f'<text x="{x}" y="{y}" font-family="Arial" font-size="9" '
            f'text-anchor="middle">{html.escape(feature.label)}</text>'
        )
    aria_label = ""
    if feature.kind == "door-opening":
        aria_label = (
            f' aria-label="{html.escape(feature.style_key, quote=True)} door '
            f'clear width {html.escape(feature.label, quote=True)}"'
        )
    return f"<g {metadata}{aria_label}>{line}{label}</g>"


def _svg_polygon_style(feature: _RenderFeature) -> tuple[str, str, int]:
    if feature.kind == "boundary":
        return "none", "#111111", 4
    if feature.layer == "rooms":
        return PALETTE.get(feature.style_key, "#eeeeee"), "#1f2933", 2
    if feature.layer == "circulation":
        return CIRCULATION_FILL, CIRCULATION_STROKE, 2
    if feature.layer == "core":
        return {
            "stair": "#f7d6d0",
            "elevator": "#d8d0e8",
            "lobby": "#e7e9ec",
            "shaft": "#c9cdd2",
        }.get(feature.kind, "#e7e9ec"), "#28323c", 2
    if feature.layer == "structure":
        return "#424b54", "#111111", 2
    if feature.layer == "furniture":
        return "#f2e2b8", "#5d4a1f", 1
    if feature.layer == "fixtures":
        return "#bfe3df", "#155d58", 1
    return "none", "#333333", 1


def _svg_line_style(feature: _RenderFeature) -> tuple[str, int, str]:
    if feature.layer == "grid":
        return "#aeb7bf", 1, ' stroke-dasharray="5 5"'
    if feature.layer == "envelope":
        return ("#0b6e99", 6, "") if feature.kind == "window" else (
            "#0087a8",
            8,
            "",
        )
    if feature.layer == "door-openings":
        return DOOR_STROKE, 4, ""
    if feature.layer == "egress":
        return "#2e7d32", 2, ' stroke-dasharray="8 5"'
    if feature.layer == "dimensions":
        return "#a34813", 2, ' stroke-dasharray="4 3"'
    return "#333333", 2, ""


def _render_png(
    features: tuple[_RenderFeature, ...],
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
) -> _RenderedOutput:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(min_x, min_y, max_x, max_y, width, height)
    canvas = SimplePngCanvas(width, height)
    rendered: list[_RenderFeature] = []
    skipped: list[dict[str, str]] = []
    for feature in features:
        reason = _feature_skip_reason(feature)
        if reason is not None:
            skipped.append(_skip_record(feature, reason))
            continue
        try:
            _png_feature(
                canvas,
                feature,
                min_x,
                min_y,
                scale,
                pad_x,
                pad_y,
                height,
            )
        except (TypeError, ValueError, OverflowError):
            skipped.append(_skip_record(feature, "render_error"))
            continue
        rendered.append(feature)
    return _RenderedOutput(canvas.to_bytes(), tuple(rendered), tuple(skipped))


def _png_feature(
    canvas: SimplePngCanvas,
    feature: _RenderFeature,
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    height: int,
) -> None:
    points = _raster_points(
        feature.points,
        min_x,
        min_y,
        scale,
        pad_x,
        pad_y,
        height,
    )
    if feature.geometry == "label":
        rows = feature.label.split("|")
        x, y = points[0]
        for index, row in enumerate(rows[:3]):
            label = _bounded_ascii(row, 18)
            origin = (x - len(label) * 3, y - 8 + index * 8)
            canvas.draw_text(label, origin, (25, 30, 35))
        return
    if feature.geometry == "polygon":
        fill, stroke, thickness = _png_polygon_style(feature)
        if fill is not None:
            canvas.fill_polygon(points, fill)
        canvas.stroke_polygon(points, stroke, thickness=thickness)
        return
    color, thickness, dashed = _png_line_style(feature)
    if feature.layer == "door-openings":
        canvas.stroke_polyline(points, (255, 255, 255), thickness=8)
    if dashed:
        canvas.stroke_dashed_polyline(
            points,
            color,
            thickness=thickness,
            dash_length=7,
            gap_length=5,
        )
    else:
        canvas.stroke_polyline(points, color, thickness=thickness)
    if feature.layer == "door-openings" and len(points) == 2:
        _draw_door_jambs(canvas, points[0], points[1])
    if feature.kind in {"egress_route", "north_arrow"} and len(points) >= 2:
        canvas.draw_arrowhead(points[-1], points[-2], color, size=6, thickness=1)
    if feature.label and feature.kind != "door-opening":
        x, y = _line_label_position(feature, points)
        label = _bounded_ascii(feature.label, 14)
        text_width = len(label) * 6
        origin_x = max(2, min(canvas.width - text_width - 2, round(x - text_width / 2)))
        origin_y = max(2, min(canvas.height - 9, round(y - 4)))
        canvas.draw_text(label, (origin_x, origin_y), color)


def _png_polygon_style(
    feature: _RenderFeature,
) -> tuple[tuple[int, int, int] | None, tuple[int, int, int], int]:
    if feature.kind == "boundary":
        return None, (15, 18, 20), 4
    if feature.layer == "rooms":
        return PNG_PALETTE.get(feature.style_key, (238, 238, 238)), (31, 41, 51), 2
    if feature.layer == "circulation":
        return PNG_CIRCULATION_FILL, PNG_CIRCULATION_STROKE, 2
    if feature.layer == "core":
        return {
            "stair": (247, 214, 208),
            "elevator": (216, 208, 232),
            "lobby": (231, 233, 236),
            "shaft": (201, 205, 210),
        }.get(feature.kind, (231, 233, 236)), (40, 50, 60), 2
    if feature.layer == "structure":
        return (66, 75, 84), (17, 17, 17), 2
    if feature.layer == "furniture":
        return (242, 226, 184), (93, 74, 31), 1
    if feature.layer == "fixtures":
        return (191, 227, 223), (21, 93, 88), 1
    return None, (51, 51, 51), 1


def _png_line_style(
    feature: _RenderFeature,
) -> tuple[tuple[int, int, int], int, bool]:
    if feature.layer == "grid":
        return (174, 183, 191), 1, True
    if feature.layer == "envelope":
        return (11, 110, 153), 6 if feature.kind == "window" else 8, False
    if feature.layer == "door-openings":
        return PNG_DOOR_STROKE, 4, False
    if feature.layer == "egress":
        return (46, 125, 50), 2, True
    if feature.layer == "dimensions":
        return (163, 72, 19), 2, True
    return (51, 51, 51), 2, False


def _feature_skip_reason(feature: _RenderFeature) -> str | None:
    if feature.invalid_reason:
        return feature.invalid_reason
    if feature.layer not in LAYER_ORDER:
        return "unsupported_layer"
    minimum = 3 if feature.geometry == "polygon" else 1 if feature.geometry == "label" else 2
    if feature.geometry not in {"polygon", "polyline", "label"}:
        return "unsupported_geometry"
    if not _finite_points(feature.points, minimum=minimum):
        return "non_finite_geometry"
    return None


def _finite_points(
    points: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    *,
    minimum: int,
) -> bool:
    try:
        return len(points) >= minimum and all(
            len(point) == 2
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in point
            )
            for point in points
        )
    except (TypeError, ValueError):
        return False


def _skip_record(feature: _RenderFeature, reason: str) -> dict[str, str]:
    return {
        "id": feature.feature_id,
        "kind": feature.kind,
        "layer": feature.layer,
        "reason": reason,
    }


def _render_evidence(
    modeled: tuple[_RenderFeature, ...],
    svg_output: _RenderedOutput,
    png_output: _RenderedOutput,
) -> dict:
    modeled_groups = _group_feature_ids(modeled)
    svg_groups = _group_feature_ids(svg_output.rendered)
    png_groups = _group_feature_ids(png_output.rendered)
    return {
        "modeled": modeled_groups,
        "svg": svg_groups,
        "png": png_groups,
        "skipped": {
            "svg": list(svg_output.skipped),
            "png": list(png_output.skipped),
        },
        "missing": {
            "svg": _missing_groups(modeled_groups, svg_groups),
            "png": _missing_groups(modeled_groups, png_groups),
        },
    }


def _group_feature_ids(features: tuple[_RenderFeature, ...]) -> dict:
    grouped: dict[str, dict[str, list[str]]] = {}
    for feature in features:
        grouped.setdefault(feature.layer, {}).setdefault(feature.kind, []).append(
            feature.feature_id
        )
    return {
        layer: {
            kind: sorted(identifiers)
            for kind, identifiers in sorted(kinds.items())
        }
        for layer, kinds in grouped.items()
    }


def _missing_groups(modeled: dict, rendered: dict) -> dict:
    missing: dict[str, dict[str, list[str]]] = {}
    for layer, kinds in modeled.items():
        for kind, identifiers in kinds.items():
            absent = sorted(set(identifiers) - set(rendered.get(layer, {}).get(kind, [])))
            if absent:
                missing.setdefault(layer, {})[kind] = absent
    return missing


def _missing_basic_design_ids(result: GenerationResult, evidence: dict) -> set[str]:
    if not result.validation.basic_design_checked or result.layout.basic_design is None:
        return set()
    required = {
        *(element.element_id for element in result.layout.basic_design.elements),
        *(line.line_id for line in result.layout.basic_design.lines),
    }
    missing = set()
    for output in ("svg", "png"):
        missing.update(
            identifier
            for kinds in evidence["missing"][output].values()
            for identifiers in kinds.values()
            for identifier in identifiers
            if identifier in required
        )
    return missing


def _layer_completeness(evidence: dict) -> dict[str, dict[str, int]]:
    completeness = {}
    for layer, kinds in evidence["modeled"].items():
        completeness[layer] = {
            output: sum(
                len(identifiers)
                for identifiers in evidence[output].get(layer, {}).values()
            )
            for output in ("modeled", "svg", "png")
        }
    return completeness


def _bounded_ascii(value: str, limit: int) -> str:
    return "".join(
        character if 32 <= ord(character) <= 126 else "?"
        for character in value
    )[:limit]


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
    area_by_room_id = {
        metric["room_id"]: metric["actual_area"] for metric in report["room_areas"]
    }
    room_form_rows = "".join(
        "<tr>"
        f'<th scope="row">{html.escape(shape["room_id"])}</th>'
        f"<td>{_display_measurement(area_by_room_id.get(shape['room_id']))}</td>"
        f"<td>{_display_measurement(shape['measured_min_width'])}</td>"
        f"<td>{_display_measurement(shape['measured_aspect_ratio'])}</td>"
        f"<td>{_display_measurement(shape['required_min_width'])}</td>"
        f"<td>{_display_measurement(shape['maximum_aspect_ratio'])}</td>"
        "</tr>"
        for shape in report["room_shapes"]
    )
    basic_design_present = result.layout.basic_design is not None
    control_labels = {
        "grid": "Grid",
        "rooms": "Rooms",
        "circulation": "Circulation",
        "core": "Core",
        "structure": "Structure",
        "envelope": "Envelope",
        "door-openings": "Doors",
        "furniture": "Furniture",
        "fixtures": "Fixtures",
        "egress": "Egress",
        "dimensions": "Dimensions / site",
        "text-labels": "Labels",
    }
    controls = "".join(
        (
            f'<button type="button" data-layer="{layer}" aria-pressed="true"'
            + (
                ' disabled aria-disabled="true"'
                if layer in _BASIC_DESIGN_LAYERS and not basic_design_present
                else ""
            )
            + f">{html.escape(control_labels[layer])}</button>"
        )
        for layer in LAYER_ORDER
    )
    completeness_rows = "".join(
        f'<tr><th scope="row">{html.escape(layer)}</th>'
        f'<td>{counts["modeled"]}</td><td>{counts["svg"]}</td>'
        f'<td>{counts["png"]}</td></tr>'
        for layer, counts in report["layer_completeness"].items()
    )
    project_id = html.escape(result.mass.project_id)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="icon" href="data:,">
  <title>{project_id} floor visual review</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ max-width: 100%; overflow-x: hidden; }}
    body {{ margin: 24px; font-family: Arial, sans-serif; background: white; color: #111; }}
    main {{ max-width: 1180px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .status {{ margin-bottom: 18px; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); gap: 20px; align-items: start; }}
    .plan {{ min-width: 0; }}
    iframe {{ width: 100%; aspect-ratio: 16 / 9; height: auto; border: 1px solid #ccc; }}
    #working-layer-controls {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 12px; }}
    #working-layer-controls button {{ min-height: 32px; padding: 5px 9px; }}
    #working-layer-controls button[disabled] {{ opacity: 0.45; cursor: not-allowed; }}
    table {{ border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }}
    thead, tbody {{ white-space: nowrap; }}
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
          {controls}
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
          <thead><tr><th scope="col">Room</th><th scope="col">Area m2</th><th scope="col">Width m</th><th scope="col">Aspect</th><th scope="col">Min width</th><th scope="col">Max aspect</th></tr></thead>
          <tbody>{room_form_rows}</tbody>
        </table>
        <h2>Render Completeness</h2>
        <table id="render-completeness">
          <thead><tr><th scope="col">Layer</th><th scope="col">Modeled</th><th scope="col">SVG</th><th scope="col">PNG</th></tr></thead>
          <tbody>{completeness_rows}</tbody>
        </table>
        <p><a href="{html.escape(png_name, quote=True)}">PNG</a></p>
        <p><a href="{html.escape(report_name, quote=True)}">Review JSON</a></p>
      </section>
    </div>
  </main>
  <script>
    const frame = document.getElementById("floor-plan");
    const controls = document.querySelectorAll("#working-layer-controls button");
    function synchronizeLayers() {{
      const documentRoot = frame.contentDocument;
      if (!documentRoot) return;
      controls.forEach((button) => {{
        const visible = button.getAttribute("aria-pressed") === "true";
        documentRoot.querySelectorAll(`[data-layer="${{button.dataset.layer}}"]`).forEach((node) => {{
          node.style.display = visible ? "" : "none";
        }});
      }});
    }}
    frame.addEventListener("load", synchronizeLayers);
    controls.forEach((button) => {{
      button.addEventListener("click", () => {{
        if (button.disabled) return;
        const pressed = button.getAttribute("aria-pressed") === "true";
        button.setAttribute("aria-pressed", String(!pressed));
        synchronizeLayers();
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


def _circulation_label_point(
    points: tuple[tuple[float, float], ...],
) -> tuple[float, float]:
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    if max_x - min_x >= max_y - min_y:
        return (min_x + (max_x - min_x) * 0.18, (min_y + max_y) / 2)
    return ((min_x + max_x) / 2, min_y + (max_y - min_y) * 0.82)


def _line_label_position(
    feature: _RenderFeature,
    points: list[tuple[int | float, int | float]],
) -> tuple[float, float]:
    midpoint_x = sum(point[0] for point in points) / len(points)
    midpoint_y = sum(point[1] for point in points) / len(points)
    if feature.kind == "grid":
        if abs(points[0][0] - points[-1][0]) < abs(
            points[0][1] - points[-1][1]
        ):
            return points[0][0], max(point[1] for point in points) + 12
        return min(point[0] for point in points) - 12, points[0][1]
    if feature.kind == "overall_width":
        return midpoint_x, midpoint_y - 30
    if feature.kind == "street":
        return midpoint_x, midpoint_y + 28
    if feature.kind in {"entrance", "scale_line"}:
        return midpoint_x, midpoint_y - 14
    if feature.kind == "overall_depth":
        return midpoint_x + 30, midpoint_y
    return midpoint_x, midpoint_y - 8


def _offset_toward(
    start: tuple[float, float],
    target: tuple[float, float],
    distance: float,
) -> tuple[float, float]:
    delta_x = target[0] - start[0]
    delta_y = target[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length == 0:
        return start
    return (
        start[0] + delta_x / length * distance,
        start[1] + delta_y / length * distance,
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
    if not validation.basic_design_checked:
        checks["basic_design"] = "not_checked"
    else:
        checks["basic_design"] = (
            "fail"
            if violation_codes & _BASIC_DESIGN_VIOLATION_CODES
            else "pass"
        )
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

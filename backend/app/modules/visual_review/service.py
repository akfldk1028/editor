from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import (
    _street_segments,
    assign_floors_from_use_mix,
    build_floor_design_evidence,
    run_building_generation,
    run_candidate_search,
)
from backend.app.modules.llm_planner.service import plan_floor_assignments
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.llm import FloorAssignment, SUPPORTED_USE_TYPES
from backend.app.schemas.loop import CandidateRecord, LoopConfig
from backend.app.schemas.layout import (
    DoorSwing,
    OpeningSegment,
    PlanElement,
    PlanLine,
    StairGeometry,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph
from backend.app.schemas.result import (
    BuildingGenerationResult,
    GenerationResult,
    PlannerProvenance,
)
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
LAYER_DISPLAY = {
    "grid": ("그리드", "#8b95a1"),
    "rooms": ("공간", "#c9dcf0"),
    "circulation": ("복도·동선", "#79a96b"),
    "core": ("코어", "#d68179"),
    "structure": ("구조", "#343a40"),
    "envelope": ("외벽·창호", "#176b87"),
    "door-openings": ("문", "#1464a5"),
    "furniture": ("가구", "#c79c3c"),
    "fixtures": ("설비", "#3d948c"),
    "egress": ("피난", "#36864a"),
    "dimensions": ("치수·대지", "#b45f24"),
    "text-labels": ("문자", "#24282d"),
}
RENDER_STYLES = {"review", "architectural"}
ARCHITECTURAL_FONT_STACK = "Noto Sans KR, Malgun Gothic, sans-serif"
ARCHITECTURAL_LABELS = {
    "shop_unit": "상가",
    "office_area": "사무공간",
    "open_work": "업무공간",
    "meeting": "회의실",
    "reception": "접수",
    "focus": "집중업무실",
    "it_storage": "전산·창고",
    "sales": "판매공간",
    "checkout": "계산대",
    "stock": "창고",
    "staff": "직원실",
    "restroom": "화장실",
    "storage": "창고",
    "utility": "설비실",
    "pantry": "탕비실",
    "ps_eps": "PS·EPS",
    "core": "코어",
    "circulation": "복도",
    "stair": "계단실",
    "elevator": "승강기",
    "lobby": "로비",
    "shaft": "샤프트",
}
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
    stair_geometry: StairGeometry | None = None
    door_swing: DoorSwing | None = None


@dataclass(frozen=True)
class _RenderedOutput:
    payload: str | bytes
    rendered: tuple[_RenderFeature, ...]
    skipped: tuple[dict[str, str], ...]
    metadata: dict[str, object] = field(default_factory=dict)


def create_building_visual_review_artifacts(
    result: BuildingGenerationResult,
    boundary: list[tuple[float, float]],
    output_dir: str | Path,
    width: int = 960,
    height: int = 540,
    *,
    render_style: str = "review",
) -> BuildingVisualReviewArtifacts:
    _validate_render_style(render_style)
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
            render_style=render_style,
        )
        floor_artifacts.append(artifacts)
        floor_reports.append(
            {
                "floor_index": floor.program.floor_index,
                "use_type": floor.program.use_type,
                "program_source": floor.program.source,
                "program_adjusted": _program_was_adjusted(floor.program),
                "program_adjustments": to_jsonable(floor.program.adjustments),
                "accepted": not artifacts.needs_iteration,
                "internal_validation": {
                    "status": (
                        "pass" if floor.validation.accepted else "fail"
                    ),
                    "policy_version": floor.validation.policy_version,
                },
                "render_validation": {
                    "status": artifacts.render_validation["status"],
                },
                "regulatory_screening": _regulatory_screening_payload(
                    floor.validation
                ),
                "area_ledger": to_jsonable(floor.area_ledger),
                "egress_graph": to_jsonable(floor.egress_graph),
                "room_count": len(floor.layout.rooms),
                "artifacts": artifacts.artifact_links,
            }
        )

    report_path = target / "building.review.json"
    index_html_path = target / "index.html"
    render_accepted = all(
        artifact.render_validation["status"] == "pass"
        for artifact in floor_artifacts
    )
    internal_validation = {
        "status": "pass" if result.accepted else "fail",
    }
    render_validation = {
        "status": "pass" if render_accepted else "fail",
    }
    regulatory_screening = _aggregate_regulatory_screening(floor_reports)
    building_accepted = (
        result.accepted
        and render_accepted
        and regulatory_screening["status"] != "fail"
    )
    report = {
        "schema_version": 1,
        "project_id": result.mass.project_id,
        "accepted": building_accepted,
        "internal_validation": internal_validation,
        "render_validation": render_validation,
        "regulatory_screening": regulatory_screening,
        "assignment_source": result.assignment_source,
        "vertical_core_aligned": result.vertical_core_aligned,
        "vertical_basic_design_aligned": result.vertical_basic_design_aligned,
        "vertical_structure_aligned": result.vertical_structure_aligned,
        "planner_provenance": to_jsonable(result.planner_provenance),
        "render_style": render_style,
        "total_area": result.total_area,
        "use_type_areas": result.use_type_areas,
        "area_ledger": to_jsonable(result.area_ledger),
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
        accepted=building_accepted,
        internal_validation=internal_validation,
        render_validation=render_validation,
        regulatory_screening=regulatory_screening,
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
    render_style: str = "review",
) -> VisualReviewArtifacts:
    if width <= 0 or height <= 0:
        raise ValueError("viewport width and height must be positive")
    _validate_render_style(render_style)

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
    svg_output = _render_svg(
        features,
        boundary,
        width,
        height,
        render_style=render_style,
    )
    png_output = _render_png(
        features,
        boundary,
        width,
        height,
        render_style=render_style,
    )
    svg_payload = str(svg_output.payload)
    svg_path.write_text(svg_payload, encoding="utf-8")
    png_path.write_bytes(bytes(png_output.payload))

    render_evidence = _render_evidence(features, svg_output, png_output)
    missing_basic_design = _missing_basic_design_ids(result, render_evidence)
    checks = _hard_validation_checks(result.validation)
    if result.validation.basic_design_checked and missing_basic_design:
        checks["basic_design"] = "fail"
    unresolved_label_collisions = int(
        png_output.metadata.get("unresolved_collision_count", 0)
    )
    if render_style == "architectural":
        checks["label_overlap"] = (
            "pass" if unresolved_label_collisions == 0 else "fail"
        )
    measurements = _layout_measurements(result)
    room_shapes = to_jsonable(result.validation.room_shapes)
    room_areas = to_jsonable(result.validation.room_areas)
    render_passed = (
        not missing_basic_design
        and (
            render_style != "architectural"
            or unresolved_label_collisions == 0
        )
    )
    regulatory_screening = _regulatory_screening_payload(
        result.validation
    )
    accepted = (
        result.validation.accepted
        and render_passed
        and regulatory_screening["status"] != "fail"
    )
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
        "program_source": result.program.source,
        "program_adjusted": _program_was_adjusted(result.program),
        "program_adjustments": to_jsonable(result.program.adjustments),
        "render_style": render_style,
        "png_text": png_output.metadata,
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
        "internal_validation": {
            "status": (
                "pass" if result.validation.accepted else "fail"
            ),
            "policy_version": result.validation.policy_version,
        },
        "render_validation": {
            "status": "pass" if render_passed else "fail",
            "missing_basic_design_ids": list(missing_basic_design),
            "unresolved_label_collision_count": unresolved_label_collisions,
        },
        "regulatory_screening": regulatory_screening,
        "area_ledger": to_jsonable(result.area_ledger),
        "egress_graph": to_jsonable(result.egress_graph),
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
        "stair_evidence": _stair_evidence(result),
        "artifacts": artifact_links,
    }
    status_text = (
        f"internal={report['internal_validation']['status']}  "
        f"render={report['render_validation']['status']}  "
        f"regulatory={report['regulatory_screening']['status']}"
    )
    svg_status = (
        f'<g data-review-status="{html.escape(status_text, quote=True)}">'
        f'<rect x="0" y="{height}" width="{width}" height="30" '
        'fill="white" fill-opacity="0.92"/>'
        f'<text x="14" y="{height + 19}" font-family="Arial" font-size="10" '
        f'fill="#333333">{html.escape(status_text)}</text></g>'
    )
    svg_payload = svg_payload.replace(
        f'viewBox="0 0 {width} {height}"',
        f'viewBox="0 0 {width} {height + 30}"',
    ).replace("</svg>", f"{svg_status}</svg>")
    svg_path.write_text(svg_payload, encoding="utf-8")
    report["status_footer"] = {
        "svg": "rendered",
        "png": "unavailable",
        "text": status_text,
        "svg_output_size": [width, height + 30],
        "png_output_size": [width, height],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    html_path.write_text(
        _render_html(
            result,
            svg_payload=svg_payload,
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
        internal_validation=report["internal_validation"],
        render_validation=report["render_validation"],
        regulatory_screening=report["regulatory_screening"],
    )


def _stair_evidence(result: GenerationResult) -> list[dict[str, object]]:
    basic_design = result.layout.basic_design
    if basic_design is None:
        return []
    return [
        {
            "element_id": element.element_id,
            "stair_geometry": to_jsonable(element.stair_geometry),
            "height_provenance": element.stair_geometry.height_source,
            "headroom_status": element.stair_geometry.headroom_status,
        }
        for element in basic_design.elements
        if element.kind == "stair" and element.stair_geometry is not None
    ]


def _validate_render_style(render_style: str) -> None:
    if render_style not in RENDER_STYLES:
        supported = ", ".join(sorted(RENDER_STYLES))
        raise ValueError(f"unsupported render style: {render_style}; expected {supported}")


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
        internal_status = floor["internal_validation"]["status"]
        render_status = floor["render_validation"]["status"]
        regulatory_status = floor["regulatory_screening"]["status"].replace(
            "_",
            " ",
        )
        status = (
            f"internal concept validation: {internal_status} | "
            f"render validation: {render_status} | "
            f"regulatory screening: {regulatory_status}"
        )
        if floor["program_adjusted"]:
            status += " | program adjusted"
        floor_sections.append(
            f"""
            <section>
              <header><h2>{title}</h2><span>{status} | {floor['room_count']} rooms</span></header>
              <a href="{review}"><img src="{png}" alt="{title} floor plan"></a>
            </section>
            """
        )
    internal_status = "pass" if result.accepted else "fail"
    render_status = (
        "pass"
        if all(floor["render_validation"]["status"] == "pass" for floor in floors)
        else "fail"
    )
    regulatory_status = _aggregate_regulatory_screening(floors)[
        "status"
    ].replace("_", " ")
    status = (
        f"internal concept validation: {internal_status} | "
        f"render validation: {render_status} | "
        f"regulatory screening: {regulatory_status}"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{html.escape(result.mass.project_id)} building review</title>
  <style>
    :root {{ font-family: "Noto Sans KR", "Malgun Gothic", Inter, Segoe UI, sans-serif; color: #17232f; background: #f4f6f8; }}
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
    review_level: str = "concept-basic",
    planner_client: object | None = None,
) -> VisualReviewLoopResult:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    if review_level not in {"concept-basic", "zoning"}:
        raise ValueError("review_level must be 'concept-basic' or 'zoning'")
    if review_level == "zoning" and planner_client is not None:
        raise ValueError("planner is only supported for concept-basic review")

    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if review_level == "concept-basic":
        return _run_concept_basic_review(
            mass,
            floor_index=floor_index,
            use_type=use_type,
            target=target,
            planner_client=planner_client,
        )

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
        area_ledger, egress_graph = build_floor_design_evidence(
            layout=candidate.layout,
            program=search.program,
            boundary=mass.footprint_polygon,
        )
        validation = validate_layout(
            candidate.layout,
            search.program,
            boundary=mass.footprint_polygon,
            street_segments=_street_segments(mass),
            building_code_context=mass.building_code_context,
            egress_graph=egress_graph,
        )
        result = GenerationResult(
            mass=search.mass,
            program=search.program,
            layout=candidate.layout,
            validation=validation,
            area_ledger=area_ledger,
            egress_graph=egress_graph,
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
        report = json.loads(review.report_path.read_text(encoding="utf-8"))
        report["review_level"] = "zoning"
        report["unchecked_checks"] = sorted(
            name
            for name, status in report["checks"].items()
            if status == "not_checked"
        )
        review.report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        reports.append(report)
        previous_validation = validation

    index = _review_index(search, reports, review_level="zoning")
    index_json_path, index_html_path = _write_review_index(target, index)
    unchecked_checks = tuple(index["unchecked_checks"])

    return VisualReviewLoopResult(
        iterations_run=len(artifacts),
        final_needs_iteration=index["needs_iteration"],
        artifacts=artifacts,
        index_json_path=index_json_path,
        index_html_path=index_html_path,
        termination_reason=search.termination_reason,
        evaluation_count=search.evaluation_count,
        accepted=index["accepted"],
        error=search.error,
        review_level="zoning",
        unchecked_checks=unchecked_checks,
        internal_validation=index["internal_validation"],
        render_validation=index["render_validation"],
        regulatory_screening=index["regulatory_screening"],
    )


def _run_concept_basic_review(
    mass: MassInput,
    *,
    floor_index: int,
    use_type: str,
    target: Path,
    planner_client: object | None,
) -> VisualReviewLoopResult:
    if floor_index < 1 or floor_index > mass.floors:
        raise ValueError("floor_index must identify a floor in the building")
    if use_type not in SUPPORTED_USE_TYPES:
        raise ValueError(f"unsupported use type: {use_type}")

    assignments: tuple[FloorAssignment, ...] = ()
    planner_provenance = _review_planner_provenance(planner_client, assignments)
    try:
        if planner_client is None:
            assignments = tuple(
                FloorAssignment(
                    assignment.floor_index,
                    (
                        use_type
                        if assignment.floor_index == floor_index
                        else assignment.use_type
                    ),
                )
                for assignment in assign_floors_from_use_mix(mass)
            )
            planner_provenance = _review_planner_provenance(None, assignments)
        else:
            plan = plan_floor_assignments(mass, planner_client)
            assignments = plan.assignments
            planner_provenance = _review_planner_provenance(
                planner_client, assignments
            )
        building = run_building_generation(
            mass,
            floor_assignments=assignments,
            planner_provenance=planner_provenance,
        )
        selected = next(
            floor
            for floor in building.floor_results
            if floor.program.floor_index == floor_index
        )
        if selected.program.use_type != use_type:
            raise ValueError(
                "planner assignment does not match requested floor/use type"
            )
    except Exception as error:
        planner_provenance = _review_planner_provenance(
            planner_client, assignments
        )
        message = f"{type(error).__name__}: {error}"
        index = {
            "schema_version": 1,
            "project_id": mass.project_id,
            "floor_index": floor_index,
            "use_type": use_type,
            "review_level": "concept-basic",
            "accepted": False,
            "needs_iteration": True,
            "internal_validation": {"status": "fail"},
            "render_validation": {"status": "fail"},
            "regulatory_screening": {
                "status": "not_checked",
                "unresolved_facts": ["generation_failed"],
            },
            "termination_reason": "failed",
            "evaluation_count": 1,
            "error": message,
            "unchecked_checks": [],
            "iterations": [],
            "score_trend": [],
            "hard_failure_trend": [],
            "lineage": [],
            "planner_provenance": to_jsonable(planner_provenance),
        }
        index_json_path, index_html_path = _write_review_index(target, index)
        return VisualReviewLoopResult(
            iterations_run=0,
            final_needs_iteration=True,
            artifacts=[],
            index_json_path=index_json_path,
            index_html_path=index_html_path,
            termination_reason="failed",
            evaluation_count=1,
            accepted=False,
            error=message,
            review_level="concept-basic",
            planner_provenance=planner_provenance,
            internal_validation=index["internal_validation"],
            render_validation=index["render_validation"],
            regulatory_screening=index["regulatory_screening"],
        )

    floor = next(
        floor
        for floor in building.floor_results
        if floor.program.floor_index == floor_index
    )
    artifact = create_visual_review_artifacts(
        floor,
        boundary=mass.footprint_polygon,
        output_dir=target / "iteration_001",
        iteration_number=1,
        run_root=target,
    )
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    report["review_level"] = "concept-basic"
    report["planner_provenance"] = to_jsonable(building.planner_provenance)
    artifact.report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    required_checks = ("openings", "corridor_width", "basic_design")
    strict_checks_pass = all(
        report["checks"].get(name) == "pass" for name in required_checks
    )
    unchecked_checks = tuple(
        sorted(
            name
            for name, status in report["checks"].items()
            if status == "not_checked"
        )
    )
    accepted = (
        building.accepted
        and strict_checks_pass
        and not unchecked_checks
        and report["regulatory_screening"]["status"] != "fail"
    )
    termination_reason = "accepted" if accepted else "strict_validation_failed"
    iteration = {
        "iteration": 1,
        "candidate_id": report["candidate_id"],
        "fingerprint": None,
        "parent_id": None,
        "operator": "concept-basic-generation",
        "operator_params": {},
        "accepted": accepted,
        "needs_iteration": not accepted,
        "internal_validation": report["internal_validation"],
        "render_validation": report["render_validation"],
        "regulatory_screening": report["regulatory_screening"],
        "hard_failure_count": report["hard_failure_count"],
        "violations": report["violations"],
        "scores": report["scores"],
        "checks": report["checks"],
        "program_source": report["program_source"],
        "program_adjusted": report["program_adjusted"],
        "total_score_delta": None,
        "hard_failure_count_delta": None,
        "artifacts": report["artifacts"],
    }
    index = {
        "schema_version": 1,
        "project_id": mass.project_id,
        "floor_index": floor_index,
        "use_type": use_type,
        "review_level": "concept-basic",
        "accepted": accepted,
        "needs_iteration": not accepted,
        "internal_validation": report["internal_validation"],
        "render_validation": report["render_validation"],
        "regulatory_screening": report["regulatory_screening"],
        "termination_reason": termination_reason,
        "evaluation_count": 1,
        "error": None,
        "unchecked_checks": list(unchecked_checks),
        "vertical_core_aligned": building.vertical_core_aligned,
        "vertical_basic_design_aligned": building.vertical_basic_design_aligned,
        "vertical_structure_aligned": building.vertical_structure_aligned,
        "planner_provenance": to_jsonable(building.planner_provenance),
        "program_source": report["program_source"],
        "program_adjusted": report["program_adjusted"],
        "iterations": [iteration],
        "score_trend": [iteration["scores"]["total_score"]],
        "hard_failure_trend": [iteration["hard_failure_count"]],
        "lineage": [
            {
                "candidate_id": iteration["candidate_id"],
                "parent_id": None,
                "operator": iteration["operator"],
                "operator_params": {},
            }
        ],
    }
    index_json_path, index_html_path = _write_review_index(target, index)
    return VisualReviewLoopResult(
        iterations_run=1,
        final_needs_iteration=not accepted,
        artifacts=[artifact],
        index_json_path=index_json_path,
        index_html_path=index_html_path,
        termination_reason=termination_reason,
        evaluation_count=1,
        accepted=accepted,
        error=None,
        review_level="concept-basic",
        unchecked_checks=unchecked_checks,
        planner_provenance=building.planner_provenance,
        internal_validation=index["internal_validation"],
        render_validation=index["render_validation"],
        regulatory_screening=index["regulatory_screening"],
    )


def _program_was_adjusted(program: ProgramGraph) -> bool:
    return bool(program.adjustments)


def _adjustment_display_by_room(
    adjustments: list[dict],
) -> dict[str, dict[str, object]]:
    display: dict[str, dict[str, object]] = {}
    for adjustment in adjustments:
        reason = str(adjustment.get("reason", ""))
        original_targets = adjustment.get("original_targets", [])
        adjusted_targets = adjustment.get("adjusted_targets", [])
        for room_id, value in original_targets:
            record = display.setdefault(
                str(room_id),
                {"original": value, "adjusted": value, "reasons": []},
            )
            record.setdefault("original", value)
        for room_id, value in adjusted_targets:
            record = display.setdefault(
                str(room_id),
                {"original": value, "adjusted": value, "reasons": []},
            )
            record["adjusted"] = value
            reasons = record["reasons"]
            if reason and reason not in reasons:
                reasons.append(reason)
    return display


def _review_planner_provenance(
    planner_client: object | None,
    assignments: tuple[FloorAssignment, ...],
) -> PlannerProvenance:
    if planner_client is None:
        return PlannerProvenance(
            planner_mode="deterministic",
            provider="deterministic",
            model=None,
            response_id=None,
            validated_assignments=assignments,
        )
    return PlannerProvenance(
        planner_mode="structured",
        provider=_nonempty_string(
            getattr(planner_client, "provider", None)
        ) or "manual",
        model=_nonempty_string(getattr(planner_client, "model", None)),
        response_id=_nonempty_string(
            getattr(planner_client, "last_response_id", None)
        ),
        validated_assignments=assignments,
    )


def _nonempty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _write_review_index(target: Path, index: dict) -> tuple[Path, Path]:
    index_json_path = target / "review.index.json"
    index_html_path = target / "index.html"
    _ensure_within_target(target, index_json_path, index_html_path)
    index_json_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    index_html_path.write_text(_render_index_html(index), encoding="utf-8")
    return index_json_path, index_html_path


def _review_index(search, reports: list[dict], *, review_level: str) -> dict:
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
            "internal_validation": report["internal_validation"],
            "render_validation": report["render_validation"],
            "regulatory_screening": report["regulatory_screening"],
            "hard_failure_count": report["hard_failure_count"],
            "violations": report["violations"],
            "scores": report["scores"],
            "checks": report["checks"],
            "total_score_delta": report["total_score_delta"],
            "hard_failure_count_delta": report["hard_failure_count_delta"],
            "artifacts": report["artifacts"],
        }
        for report in reports
    ]
    final_report = reports[-1] if reports else None
    final_accepted = bool(
        final_report is not None and final_report["accepted"]
    )
    return {
        "schema_version": 1,
        "project_id": search.mass.project_id,
        "floor_index": search.program.floor_index,
        "use_type": search.program.use_type,
        "review_level": review_level,
        "accepted": final_accepted,
        "needs_iteration": not final_accepted,
        "internal_validation": (
            final_report["internal_validation"]
            if final_report is not None
            else {"status": "fail"}
        ),
        "render_validation": (
            final_report["render_validation"]
            if final_report is not None
            else {"status": "fail"}
        ),
        "regulatory_screening": (
            final_report["regulatory_screening"]
            if final_report is not None
            else {
                "status": "not_checked",
                "unresolved_facts": ["generation_failed"],
            }
        ),
        "termination_reason": search.termination_reason,
        "evaluation_count": search.evaluation_count,
        "error": search.error,
        "unchecked_checks": sorted(
            {
                name
                for report in reports
                for name, status in report["checks"].items()
                if status == "not_checked"
            }
        ),
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
            f"<td>{html.escape(str(entry['fingerprint'] or ''))}</td>"
            f"<td>{html.escape(entry['parent_id'] or '')}</td>"
            f"<td>{html.escape(entry['operator'])}</td>"
            f"<td>{html.escape(operator_params)}</td>"
            f"<td>{entry['hard_failure_count']}</td>"
            f"<td>{entry['scores']['total_score']}</td>"
            f"<td>{html.escape(entry['internal_validation']['status'])}</td>"
            f"<td>{html.escape(entry['render_validation']['status'])}</td>"
            f"<td>{html.escape(entry['regulatory_screening']['status'].replace('_', ' '))}</td>"
            f"<td>{artifact_links}</td>"
            "</tr>"
        )
    internal_status = index["internal_validation"]["status"]
    render_status = index["render_validation"]["status"]
    regulatory_status = index["regulatory_screening"]["status"].replace(
        "_",
        " ",
    )
    project_id = html.escape(index["project_id"])
    review_level = html.escape(index["review_level"])
    unchecked = ", ".join(index["unchecked_checks"]) or "none"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="icon" href="data:,">
  <title>{project_id} review history</title>
  <style>
    body {{ margin: 24px; font-family: "Noto Sans KR", "Malgun Gothic", Arial, sans-serif; background: white; color: #111; }}
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
      <p>internal concept validation: {html.escape(internal_status)}.
      render validation: {html.escape(render_status)}.
      regulatory screening: {html.escape(regulatory_status)}.
      Termination: {html.escape(index["termination_reason"])}.
      Evaluations: {index["evaluation_count"]}. Review level: {review_level}.
      Unchecked checks: {html.escape(unchecked)}.</p>
    </section>
    <section aria-labelledby="iteration-history">
      <h2 id="iteration-history">Iteration History</h2>
      <table>
        <thead><tr><th scope="col">Iteration</th><th scope="col">Candidate</th>
        <th scope="col">Fingerprint</th><th scope="col">Parent</th>
        <th scope="col">Operator</th><th scope="col">Operator parameters</th>
        <th scope="col">Hard failures</th>
        <th scope="col">Total score</th>
        <th scope="col">Internal concept validation</th>
        <th scope="col">Render validation</th>
        <th scope="col">Regulatory screening</th>
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
                    _line_style_key(line),
                    door_swing=line.door_swing,
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
                    stair_geometry=element.stair_geometry,
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
                        style_key=element.kind,
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


def _line_style_key(line: PlanLine) -> str:
    if line.kind == "entrance":
        return "common-entrance" if line.target_id else "tenant-entrance"
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
    *,
    render_style: str = "review",
) -> _RenderedOutput:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(
        min_x, min_y, max_x, max_y, width, height
    )
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
            reason = _render_skip_reason(
                feature,
                min_x,
                min_y,
                scale,
                pad_x,
                pad_y,
                width,
                height,
            )
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
                        render_style,
                    )
                )
            except (TypeError, ValueError, OverflowError):
                skipped.append(_skip_record(feature, "render_error"))
                continue
            rendered.append(feature)
        parts.append("</g>")
        if deferred_boundary is not None:
            reason = _render_skip_reason(
                deferred_boundary,
                min_x,
                min_y,
                scale,
                pad_x,
                pad_y,
                width,
                height,
            )
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
                            render_style,
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
    render_style: str,
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
        if (
            render_style == "architectural"
            and not _architectural_label_visible(feature)
        ):
            return f"<g {metadata}></g>"
        rows = _display_label(feature, render_style).split("|")
        if len(rows) == 1:
            return (
                f"<text {metadata} x=\"{x}\" y=\"{y}\" "
                f'font-family="{ARCHITECTURAL_FONT_STACK if render_style == "architectural" else "Arial"}" '
                f'font-size="10" text-anchor="middle">'
                f"{html.escape(rows[0])}</text>"
            )
        tspans = "".join(
            f'<tspan x="{x}" dy="{0 if index == 0 else 12}">'
            f"{html.escape(row)}</tspan>"
            for index, row in enumerate(rows)
        )
        return (
            f"<text {metadata} x=\"{x}\" y=\"{y}\" "
            f'font-family="{ARCHITECTURAL_FONT_STACK if render_style == "architectural" else "Arial"}" '
            f'font-size="10" text-anchor="middle">{tspans}</text>'
        )
    if feature.geometry == "polygon":
        points = " ".join(f"{x},{y}" for x, y in raster)
        fill, stroke, stroke_width = _svg_polygon_style(feature, render_style)
        polygon = (
            f'<polygon {metadata} points="{points}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        if render_style == "architectural":
            polygon += _svg_architectural_polygon_symbol(feature, raster)
        return polygon
    points = " ".join(f"{x},{y}" for x, y in raster)
    if render_style == "architectural" and feature.kind == "window":
        return _svg_window_symbol(metadata, raster)
    if render_style == "architectural" and feature.door_swing is not None:
        swing = feature.door_swing
        leaf_end = (
            _sx(swing.leaf_end[0], min_x, scale, pad_x),
            _sy(swing.leaf_end[1], min_y, scale, pad_y, height),
        )
        return _svg_door_symbol(
            metadata,
            feature,
            raster,
            symbol_name="modeled-door-swing",
            leaf_end_override=leaf_end,
        )
    if render_style == "architectural" and feature.kind == "entrance":
        return _svg_door_symbol(
            metadata,
            feature,
            raster,
            symbol_name="entrance-door",
            swing_inward=True,
        )
    if render_style == "architectural" and feature.layer == "door-openings":
        return _svg_door_symbol(metadata, feature, raster)
    if render_style == "architectural" and feature.layer == "dimensions":
        return _svg_dimension_chain(metadata, feature, raster)
    stroke, stroke_width, dash = _svg_line_style(feature, render_style)
    line = (
        f'<polyline points="{points}" fill="none" stroke="{stroke}" '
        f'stroke-width="{stroke_width}"{dash}/>'
    )
    label = ""
    if (
        feature.label
        and feature.kind != "door-opening"
        and (
            render_style != "architectural"
            or _architectural_label_visible(feature)
        )
    ):
        x, y = _line_label_position(feature, raster)
        display_label = _display_label(feature, render_style)
        label = (
            f'<text x="{x}" y="{y}" '
            f'font-family="{ARCHITECTURAL_FONT_STACK if render_style == "architectural" else "Arial"}" font-size="9" '
            f'text-anchor="middle">{html.escape(display_label)}</text>'
        )
    aria_label = ""
    if feature.kind == "door-opening":
        aria_label = (
            f' aria-label="{html.escape(feature.style_key, quote=True)} door '
            f'clear width {html.escape(feature.label, quote=True)}"'
        )
    return f"<g {metadata}{aria_label}>{line}{label}</g>"


def _svg_polygon_style(
    feature: _RenderFeature,
    render_style: str = "review",
) -> tuple[str, str, int]:
    if render_style == "architectural":
        if feature.kind == "boundary":
            return "none", "#111111", 6
        if feature.layer in {"rooms", "circulation", "core"}:
            return "white", "#202020", 4 if feature.layer != "circulation" else 2
        if feature.layer == "structure":
            return "#555555", "#111111", 2
        if feature.layer in {"furniture", "fixtures"}:
            return "white", "#666666", 1
        return "none", "#555555", 1
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


def _svg_line_style(
    feature: _RenderFeature,
    render_style: str = "review",
) -> tuple[str, int, str]:
    if render_style == "architectural":
        if feature.layer == "grid":
            return "#888888", 1, ' stroke-dasharray="4 5"'
        if feature.layer == "egress":
            return "#777777", 1, ' stroke-dasharray="7 5"'
        if feature.layer == "dimensions":
            return "#333333", 1, ""
        if feature.layer == "envelope":
            return "#222222", 2, ""
        return "#444444", 1, ""
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


def _svg_window_symbol(
    metadata: str,
    raster: list[tuple[float, float]],
) -> str:
    first, last = raster[0], raster[-1]
    offset_x, offset_y = _normal_offset(first, last, 2.0)
    rails = []
    for direction in (-1, 1):
        points = " ".join(
            f"{x + offset_x * direction},{y + offset_y * direction}"
            for x, y in raster
        )
        rails.append(
            f'<polyline points="{points}" fill="none" stroke="#222222" stroke-width="1"/>'
        )
    return f'<g {metadata} data-symbol="window-double-line">{"".join(rails)}</g>'


def _svg_door_symbol(
    metadata: str,
    feature: _RenderFeature,
    raster: list[tuple[float, float]],
    *,
    symbol_name: str = "door-swing",
    swing_inward: bool = False,
    leaf_end_override: tuple[float, float] | None = None,
) -> str:
    start, end = raster[0], raster[-1]
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    swing_sign = -1 if swing_inward else 1
    leaf_end = leaf_end_override or (
        start[0] - delta_y * swing_sign,
        start[1] + delta_x * swing_sign,
    )
    arc_points = _door_arc_points(
        start,
        end,
        leaf_end,
        abs(feature.door_swing.angle_degrees) if feature.door_swing else 90.0,
    )
    arc = " ".join(f"{point[0]},{point[1]}" for point in arc_points)
    aria = ""
    if feature.kind == "door-opening":
        aria = (
            f' aria-label="{html.escape(feature.style_key, quote=True)} door '
            f'clear width {html.escape(feature.label, quote=True)}"'
        )
    label = ""
    if feature.kind == "entrance":
        x, y = _architectural_line_label_position(feature, raster)
        label = (
            f'<text x="{x}" y="{y}" font-family="{ARCHITECTURAL_FONT_STACK}" '
            f'font-size="9" text-anchor="middle">'
            f'{html.escape(_display_label(feature, "architectural"))}</text>'
        )
    return (
        f'<g {metadata} data-symbol="{symbol_name}"{aria}>'
        f'<polyline points="{start[0]},{start[1]} {end[0]},{end[1]}" '
        'fill="none" stroke="white" stroke-width="8"/>'
        f'<line x1="{start[0]}" y1="{start[1]}" x2="{leaf_end[0]}" '
        f'y2="{leaf_end[1]}" stroke="#222222" stroke-width="2"/>'
        f'<polyline points="{arc}" fill="none" stroke="#777777" '
        'stroke-width="1"/>'
        f"{label}"
        "</g>"
    )


def _door_arc_points(
    hinge: tuple[float, float],
    closed_end: tuple[float, float],
    open_end: tuple[float, float],
    angle_degrees: float,
) -> list[tuple[float, float]]:
    radius = math.dist(hinge, closed_end)
    start_angle = math.atan2(
        closed_end[1] - hinge[1],
        closed_end[0] - hinge[0],
    )
    end_angle = math.atan2(
        open_end[1] - hinge[1],
        open_end[0] - hinge[0],
    )
    delta = (end_angle - start_angle + math.pi) % (2 * math.pi) - math.pi
    requested = math.radians(angle_degrees)
    delta = math.copysign(requested, delta)
    return [
        (
            hinge[0] + math.cos(start_angle + delta * index / 12) * radius,
            hinge[1] + math.sin(start_angle + delta * index / 12) * radius,
        )
        for index in range(13)
    ]


def _svg_architectural_polygon_symbol(
    feature: _RenderFeature,
    raster: list[tuple[float, float]],
) -> str:
    min_x = min(point[0] for point in raster)
    max_x = max(point[0] for point in raster)
    min_y = min(point[1] for point in raster)
    max_y = max(point[1] for point in raster)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    if feature.kind == "elevator":
        return (
            '<g data-symbol="elevator-car">'
            f'<rect x="{min_x + 4}" y="{min_y + 4}" '
            f'width="{max(0, max_x - min_x - 8)}" '
            f'height="{max(0, max_y - min_y - 8)}" fill="none" '
            'stroke="#555555" stroke-width="1"/>'
            f'<line x1="{center_x}" y1="{max_y - 4}" x2="{center_x}" '
            f'y2="{max_y}" stroke="#222222" stroke-width="2"/></g>'
        )
    if feature.layer == "fixtures":
        return (
            '<g data-symbol="fixture">'
            f'<ellipse cx="{center_x}" cy="{center_y}" '
            f'rx="{max(2, (max_x - min_x) * 0.28)}" '
            f'ry="{max(2, (max_y - min_y) * 0.28)}" fill="none" '
            'stroke="#666666" stroke-width="1"/>'
            f'<line x1="{center_x}" y1="{min_y + 2}" x2="{center_x}" '
            f'y2="{center_y}" stroke="#666666" stroke-width="1"/></g>'
        )
    if feature.layer == "furniture":
        return (
            '<g data-symbol="furniture">'
            f'<line x1="{min_x + 3}" y1="{center_y}" x2="{max_x - 3}" '
            f'y2="{center_y}" stroke="#777777" stroke-width="1"/>'
            f'<circle cx="{center_x}" cy="{center_y}" r="2.5" fill="none" '
            'stroke="#777777" stroke-width="1"/></g>'
        )
    if feature.kind != "stair":
        return ""
    tread_rasters = _stair_tread_rasters(feature, raster)
    lines = "".join(
        f'<line data-symbol="stair-tread" data-flight="{flight_index}" '
        f'x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" '
        'stroke="#555555" stroke-width="1"/>'
        for flight_index, start, end in tread_rasters
    )
    return (
        f'<g data-symbol="stair-treads">{lines}'
        f'<line x1="{center_x}" y1="{max_y - 5}" x2="{center_x}" '
        f'y2="{min_y + 8}" stroke="#222222" stroke-width="1"/>'
        f'<text x="{center_x + 5}" y="{min_y + 12}" '
        f'font-family="{ARCHITECTURAL_FONT_STACK}" font-size="8">UP</text></g>'
    )


def _stair_tread_rasters(
    feature: _RenderFeature,
    raster: list[tuple[float, float]],
) -> list[tuple[int, tuple[float, float], tuple[float, float]]]:
    geometry = feature.stair_geometry
    if geometry is None:
        return []
    model_min_x = min(point[0] for point in feature.points)
    model_max_x = max(point[0] for point in feature.points)
    model_min_y = min(point[1] for point in feature.points)
    model_max_y = max(point[1] for point in feature.points)
    raster_min_x = min(point[0] for point in raster)
    raster_max_x = max(point[0] for point in raster)
    raster_min_y = min(point[1] for point in raster)
    raster_max_y = max(point[1] for point in raster)

    def project(point: tuple[float, float]) -> tuple[float, float]:
        x_ratio = (point[0] - model_min_x) / (model_max_x - model_min_x)
        y_ratio = (point[1] - model_min_y) / (model_max_y - model_min_y)
        return (
            raster_min_x + x_ratio * (raster_max_x - raster_min_x),
            raster_max_y - y_ratio * (raster_max_y - raster_min_y),
        )

    result = []
    for flight in geometry.flights:
        min_x = min(point[0] for point in flight.footprint)
        max_x = max(point[0] for point in flight.footprint)
        min_y = min(point[1] for point in flight.footprint)
        max_y = max(point[1] for point in flight.footprint)
        for index in range(1, flight.tread_count + 1):
            ratio = index / (flight.tread_count + 1)
            if flight.direction in {"+x", "-x"}:
                x = min_x + (max_x - min_x) * ratio
                start, end = project((x, min_y)), project((x, max_y))
            else:
                y = min_y + (max_y - min_y) * ratio
                start, end = project((min_x, y)), project((max_x, y))
            result.append((flight.flight_index, start, end))
    return result


def _svg_dimension_chain(
    metadata: str,
    feature: _RenderFeature,
    raster: list[tuple[float, float]],
) -> str:
    start, end = raster[0], raster[-1]
    offset_x, offset_y = _normal_offset(start, end, 5.0)
    points = " ".join(f"{x},{y}" for x, y in raster)
    ticks = "".join(
        f'<line x1="{x - offset_x}" y1="{y - offset_y}" '
        f'x2="{x + offset_x}" y2="{y + offset_y}" '
        'stroke="#333333" stroke-width="1"/>'
        for x, y in (start, end)
    )
    x, y = _architectural_line_label_position(feature, raster)
    label = (
        f'<text x="{x}" y="{y}" font-family="{ARCHITECTURAL_FONT_STACK}" '
        f'font-size="9" text-anchor="middle">'
        f'{html.escape(_display_label(feature, "architectural"))}</text>'
        if feature.label and _architectural_label_visible(feature)
        else ""
    )
    return (
        f'<g {metadata} data-symbol="dimension-chain">'
        f'<polyline points="{points}" fill="none" stroke="#333333" '
        f'stroke-width="1"/>{ticks}{label}</g>'
    )


def _render_png(
    features: tuple[_RenderFeature, ...],
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
    *,
    render_style: str = "review",
) -> _RenderedOutput:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(
        min_x, min_y, max_x, max_y, width, height
    )
    canvas = SimplePngCanvas(width, height)
    rendered: list[_RenderFeature] = []
    skipped: list[dict[str, str]] = []
    for feature in features:
        reason = _render_skip_reason(
            feature,
            min_x,
            min_y,
            scale,
            pad_x,
            pad_y,
            width,
            height,
        )
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
                render_style,
            )
        except (TypeError, ValueError, OverflowError):
            skipped.append(_skip_record(feature, "render_error"))
            continue
        rendered.append(feature)
    payload = canvas.to_bytes()
    metadata: dict[str, object] = {
        "renderer": "bitmap-ascii",
        "font_path": None,
        "fallback": False,
    }
    if render_style == "architectural":
        payload, metadata = _draw_architectural_png_text(
            payload,
            canvas,
            features,
            min_x,
            min_y,
            scale,
            pad_x,
            pad_y,
            height,
        )
    return _RenderedOutput(payload, tuple(rendered), tuple(skipped), metadata)


def _png_feature(
    canvas: SimplePngCanvas,
    feature: _RenderFeature,
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    height: int,
    render_style: str = "review",
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
        if render_style == "architectural":
            return
        rows = feature.label.split("|")
        x, y = points[0]
        for index, row in enumerate(rows[:3]):
            label = _bounded_ascii(row, 18)
            origin = (x - len(label) * 3, y - 8 + index * 8)
            canvas.draw_text(label, origin, (25, 30, 35))
        return
    if feature.geometry == "polygon":
        fill, stroke, thickness = _png_polygon_style(feature, render_style)
        if fill is not None:
            canvas.fill_polygon(points, fill)
        canvas.stroke_polygon(points, stroke, thickness=thickness)
        if render_style == "architectural":
            _draw_png_architectural_polygon_symbol(canvas, feature, points)
        return
    if render_style == "architectural" and feature.kind == "window":
        _draw_png_window(canvas, points)
        return
    if render_style == "architectural" and feature.door_swing is not None:
        swing = feature.door_swing
        leaf_end = (
            round(_sx(swing.leaf_end[0], min_x, scale, pad_x)),
            round(_sy(swing.leaf_end[1], min_y, scale, pad_y, height)),
        )
        _draw_png_door_swing(
            canvas,
            points,
            leaf_end_override=leaf_end,
            angle_degrees=abs(swing.angle_degrees),
        )
        return
    if render_style == "architectural" and feature.kind == "entrance":
        _draw_png_door_swing(canvas, points, swing_inward=True)
        return
    if render_style == "architectural" and feature.layer == "door-openings":
        _draw_png_door_swing(canvas, points)
        return
    if render_style == "architectural" and feature.layer == "dimensions":
        _draw_png_dimension_chain(canvas, points)
    color, thickness, dashed = _png_line_style(feature, render_style)
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
    if (
        feature.label
        and feature.kind != "door-opening"
        and render_style != "architectural"
    ):
        x, y = _line_label_position(feature, points)
        label = _bounded_ascii(feature.label, 14)
        text_width = len(label) * 6
        origin_x = max(2, min(canvas.width - text_width - 2, round(x - text_width / 2)))
        origin_y = max(2, min(canvas.height - 9, round(y - 4)))
        canvas.draw_text(label, (origin_x, origin_y), color)


def _png_polygon_style(
    feature: _RenderFeature,
    render_style: str = "review",
) -> tuple[tuple[int, int, int] | None, tuple[int, int, int], int]:
    if render_style == "architectural":
        if feature.kind == "boundary":
            return None, (17, 17, 17), 6
        if feature.layer in {"rooms", "circulation", "core"}:
            return (255, 255, 255), (32, 32, 32), (
                4 if feature.layer != "circulation" else 2
            )
        if feature.layer == "structure":
            return (85, 85, 85), (17, 17, 17), 2
        if feature.layer in {"furniture", "fixtures"}:
            return (255, 255, 255), (102, 102, 102), 1
        return None, (85, 85, 85), 1
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
    render_style: str = "review",
) -> tuple[tuple[int, int, int], int, bool]:
    if render_style == "architectural":
        if feature.layer == "grid":
            return (136, 136, 136), 1, True
        if feature.layer == "egress":
            return (119, 119, 119), 1, True
        if feature.layer == "dimensions":
            return (51, 51, 51), 1, False
        return (68, 68, 68), 1, False
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


def _draw_png_window(
    canvas: SimplePngCanvas,
    points: list[tuple[int, int]],
) -> None:
    offset_x, offset_y = _normal_offset(points[0], points[-1], 2.0)
    for direction in (-1, 1):
        rail = [
            (
                round(x + offset_x * direction),
                round(y + offset_y * direction),
            )
            for x, y in points
        ]
        canvas.stroke_polyline(rail, (34, 34, 34), thickness=1)


def _draw_png_door_swing(
    canvas: SimplePngCanvas,
    points: list[tuple[int, int]],
    *,
    swing_inward: bool = False,
    leaf_end_override: tuple[int, int] | None = None,
    angle_degrees: float = 90.0,
) -> None:
    if len(points) != 2:
        canvas.stroke_polyline(points, (34, 34, 34), thickness=1)
        return
    start, end = points
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    swing_sign = -1 if swing_inward else 1
    leaf_end = leaf_end_override or (
        start[0] - delta_y * swing_sign,
        start[1] + delta_x * swing_sign,
    )
    canvas.stroke_polyline((start, end), (255, 255, 255), thickness=8)
    canvas.stroke_polyline((start, leaf_end), (34, 34, 34), thickness=2)
    arc = [
        (round(point[0]), round(point[1]))
        for point in _door_arc_points(start, end, leaf_end, angle_degrees)
    ]
    canvas.stroke_polyline(arc, (119, 119, 119), thickness=1)


def _draw_png_architectural_polygon_symbol(
    canvas: SimplePngCanvas,
    feature: _RenderFeature,
    points: list[tuple[int, int]],
) -> None:
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    center_x = round((min_x + max_x) / 2)
    center_y = round((min_y + max_y) / 2)
    if feature.kind == "elevator":
        canvas.stroke_rect(
            min_x + 4,
            min_y + 4,
            max_x - 4,
            max_y - 4,
            (85, 85, 85),
            thickness=1,
        )
        canvas.stroke_polyline(
            ((center_x, max_y - 4), (center_x, max_y)),
            (34, 34, 34),
            thickness=2,
        )
        return
    if feature.layer == "fixtures":
        radius = max(2, min(max_x - min_x, max_y - min_y) // 4)
        canvas.stroke_circle((center_x, center_y), radius, (102, 102, 102))
        canvas.stroke_polyline(
            ((center_x, min_y + 2), (center_x, center_y)),
            (102, 102, 102),
            thickness=1,
        )
        return
    if feature.layer == "furniture":
        canvas.stroke_polyline(
            ((min_x + 3, center_y), (max_x - 3, center_y)),
            (119, 119, 119),
            thickness=1,
        )
        canvas.stroke_circle((center_x, center_y), 2, (119, 119, 119))
        return
    if feature.kind != "stair":
        return
    for _, start, end in _stair_tread_rasters(
        feature,
        [(float(x), float(y)) for x, y in points],
    ):
        canvas.stroke_polyline(
            (
                (round(start[0]), round(start[1])),
                (round(end[0]), round(end[1])),
            ),
            (85, 85, 85),
            thickness=1,
        )
    canvas.stroke_polyline(
        ((center_x, max_y - 5), (center_x, min_y + 8)),
        (34, 34, 34),
        thickness=1,
    )
    canvas.draw_arrowhead(
        (center_x, min_y + 8),
        (center_x, max_y - 5),
        (34, 34, 34),
        size=4,
        thickness=1,
    )


def _draw_png_dimension_chain(
    canvas: SimplePngCanvas,
    points: list[tuple[int, int]],
) -> None:
    start, end = points[0], points[-1]
    canvas.stroke_polyline(points, (51, 51, 51), thickness=1)
    offset_x, offset_y = _normal_offset(start, end, 5.0)
    for x, y in (start, end):
        canvas.stroke_polyline(
            (
                (round(x - offset_x), round(y - offset_y)),
                (round(x + offset_x), round(y + offset_y)),
            ),
            (51, 51, 51),
            thickness=1,
        )


def _draw_architectural_png_text(
    payload: bytes,
    fallback_canvas: SimplePngCanvas,
    features: tuple[_RenderFeature, ...],
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    height: int,
) -> tuple[bytes, dict[str, object]]:
    font_path = _architectural_font_path()
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        font_path = None
    if font_path is None:
        return _draw_architectural_ascii_fallback(
            fallback_canvas,
            features,
            min_x,
            min_y,
            scale,
            pad_x,
            pad_y,
            height,
        )

    image = Image.open(io.BytesIO(payload)).convert("RGB")
    drawing = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 12)
    occupied: list[tuple[float, float, float, float]] = []
    adjusted_count = 0
    label_count = 0
    unresolved_collision_count = 0
    for feature in features:
        if (
            not feature.label
            or feature.kind == "door-opening"
            or not _architectural_label_visible(feature)
        ):
            continue
        label_count += 1
        raster = [
            (
                _sx(x, min_x, scale, pad_x),
                _sy(y, min_y, scale, pad_y, height),
            )
            for x, y in feature.points
        ]
        if feature.geometry == "label":
            x, y = raster[0]
        else:
            x, y = _architectural_line_label_position(feature, raster)
        text = _display_label(feature, "architectural").replace("|", "\n")
        box = drawing.multiline_textbbox((0, 0), text, font=font, spacing=1, align="center")
        text_width = box[2] - box[0]
        text_height = box[3] - box[1]
        origin = (x - text_width / 2, y - text_height / 2)
        offsets = [(0, 0)]
        for radius in (16, 28, 42, 58, 76):
            offsets.extend(
                (
                    (0, -radius),
                    (0, radius),
                    (radius, 0),
                    (-radius, 0),
                    (radius, radius),
                    (radius, -radius),
                    (-radius, radius),
                    (-radius, -radius),
                )
            )
        for offset_x, offset_y in offsets:
            candidate = (
                origin[0] + offset_x,
                origin[1] + offset_y,
                origin[0] + offset_x + text_width,
                origin[1] + offset_y + text_height,
            )
            inside_canvas = (
                candidate[0] >= 2
                and candidate[1] >= 2
                and candidate[2] <= image.width - 2
                and candidate[3] <= image.height - 2
            )
            if inside_canvas and not any(
                _rectangles_intersect(candidate, item) for item in occupied
            ):
                if offset_x or offset_y:
                    adjusted_count += 1
                origin = (candidate[0], candidate[1])
                occupied.append(candidate)
                break
        else:
            unresolved_collision_count += 1
            occupied.append(
                (origin[0], origin[1], origin[0] + text_width, origin[1] + text_height)
            )
        drawing.multiline_text(
            origin,
            text,
            fill=(25, 25, 25),
            font=font,
            spacing=1,
            align="center",
        )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue(), {
        "renderer": "pillow",
        "font_path": str(font_path),
        "fallback": False,
        "collision_strategy": "offset",
        "label_count": label_count,
        "adjusted_count": adjusted_count,
        "unresolved_collision_count": unresolved_collision_count,
    }


def _architectural_font_path() -> Path | None:
    candidates = (
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _draw_architectural_ascii_fallback(
    canvas: SimplePngCanvas,
    features: tuple[_RenderFeature, ...],
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    height: int,
) -> tuple[bytes, dict[str, object]]:
    for feature in features:
        if (
            not feature.label
            or feature.kind == "door-opening"
            or not _architectural_label_visible(feature)
        ):
            continue
        raster = [
            (
                _sx(x, min_x, scale, pad_x),
                _sy(y, min_y, scale, pad_y, height),
            )
            for x, y in feature.points
        ]
        if feature.geometry == "label":
            x, y = raster[0]
        else:
            x, y = _architectural_line_label_position(feature, raster)
        x = round(x)
        y = round(y)
        label = _architectural_ascii_label(feature)
        canvas.draw_text(
            label,
            (x - len(label) * 3, y - 4),
            (25, 25, 25),
        )
    return canvas.to_bytes(), {
        "renderer": "bitmap-ascii",
        "font_path": None,
        "fallback": True,
        "collision_strategy": "none",
        "label_count": sum(feature.geometry == "label" for feature in features),
        "adjusted_count": 0,
        "unresolved_collision_count": 1,
    }


def _architectural_ascii_label(feature: _RenderFeature) -> str:
    names = {
        "office_area": "OFFICE",
        "open_work": "OPEN WORK",
        "meeting": "MEETING",
        "reception": "RECEPTION",
        "focus": "FOCUS",
        "it_storage": "IT/STOR",
        "sales": "SALES",
        "checkout": "CHECKOUT",
        "stock": "STOCK",
        "staff": "STAFF",
        "restroom": "WC",
        "circulation": "CORRIDOR",
        "tenant-entrance": "TENANT ENTRY",
        "common-entrance": "COMMON ENTRY",
    }
    if feature.style_key in names:
        return names[feature.style_key]
    ascii_text = _bounded_ascii(feature.label.replace("|", " "), 18).replace("?", "")
    return ascii_text.strip() or feature.kind.upper()[:18]


def _display_label(feature: _RenderFeature, render_style: str) -> str:
    if render_style != "architectural":
        return feature.label
    if feature.kind in {"overall_width", "overall_depth"}:
        return re.sub(r"^(WIDTH|DEPTH)\s+", "", feature.label)
    if feature.kind == "street":
        return "도로"
    if feature.kind == "entrance":
        return (
            "공용 출입"
            if feature.style_key == "common-entrance"
            else "임대 출입"
        )
    key = feature.style_key
    rows = feature.label.split("|")
    if not key and feature.kind == "room-label":
        key = rows[-2] if len(rows) >= 3 else rows[0]
    elif not key and feature.kind == "circulation":
        key = "circulation"
    elif feature.kind == "core-label":
        if key == "stair" or rows[0].strip().upper() in {"STAIR", "UP", "DN"}:
            key = "stair"
        elif not key:
            key = {
                "ELEVATOR": "elevator",
                "LOBBY": "lobby",
                "SHAFT": "shaft",
            }.get(rows[0].strip().upper().split(" ", 1)[0])
    translated = ARCHITECTURAL_LABELS.get(key)
    if translated is None:
        return feature.label
    if feature.kind == "room-label" and len(rows) >= 2:
        return f"{translated}|{rows[-1]}"
    return translated


def _architectural_label_visible(feature: _RenderFeature) -> bool:
    if feature.geometry == "label":
        return feature.kind != "door-width"
    return feature.kind in {
        "grid",
        "north_arrow",
        "overall_width",
        "overall_depth",
        "street",
        "entrance",
    }


def _architectural_line_label_position(
    feature: _RenderFeature,
    points: list[tuple[int | float, int | float]],
) -> tuple[float, float]:
    midpoint_x = sum(point[0] for point in points) / len(points)
    midpoint_y = sum(point[1] for point in points) / len(points)
    if feature.kind == "overall_width":
        return midpoint_x, midpoint_y + 24
    if feature.kind == "overall_depth":
        return midpoint_x - 28, midpoint_y
    if feature.kind == "street":
        return midpoint_x, midpoint_y + 28
    if feature.kind == "entrance":
        return midpoint_x, midpoint_y + 20
    return _line_label_position(feature, points)


def _normal_offset(
    start: tuple[float, float],
    end: tuple[float, float],
    distance: float,
) -> tuple[float, float]:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length == 0:
        return 0.0, 0.0
    return -delta_y / length * distance, delta_x / length * distance


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


def _render_skip_reason(
    feature: _RenderFeature,
    min_x: float,
    min_y: float,
    scale: float,
    pad_x: float,
    pad_y: float,
    width: int,
    height: int,
) -> str | None:
    reason = _feature_skip_reason(feature)
    if reason is not None:
        return reason
    if feature.geometry == "polyline" and not any(
        math.dist(start, end) > 1e-9
        for start, end in zip(feature.points, feature.points[1:])
    ):
        return "degenerate_geometry"
    if feature.geometry == "polygon" and abs(_signed_area(feature.points)) <= 1e-9:
        return "degenerate_geometry"
    screen_points = tuple(
        (
            _sx(x, min_x, scale, pad_x),
            _sy(y, min_y, scale, pad_y, height),
        )
        for x, y in feature.points
    )
    if not _screen_geometry_visible(
        feature,
        screen_points,
        width,
        height,
    ):
        return "off_canvas"
    return None


def _screen_geometry_visible(
    feature: _RenderFeature,
    points: tuple[tuple[float, float], ...],
    width: int,
    height: int,
) -> bool:
    max_x = width - 1
    max_y = height - 1
    if feature.geometry == "label":
        x, y = points[0]
        half_width = max(3.0, len(feature.label) * 3.0)
        return _rectangles_intersect(
            (x - half_width, y - 8.0, x + half_width, y + 16.0),
            (0.0, 0.0, max_x, max_y),
        )
    if feature.geometry == "polyline":
        return any(
            _segment_intersects_viewport(start, end, max_x, max_y)
            for start, end in zip(points, points[1:])
        )
    return _polygon_intersects_viewport(points, max_x, max_y)


def _polygon_intersects_viewport(
    points: tuple[tuple[float, float], ...],
    max_x: float,
    max_y: float,
) -> bool:
    if any(_point_in_viewport(point, max_x, max_y) for point in points):
        return True
    if any(
        _segment_intersects_viewport(start, end, max_x, max_y)
        for start, end in zip(points, (*points[1:], points[0]))
    ):
        return True
    return any(
        _point_in_polygon(corner, points)
        for corner in ((0.0, 0.0), (max_x, 0.0), (max_x, max_y), (0.0, max_y))
    )


def _segment_intersects_viewport(
    start: tuple[float, float],
    end: tuple[float, float],
    max_x: float,
    max_y: float,
) -> bool:
    if _point_in_viewport(start, max_x, max_y) or _point_in_viewport(
        end,
        max_x,
        max_y,
    ):
        return True
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    start_ratio = 0.0
    end_ratio = 1.0
    for direction, distance in (
        (-delta_x, start[0]),
        (delta_x, max_x - start[0]),
        (-delta_y, start[1]),
        (delta_y, max_y - start[1]),
    ):
        if direction == 0:
            if distance < 0:
                return False
            continue
        ratio = distance / direction
        if direction < 0:
            start_ratio = max(start_ratio, ratio)
        else:
            end_ratio = min(end_ratio, ratio)
        if start_ratio > end_ratio:
            return False
    return True


def _point_in_viewport(
    point: tuple[float, float],
    max_x: float,
    max_y: float,
) -> bool:
    return 0.0 <= point[0] <= max_x and 0.0 <= point[1] <= max_y


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    inside = False
    x, y = point
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _signed_area(points: tuple[tuple[float, float], ...]) -> float:
    return 0.5 * sum(
        start[0] * end[1] - end[0] * start[1]
        for start, end in zip(points, (*points[1:], points[0]))
    )


def _rectangles_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


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
    svg_payload: str,
    png_name: str,
    report_name: str,
    report: dict,
) -> str:
    internal_status = report["internal_validation"]["status"]
    render_status = report["render_validation"]["status"]
    review_disposition = (
        "needs iteration"
        if report["needs_iteration"]
        else "accepted for internal review"
    )
    regulatory_status = report["regulatory_screening"]["status"].replace(
        "_",
        " ",
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
    area_ledger = report.get("area_ledger") or {}
    area_rows = "".join(
        "<tr>"
        f'<th scope="row">{html.escape(str(entry["bucket"]))}</th>'
        f"<td>{_display_measurement(entry['area_m2'])}</td>"
        f"<td>{html.escape(', '.join(entry['provenance']['source_ids']) or '-')}</td>"
        "</tr>"
        for entry in area_ledger.get("entries", [])
    )
    travel = next(
        (
            check
            for check in report["regulatory_screening"].get("checks", [])
            if check.get("rule_id") == "KR-EGRESS-TRAVEL-DISTANCE-ART34"
        ),
        {},
    )
    unresolved = tuple(
        dict.fromkeys(
            [
                *report["regulatory_screening"].get("unresolved_facts", []),
                *(report.get("egress_graph") or {}).get(
                    "unresolved_facts",
                    [],
                ),
            ]
        )
    )
    unresolved_items = "".join(
        f"<li>{html.escape(str(item))}</li>"
        for item in unresolved
    ) or "<li>none</li>"
    area_by_room_id = {
        metric["room_id"]: metric["actual_area"] for metric in report["room_areas"]
    }
    adjustment_by_room = _adjustment_display_by_room(
        report["program_adjustments"]
    )
    room_form_rows = "".join(
        "<tr>"
        f'<th scope="row">{html.escape(shape["room_id"])}</th>'
        f"<td>{_display_measurement(adjustment_by_room.get(shape['room_id'], {}).get('original'))}</td>"
        f"<td>{_display_measurement(adjustment_by_room.get(shape['room_id'], {}).get('adjusted'))}</td>"
        f"<td>{_display_measurement(area_by_room_id.get(shape['room_id']))}</td>"
        f"<td>{_display_measurement(shape['measured_min_width'])}</td>"
        f"<td>{_display_measurement(shape['measured_aspect_ratio'])}</td>"
        f"<td>{_display_measurement(shape['required_min_width'])}</td>"
        f"<td>{_display_measurement(shape['maximum_aspect_ratio'])}</td>"
        f"<td>{html.escape(', '.join(adjustment_by_room.get(shape['room_id'], {}).get('reasons', []))) or '-'}</td>"
        "</tr>"
        for shape in report["room_shapes"]
    )
    basic_design_present = result.layout.basic_design is not None
    layer_rows = []
    for layer in LAYER_ORDER:
        disabled = layer in _BASIC_DESIGN_LAYERS and not basic_design_present
        label, color = LAYER_DISPLAY[layer]
        modeled_count = report["layer_completeness"].get(layer, {}).get(
            "modeled",
            0,
        )
        layer_rows.append(
            f'<div class="cad-layer-row" data-layer="{layer}">'
            f'<input type="checkbox" data-layer="{layer}" '
            f'aria-label="{label} 표시" checked'
            + (' disabled aria-disabled="true"' if disabled else "")
            + ">"
            f'<button type="button" class="layer-select" data-layer="{layer}" '
            'aria-pressed="false"'
            + (' disabled aria-disabled="true"' if disabled else "")
            + ">"
            f'<span class="layer-swatch" style="--layer-color: {color}" '
            'aria-hidden="true"></span>'
            f'<span class="layer-name">{label}</span>'
            f'<span class="layer-modeled-count" '
            f'aria-label="모델링 객체 {modeled_count}개">{modeled_count}</span>'
            "</button>"
            "</div>"
        )
    controls = "".join(layer_rows)
    completeness_rows = "".join(
        f'<tr><th scope="row">{html.escape(layer)}</th>'
        f'<td>{counts["modeled"]}</td><td>{counts["svg"]}</td>'
        f'<td>{counts["png"]}</td></tr>'
        for layer, counts in report["layer_completeness"].items()
    )
    project_id = html.escape(result.mass.project_id)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <link rel="icon" href="data:,">
  <title>{project_id} floor visual review</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ max-width: 100%; overflow-x: hidden; }}
    body {{ margin: 24px; font-family: "Noto Sans KR", "Malgun Gothic", Arial, sans-serif; background: white; color: #111; }}
    main {{ max-width: 1180px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .status {{ margin-bottom: 18px; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); gap: 20px; align-items: start; }}
    .grid > section {{ min-width: 0; }}
    .plan {{ grid-column: 1 / -1; }}
    .review-workspace {{ display: grid; grid-template-columns: minmax(0, 1fr) 272px; gap: 14px; align-items: start; }}
    .drawing-pane {{ min-width: 0; }}
    .drawing-pane svg {{ display: block; width: 100%; aspect-ratio: 16 / 9; height: auto; border: 1px solid #ccc; }}
    #cad-layer-manager {{ min-width: 0; border: 1px solid #b9c0c7; background: #fff; color: #171a1d; }}
    .cad-layer-header {{ padding: 9px 10px; border-bottom: 1px solid #cbd0d5; font-size: 14px; font-weight: 700; }}
    .cad-layer-commands {{ display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 8px; border-bottom: 1px solid #d8dde1; }}
    .cad-layer-commands button {{ min-height: 32px; padding: 5px 7px; border: 1px solid #aeb6bd; border-radius: 3px; background: #f7f8f9; color: #171a1d; font: inherit; cursor: pointer; }}
    .cad-layer-commands button:hover:not(:disabled) {{ background: #e8edf1; }}
    .cad-layer-commands button:focus-visible, .cad-layer-row input:focus-visible, .layer-select:focus-visible {{ outline: 2px solid #1261a0; outline-offset: 2px; }}
    .cad-layer-commands button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .cad-layer-list {{ display: grid; padding: 4px 0; }}
    .cad-layer-row {{ display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 7px; align-items: center; min-height: 33px; padding: 4px 10px; border-bottom: 1px solid #edf0f2; }}
    .cad-layer-row:last-child {{ border-bottom: 0; }}
    .cad-layer-row:hover {{ background: #f5f7f8; }}
    .cad-layer-row[data-active="true"] {{ background: #e5f0f8; box-shadow: inset 3px 0 #1261a0; }}
    .cad-layer-row:has(input:disabled) {{ color: #8b9298; }}
    .cad-layer-row input {{ width: 16px; height: 16px; margin: 0; accent-color: #1261a0; }}
    .layer-select {{ display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 7px; align-items: center; width: 100%; min-height: 27px; padding: 0; border: 0; border-radius: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }}
    .layer-select:disabled {{ cursor: not-allowed; }}
    .layer-swatch {{ width: 13px; height: 13px; border: 1px solid #6d747a; background: var(--layer-color); }}
    .layer-name {{ min-width: 0; font-size: 13px; }}
    .layer-modeled-count {{ min-width: 24px; color: #5b6268; font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; }}
    table {{ border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }}
    thead, tbody {{ white-space: nowrap; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: left; }}
    a {{ color: #0645ad; }}
    @media (max-width: 680px) {{ body {{ margin: 14px; }} .grid, .review-workspace {{ grid-template-columns: 1fr; }} .plan {{ grid-column: auto; }} #cad-layer-manager {{ width: 100%; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Visual Review: {project_id} F{result.program.floor_index}</h1>
    <div class="status">
      <div>review disposition: {html.escape(review_disposition)}</div>
      <div>internal concept validation: {html.escape(internal_status)}</div>
      <div>render validation: {html.escape(render_status)}</div>
      <div>regulatory screening: {html.escape(regulatory_status)}</div>
    </div>
    <div class="grid">
      <section class="plan">
        <div class="review-workspace">
          <div class="drawing-pane">
            {svg_payload}
          </div>
          <aside id="cad-layer-manager" aria-label="도면 레이어">
            <div class="cad-layer-header">레이어</div>
            <div class="cad-layer-commands" aria-label="레이어 명령">
              <button type="button" data-command="all-on">전체 켜기</button>
              <button type="button" data-command="all-off">전체 끄기</button>
              <button type="button" data-command="isolate">선택만 보기</button>
              <button type="button" data-command="reset">초기화</button>
            </div>
            <div class="cad-layer-list">
              {controls}
            </div>
          </aside>
        </div>
      </section>
      <section>
        <h2>Hard Validation Checks</h2>
        <table>
          <thead><tr><th scope="col">Hard gate</th><th scope="col">Status</th></tr></thead>
          <tbody>{checks}</tbody>
        </table>
        <h2>Area Ledger</h2>
        <p>status: {html.escape(str(area_ledger.get("status", "not_checked")))}</p>
        <table id="area-ledger">
          <thead><tr><th scope="col">Bucket</th><th scope="col">Area m2</th><th scope="col">Sources</th></tr></thead>
          <tbody>{area_rows}</tbody>
        </table>
        <h2>Travel Distance</h2>
        <table id="travel-distance">
          <tbody>
            <tr><th scope="row">Status</th><td>{html.escape(str(travel.get("status", "not_checked")))}</td></tr>
            <tr><th scope="row">Measured m</th><td>{_display_measurement(travel.get("measured_value"))}</td></tr>
            <tr><th scope="row">Threshold m</th><td>{_display_measurement(travel.get("threshold"))}</td></tr>
          </tbody>
        </table>
        <h2>Unresolved Evidence</h2>
        <ul id="unresolved-evidence">{unresolved_items}</ul>
        <h2>Advisory Scores</h2>
        <table>
          <thead><tr><th scope="col">Metric</th><th scope="col">Score</th></tr></thead>
          <tbody>{advisory_scores}</tbody>
        </table>
        <h2>Room Program and Form</h2>
        <table id="room-form-report">
          <thead><tr><th scope="col">Room</th><th scope="col">Original target m2</th><th scope="col">Adjusted target m2</th><th scope="col">Area m2</th><th scope="col">Width m</th><th scope="col">Aspect</th><th scope="col">Min width</th><th scope="col">Max aspect</th><th scope="col">Adjustment reason</th></tr></thead>
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
    const drawingRoot = document.querySelector(".drawing-pane svg");
    const checkboxes = Array.from(
      document.querySelectorAll('#cad-layer-manager input[type="checkbox"][data-layer]')
    );
    const rows = Array.from(
      document.querySelectorAll("#cad-layer-manager .cad-layer-row[data-layer]")
    );
    const selectionButtons = Array.from(
      document.querySelectorAll("#cad-layer-manager .layer-select[data-layer]")
    );
    const commandButtons = document.querySelectorAll(
      "#cad-layer-manager button[data-command]"
    );
    const isolateButton = document.querySelector(
      '#cad-layer-manager button[data-command="isolate"]'
    );
    let activeLayer = null;
    function enabledCheckboxes() {{
      return checkboxes.filter((checkbox) => !checkbox.disabled);
    }}
    function setActiveLayer(layer) {{
      if (layer !== null) {{
        const checkbox = checkboxes.find(
          (candidate) => candidate.dataset.layer === layer
        );
        if (!checkbox || checkbox.disabled) return;
      }}
      activeLayer = layer;
      rows.forEach((row) => {{
        const active = row.dataset.layer === activeLayer;
        row.dataset.active = String(active);
      }});
      selectionButtons.forEach((selectButton) => {{
        const active = selectButton.dataset.layer === activeLayer;
        selectButton.setAttribute("aria-pressed", String(active));
      }});
      updateCommandState();
    }}
    function updateCommandState() {{
      isolateButton.disabled = activeLayer === null;
    }}
    function synchronizeLayers() {{
      if (!drawingRoot) return;
      checkboxes.forEach((checkbox) => {{
        const visible = checkbox.checked;
        drawingRoot.querySelectorAll(`[data-layer="${{checkbox.dataset.layer}}"]`).forEach((node) => {{
          node.style.display = visible ? "" : "none";
        }});
      }});
    }}
    checkboxes.forEach((checkbox) => {{
      checkbox.addEventListener("change", () => {{
        synchronizeLayers();
        updateCommandState();
      }});
    }});
    selectionButtons.forEach((selectButton) => {{
      selectButton.addEventListener("click", () => {{
        setActiveLayer(selectButton.dataset.layer);
      }});
    }});
    commandButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        const enabled = enabledCheckboxes();
        if (button.dataset.command === "all-on") {{
          enabled.forEach((checkbox) => {{ checkbox.checked = true; }});
        }} else if (button.dataset.command === "all-off") {{
          enabled.forEach((checkbox) => {{ checkbox.checked = false; }});
        }} else if (
          button.dataset.command === "isolate" && activeLayer !== null
        ) {{
          enabled.forEach((checkbox) => {{
            checkbox.checked = checkbox.dataset.layer === activeLayer;
          }});
        }} else if (button.dataset.command === "reset") {{
          enabled.forEach((checkbox) => {{ checkbox.checked = true; }});
          setActiveLayer(null);
        }}
        synchronizeLayers();
        updateCommandState();
      }});
    }});
    updateCommandState();
    synchronizeLayers();
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


def _regulatory_screening_payload(validation: ValidationReport) -> dict:
    if validation.regulatory_screening is not None:
        return to_jsonable(validation.regulatory_screening)
    return {
        "ruleset_id": "not-configured",
        "status": "not_checked",
        "checks": [],
        "unresolved_facts": ["building_code_context"],
    }


def _aggregate_regulatory_screening(records: list[dict]) -> dict:
    screenings = [record["regulatory_screening"] for record in records]
    statuses = [screening["status"] for screening in screenings]
    if statuses and all(status == "pass" for status in statuses):
        status = "pass"
    elif any(status == "fail" for status in statuses):
        status = "fail"
    else:
        status = "not_checked"
    unresolved = sorted(
        {
            fact
            for screening in screenings
            for fact in screening.get("unresolved_facts", [])
        }
    )
    return {
        "status": status,
        "unresolved_facts": unresolved,
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

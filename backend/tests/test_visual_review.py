import json
import struct
import subprocess
import sys
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

import backend.app.modules.visual_review.service as visual_review_service
from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generation_loop.service import (
    run_building_generation,
    run_generation_loop,
)
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
    create_visual_review_artifacts,
    run_visual_review_loop,
)
from backend.app.schemas.layout import OpeningSegment, RoomPolygon
from backend.app.schemas.loop import CandidateRecord, IterationRecord, LoopResult
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import ValidationViolation


def _sample_result():
    mass = MassInput(
        project_id="visual",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )
    return run_generation_loop(mass, floor_index=1, use_type="neighborhood_commercial"), mass.footprint_polygon


def _strict_building_floor():
    mass = MassInput(
        project_id="strict-visual",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    building = run_building_generation(mass)
    return building.floor_results[0], mass.footprint_polygon


def _l_shaped_result(project_id: str = "visual"):
    result, boundary = _sample_result()
    room = replace(
        result.layout.rooms[0],
        space_type="shop_unit",
        polygon=[(0, 0), (20, 0), (20, 4), (8, 4), (8, 10), (0, 10)],
    )
    layout = replace(result.layout, rooms=[room])
    return replace(result, mass=replace(result.mass, project_id=project_id), layout=layout), boundary


def _png_pixel(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    offset = 8
    compressed = b""
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IDAT":
            compressed += payload
    raw = zlib.decompress(compressed)
    width = struct.unpack(">I", data[16:20])[0]
    row_stride = width * 3 + 1
    pixel = y * row_stride + 1 + x * 3
    return tuple(raw[pixel : pixel + 3])


def test_create_visual_review_artifacts_writes_svg_png_and_report(tmp_path):
    result, boundary = _sample_result()

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)

    assert review.svg_path.exists()
    assert review.png_path.exists()
    assert review.html_path.exists()
    assert review.report_path.exists()
    assert "<svg" in review.svg_path.read_text(encoding="utf-8")
    assert "visual review" in review.html_path.read_text(encoding="utf-8").lower()
    assert review.png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["project_id"] == "visual"
    assert report["needs_iteration"] is True
    assert report["checks"]["boundary"] == "pass"
    assert report["checks"]["openings"] == "not_checked"
    assert report["checks"]["corridor_width"] == "not_checked"


def test_building_review_writes_navigable_artifacts_for_every_floor(tmp_path):
    mass = MassInput(
        project_id="five-floor-review",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )
    result = run_building_generation(mass)

    artifacts = create_building_visual_review_artifacts(
        result,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path,
    )

    assert artifacts.index_html_path.is_file()
    assert artifacts.report_path.is_file()
    assert len(artifacts.floor_artifacts) == 5
    assert all(review.png_path.is_file() for review in artifacts.floor_artifacts)
    assert all(review.svg_path.is_file() for review in artifacts.floor_artifacts)
    index = artifacts.index_html_path.read_text(encoding="utf-8")
    assert '<link rel="icon" href="data:,"' in index
    assert "F1 · neighborhood_commercial" in index
    assert "F5 · office" in index
    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    assert report["accepted"] is True
    assert report["vertical_core_aligned"] is True
    assert [floor["floor_index"] for floor in report["floors"]] == [1, 2, 3, 4, 5]


def test_png_artifact_has_requested_pixel_size(tmp_path):
    result, boundary = _sample_result()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=640,
        height=320,
    )

    data = review.png_path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (640, 320)


def test_polygon_artifacts_render_an_l_shape_without_filling_its_missing_corner(tmp_path):
    result, boundary = _l_shaped_result()

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path, width=200, height=100)

    png = review.png_path.read_bytes()
    assert _png_pixel(png, 50, 26) == (217, 234, 211)
    assert _png_pixel(png, 141, 26) == (255, 255, 255)
    svg = review.svg_path.read_text(encoding="utf-8")
    assert '18.0,91.0 182.0,91.0 182.0,58.2 83.6,58.2 83.6,9.0 18.0,9.0' in svg


def test_artifacts_render_circulation_in_svg_and_png(tmp_path):
    result, boundary = _sample_result()
    corridor = RoomPolygon(
        room_id="corridor",
        space_type="circulation",
        polygon=[(9, 0), (11, 0), (11, 10), (9, 10)],
    )
    result = replace(
        result,
        layout=replace(result.layout, circulation=[corridor]),
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=200,
        height=100,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    assert 'data-kind="circulation"' in svg
    assert 'fill="#d9d9d9" stroke="#38761d"' in svg
    assert ">circulation</text>" in svg
    assert _png_pixel(review.png_path.read_bytes(), 100, 50) == (217, 217, 217)


def test_svg_renders_door_width_and_room_identity_area_labels(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=300,
        height=100,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    assert svg.count('data-kind="door-opening"') == len(result.layout.openings)
    assert svg.count('data-kind="door-width"') == len(result.layout.openings)
    assert 'aria-label="office_area door clear width 0.9 m"' in svg
    assert ">0.9 m</text>" in svg
    assert 'data-kind="room-label"' in svg
    assert "office_area" in svg
    assert "210.6 m2" in svg


def test_png_renders_high_contrast_door_segment_pixels(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=300,
        height=100,
    )

    png = review.png_path.read_bytes()
    assert _png_pixel(png, 200, 50) == (0, 86, 179)
    assert _png_pixel(png, 197, 46) == (0, 0, 0)


def test_review_report_exposes_validated_opening_and_corridor_measurements(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["openings"] == "pass"
    assert report["checks"]["corridor_width"] == "pass"
    assert report["measurements"] == {
        "door_count": len(result.layout.openings),
        "min_door_width": 0.9,
        "min_corridor_width": 3.0,
    }


@pytest.mark.parametrize(
    ("invalid_x", "clear_width"),
    [
        (float("nan"), 0.9),
        ("not-a-coordinate", 0.9),
        (21.06, "0.9"),
    ],
)
def test_invalid_opening_coordinate_is_skipped_without_blocking_review_artifacts(
    tmp_path,
    invalid_x,
    clear_width,
):
    result, boundary = _strict_building_floor()
    invalid = OpeningSegment(
        opening_id="invalid-door",
        kind="door",
        connects=("office_area", "corridor"),
        start=(invalid_x, 4.0),
        end=(21.06, 4.9),
        clear_width=clear_width,
    )
    validation = replace(
        result.validation,
        accepted=False,
        is_valid=False,
        hard_violation_count=1,
        violations=[
            *result.validation.violations,
            ValidationViolation(
                code="door_geometry",
                subject=invalid.opening_id,
                message="door coordinates must be finite",
            ),
        ],
    )
    result = replace(
        result,
        layout=replace(result.layout, openings=[*result.layout.openings, invalid]),
        validation=validation,
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    assert all(
        path.is_file()
        for path in (
            review.svg_path,
            review.png_path,
            review.html_path,
            review.report_path,
        )
    )
    svg = review.svg_path.read_text(encoding="utf-8")
    assert "invalid-door" not in svg
    assert "nan" not in svg.lower()
    assert svg.count('data-kind="door-opening"') == len(result.layout.openings) - 1
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["openings"] == "fail"
    assert report["measurements"]["door_count"] == len(result.layout.openings)


def test_present_but_unchecked_openings_are_not_reported_as_pass(tmp_path):
    result, boundary = _strict_building_floor()
    result = replace(
        result,
        validation=replace(
            result.validation,
            openings_checked=False,
            corridor_width_checked=False,
        ),
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["openings"] == "not_checked"
    assert report["checks"]["corridor_width"] == "not_checked"


def test_artifacts_escape_text_use_safe_stems_and_keep_links_under_output_root(tmp_path):
    result, boundary = _l_shaped_result(project_id='../../Project <script>alert(1)</script>')
    room = replace(result.layout.rooms[0], space_type='<svg onload="alert(1)">')
    result = replace(result, layout=replace(result.layout, rooms=[room]))

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)

    for path in (review.svg_path, review.png_path, review.html_path, review.report_path):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        assert "/" not in path.name
        assert "<" not in path.name
    assert review.svg_path.stem.startswith("project-script-alert-1-script-")
    assert review.svg_path.stem.endswith("-f1")
    assert '<svg onload="alert(1)">' not in review.svg_path.read_text(encoding="utf-8")
    assert "&lt;svg onload=&quot;alert(1)&quot;&gt;" in review.svg_path.read_text(encoding="utf-8")
    html = review.html_path.read_text(encoding="utf-8")
    assert "Project &lt;script&gt;alert(1)&lt;/script&gt;" in html
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    for artifact in report["artifacts"].values():
        assert not Path(artifact).is_absolute()
        assert ".." not in Path(artifact).parts


@pytest.mark.parametrize(
    ("first_project_id", "second_project_id"),
    [
        ("!!!", "@@@"),
        ("a" * 80 + "-first", "a" * 80 + "-second"),
    ],
)
def test_distinct_project_ids_have_distinct_deterministic_artifact_stems(
    tmp_path, first_project_id, second_project_id
):
    first_result, boundary = _l_shaped_result(project_id=first_project_id)
    second_result, _ = _l_shaped_result(project_id=second_project_id)

    first_review = create_visual_review_artifacts(first_result, boundary=boundary, output_dir=tmp_path)
    repeated_review = create_visual_review_artifacts(first_result, boundary=boundary, output_dir=tmp_path)
    second_review = create_visual_review_artifacts(second_result, boundary=boundary, output_dir=tmp_path)

    assert first_review.svg_path == repeated_review.svg_path
    assert first_review.svg_path != second_review.svg_path
    assert len(first_review.svg_path.stem) <= 96
    assert len(second_review.svg_path.stem) <= 96


@pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (-1, 100), (100, -1)])
def test_artifact_viewport_dimensions_must_be_positive(tmp_path, width, height):
    result, boundary = _sample_result()

    with pytest.raises(ValueError, match="viewport width and height must be positive"):
        create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path, width=width, height=height)


def test_cli_review_generates_visual_artifacts(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-review",
                "floors": 2,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "neighborhood_commercial",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["needs_iteration"] is True
    for key in ("svg_path", "png_path", "html_path", "report_path"):
        artifact_path = Path(payload[key])
        assert artifact_path.exists()
        assert artifact_path.is_relative_to(output_dir)


def test_run_visual_review_loop_writes_search_history_and_canonical_index(tmp_path):
    mass = MassInput(
        project_id="loop-review",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )

    result = run_visual_review_loop(
        mass,
        floor_index=1,
        use_type="neighborhood_commercial",
        output_dir=tmp_path,
        max_iterations=5,
    )

    assert result.iterations_run == 2
    assert result.final_needs_iteration is False
    assert result.accepted is True
    assert result.termination_reason == "accepted"
    assert result.evaluation_count > result.iterations_run
    assert result.index_json_path == tmp_path / "review.index.json"
    assert result.index_html_path == tmp_path / "index.html"

    reports = [
        json.loads(artifact.report_path.read_text(encoding="utf-8"))
        for artifact in result.artifacts
    ]
    assert [artifact.report_path.parent.name for artifact in result.artifacts] == [
        "iteration_001",
        "iteration_002",
    ]
    assert reports[0]["fingerprint"] != reports[1]["fingerprint"]
    assert reports[0]["accepted"] is False
    assert reports[0]["needs_iteration"] is True
    assert "circulation_missing" in {
        violation["code"] for violation in reports[0]["violations"]
    }
    assert reports[1]["accepted"] is True
    assert reports[1]["needs_iteration"] is False
    assert reports[1]["checks"] == {
        "area": "pass",
        "boundary": "pass",
        "circulation_access": "pass",
        "corridor_width": "not_checked",
        "openings": "not_checked",
        "overlap": "pass",
    }
    assert reports[1]["scores"]["area_score"] < 1
    assert all(
        reports[1]["checks"][name] == "pass"
        for name in ("area", "boundary", "circulation_access", "overlap")
    )
    accepted_html = result.artifacts[1].html_path.read_text(encoding="utf-8")
    assert "passes hard validation" in accepted_html
    assert "Hard Validation Checks" in accepted_html
    assert "Advisory Scores" in accepted_html
    assert "<td>fail</td>" not in accepted_html
    assert reports[1]["parent_id"] is not None
    assert reports[1]["operator"] == "corridor-vertical"
    assert reports[1]["operator_params"]
    assert reports[0]["total_score_delta"] is None
    assert reports[0]["hard_failure_count_delta"] is None
    assert reports[1]["total_score_delta"] == pytest.approx(
        reports[1]["scores"]["total_score"] - reports[0]["scores"]["total_score"]
    )
    assert reports[1]["hard_failure_count_delta"] == (
        reports[1]["hard_failure_count"] - reports[0]["hard_failure_count"]
    )

    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == 1
    assert index["project_id"] == "loop-review"
    assert index["floor_index"] == 1
    assert index["use_type"] == "neighborhood_commercial"
    assert index["accepted"] is True
    assert index["termination_reason"] == "accepted"
    assert index["evaluation_count"] == result.evaluation_count
    assert [entry["iteration"] for entry in index["iterations"]] == [1, 2]
    assert index["score_trend"] == [
        report["scores"]["total_score"] for report in reports
    ]
    assert index["lineage"] == [
        {
            "candidate_id": report["candidate_id"],
            "parent_id": report["parent_id"],
            "operator": report["operator"],
            "operator_params": report["operator_params"],
        }
        for report in reports
    ]
    assert [
        entry["fingerprint"] for entry in index["iterations"]
    ] == [report["fingerprint"] for report in reports]
    assert str(tmp_path.resolve()) not in json.dumps(index)
    for entry in index["iterations"]:
        for relative_path in entry["artifacts"].values():
            assert not Path(relative_path).is_absolute()
            assert (tmp_path / relative_path).exists()

    index_html = result.index_html_path.read_text(encoding="utf-8")
    assert "<h1>" in index_html
    assert "<th" in index_html
    assert "<script" not in index_html.lower()
    for entry in index["iterations"]:
        assert entry["artifacts"]["html"] in index_html


def test_review_index_is_identical_across_output_roots(tmp_path):
    mass = MassInput(
        project_id="deterministic-review",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )

    first = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path / "first", max_iterations=5
    )
    second = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path / "second", max_iterations=5
    )

    first_index = json.loads(first.index_json_path.read_text(encoding="utf-8"))
    second_index = json.loads(second.index_json_path.read_text(encoding="utf-8"))
    assert first_index == second_index


def test_review_loop_iteration_budget_exhaustion_is_not_accepted(tmp_path):
    mass = MassInput(
        project_id="budget-review",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path, max_iterations=1
    )
    index = json.loads((tmp_path / "review.index.json").read_text(encoding="utf-8"))

    assert result.accepted is False
    assert result.final_needs_iteration is True
    assert result.termination_reason == "iteration_budget_exhausted"
    assert index["accepted"] is False
    assert index["needs_iteration"] is True
    assert index["termination_reason"] == "iteration_budget_exhausted"


def test_failed_review_loop_preserves_search_diagnostic(tmp_path, monkeypatch):
    generated, _ = _sample_result()
    search = LoopResult(
        mass=generated.mass,
        program=generated.program,
        best=None,
        iterations=[],
        history=[],
        termination_reason="failed",
        evaluation_count=0,
        error="RuntimeError: evaluator failed",
    )
    monkeypatch.setattr(
        visual_review_service,
        "run_candidate_search",
        lambda *args, **kwargs: search,
    )
    mass = MassInput(
        project_id="failed-review",
        floors=1,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_visual_review_loop(
        mass,
        1,
        "neighborhood_commercial",
        tmp_path,
    )
    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))

    assert result.error == "RuntimeError: evaluator failed"
    assert index["error"] == "RuntimeError: evaluator failed"


def test_review_report_uses_search_iteration_when_best_candidate_is_unchanged(
    tmp_path, monkeypatch
):
    generated, _ = _sample_result()
    candidate = CandidateRecord(
        iteration=1,
        layout=generated.layout,
        validation=generated.validation,
        fingerprint=layout_fingerprint(generated.layout),
        parent_id=None,
        operator="baseline",
        operator_params={"output": Path("relative-artifact")},
    )
    search = LoopResult(
        mass=generated.mass,
        program=generated.program,
        best=candidate,
        iterations=[
            IterationRecord(1, [candidate], candidate, candidate),
            IterationRecord(2, [candidate], candidate, candidate),
        ],
        history=[candidate],
        termination_reason="stagnated",
        evaluation_count=2,
    )
    monkeypatch.setattr(
        visual_review_service, "run_candidate_search", lambda *args, **kwargs: search
    )
    mass = MassInput(
        project_id="visual",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path, max_iterations=2
    )
    reports = [
        json.loads(artifact.report_path.read_text(encoding="utf-8"))
        for artifact in result.artifacts
    ]

    assert [report["iteration"] for report in reports] == [1, 2]
    assert reports[1]["fingerprint"] == reports[0]["fingerprint"]
    assert reports[1]["total_score_delta"] == 0
    assert reports[1]["hard_failure_count_delta"] == 0
    assert reports[0]["operator_params"] == {"output": "relative-artifact"}
    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))
    assert index["iterations"][0]["operator_params"] == {
        "output": "relative-artifact"
    }
    assert index["lineage"][0]["operator_params"] == {
        "output": "relative-artifact"
    }
    assert "relative-artifact" in result.index_html_path.read_text(encoding="utf-8")


def test_cli_loop_review_runs_iterations_and_prints_final_state(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "loop"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-loop",
                "floors": 2,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "loop-review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "neighborhood_commercial",
            "--output-dir",
            str(output_dir),
            "--max-iterations",
            "3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["iterations_run"] == 2
    assert payload["final_needs_iteration"] is False
    assert payload["accepted"] is True
    assert payload["termination_reason"] == "accepted"
    assert Path(payload["index_json_path"]).exists()
    assert Path(payload["index_html_path"]).exists()
    assert all(Path(artifact["html_path"]).exists() for artifact in payload["artifacts"])

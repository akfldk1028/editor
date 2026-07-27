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
from backend.app.modules.generation_loop.service import run_generation_loop
from backend.app.modules.visual_review.service import create_visual_review_artifacts, run_visual_review_loop
from backend.app.schemas.loop import CandidateRecord, IterationRecord, LoopResult
from backend.app.schemas.mass import MassInput


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

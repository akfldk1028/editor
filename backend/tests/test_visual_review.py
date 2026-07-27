import json
import struct
import subprocess
import sys
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.modules.generation_loop.service import run_generation_loop
from backend.app.modules.visual_review.service import create_visual_review_artifacts, run_visual_review_loop
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
    assert report["needs_iteration"] is False
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
    assert review.svg_path.stem.startswith("project-script-alert-1-script-f1")
    assert '<svg onload="alert(1)">' not in review.svg_path.read_text(encoding="utf-8")
    assert "&lt;svg onload=&quot;alert(1)&quot;&gt;" in review.svg_path.read_text(encoding="utf-8")
    html = review.html_path.read_text(encoding="utf-8")
    assert "Project &lt;script&gt;alert(1)&lt;/script&gt;" in html
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    for artifact in report["artifacts"].values():
        assert not Path(artifact).is_absolute()
        assert ".." not in Path(artifact).parts


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
    assert payload["needs_iteration"] is False
    assert (output_dir / "cli-review-f1.svg").exists()
    assert (output_dir / "cli-review-f1.png").exists()
    assert (output_dir / "cli-review-f1.html").exists()
    assert (output_dir / "cli-review-f1.review.json").exists()


def test_run_visual_review_loop_stops_after_first_passing_iteration(tmp_path):
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
        max_iterations=3,
    )

    assert result.iterations_run == 1
    assert result.final_needs_iteration is False
    assert result.artifacts[0].html_path.exists()
    assert (tmp_path / "iteration_001" / "loop-review-f1.review.json").exists()


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
    assert payload["iterations_run"] == 1
    assert payload["final_needs_iteration"] is False
    assert (output_dir / "iteration_001" / "cli-loop-f1.html").exists()

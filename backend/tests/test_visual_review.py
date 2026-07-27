import json
import struct
import subprocess
import sys

from backend.app.modules.generation_loop.service import run_generation_loop
from backend.app.modules.visual_review.service import create_visual_review_artifacts
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

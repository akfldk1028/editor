import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import pytest

import backend.app.cli as cli_module


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_sample_loop_review(
    manifest_name: str,
    use_type: str,
    output_dir: Path,
) -> tuple[dict, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "loop-review",
            "--input",
            str(REPOSITORY_ROOT / "datasets" / "manifests" / manifest_name),
            "--floor",
            "1",
            "--use-type",
            use_type,
            "--output-dir",
            str(output_dir),
            "--max-iterations",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    )
    return json.loads(completed.stdout), json.loads(
        (output_dir / "review.index.json").read_text(encoding="utf-8")
    )


def _assert_index_artifacts_resolve(output_dir: Path, index: dict) -> None:
    assert (output_dir / "index.html").is_file()
    assert index["iterations"]
    for iteration in index["iterations"]:
        for relative_path in iteration["artifacts"].values():
            path = output_dir / relative_path
            assert path.is_file()
            assert path.resolve().is_relative_to(output_dir.resolve())


def _rendered_boundary_points(svg_path: Path) -> list[tuple[float, float]]:
    root = ElementTree.fromstring(svg_path.read_text(encoding="utf-8"))
    polygons = root.findall("{http://www.w3.org/2000/svg}polygon")
    return [
        tuple(float(coordinate) for coordinate in point.split(","))
        for point in polygons[-1].attrib["points"].split()
    ]


def _expected_svg_points(
    points: list[list[float]],
    *,
    width: int = 960,
    height: int = 540,
) -> list[tuple[float, float]]:
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    scale = min((width * 0.86) / (max_x - min_x), (height * 0.82) / (max_y - min_y))
    pad_x = (width - (max_x - min_x) * scale) / 2
    pad_y = (height - (max_y - min_y) * scale) / 2
    return [
        (
            round((x - min_x) * scale + pad_x, 2),
            round(height - ((y - min_y) * scale + pad_y), 2),
        )
        for x, y in points
    ]


def _turn_signs(points: list[tuple[float, float]]) -> list[float]:
    return [
        (points[(index + 1) % len(points)][0] - point[0])
        * (points[(index + 2) % len(points)][1] - points[(index + 1) % len(points)][1])
        - (points[(index + 1) % len(points)][1] - point[1])
        * (points[(index + 2) % len(points)][0] - points[(index + 1) % len(points)][0])
        for index, point in enumerate(points)
    ]


def test_cli_generate_reads_mass_json_and_prints_generation_result(tmp_path):
    input_path = tmp_path / "mass.json"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli",
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
            "generate",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "neighborhood_commercial",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["mass"]["project_id"] == "cli"
    assert payload["program"]["use_type"] == "neighborhood_commercial"
    assert payload["layout"]["candidate_id"] == "cli-f1-baseline"
    assert "total_score" in payload["validation"]


def test_cli_loop_review_honors_max_iterations_and_writes_index(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "review-loop"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-budget",
                "floors": 2,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 1.0},
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
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["iterations_run"] == 1
    assert payload["accepted"] is False
    assert payload["termination_reason"] == "iteration_budget_exhausted"
    assert Path(payload["index_json_path"]) == output_dir / "review.index.json"
    assert Path(payload["index_html_path"]) == output_dir / "index.html"


def test_cli_rectangular_sample_accepts_after_distinct_review_iterations(tmp_path):
    output_dir = tmp_path / "rectangular"

    payload, index = _run_sample_loop_review(
        "sample_mass_office_commercial.json",
        "neighborhood_commercial",
        output_dir,
    )

    assert payload["accepted"] is True
    assert payload["termination_reason"] == "accepted"
    assert index["accepted"] is True
    assert index["termination_reason"] == "accepted"
    assert len(index["iterations"]) >= 2
    fingerprints = [entry["fingerprint"] for entry in index["iterations"]]
    assert len(fingerprints) == len(set(fingerprints))
    assert index["hard_failure_trend"][-1] == 0
    _assert_index_artifacts_resolve(output_dir, index)
    final_svg = output_dir / index["iterations"][-1]["artifacts"]["svg"]
    root = ElementTree.fromstring(final_svg.read_text(encoding="utf-8"))
    circulation = root.find(
        "{http://www.w3.org/2000/svg}polygon[@data-kind='circulation']"
    )
    assert circulation is not None
    assert circulation.attrib["points"] == (
        "602.19,435.12 684.75,435.12 684.75,104.88 602.19,104.88"
    )
    assert _rendered_svg_text(root, "circulation") == "circulation"


def test_cli_concave_sample_reports_truthful_non_acceptance_and_polygon_boundary(tmp_path):
    output_dir = tmp_path / "concave"

    payload, index = _run_sample_loop_review(
        "sample_mass_concave.json",
        "office",
        output_dir,
    )

    assert payload["accepted"] is False
    assert index["accepted"] is False
    assert index["termination_reason"] in {
        "search_exhausted",
        "stagnated",
        "iteration_budget_exhausted",
    }
    assert any(count > 0 for count in index["hard_failure_trend"])
    _assert_index_artifacts_resolve(output_dir, index)

    manifest = json.loads(
        (REPOSITORY_ROOT / "datasets" / "manifests" / "sample_mass_concave.json").read_text(
            encoding="utf-8"
        )
    )
    final_svg = output_dir / index["iterations"][-1]["artifacts"]["svg"]
    boundary_points = _rendered_boundary_points(final_svg)
    assert boundary_points == _expected_svg_points(manifest["footprint_polygon"])
    turns = _turn_signs(boundary_points)
    assert min(turns) < 0 < max(turns)


def _rendered_svg_text(root, kind: str) -> str | None:
    for text in root.findall("{http://www.w3.org/2000/svg}text"):
        if text.attrib.get("data-kind") == kind:
            return text.text
    return None


def test_cli_tiny_positive_mass_does_not_fail_search(tmp_path):
    input_path = tmp_path / "tiny.json"
    output_dir = tmp_path / "tiny-review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "tiny-positive-mass",
                "floors": 1,
                "footprint_polygon": [[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [],
                "use_mix": {"neighborhood_commercial": 1.0},
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
            "5",
        ],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["termination_reason"] != "failed"
    assert payload["error"] is None


def test_cli_failed_loop_prints_diagnostic_json_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    @dataclass(frozen=True)
    class FailedReview:
        termination_reason: str = "failed"
        error: str = "RuntimeError: evaluator failed"

    input_path = tmp_path / "mass.json"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-failed",
                "floors": 1,
                "footprint_polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "site_edges": [],
                "access_candidates": [],
                "use_mix": {"neighborhood_commercial": 1.0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "run_visual_review_loop",
        lambda *args, **kwargs: FailedReview(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "loop-review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "neighborhood_commercial",
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli_module.main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "termination_reason": "failed",
        "error": "RuntimeError: evaluator failed",
    }

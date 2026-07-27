import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree


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

    final_svg = output_dir / index["iterations"][-1]["artifacts"]["svg"]
    root = ElementTree.fromstring(final_svg.read_text(encoding="utf-8"))
    polygons = root.findall("{http://www.w3.org/2000/svg}polygon")
    boundary_points = polygons[-1].attrib["points"].split()
    assert len(boundary_points) == 6

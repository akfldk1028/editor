import json
import subprocess
import sys


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

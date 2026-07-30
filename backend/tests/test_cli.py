import json
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

import backend.app.cli as cli_module
from backend.app.modules.alternative_composer.contracts import StructuralAlternative
from backend.app.modules.building_quality.contracts import (
    AlternativeDiversityReport,
    BuildingQualityReport,
    FloorQualityMetrics,
    VerticalQualityMetrics,
)
from backend.app.modules.local_topology_planner.contracts import (
    TopologyAdjacency,
    TopologyProposal,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.result import BuildingGenerationResult
from backend.app.schemas.visual import BuildingVisualReviewArtifacts
from backend.app.schemas.visual import VisualReviewArtifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_cli_irregular_review_records_task_8_quality_phase_boundary(tmp_path):
    output_dir = tmp_path / "irregular-review"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "irregular-alternatives-review",
            "--input",
            str(
                REPOSITORY_ROOT
                / "datasets"
                / "manifests"
                / "sample_mass_irregular_12v_setback_office.json"
            ),
            "--output-dir",
            str(output_dir),
            "--limit",
            "3",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1, completed.stderr
    report = json.loads(
        (output_dir / "alternatives.review.json").read_text(encoding="utf-8")
    )
    assert report["accepted_count"] == 1
    assert report["quality_thresholds"] == {
        "minimum_floor_coverage": 0.60,
        "maximum_unallocated_ratio": 0.40,
        "maximum_unresolved_label_collisions": 0,
        "minimum_primary_share_factor": 0.75,
    }
    assert report["distinct_structural_count"] == 1
    assert report["distinct_core_count"] == 1
    assert report["distinct_circulation_count"] == 1
    assert report["distinct_candidate_png_count"] == 1
    assert report["unresolved_regulatory_facts"]
    assert "rejected_strategies" in report
    assert report["quality_policy_version"] == "building-quality/v1"
    assert report["pairwise_diversity"] == []
    assert [
        item
        for item in report["rejected_strategies"]
        if item["reason_type"] == "BuildingQualityRejected"
    ] == [
        {
            "strategy": "long_edge_adjacent",
            "reason_type": "BuildingQualityRejected",
            "reason": "legacy: primary_daylight_ratio:0.662530965716/0.7",
        }
    ]
    for alternative in report["alternatives"]:
        quality = alternative["building_quality"]
        assert quality["hard_pass"] is True
        assert 0 <= quality["score"] <= 1
        assert set(quality["component_scores"]) == {
            "daylight",
            "room_form",
            "vertical_stacking",
            "egress",
            "coverage_efficiency",
        }
        assert quality["vertical"]["core_stack_ratio"] >= 0.95
        assert quality["vertical"]["shaft_stack_ratio"] >= 0.90
        for floor in quality["floors"]:
            assert floor["primary_daylight_ratio"] >= 0.70
            assert floor["room_form_pass_ratio"] >= 0.90
        assert set(alternative["fingerprints"]) == {
            "core",
            "circulation",
            "room",
            "structural",
        }
        assert alternative["validation_scores"]
        assert alternative["quality_accepted"] is True
        ordered_hashes = [
            floor["png_sha256"]
            for floor in sorted(
                alternative["floors"],
                key=lambda item: item["floor_index"],
            )
        ]
        assert alternative["candidate_png_fingerprint"] == sha256(
            ":".join(ordered_hashes).encode()
        ).hexdigest()
        assert len(alternative["floors"]) == 3
        for floor in alternative["floors"]:
            assert {
                "floor_index",
                "svg",
                "png",
                "html",
                "review_json",
                "png_sha256",
                "coverage_score",
                "unallocated_ratio",
                "unresolved_label_collision_count",
                "office_space_ratio",
            } <= floor.keys()
            assert floor["coverage_score"] >= 0.60
            assert floor["unallocated_ratio"] == pytest.approx(
                1.0 - floor["coverage_score"],
                abs=0.0001,
            )
            assert floor["unresolved_label_collision_count"] == 0
            assert floor["png_output_size"] == [1920, 1080]
            ratio = floor["office_space_ratio"]
            assert ratio["baseline_prior_share"] > 0
            assert ratio["minimum_primary_share"] == pytest.approx(
                ratio["baseline_prior_share"] * 0.75,
            )
            assert ratio["actual_primary_share"] >= ratio["minimum_primary_share"]
            assert ratio["primary_is_largest_non_core"] is True
            assert ratio["passed"] is True
            for key in ("svg", "png", "html", "review_json"):
                assert (output_dir / floor[key]).is_file()
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "building-quality/v1" in index_html
    assert "Daylight proxy" in index_html
    assert "Room form" in index_html
    assert "Core stack" in index_html
    assert "Shaft stack" in index_html
    assert "Regulatory: not_checked" in index_html


def test_cli_irregular_review_quality_evidence_fast(tmp_path, monkeypatch):
    mass = MassInput(
        project_id="fast-quality-evidence",
        floors=1,
        footprint_polygon=[(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )

    def alternative(
        strategy: str,
        *,
        score: float,
        daylight: float,
        room_form: float,
    ) -> StructuralAlternative:
        floor_result = SimpleNamespace(
            program=SimpleNamespace(floor_index=1),
            layout=SimpleNamespace(
                rooms=(SimpleNamespace(space_type="open_work", room_id="open-work"),)
            ),
            validation=SimpleNamespace(
                room_areas=(
                    SimpleNamespace(room_id="open-work", actual_area=60.0),
                    SimpleNamespace(room_id="tenant", actual_area=40.0),
                    SimpleNamespace(room_id="core", actual_area=20.0),
                )
            ),
        )
        building = object.__new__(BuildingGenerationResult)
        object.__setattr__(building, "floor_results", (floor_result,))
        object.__setattr__(building, "marker", strategy)
        components = tuple(
            sha256(f"{strategy}:{label}".encode()).hexdigest()
            for label in ("core", "circulation", "room")
        )
        return StructuralAlternative(
            strategy=strategy,
            building=building,
            quality_report=BuildingQualityReport(
                policy_version="building-quality/v1",
                hard_pass=True,
                score=score,
                component_scores={
                    "daylight": 0.8123456789,
                    "room_form": 0.9234567891,
                    "vertical_stacking": 0.9456789123,
                    "egress": 1.0,
                    "coverage_efficiency": 0.8345678912,
                },
                floors=(
                    FloorQualityMetrics(
                        floor_index=1,
                        coverage=0.8,
                        primary_daylight_ratio=daylight,
                        room_form_pass_ratio=room_form,
                        worst_aspect_ratio=2.0,
                        narrowest_room_width_m=2.4,
                        egress_status="pass",
                    ),
                ),
                vertical=VerticalQualityMetrics(
                    core_stack_ratio=1.0,
                    shaft_stack_ratio=1.0,
                    wet_service_stack_ratio=0.9,
                    maximum_service_centroid_shift_m=0.2,
                ),
                issues=(),
                unresolved_facts=(),
            ),
            core_fingerprint=components[0],
            circulation_fingerprint=components[1],
            room_fingerprint=components[2],
            structural_fingerprint=sha256(":".join(components).encode()).hexdigest(),
        )

    alternatives = (
        alternative(
            "first & <two>",
            score=0.8123456789,
            daylight=0.7123456789,
            room_form=0.9123456789,
        ),
        alternative(
            "second",
            score=0.8234567891,
            daylight=0.7234567891,
            room_form=0.9234567891,
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "compose_structural_alternatives",
        lambda *_args, **_kwargs: SimpleNamespace(
            alternatives=alternatives,
            rejections=(),
        ),
    )
    monkeypatch.setattr(cli_module, "analyze_mass", lambda _mass: object())
    monkeypatch.setattr(
        cli_module,
        "generate_program_graph",
        lambda *_args, **_kwargs: SimpleNamespace(
            nodes=(
                SimpleNamespace(space_type="open_work", target_area=60.0),
                SimpleNamespace(space_type="tenant", target_area=40.0),
            )
        ),
    )
    render_sizes = []

    def fake_artifacts(building, *, output_dir, width, height, **_kwargs):
        render_sizes.append((width, height))
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        marker = building.marker
        svg_path = target / "floor.svg"
        png_path = target / "floor.png"
        html_path = target / "floor.html"
        floor_report_path = target / "floor.review.json"
        report_path = target / "building.review.json"
        svg_path.write_text("<svg/>", encoding="utf-8")
        png_path.write_bytes(marker.encode())
        html_path.write_text("<div id=\"cad-layer-manager\"></div>", encoding="utf-8")
        floor_report_path.write_text(
            json.dumps(
                {
                    "floor_index": 1,
                    "floor_boundary": [[0, 0], [20, 0], [20, 10], [0, 10]],
                    "scores": {"coverage_score": 0.8, "total_score": 0.4567891234},
                    "render_validation": {"unresolved_label_collision_count": 0},
                    "status_footer": {"png_output_size": [1920, 1080]},
                }
            ),
            encoding="utf-8",
        )
        regulatory = {
            "status": "not_checked",
            "unresolved_facts": ["needs <authority>"],
        }
        report_path.write_text(
            json.dumps({"regulatory_screening": regulatory}),
            encoding="utf-8",
        )
        floor_artifact = VisualReviewArtifacts(
            svg_path=svg_path,
            png_path=png_path,
            html_path=html_path,
            report_path=floor_report_path,
            artifact_links={},
            needs_iteration=False,
            checks={},
            internal_validation={"status": "pass"},
            render_validation={"status": "pass"},
            regulatory_screening=regulatory,
        )
        return BuildingVisualReviewArtifacts(
            index_html_path=target / "index.html",
            report_path=report_path,
            floor_artifacts=(floor_artifact,),
            accepted=True,
            internal_validation={"status": "pass"},
            render_validation={"status": "pass"},
            regulatory_screening=regulatory,
        )

    monkeypatch.setattr(
        cli_module,
        "create_building_visual_review_artifacts",
        fake_artifacts,
    )
    diversity_value = 0.4567891234
    monkeypatch.setattr(
        cli_module,
        "compare_building_diversity",
        lambda first, second: AlternativeDiversityReport(
            first_fingerprint=first.marker,
            second_fingerprint=second.marker,
            core_distance=diversity_value,
            circulation_distance=diversity_value,
            topology_distance=diversity_value,
            area_distribution_distance=diversity_value,
            total_distance=diversity_value,
            nonzero_component_count=4,
            quality_distinct=True,
        ),
    )

    output_dir = tmp_path / "quality-evidence"
    cli_module._run_irregular_alternatives_review(
        SimpleNamespace(output_dir=output_dir, limit=2),
        mass,
    )

    report = json.loads(
        (output_dir / "alternatives.review.json").read_text(encoding="utf-8")
    )
    assert render_sizes == [(1920, 1080), (1920, 1080)]
    assert report["accepted_count"] == 2
    assert len(report["pairwise_diversity"]) == 2 * (2 - 1) // 2
    assert report["pairwise_diversity"] == [
        {
            "first_fingerprint": "first & <two>",
            "second_fingerprint": "second",
            "core_distance": diversity_value,
            "circulation_distance": diversity_value,
            "topology_distance": diversity_value,
            "area_distribution_distance": diversity_value,
            "total_distance": diversity_value,
            "nonzero_component_count": 4,
            "quality_distinct": True,
        }
    ]
    first_quality = report["alternatives"][0]["building_quality"]
    assert first_quality["score"] == 0.8123456789
    assert first_quality["component_scores"] == {
        "daylight": 0.8123456789,
        "room_form": 0.9234567891,
        "vertical_stacking": 0.9456789123,
        "egress": 1.0,
        "coverage_efficiency": 0.8345678912,
    }
    assert first_quality["floors"] == [
        {
            "floor_index": 1,
            "coverage": 0.8,
            "primary_daylight_ratio": 0.7123456789,
            "room_form_pass_ratio": 0.9123456789,
            "worst_aspect_ratio": 2.0,
            "narrowest_room_width_m": 2.4,
            "egress_status": "pass",
        }
    ]
    assert first_quality["vertical"] == {
        "core_stack_ratio": 1.0,
        "shaft_stack_ratio": 1.0,
        "wet_service_stack_ratio": 0.9,
        "maximum_service_centroid_shift_m": 0.2,
    }
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "first &amp; &lt;two&gt;" in index_html
    assert "needs &lt;authority&gt;" in index_html
    assert "Total score</th><td>0.8123" in index_html
    assert "daylight proxy=0.7123 | room form=0.9123" in index_html
    assert "daylight proxy=0.7235 | room form=0.9235" in index_html


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
            "--review-level",
            "zoning",
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


def test_cli_local_topology_review_generates_ranked_png_artifacts(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "local-topology"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-local-topology",
                "floors": 1,
                "footprint_polygon": [
                    [0, 0],
                    [30, 0],
                    [30, 12],
                    [18, 12],
                    [18, 18],
                    [0, 18],
                ],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def propose(_self, program, *, candidate_count, **_context):
        node_ids = tuple(node.node_id for node in program.nodes)
        assert candidate_count == 2
        return (
            TopologyProposal(
                candidate_id="topology-1",
                sequence=node_ids,
                adjacencies=(
                    TopologyAdjacency(
                        "reception",
                        "open_work",
                        "functional_adjacency",
                        1.0,
                    ),
                ),
            ),
            TopologyProposal(
                candidate_id="topology-2",
                sequence=tuple(reversed(node_ids)),
                adjacencies=(
                    TopologyAdjacency(
                        "core",
                        "pantry",
                        "service_adjacent",
                        1.0,
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        cli_module.LocalTopologyPlannerClient,
        "propose",
        propose,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "local-topology-review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "office",
            "--output-dir",
            str(output_dir),
            "--candidate-count",
            "2",
        ],
    )

    cli_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["alternatives"]) == 2
    assert [item["rank"] for item in payload["alternatives"]] == [1, 2]
    assert all(item["geometry_fingerprint"] for item in payload["alternatives"])
    assert payload["planner_input"]["core_geometry_status"] == (
        "unresolved_pre_generation"
    )
    assert (output_dir / "index.html").is_file()
    assert (output_dir / "local-topology.review.json").is_file()
    for item in payload["alternatives"]:
        candidate_dir = output_dir / item["candidate_id"]
        assert (candidate_dir / "index.html").is_file()
        assert len(list(candidate_dir.glob("*.png"))) == 1


def test_cli_local_topology_review_discards_duplicate_geometry(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "deduplicated"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-local-deduplicate",
                "floors": 1,
                "footprint_polygon": [
                    [0, 0],
                    [42, 0],
                    [42, 16],
                    [36, 22],
                    [6, 22],
                    [0, 16],
                ],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def propose(_self, program, *, candidate_count, **_context):
        ids = tuple(node.node_id for node in program.nodes)
        return (
            TopologyProposal(
                "topology-1",
                ids,
                (
                    TopologyAdjacency(
                        "reception",
                        "open_work",
                        "functional_adjacency",
                        1.0,
                    ),
                ),
            ),
            TopologyProposal(
                "topology-2",
                tuple(reversed(ids)),
                (
                    TopologyAdjacency(
                        "core",
                        "pantry",
                        "service_adjacent",
                        1.0,
                    ),
                ),
            ),
        )

    original_generation = cli_module.run_building_generation
    cached = None

    def same_geometry(*args, **kwargs):
        nonlocal cached
        if cached is None:
            cached = original_generation(*args, **kwargs)
        return cached

    monkeypatch.setattr(
        cli_module.LocalTopologyPlannerClient,
        "propose",
        propose,
    )
    monkeypatch.setattr(
        cli_module,
        "run_building_generation",
        same_geometry,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "local-topology-review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "office",
            "--output-dir",
            str(output_dir),
            "--candidate-count",
            "2",
        ],
    )

    cli_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["alternatives"]) == 1
    assert payload["discarded_duplicate_geometry"] == ["topology-2"]


def test_cli_building_review_generates_all_floors(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "building-review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-building",
                "floors": 5,
                "footprint_polygon": [[0, 0], [30, 0], [30, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.2, "office": 0.8},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "building-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["accepted"] is True
    assert payload["internal_validation"]["status"] == "pass"
    assert payload["render_validation"]["status"] == "pass"
    assert payload["regulatory_screening"]["status"] == "not_checked"
    assert len(payload["floor_artifacts"]) == 5
    assert (output_dir / "index.html").is_file()
    assert (output_dir / "building.review.json").is_file()


def test_cli_parses_floor_specific_footprints():
    mass = cli_module._mass_input_from_payload(
        {
            "project_id": "cli-stepped",
            "floors": 3,
            "footprint_polygon": [[0, 0], [30, 0], [30, 20], [0, 20]],
            "floor_footprints": [
                {
                    "floor_index": 1,
                    "footprint_polygon": [
                        [0, 0],
                        [30, 0],
                        [30, 20],
                        [0, 20],
                    ],
                },
                {
                    "floor_index": 2,
                    "footprint_polygon": [
                        [0, 0],
                        [24, 0],
                        [24, 16],
                        [0, 16],
                    ],
                },
                {
                    "floor_index": 3,
                    "footprint_polygon": [
                        [0, 0],
                        [18, 0],
                        [18, 12],
                        [0, 12],
                    ],
                },
            ],
            "site_edges": [{"edge_index": 0, "kind": "street"}],
            "access_candidates": [],
            "use_mix": {"office": 1.0},
        }
    )

    assert mass.footprint_for_floor(1) == (
        (0, 0),
        (30, 0),
        (30, 20),
        (0, 20),
    )
    assert mass.footprint_for_floor(2) == (
        (0, 0),
        (24, 0),
        (24, 16),
        (0, 16),
    )


def test_cli_alternatives_review_generates_comparison_and_all_floor_artifacts(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "alternatives-review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-alternatives",
                "floors": 2,
                "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
                "building_code_context": {
                    "jurisdiction": "KR",
                    "effective_date": "2025-10-31",
                    "sprinklered": True,
                },
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "alternatives-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["accepted_count"] == sum(
        alternative["accepted"] for alternative in payload["alternatives"]
    )
    assert completed.returncode == (0 if payload["accepted_count"] >= 2 else 1)
    assert len(payload["alternatives"]) == 2
    assert payload["internal_validation"]["status"] in {"pass", "fail"}
    assert payload["render_validation"]["status"] in {"pass", "fail"}
    assert payload["regulatory_screening"]["status"] == "not_checked"
    assert all(
        alternative["regulatory_screening"]["status"] == "not_checked"
        for alternative in payload["alternatives"]
    )
    assert (output_dir / "index.html").is_file()
    assert (output_dir / "alternatives.review.json").is_file()
    index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "internal concept validation" in index
    assert "render validation" in index
    assert "regulatory screening" in index
    assert ">PASS<" not in index
    for alternative in payload["alternatives"]:
        alternative_dir = output_dir / alternative["alternative_id"]
        assert not Path(alternative["index_html"]).is_absolute()
        assert not Path(alternative["report_json"]).is_absolute()
        assert (
            (output_dir / alternative["index_html"])
            .resolve()
            .is_relative_to(output_dir.resolve())
        )
        assert (alternative_dir / "index.html").is_file()
        assert (alternative_dir / "building.review.json").is_file()
        assert len(list(alternative_dir.glob("floor_*/*.png"))) == 2


def test_cli_alternatives_review_preserves_infeasible_family_rejection(tmp_path):
    input_path = tmp_path / "infeasible.json"
    output_dir = tmp_path / "infeasible-review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-<infeasible>",
                "floors": 2,
                "footprint_polygon": [[0, 0], [18, 0], [18, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "alternatives-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["alternatives"] == []
    assert payload["rejected_families"] == [
        {
            "family": "conservative_redundant_two_stair",
            "reasons": [
                ("concept-basic footprint requires width >= 20.0 m and depth >= 10.0 m")
            ],
        }
    ]
    report = json.loads(
        (output_dir / "alternatives.review.json").read_text(encoding="utf-8")
    )
    assert report["rejected_families"] == payload["rejected_families"]
    page = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "conservative_redundant_two_stair" in page
    assert "width &gt;= 20.0 m" in page
    assert "cli-&lt;infeasible&gt;" in page
    assert "<infeasible>" not in page


def test_cli_alternatives_count_and_exit_include_render_validation(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "alternatives"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-alternative-render",
                "floors": 1,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def alternative(index):
        return SimpleNamespace(
            alternative_id=f"alternative-{index}",
            building=object(),
            strategy=f"strategy-{index}",
            rank=index,
            score=1.0 / index,
            accepted=True,
            fingerprints=(),
            core_centroid=(10.0, 5.0),
            circulation_orientation="horizontal",
            circulation_bounds=(0.0, 0.0, 20.0, 2.0),
            circulation_graph_signature="graph",
            tenant_assignment_signature="tenant",
            tenant_count=1,
            tenant_entrance_assignments=(),
            core_public_entrance="entrance",
            design_family_signature="family",
            floor_results=(),
        )

    alternatives = tuple(alternative(index) for index in (1, 2, 3))
    monkeypatch.setattr(
        cli_module,
        "run_building_alternatives",
        lambda _mass: SimpleNamespace(
            alternatives=alternatives,
            accepted_count=3,
            comparisons=(),
        ),
    )

    render_statuses = iter(("fail", "fail", "pass"))

    def fake_artifacts(*_args, output_dir, **_kwargs):
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        render_status = next(render_statuses)
        report_path = target / "building.review.json"
        index_path = target / "index.html"
        report = {
            "internal_validation": {"status": "pass"},
            "render_validation": {"status": render_status},
            "regulatory_screening": {"status": "not_checked"},
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        index_path.write_text("<!doctype html>", encoding="utf-8")
        return BuildingVisualReviewArtifacts(
            index_html_path=index_path,
            report_path=report_path,
            floor_artifacts=(),
            accepted=render_status == "pass",
            internal_validation=report["internal_validation"],
            render_validation=report["render_validation"],
            regulatory_screening=report["regulatory_screening"],
        )

    monkeypatch.setattr(
        cli_module,
        "create_building_visual_review_artifacts",
        fake_artifacts,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend.app.cli",
            "alternatives-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli_module.main()

    assert error.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["accepted_count"] == 1
    assert [item["accepted"] for item in payload["alternatives"]] == [
        False,
        False,
        True,
    ]
    page = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "대안 비교" in page
    assert "순위" in page
    assert "\ufffd" not in page


def test_committed_alternative_review_json_has_no_checkout_absolute_paths():
    checkout = str(Path(__file__).resolve().parents[2]).casefold()
    docs_root = (
        Path(__file__).resolve().parents[2] / "docs" / "plan-alternatives-architectural"
    )

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    offenders = [
        f"{path.relative_to(docs_root)}: {value}"
        for path in docs_root.rglob("*.json")
        for value in strings(json.loads(path.read_text(encoding="utf-8")))
        if checkout in value.casefold()
    ]

    assert offenders == []


def test_cli_building_review_can_use_openai_planner(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "llm-building-review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-llm-building",
                "floors": 2,
                "footprint_polygon": [[0, 0], [24, 0], [24, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
            }
        ),
        encoding="utf-8",
    )

    class FakePlanner:
        provider = "openai"
        model = "gpt-building"
        last_response_id = None

        def complete_json(self, *, system_prompt, user_payload):
            self.last_response_id = "resp_building_123"
            return json.dumps(
                {
                    "project_id": user_payload["project_id"],
                    "assignments": [
                        {
                            "floor_index": 1,
                            "use_type": "neighborhood_commercial",
                        },
                        {"floor_index": 2, "use_type": "office"},
                    ],
                }
            )

    monkeypatch.setattr(
        cli_module,
        "OpenAIResponsesPlannerClient",
        FakePlanner,
        raising=False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "building-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--planner",
            "openai",
        ],
    )

    cli_module.main()

    payload = json.loads(capsys.readouterr().out)
    report = json.loads(
        (output_dir / "building.review.json").read_text(encoding="utf-8")
    )
    assert payload["accepted"] is True
    assert report["assignment_source"] == "structured"
    assert report["planner_provenance"] == {
        "planner_mode": "structured",
        "provider": "openai",
        "model": "gpt-building",
        "response_id": "resp_building_123",
        "validated_assignments": [
            {"floor_index": 1, "use_type": "neighborhood_commercial"},
            {"floor_index": 2, "use_type": "office"},
        ],
    }


def test_cli_openai_planner_failure_returns_diagnostic_json(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "mass.json"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-llm-failure",
                "floors": 1,
                "footprint_polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
                "site_edges": [],
                "access_candidates": [],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    class FailingPlanner:
        def complete_json(self, **kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        cli_module,
        "OpenAIResponsesPlannerClient",
        FailingPlanner,
        raising=False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "building-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(tmp_path / "unused"),
            "--planner",
            "openai",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli_module.main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "accepted": False,
        "planner": "openai",
        "error": "RuntimeError: provider unavailable",
        "internal_validation": {"status": "fail"},
        "render_validation": {"status": "fail"},
        "regulatory_screening": {
            "status": "not_checked",
            "unresolved_facts": ["generation_failed"],
        },
    }


def test_cli_loop_review_openai_persists_provenance_in_index_and_floor_report(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "llm-loop-review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-llm-loop",
                "floors": 2,
                "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
            }
        ),
        encoding="utf-8",
    )

    class FakePlanner:
        provider = "openai"

        def __init__(self, model=None):
            self.model = model or "gpt-default"
            self.last_response_id = None

        def complete_json(self, *, system_prompt, user_payload):
            self.last_response_id = "resp_loop_123"
            return json.dumps(
                {
                    "project_id": user_payload["project_id"],
                    "assignments": [
                        {
                            "floor_index": 1,
                            "use_type": "neighborhood_commercial",
                        },
                        {"floor_index": 2, "use_type": "office"},
                    ],
                }
            )

    monkeypatch.setattr(cli_module, "OpenAIResponsesPlannerClient", FakePlanner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "loop-review",
            "--input",
            str(input_path),
            "--floor",
            "2",
            "--use-type",
            "office",
            "--output-dir",
            str(output_dir),
            "--planner",
            "openai",
            "--llm-model",
            "gpt-loop",
        ],
    )

    cli_module.main()

    payload = json.loads(capsys.readouterr().out)
    index = json.loads((output_dir / "review.index.json").read_text(encoding="utf-8"))
    report = json.loads(
        Path(payload["artifacts"][0]["report_path"]).read_text(encoding="utf-8")
    )
    expected = {
        "planner_mode": "structured",
        "provider": "openai",
        "model": "gpt-loop",
        "response_id": "resp_loop_123",
        "validated_assignments": [
            {"floor_index": 1, "use_type": "neighborhood_commercial"},
            {"floor_index": 2, "use_type": "office"},
        ],
    }
    assert payload["accepted"] is True
    assert index["planner_provenance"] == expected
    assert report["planner_provenance"] == expected
    assert report["floor_index"] == 2
    assert report["use_type"] == "office"


def test_cli_zoning_review_rejects_openai_planner(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "mass.json"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "zoning-planner-rejected",
                "floors": 1,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
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
            "office",
            "--output-dir",
            str(tmp_path / "output"),
            "--review-level",
            "zoning",
            "--planner",
            "openai",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli_module.main()

    assert exit_info.value.code == 2
    assert "only supported for concept-basic" in capsys.readouterr().err


def test_cli_loop_review_openai_failure_has_no_deterministic_fallback(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "failed-openai-loop"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "failed-openai-loop",
                "floors": 1,
                "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    class FailingPlanner:
        provider = "openai"
        model = "gpt-failing"
        last_response_id = None

        def complete_json(self, **kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        cli_module,
        "OpenAIResponsesPlannerClient",
        lambda **kwargs: FailingPlanner(),
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
            "office",
            "--output-dir",
            str(output_dir),
            "--planner",
            "openai",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli_module.main()

    assert exit_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["review_level"] == "concept-basic"
    assert payload["accepted"] is False
    assert payload["termination_reason"] == "failed"
    assert payload["artifacts"] == []
    assert payload["error"] == "RuntimeError: provider unavailable"
    assert (output_dir / "review.index.json").is_file()


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
            "--review-level",
            "zoning",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["iterations_run"] == 1
    assert payload["accepted"] is False
    assert payload["internal_validation"]["status"] in {"pass", "fail"}
    assert payload["render_validation"]["status"] in {"pass", "fail"}
    assert payload["regulatory_screening"]["status"] == "not_checked"
    assert payload["termination_reason"] == "iteration_budget_exhausted"
    assert Path(payload["index_json_path"]) == output_dir / "review.index.json"
    assert Path(payload["index_html_path"]) == output_dir / "index.html"


def test_cli_building_review_exits_nonzero_when_render_validation_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "mass.json"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-render-failure",
                "floors": 1,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )
    artifacts = BuildingVisualReviewArtifacts(
        index_html_path=tmp_path / "index.html",
        report_path=tmp_path / "building.review.json",
        floor_artifacts=(),
        accepted=False,
        internal_validation={"status": "pass"},
        render_validation={"status": "fail"},
        regulatory_screening={"status": "not_checked"},
    )
    monkeypatch.setattr(
        cli_module,
        "run_building_generation",
        lambda _mass: SimpleNamespace(accepted=True),
    )
    monkeypatch.setattr(
        cli_module,
        "create_building_visual_review_artifacts",
        lambda *_args, **_kwargs: artifacts,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend.app.cli",
            "building-review",
            "--input",
            str(input_path),
            "--output-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli_module.main()

    assert error.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["accepted"] is False
    assert payload["internal_validation"]["status"] == "pass"
    assert payload["render_validation"]["status"] == "fail"
    assert payload["regulatory_screening"]["status"] == "not_checked"


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
        ".//{http://www.w3.org/2000/svg}polygon[@data-kind='circulation']"
    )
    assert circulation is not None
    assert len(circulation.attrib["points"].split()) == 4
    assert _rendered_svg_text(root, "circulation") == "circulation"


def test_cli_concave_sample_reports_truthful_non_acceptance_and_polygon_boundary(
    tmp_path,
):
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
        (
            REPOSITORY_ROOT / "datasets" / "manifests" / "sample_mass_concave.json"
        ).read_text(encoding="utf-8")
    )
    final_svg = output_dir / index["iterations"][-1]["artifacts"]["svg"]
    boundary_points = _rendered_boundary_points(final_svg)
    assert boundary_points == _expected_svg_points(manifest["footprint_polygon"])
    turns = _turn_signs(boundary_points)
    assert min(turns) < 0 < max(turns)


def _rendered_svg_text(root, kind: str) -> str | None:
    for text in root.findall(".//{http://www.w3.org/2000/svg}text"):
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
            "--review-level",
            "zoning",
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

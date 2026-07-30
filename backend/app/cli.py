from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
from itertools import combinations
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.alternative_composer.service import (
    compose_structural_alternatives,
)
from backend.app.modules.building_quality import (
    AlternativeDiversityReport,
    BuildingQualityReport,
    DEFAULT_QUALITY_POLICY,
    compare_building_diversity,
)
from backend.app.modules.generation_loop.service import (
    _street_segments_for_boundary,
    assign_floors_from_use_mix,
    run_building_alternatives,
    run_building_generation,
    run_generation_loop,
)
from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generator_adapters.graph2plan_raw import (
    Graph2PlanRawConfig,
    Graph2PlanRawError,
    run_graph2plan_raw_benchmark,
)
from backend.app.modules.local_topology_planner.contracts import (
    apply_topology_proposals,
)
from backend.app.modules.local_topology_planner.service import (
    LocalTopologyPlannerClient,
)
from backend.app.modules.llm_planner.openai_client import (
    OpenAIResponsesPlannerClient,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.llm_planner.service import run_llm_building_generation
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
    create_visual_review_artifacts,
    run_visual_review_loop,
)
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import (
    BuildingCodeContext,
    FloorCodeContext,
    FloorFootprint,
    MassInput,
)

_IRREGULAR_MINIMUM_FLOOR_COVERAGE = 0.60
_IRREGULAR_MAXIMUM_UNALLOCATED_RATIO = 0.40
_IRREGULAR_MAXIMUM_LABEL_COLLISIONS = 0
_IRREGULAR_MINIMUM_PRIMARY_SHARE_FACTOR = 0.75


def _mass_input_from_payload(payload: dict) -> MassInput:
    context_payload = payload.get("building_code_context")
    context = None
    if context_payload is not None:
        if not isinstance(context_payload, dict):
            raise TypeError("building_code_context must be an object")
        floor_payloads = context_payload.get("floor_facts", [])
        if not isinstance(floor_payloads, list):
            raise TypeError("building_code_context.floor_facts must be a list")
        context = BuildingCodeContext(
            jurisdiction=context_payload.get("jurisdiction"),
            effective_date=context_payload.get("effective_date"),
            floor_to_floor_height_m=context_payload.get("floor_to_floor_height_m"),
            sprinklered=context_payload.get("sprinklered"),
            fire_resistant=context_payload.get("fire_resistant"),
            qualifying_sprinkler_protection=context_payload.get(
                "qualifying_sprinkler_protection"
            ),
            travel_construction_class=context_payload.get("travel_construction_class"),
            travel_limit_classification=context_payload.get(
                "travel_limit_classification"
            ),
            floor_facts=tuple(
                FloorCodeContext(
                    floor_index=fact["floor_index"],
                    occupancy=fact.get("occupancy"),
                    occupant_load=fact.get("occupant_load"),
                    above_grade=fact.get("above_grade"),
                    occupancy_category=fact.get("occupancy_category"),
                    story_number=fact.get("story_number"),
                    habitable_area_m2=fact.get("habitable_area_m2"),
                    is_evacuation_floor=fact.get("is_evacuation_floor"),
                )
                for fact in floor_payloads
            ),
        )
    floor_footprint_payloads = payload.get("floor_footprints", [])
    if not isinstance(floor_footprint_payloads, list):
        raise TypeError("floor_footprints must be a list")
    return MassInput(
        project_id=payload["project_id"],
        floors=int(payload["floors"]),
        footprint_polygon=[tuple(point) for point in payload["footprint_polygon"]],
        site_edges=list(payload.get("site_edges", [])),
        access_candidates=list(payload.get("access_candidates", [])),
        use_mix=dict(payload.get("use_mix", {})),
        building_code_context=context,
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=int(record["floor_index"]),
                footprint_polygon=tuple(
                    tuple(point) for point in record["footprint_polygon"]
                ),
            )
            for record in floor_footprint_payloads
        ),
    )


def _aggregate_review_status(records: list[dict], key: str) -> dict:
    statuses = [record[key]["status"] for record in records]
    if statuses and all(status == "pass" for status in statuses):
        status = "pass"
    elif any(status == "fail" for status in statuses):
        status = "fail"
    else:
        status = "not_checked"
    return {"status": status}


def _serialize_quality_evidence(
    report: BuildingQualityReport | AlternativeDiversityReport,
) -> dict:
    """Convert immutable quality reports into JSON-safe review evidence."""
    serialized = to_jsonable(report)
    if not isinstance(serialized, dict):
        raise TypeError("quality evidence must serialize to an object")
    return serialized


def _quality_table_html(item: dict) -> str:
    quality = item["building_quality"]
    components = quality["component_scores"]
    vertical = quality["vertical"]
    regulatory = item["regulatory_screening"]
    unresolved_facts = ", ".join(regulatory.get("unresolved_facts", ())) or "-"
    rows = (
        ("Quality policy", quality["policy_version"]),
        ("Hard pass", str(quality["hard_pass"]).lower()),
        ("Total score", f"{quality['score']:.4f}"),
        ("Daylight proxy", f"{components['daylight']:.4f}"),
        ("Room form", f"{components['room_form']:.4f}"),
        ("Vertical stacking", f"{components['vertical_stacking']:.4f}"),
        ("Egress", f"{components['egress']:.4f}"),
        ("Coverage/efficiency", f"{components['coverage_efficiency']:.4f}"),
        ("Core stack", f"{vertical['core_stack_ratio']:.4f}"),
        ("Shaft stack", f"{vertical['shaft_stack_ratio']:.4f}"),
        ("Wet-service stack", f"{vertical['wet_service_stack_ratio']:.4f}"),
        ("Regulatory", f"Regulatory: {regulatory['status']}"),
        ("Unresolved regulatory facts", unresolved_facts),
    )
    return (
        '<table class="quality"><tbody>'
        + "".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
            for label, value in rows
        )
        + "</tbody></table>"
    )


def _floor_caption_html(item: dict, floor: dict) -> str:
    quality_floor = next(
        (
            candidate
            for candidate in item["building_quality"]["floors"]
            if candidate["floor_index"] == floor["floor_index"]
        ),
        None,
    )
    if quality_floor is None:
        raise ValueError("floor quality evidence is missing")
    return (
        f"<figcaption>Floor {floor['floor_index']} | "
        f"coverage={floor['coverage_score']:.4f} | "
        f"unallocated={floor['unallocated_ratio']:.4f} | "
        "open work share="
        f"{floor['office_space_ratio']['actual_primary_share']:.4f} | "
        "daylight proxy="
        f"{quality_floor['primary_daylight_ratio']:.4f} | "
        f"room form={quality_floor['room_form_pass_ratio']:.4f}"
        "</figcaption>"
    )


def _run_irregular_alternatives_review(args, mass: MassInput) -> None:
    composition = compose_structural_alternatives(mass, limit=args.limit)
    analysis = analyze_mass(mass)
    baseline_primary_shares = {}
    for floor_index in range(1, mass.floors + 1):
        prior = generate_program_graph(
            analysis,
            floor_index=floor_index,
            use_type="office",
        )
        non_core_targets = [
            float(node.target_area)
            for node in prior.nodes
            if node.space_type != "core"
        ]
        primary_target = next(
            float(node.target_area)
            for node in prior.nodes
            if node.space_type == "open_work"
        )
        baseline_primary_shares[floor_index] = (
            primary_target / sum(non_core_targets)
        )
    target = Path(args.output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    summaries = []
    unresolved_regulatory_facts: set[str] = set()

    for rank, alternative in enumerate(composition.alternatives, start=1):
        candidate_id = f"alternative-{rank:02d}"
        artifacts = create_building_visual_review_artifacts(
            alternative.building,
            boundary=mass.footprint_polygon,
            output_dir=target / candidate_id,
            width=1920,
            height=1080,
            render_style="architectural",
        )
        building_report = json.loads(
            artifacts.report_path.read_text(encoding="utf-8")
        )
        unresolved_regulatory_facts.update(
            building_report["regulatory_screening"].get("unresolved_facts", [])
        )
        floors = []
        floor_scores = []
        for floor_artifact in artifacts.floor_artifacts:
            floor_report = json.loads(
                floor_artifact.report_path.read_text(encoding="utf-8")
            )
            floor_index = int(floor_report["floor_index"])
            floor_result = next(
                floor
                for floor in alternative.building.floor_results
                if floor.program.floor_index == floor_index
            )
            copied_png = target / (
                f"{candidate_id}-floor-{floor_index:03d}.png"
            )
            shutil.copyfile(floor_artifact.png_path, copied_png)
            png_sha256 = hashlib.sha256(copied_png.read_bytes()).hexdigest()
            scores = floor_report["scores"]
            coverage_score = float(scores["coverage_score"])
            unresolved_label_collisions = int(
                floor_report["render_validation"][
                    "unresolved_label_collision_count"
                ]
            )
            primary_room = next(
                room
                for room in floor_result.layout.rooms
                if room.space_type == "open_work"
            )
            primary_area = next(
                float(metric.actual_area)
                for metric in floor_result.validation.room_areas
                if metric.room_id == primary_room.room_id
            )
            non_core_areas = {
                metric.room_id: float(metric.actual_area)
                for metric in floor_result.validation.room_areas
                if metric.room_id != "core"
            }
            non_core_total = sum(non_core_areas.values())
            actual_primary_share = primary_area / non_core_total
            baseline_primary_share = baseline_primary_shares[floor_index]
            minimum_primary_share = (
                baseline_primary_share
                * _IRREGULAR_MINIMUM_PRIMARY_SHARE_FACTOR
            )
            primary_is_largest = primary_area == max(non_core_areas.values())
            office_space_ratio_passed = (
                primary_is_largest
                and actual_primary_share >= minimum_primary_share
            )
            floor_scores.append(
                {"floor_index": floor_index, **scores}
            )
            floors.append(
                {
                    "floor_index": floor_index,
                    "svg": str(floor_artifact.svg_path.relative_to(target)),
                    "png": str(copied_png.relative_to(target)),
                    "html": str(floor_artifact.html_path.relative_to(target)),
                    "review_json": str(
                        floor_artifact.report_path.relative_to(target)
                    ),
                    "png_sha256": png_sha256,
                    "floor_boundary": floor_report["floor_boundary"],
                    "coverage_score": coverage_score,
                    "unallocated_ratio": round(1.0 - coverage_score, 4),
                    "unresolved_label_collision_count": (
                        unresolved_label_collisions
                    ),
                    "png_output_size": floor_report["status_footer"][
                        "png_output_size"
                    ],
                    "office_space_ratio": {
                        "baseline_prior_share": baseline_primary_share,
                        "minimum_primary_share": minimum_primary_share,
                        "actual_primary_share": actual_primary_share,
                        "primary_open_work_area": primary_area,
                        "non_core_program_area": non_core_total,
                        "primary_is_largest_non_core": primary_is_largest,
                        "passed": office_space_ratio_passed,
                    },
                }
            )
        ordered_png_hashes = [
            floor["png_sha256"]
            for floor in sorted(floors, key=lambda item: item["floor_index"])
        ]
        candidate_png_fingerprint = hashlib.sha256(
            ":".join(ordered_png_hashes).encode()
        ).hexdigest()
        coverage_passed = all(
            floor["coverage_score"] >= _IRREGULAR_MINIMUM_FLOOR_COVERAGE
            and floor["unallocated_ratio"]
            <= _IRREGULAR_MAXIMUM_UNALLOCATED_RATIO
            for floor in floors
        )
        label_collision_passed = all(
            floor["unresolved_label_collision_count"]
            <= _IRREGULAR_MAXIMUM_LABEL_COLLISIONS
            for floor in floors
        )
        office_space_ratio_passed = all(
            floor["office_space_ratio"]["passed"] for floor in floors
        )
        quality_accepted = (
            artifacts.accepted
            and coverage_passed
            and label_collision_passed
            and office_space_ratio_passed
        )
        summaries.append(
            {
                "alternative_id": candidate_id,
                "strategy": alternative.strategy,
                "accepted": artifacts.accepted,
                "quality_accepted": quality_accepted,
                "quality_checks": {
                    "floor_coverage": "pass" if coverage_passed else "fail",
                    "label_overlap": (
                        "pass" if label_collision_passed else "fail"
                    ),
                    "office_space_ratio": (
                        "pass" if office_space_ratio_passed else "fail"
                    ),
                },
                "fingerprints": {
                    "core": alternative.core_fingerprint,
                    "circulation": alternative.circulation_fingerprint,
                    "room": alternative.room_fingerprint,
                    "structural": alternative.structural_fingerprint,
                },
                "validation_scores": {
                    "floors": floor_scores,
                    "total_score": sum(
                        item["total_score"] for item in floor_scores
                    ),
                },
                "building_quality": _serialize_quality_evidence(
                    alternative.quality_report
                ),
                "internal_validation": artifacts.internal_validation,
                "render_validation": artifacts.render_validation,
                "regulatory_screening": artifacts.regulatory_screening,
                "index_html": str(
                    artifacts.index_html_path.relative_to(target)
                ),
                "building_review_json": str(
                    artifacts.report_path.relative_to(target)
                ),
                "candidate_png_fingerprint": candidate_png_fingerprint,
                "floors": floors,
            }
        )

    accepted = [item for item in summaries if item["quality_accepted"]]
    distinct_structural_count = len(
        {item["fingerprints"]["structural"] for item in accepted}
    )
    distinct_core_count = len(
        {item["fingerprints"]["core"] for item in accepted}
    )
    distinct_circulation_count = len(
        {item["fingerprints"]["circulation"] for item in accepted}
    )
    distinct_candidate_png_count = len(
        {item["candidate_png_fingerprint"] for item in accepted}
    )
    pairwise_diversity = [
        _serialize_quality_evidence(
            compare_building_diversity(first.building, second.building)
        )
        for first, second in combinations(composition.alternatives, 2)
    ]
    payload = {
        "schema_version": 1,
        "project_id": mass.project_id,
        "quality_policy_version": (
            composition.alternatives[0].quality_report.policy_version
            if composition.alternatives
            else DEFAULT_QUALITY_POLICY.version
        ),
        "accepted_count": len(accepted),
        "distinct_structural_count": distinct_structural_count,
        "distinct_core_count": distinct_core_count,
        "distinct_circulation_count": distinct_circulation_count,
        "distinct_candidate_png_count": distinct_candidate_png_count,
        "distinct_png_count": distinct_candidate_png_count,
        "quality_thresholds": {
            "minimum_floor_coverage": _IRREGULAR_MINIMUM_FLOOR_COVERAGE,
            "maximum_unallocated_ratio": (
                _IRREGULAR_MAXIMUM_UNALLOCATED_RATIO
            ),
            "maximum_unresolved_label_collisions": (
                _IRREGULAR_MAXIMUM_LABEL_COLLISIONS
            ),
            "minimum_primary_share_factor": (
                _IRREGULAR_MINIMUM_PRIMARY_SHARE_FACTOR
            ),
        },
        "alternatives": summaries,
        "pairwise_diversity": pairwise_diversity,
        "rejected_strategies": to_jsonable(composition.rejections),
        "unresolved_regulatory_facts": sorted(unresolved_regulatory_facts),
    }
    (target / "alternatives.review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cards = "".join(
        (
            '<section class="alternative">'
            f"<h2>{html.escape(item['alternative_id'])}: "
            f"{html.escape(item['strategy'])}</h2>"
            f"<p>accepted={str(item['accepted']).lower()} | "
            f"quality accepted={str(item['quality_accepted']).lower()} | "
            f"score={item['validation_scores']['total_score']:.4f}</p>"
            + _quality_table_html(item)
            + '<div class="floors">'
            + "".join(
                (
                    "<figure>"
                    f'<img src="{html.escape(floor["png"], quote=True)}" '
                    f'alt="{html.escape(item["alternative_id"])} '
                    f'floor {floor["floor_index"]}">'
                    + _floor_caption_html(item, floor)
                    + "</figure>"
                )
                for floor in item["floors"]
            )
            + "</div></section>"
        )
        for item in summaries
    )
    (target / "index.html").write_text(
        (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<link rel="icon" href="data:,">'
            "<title>Irregular structural alternatives</title>"
            "<style>*{box-sizing:border-box}body{margin:0;background:#fff;"
            "color:#171717;font:14px Arial,sans-serif}main{max-width:1560px;"
            "margin:auto;padding:24px}h1{font-size:24px}.alternative{"
            "border-top:1px solid #bbb;padding:20px 0}.floors{display:grid;"
            "grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}"
            ".quality{border-collapse:collapse;margin:12px 0;max-width:720px}"
            ".quality th,.quality td{border:1px solid #bbb;padding:5px 8px;"
            "text-align:left}.quality th{background:#f5f5f5}"
            "figure{margin:0}img{display:block;width:100%;height:auto;"
            "background:#fff;border:1px solid #bbb}figcaption{padding:6px 0;"
            "font-weight:700}@media(max-width:900px){.floors{"
            "grid-template-columns:1fr}}</style></head><body><main>"
            f"<h1>{html.escape(mass.project_id)}</h1>{cards}"
            "</main></body></html>"
        ),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    exit_ready = (
        len(accepted) >= 2
        and distinct_structural_count >= 2
        and distinct_core_count >= 2
        and distinct_circulation_count >= 2
        and distinct_candidate_png_count >= 2
    )
    if not exit_ready:
        raise SystemExit(1)


def _run_local_topology_review(args, mass: MassInput) -> None:
    analysis = analyze_mass(mass)
    baseline = generate_program_graph(
        analysis,
        floor_index=args.floor,
        use_type=args.use_type,
    )
    model_path = Path(args.base_model).resolve()
    client = LocalTopologyPlannerClient(
        command=(
            str(Path(args.runtime_python)),
            "-m",
            "backend.app.modules.local_topology_planner.worker",
            "--model-path",
            str(model_path),
        ),
    )
    proposals = client.propose(
        baseline,
        candidate_count=args.candidate_count,
        boundary=mass.footprint_for_floor(args.floor),
        access_candidates=mass.access_candidates,
        street_edge_indices=tuple(
            int(edge["edge_index"])
            for edge in mass.site_edges
            if edge.get("kind") == "street"
        ),
        street_segments=_street_segments_for_boundary(
            mass,
            mass.footprint_for_floor(args.floor),
        ),
    )
    programs = apply_topology_proposals(baseline, proposals)
    assignments = tuple(
        FloorAssignment(
            floor_index=assignment.floor_index,
            use_type=(
                args.use_type
                if assignment.floor_index == args.floor
                else assignment.use_type
            ),
        )
        for assignment in assign_floors_from_use_mix(mass)
    )
    buildings = [
        (
            proposal,
            run_building_generation(
                mass,
                floor_assignments=assignments,
                program_overrides={args.floor: program},
            ),
        )
        for proposal, program in zip(proposals, programs, strict=True)
    ]
    distinct_buildings = []
    seen_geometry: set[str] = set()
    geometry_fingerprints: dict[str, str] = {}
    discarded_duplicate_geometry: list[str] = []
    for proposal, building in buildings:
        floor = next(
            result
            for result in building.floor_results
            if result.program.floor_index == args.floor
        )
        fingerprint = layout_fingerprint(floor.layout)
        if fingerprint in seen_geometry:
            discarded_duplicate_geometry.append(proposal.candidate_id)
            continue
        seen_geometry.add(fingerprint)
        geometry_fingerprints[proposal.candidate_id] = fingerprint
        distinct_buildings.append((proposal, building))
    buildings = distinct_buildings
    buildings.sort(
        key=lambda item: (
            0
            if next(
                floor
                for floor in item[1].floor_results
                if floor.program.floor_index == args.floor
            ).validation.accepted
            else 1,
            next(
                floor
                for floor in item[1].floor_results
                if floor.program.floor_index == args.floor
            ).validation.hard_violation_count,
            next(
                floor
                for floor in item[1].floor_results
                if floor.program.floor_index == args.floor
            ).validation.violation_score,
            -next(
                floor
                for floor in item[1].floor_results
                if floor.program.floor_index == args.floor
            ).validation.total_score,
            item[0].candidate_id,
        )
    )

    target = Path(args.output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    boundary = mass.footprint_for_floor(args.floor)
    summaries: list[dict] = []
    for rank, (proposal, building) in enumerate(buildings, start=1):
        result = next(
            floor
            for floor in building.floor_results
            if floor.program.floor_index == args.floor
        )
        candidate_dir = target / proposal.candidate_id
        artifacts = create_visual_review_artifacts(
            result,
            boundary=list(boundary),
            output_dir=candidate_dir,
            run_root=target,
        )
        candidate_index = candidate_dir / "index.html"
        candidate_index.write_text(
            (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                f"<title>{html.escape(proposal.candidate_id)}</title>"
                "</head><body style=\"margin:0;background:#fff\">"
                f"<iframe src=\"{html.escape(artifacts.html_path.name)}\" "
                "style=\"width:100%;height:100vh;border:0\"></iframe>"
                "</body></html>"
            ),
            encoding="utf-8",
        )
        summaries.append(
            {
                "candidate_id": proposal.candidate_id,
                "rank": rank,
                "accepted": result.validation.accepted,
                "termination_reason": (
                    "accepted" if result.validation.accepted else "rejected"
                ),
                "score": result.validation.total_score,
                "hard_violation_count": (
                    result.validation.hard_violation_count
                ),
                "program_source": result.program.source,
                "sequence": list(proposal.sequence),
                "adjacencies": to_jsonable(proposal.adjacencies),
                "effective_adjacencies": to_jsonable(result.program.edges),
                "geometry_fingerprint": geometry_fingerprints[
                    proposal.candidate_id
                ],
                "png": str(artifacts.png_path.relative_to(target)),
                "html": str(candidate_index.relative_to(target)),
                "review_json": str(artifacts.report_path.relative_to(target)),
                "internal_validation": artifacts.internal_validation,
                "render_validation": artifacts.render_validation,
                "regulatory_screening": artifacts.regulatory_screening,
            }
        )
    report = {
        "schema_version": 1,
        "project_id": mass.project_id,
        "planner": "local_qwen3_4b_topology",
        "model_path": str(model_path),
        "generation": {"seed": 17, "max_attempts": 3},
        "floor_index": args.floor,
        "use_type": args.use_type,
        "planner_input": {
            "boundary": to_jsonable(mass.footprint_for_floor(args.floor)),
            "street_edge_indices": [
                int(edge["edge_index"])
                for edge in mass.site_edges
                if edge.get("kind") == "street"
            ],
            "street_segments": to_jsonable(
                _street_segments_for_boundary(
                    mass,
                    mass.footprint_for_floor(args.floor),
                )
            ),
            "access_candidates": to_jsonable(mass.access_candidates),
            "baseline_program": to_jsonable(baseline),
            "core_geometry_status": "unresolved_pre_generation",
        },
        "accepted_count": sum(item["accepted"] for item in summaries),
        "requested_candidate_count": args.candidate_count,
        "distinct_geometry_count": len(summaries),
        "discarded_duplicate_geometry": discarded_duplicate_geometry,
        "alternatives": summaries,
    }
    report_path = target / "local-topology.review.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = "\n".join(
        (
            "<section style=\"border-top:1px solid #ddd;padding:24px 0\">"
            f"<h2 style=\"font-size:18px\">#{item['rank']} "
            f"{html.escape(item['candidate_id'])}</h2>"
            f"<p>accepted={str(item['accepted']).lower()} | "
            f"score={item['score']:.4f} | "
            f"hard violations={item['hard_violation_count']}</p>"
            f"<a href=\"{html.escape(item['html'])}\">"
            f"<img src=\"{html.escape(item['png'])}\" "
            "style=\"max-width:100%;height:auto\" "
            f"alt=\"{html.escape(item['candidate_id'])}\"></a>"
            "</section>"
        )
        for item in summaries
    )
    (target / "index.html").write_text(
        (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<title>Local topology review</title></head>"
            "<body style=\"margin:0;background:#fff;color:#111;"
            "font:14px Arial,sans-serif\"><main style=\"max-width:1100px;"
            "margin:auto;padding:24px\"><h1 style=\"font-size:24px\">"
            f"{html.escape(mass.project_id)} local topology review</h1>"
            f"{rows}</main></body></html>"
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="plan")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--input", required=True)
    generate.add_argument("--floor", required=True, type=int)
    generate.add_argument("--use-type", required=True)

    review = subparsers.add_parser("review")
    review.add_argument("--input", required=True)
    review.add_argument("--floor", required=True, type=int)
    review.add_argument("--use-type", required=True)
    review.add_argument("--output-dir", required=True)

    loop_review = subparsers.add_parser("loop-review")
    loop_review.add_argument("--input", required=True)
    loop_review.add_argument("--floor", required=True, type=int)
    loop_review.add_argument("--use-type", required=True)
    loop_review.add_argument("--output-dir", required=True)
    loop_review.add_argument("--max-iterations", type=int, default=3)
    loop_review.add_argument(
        "--review-level",
        choices=("concept-basic", "zoning"),
        default="concept-basic",
    )
    loop_review.add_argument(
        "--planner",
        choices=("deterministic", "openai"),
        default=None,
    )
    loop_review.add_argument("--llm-model")

    building_review = subparsers.add_parser("building-review")
    building_review.add_argument("--input", required=True)
    building_review.add_argument("--output-dir", required=True)
    building_review.add_argument(
        "--planner",
        choices=("deterministic", "openai"),
        default="deterministic",
    )
    building_review.add_argument("--llm-model")

    alternatives_review = subparsers.add_parser("alternatives-review")
    alternatives_review.add_argument("--input", required=True)
    alternatives_review.add_argument("--output-dir", required=True)
    alternatives_review.add_argument(
        "--render-style",
        choices=("review", "architectural"),
        default="architectural",
    )
    irregular_alternatives_review = subparsers.add_parser(
        "irregular-alternatives-review"
    )
    irregular_alternatives_review.add_argument("--input", required=True)
    irregular_alternatives_review.add_argument("--output-dir", required=True)
    irregular_alternatives_review.add_argument("--limit", type=int, default=3)
    graph2plan_raw = subparsers.add_parser("graph2plan-raw")
    graph2plan_raw.add_argument("--repository", required=True)
    graph2plan_raw.add_argument("--checkpoint", required=True)
    graph2plan_raw.add_argument("--data", required=True)
    graph2plan_raw.add_argument("--output-dir", required=True)
    graph2plan_raw.add_argument(
        "--record-index",
        required=True,
        type=int,
    )
    graph2plan_raw.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
    )
    local_topology = subparsers.add_parser("local-topology-review")
    local_topology.add_argument("--input", required=True)
    local_topology.add_argument("--floor", required=True, type=int)
    local_topology.add_argument("--use-type", required=True)
    local_topology.add_argument("--output-dir", required=True)
    local_topology.add_argument(
        "--candidate-count",
        type=int,
        choices=range(2, 7),
        default=4,
    )
    local_topology.add_argument(
        "--runtime-python",
        default=os.environ.get(
            "PLAN_LOCAL_LLM_PYTHON",
            r"C:\Users\User\anaconda3\envs\maas-qwen\python.exe",
        ),
    )
    local_topology.add_argument(
        "--base-model",
        default=str(
            Path("clone") / "models" / "Qwen3-4B-Instruct-2507"
        ),
    )

    args = parser.parse_args()
    if args.command == "graph2plan-raw":
        try:
            artifacts = run_graph2plan_raw_benchmark(
                Graph2PlanRawConfig(
                    repository_path=Path(args.repository),
                    checkpoint_path=Path(args.checkpoint),
                    data_path=Path(args.data),
                    output_path=Path(args.output_dir),
                    record_index=args.record_index,
                    device=args.device,
                )
            )
        except (Graph2PlanRawError, ValueError) as error:
            print(
                json.dumps(
                    {
                        "backend": "graph2plan",
                        "scope": "raw_forward_only",
                        "candidate_status": "RAW_OUTPUT_NOT_VALIDATED",
                        "raw_forward_completed": False,
                        "error": str(error),
                    },
                    ensure_ascii=False,
                )
            )
            raise SystemExit(1) from None
        print(
            json.dumps(
                {
                    "backend": "graph2plan",
                    "scope": artifacts.scope,
                    "candidate_status": "RAW_OUTPUT_NOT_VALIDATED",
                    "arrays_path": str(artifacts.arrays_path),
                    "input_path": str(artifacts.input_path),
                    "png_path": str(artifacts.png_path),
                    "metadata_path": str(artifacts.metadata_path),
                    "metadata_sha256": artifacts.metadata_sha256,
                },
                ensure_ascii=False,
            )
        )
        return
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    mass = _mass_input_from_payload(payload)
    if args.command == "local-topology-review":
        _run_local_topology_review(args, mass)
    elif args.command == "irregular-alternatives-review":
        _run_irregular_alternatives_review(args, mass)
    elif args.command == "generate":
        result = run_generation_loop(
            mass, floor_index=args.floor, use_type=args.use_type
        )
        print(json.dumps(to_jsonable(result), ensure_ascii=False))
    elif args.command == "review":
        result = run_generation_loop(
            mass, floor_index=args.floor, use_type=args.use_type
        )
        artifacts = create_visual_review_artifacts(
            result,
            boundary=mass.footprint_polygon,
            output_dir=args.output_dir,
        )
        print(json.dumps(to_jsonable(artifacts), ensure_ascii=False))
    elif args.command == "loop-review":
        if args.review_level == "zoning" and (
            args.planner is not None or args.llm_model is not None
        ):
            parser.error("planner options are only supported for concept-basic review")
        planner_client = None
        if args.planner == "openai":
            planner_client = (
                OpenAIResponsesPlannerClient(model=args.llm_model)
                if args.llm_model
                else OpenAIResponsesPlannerClient()
            )
        result = run_visual_review_loop(
            mass,
            floor_index=args.floor,
            use_type=args.use_type,
            output_dir=args.output_dir,
            max_iterations=args.max_iterations,
            review_level=args.review_level,
            planner_client=planner_client,
        )
        print(json.dumps(to_jsonable(result), ensure_ascii=False))
        if result.termination_reason == "failed" or (
            result.review_level == "concept-basic" and not result.accepted
        ):
            raise SystemExit(1)
    elif args.command == "building-review":
        if args.planner == "openai":
            planner = (
                OpenAIResponsesPlannerClient(model=args.llm_model)
                if args.llm_model
                else OpenAIResponsesPlannerClient()
            )
            try:
                result = run_llm_building_generation(mass, planner)
            except Exception as error:
                print(
                    json.dumps(
                        {
                            "accepted": False,
                            "planner": "openai",
                            "error": f"{type(error).__name__}: {error}",
                            "internal_validation": {"status": "fail"},
                            "render_validation": {"status": "fail"},
                            "regulatory_screening": {
                                "status": "not_checked",
                                "unresolved_facts": ["generation_failed"],
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                raise SystemExit(1) from error
        else:
            result = run_building_generation(mass)
        artifacts = create_building_visual_review_artifacts(
            result,
            boundary=mass.footprint_polygon,
            output_dir=args.output_dir,
        )
        print(json.dumps(to_jsonable(artifacts), ensure_ascii=False))
        if not artifacts.accepted:
            raise SystemExit(1)
    elif args.command == "alternatives-review":
        result = run_building_alternatives(mass)
        target = Path(args.output_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)
        summaries = []
        for alternative in result.alternatives:
            artifacts = create_building_visual_review_artifacts(
                alternative.building,
                boundary=mass.footprint_polygon,
                output_dir=target / alternative.alternative_id,
                render_style=args.render_style,
            )
            building_report = json.loads(
                artifacts.report_path.read_text(encoding="utf-8")
            )
            summaries.append(
                {
                    "alternative_id": alternative.alternative_id,
                    "strategy": alternative.strategy,
                    "rank": alternative.rank,
                    "score": alternative.score,
                    "accepted": artifacts.accepted,
                    "internal_validation": building_report["internal_validation"],
                    "render_validation": building_report["render_validation"],
                    "regulatory_screening": building_report["regulatory_screening"],
                    "fingerprints": alternative.fingerprints,
                    "core_centroid": alternative.core_centroid,
                    "circulation_orientation": alternative.circulation_orientation,
                    "circulation_bounds": alternative.circulation_bounds,
                    "circulation_graph_signature": (
                        alternative.circulation_graph_signature
                    ),
                    "tenant_assignment_signature": (
                        alternative.tenant_assignment_signature
                    ),
                    "tenant_count": alternative.tenant_count,
                    "tenant_entrance_assignments": (
                        alternative.tenant_entrance_assignments
                    ),
                    "core_public_entrance": alternative.core_public_entrance,
                    "design_family_signature": alternative.design_family_signature,
                    "render_style": args.render_style,
                    "floor_count": len(alternative.floor_results),
                    "index_html": str(artifacts.index_html_path.relative_to(target)),
                    "report_json": str(artifacts.report_path.relative_to(target)),
                }
            )
        accepted_count = sum(summary["accepted"] for summary in summaries)
        rejected_families = to_jsonable(getattr(result, "rejected_families", ()))
        payload = {
            "schema_version": 1,
            "project_id": mass.project_id,
            "accepted_count": accepted_count,
            "internal_validation": _aggregate_review_status(
                summaries,
                "internal_validation",
            ),
            "render_validation": _aggregate_review_status(
                summaries,
                "render_validation",
            ),
            "regulatory_screening": _aggregate_review_status(
                summaries,
                "regulatory_screening",
            ),
            "alternatives": summaries,
            "comparisons": to_jsonable(result.comparisons),
            "rejected_families": rejected_families,
        }
        report_path = target / "alternatives.review.json"
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows = "\n".join(
            (
                "<tr>"
                f"<td>{summary['rank']}</td>"
                f'<td><a href="{summary["alternative_id"]}/index.html">'
                f"{html.escape(summary['alternative_id'])}</a></td>"
                f"<td>{html.escape(summary['strategy'])}</td>"
                f"<td>{summary['score']:.4f}</td>"
                f"<td>{html.escape(summary['internal_validation']['status'])}</td>"
                f"<td>{html.escape(summary['render_validation']['status'])}</td>"
                f"<td>{html.escape(summary['regulatory_screening']['status'].replace('_', ' '))}</td>"
                f"<td>{html.escape(str(tuple(summary['core_centroid'])))}</td>"
                f"<td>{html.escape(summary['circulation_orientation'])}</td>"
                "</tr>"
            )
            for summary in summaries
        )
        rejected_family_review = (
            "<section><h2>Rejected alternative families</h2><ul>"
            + "".join(
                (
                    f"<li><strong>{html.escape(item['family'])}</strong>"
                    "<ul>"
                    + "".join(
                        f"<li>{html.escape(reason)}</li>" for reason in item["reasons"]
                    )
                    + "</ul></li>"
                )
                for item in rejected_families
            )
            + "</ul></section>"
            if rejected_families
            else ""
        )
        (target / "index.html").write_text(
            (
                '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                '<link rel="icon" href="data:,">'
                "<title>Floor-plan alternatives</title>"
                "<style>body{font-family:Arial,sans-serif;margin:24px;color:#171717}"
                "table{border-collapse:collapse;width:100%}th,td{padding:9px;"
                "border:1px solid #bbb;text-align:left}th{background:#f3f3f3}"
                "a{color:#0056b3}</style></head><body>"
                f"<h1>{html.escape(mass.project_id)} 대안 비교</h1>"
                "<table><thead><tr><th>순위</th><th>대안</th><th>전략</th>"
                "<th>점수</th><th>internal concept validation</th>"
                "<th>render validation</th><th>regulatory screening</th>"
                "<th>코어 중심</th><th>복도 주축</th>"
                f"</tr></thead><tbody>{rows}</tbody></table>"
                f"{rejected_family_review}</body></html>"
            ),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False))
        if accepted_count < 2:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

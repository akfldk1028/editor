from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

from backend.app.core.serialization import to_jsonable
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

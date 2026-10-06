from __future__ import annotations

import html
import json
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassInput


def _run_local_topology_review(args, mass: MassInput) -> None:
    from backend.app import cli as _cli

    analysis = _cli.analyze_mass(mass)
    baseline = _cli.generate_program_graph(
        analysis,
        floor_index=args.floor,
        use_type=args.use_type,
    )
    model_path = Path(args.base_model).resolve()
    client = _cli.LocalTopologyPlannerClient(
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
        street_segments=_cli._street_segments_for_boundary(
            mass,
            mass.footprint_for_floor(args.floor),
        ),
    )
    programs = _cli.apply_topology_proposals(baseline, proposals)
    assignments = tuple(
        FloorAssignment(
            floor_index=assignment.floor_index,
            use_type=(
                args.use_type
                if assignment.floor_index == args.floor
                else assignment.use_type
            ),
        )
        for assignment in _cli.assign_floors_from_use_mix(mass)
    )
    buildings = [
        (
            proposal,
            _cli.run_building_generation(
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
        fingerprint = _cli.layout_fingerprint(floor.layout)
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
        artifacts = _cli.create_visual_review_artifacts(
            result,
            boundary=list(boundary),
            output_dir=candidate_dir,
            run_root=target,
        )
        candidate_index = candidate_dir / "index.html"
        candidate_index.write_text(
            (
                '<!doctype html><html><head><meta charset="utf-8">'
                f"<title>{html.escape(proposal.candidate_id)}</title>"
                '</head><body style="margin:0;background:#fff">'
                f'<iframe src="{html.escape(artifacts.html_path.name)}" '
                'style="width:100%;height:100vh;border:0"></iframe>'
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
                "hard_violation_count": (result.validation.hard_violation_count),
                "program_source": result.program.source,
                "sequence": list(proposal.sequence),
                "adjacencies": to_jsonable(proposal.adjacencies),
                "effective_adjacencies": to_jsonable(result.program.edges),
                "geometry_fingerprint": geometry_fingerprints[proposal.candidate_id],
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
                _cli._street_segments_for_boundary(
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
            '<section style="border-top:1px solid #ddd;padding:24px 0">'
            f'<h2 style="font-size:18px">#{item["rank"]} '
            f"{html.escape(item['candidate_id'])}</h2>"
            f"<p>accepted={str(item['accepted']).lower()} | "
            f"score={item['score']:.4f} | "
            f"hard violations={item['hard_violation_count']}</p>"
            f'<a href="{html.escape(item["html"])}">'
            f'<img src="{html.escape(item["png"])}" '
            'style="max-width:100%;height:auto" '
            f'alt="{html.escape(item["candidate_id"])}"></a>'
            "</section>"
        )
        for item in summaries
    )
    (target / "index.html").write_text(
        (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>Local topology review</title></head>"
            '<body style="margin:0;background:#fff;color:#111;'
            'font:14px Arial,sans-serif"><main style="max-width:1100px;'
            'margin:auto;padding:24px"><h1 style="font-size:24px">'
            f"{html.escape(mass.project_id)} local topology review</h1>"
            f"{rows}</main></body></html>"
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))

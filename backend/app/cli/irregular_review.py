from __future__ import annotations

import hashlib
import html
import json
import shutil
from itertools import combinations
from pathlib import Path

from backend.app.cli.review_html import (
    _floor_caption_html,
    _generator_repairs_table_html,
    _quality_table_html,
)
from backend.app.cli.serialization import (
    _serialize_quality_evidence,
    _serialize_rejected_strategy,
)
from backend.app.core.serialization import to_jsonable
from backend.app.modules.building_quality import DEFAULT_QUALITY_POLICY
from backend.app.schemas.mass import MassInput

_IRREGULAR_MINIMUM_FLOOR_COVERAGE = 0.60
_IRREGULAR_MAXIMUM_UNALLOCATED_RATIO = 0.40
_IRREGULAR_MAXIMUM_LABEL_COLLISIONS = 0
_IRREGULAR_MINIMUM_PRIMARY_SHARE_FACTOR = 0.75


def _run_irregular_alternatives_review(args, mass: MassInput) -> None:
    from backend.app import cli as _cli

    composition = _cli.compose_structural_alternatives(mass, limit=args.limit)
    analysis = _cli.analyze_mass(mass)
    baseline_primary_shares = {}
    for floor_index in range(1, mass.floors + 1):
        prior = _cli.generate_program_graph(
            analysis,
            floor_index=floor_index,
            use_type="office",
        )
        non_core_targets = [
            float(node.target_area) for node in prior.nodes if node.space_type != "core"
        ]
        primary_target = next(
            float(node.target_area)
            for node in prior.nodes
            if node.space_type == "open_work"
        )
        baseline_primary_shares[floor_index] = primary_target / sum(non_core_targets)
    target = Path(args.output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    summaries = []
    unresolved_regulatory_facts: set[str] = set()

    for rank, alternative in enumerate(composition.alternatives, start=1):
        candidate_id = f"alternative-{rank:02d}"
        artifacts = _cli.create_building_visual_review_artifacts(
            alternative.building,
            boundary=mass.footprint_polygon,
            output_dir=target / candidate_id,
            width=1920,
            height=1080,
            render_style="architectural",
        )
        building_report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
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
            copied_png = target / (f"{candidate_id}-floor-{floor_index:03d}.png")
            shutil.copyfile(floor_artifact.png_path, copied_png)
            png_sha256 = hashlib.sha256(copied_png.read_bytes()).hexdigest()
            scores = floor_report["scores"]
            coverage_score = float(scores["coverage_score"])
            unresolved_label_collisions = int(
                floor_report["render_validation"]["unresolved_label_collision_count"]
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
                baseline_primary_share * _IRREGULAR_MINIMUM_PRIMARY_SHARE_FACTOR
            )
            primary_is_largest = primary_area == max(non_core_areas.values())
            office_space_ratio_passed = (
                primary_is_largest and actual_primary_share >= minimum_primary_share
            )
            floor_scores.append({"floor_index": floor_index, **scores})
            floors.append(
                {
                    "floor_index": floor_index,
                    "svg": str(floor_artifact.svg_path.relative_to(target)),
                    "png": str(copied_png.relative_to(target)),
                    "html": str(floor_artifact.html_path.relative_to(target)),
                    "review_json": str(floor_artifact.report_path.relative_to(target)),
                    "png_sha256": png_sha256,
                    "floor_boundary": floor_report["floor_boundary"],
                    "coverage_score": coverage_score,
                    "unallocated_ratio": round(1.0 - coverage_score, 4),
                    "unresolved_label_collision_count": (unresolved_label_collisions),
                    "png_output_size": floor_report["status_footer"]["png_output_size"],
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
            and floor["unallocated_ratio"] <= _IRREGULAR_MAXIMUM_UNALLOCATED_RATIO
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
                    "label_overlap": ("pass" if label_collision_passed else "fail"),
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
                    "total_score": sum(item["total_score"] for item in floor_scores),
                },
                "building_quality": _serialize_quality_evidence(
                    alternative.quality_report
                ),
                "generator_repairs": to_jsonable(alternative.generator_repairs),
                "internal_validation": artifacts.internal_validation,
                "render_validation": artifacts.render_validation,
                "regulatory_screening": artifacts.regulatory_screening,
                "index_html": str(artifacts.index_html_path.relative_to(target)),
                "building_review_json": str(artifacts.report_path.relative_to(target)),
                "candidate_png_fingerprint": candidate_png_fingerprint,
                "floors": floors,
            }
        )

    accepted = [item for item in summaries if item["quality_accepted"]]
    distinct_structural_count = len(
        {item["fingerprints"]["structural"] for item in accepted}
    )
    distinct_core_count = len({item["fingerprints"]["core"] for item in accepted})
    distinct_circulation_count = len(
        {item["fingerprints"]["circulation"] for item in accepted}
    )
    distinct_candidate_png_count = len(
        {item["candidate_png_fingerprint"] for item in accepted}
    )
    alternative_summaries = tuple(
        zip(composition.alternatives, summaries, strict=True)
    )
    comparisons = tuple(
        (
            first,
            second,
            first_summary,
            second_summary,
            _cli.compare_building_diversity(first.building, second.building),
        )
        for (first, first_summary), (second, second_summary) in combinations(
            alternative_summaries,
            2,
        )
    )
    pairwise_diversity = [
        _serialize_quality_evidence(comparison)
        for _, _, _, _, comparison in comparisons
    ]
    accepted_pairwise_diversity = [
        _serialize_quality_evidence(comparison)
        for first, second, first_summary, second_summary, comparison in comparisons
        if first_summary["quality_accepted"]
        and second_summary["quality_accepted"]
        and first.quality_report.hard_pass
        and second.quality_report.hard_pass
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
            "maximum_unallocated_ratio": (_IRREGULAR_MAXIMUM_UNALLOCATED_RATIO),
            "maximum_unresolved_label_collisions": (
                _IRREGULAR_MAXIMUM_LABEL_COLLISIONS
            ),
            "minimum_primary_share_factor": (_IRREGULAR_MINIMUM_PRIMARY_SHARE_FACTOR),
        },
        "alternatives": summaries,
        "pairwise_diversity": pairwise_diversity,
        "accepted_pairwise_diversity": accepted_pairwise_diversity,
        "rejected_strategies": [
            _serialize_rejected_strategy(rejection)
            for rejection in composition.rejections
        ],
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
            + _generator_repairs_table_html(item)
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
            ".generator-repairs{border-collapse:collapse;margin:12px 0;"
            "max-width:720px}.generator-repairs th,.generator-repairs td{"
            "border:1px solid #bbb;padding:5px 8px;text-align:left}"
            ".generator-repairs th{background:#f5f5f5}"
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
    exit_ready = len(accepted) >= 2 and any(
        comparison["quality_distinct"]
        for comparison in accepted_pairwise_diversity
    )
    if not exit_ready:
        raise SystemExit(1)

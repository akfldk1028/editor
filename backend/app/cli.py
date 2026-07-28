from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import (
    run_building_generation,
    run_generation_loop,
)
from backend.app.modules.llm_planner.openai_client import (
    OpenAIResponsesPlannerClient,
)
from backend.app.modules.llm_planner.service import run_llm_building_generation
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
    create_visual_review_artifacts,
    run_visual_review_loop,
)
from backend.app.schemas.mass import MassInput


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

    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    mass = MassInput(
        project_id=payload["project_id"],
        floors=int(payload["floors"]),
        footprint_polygon=[tuple(point) for point in payload["footprint_polygon"]],
        site_edges=list(payload.get("site_edges", [])),
        access_candidates=list(payload.get("access_candidates", [])),
        use_mix=dict(payload.get("use_mix", {})),
    )
    if args.command == "generate":
        result = run_generation_loop(mass, floor_index=args.floor, use_type=args.use_type)
        print(json.dumps(to_jsonable(result), ensure_ascii=False))
    elif args.command == "review":
        result = run_generation_loop(mass, floor_index=args.floor, use_type=args.use_type)
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
        if not result.accepted:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

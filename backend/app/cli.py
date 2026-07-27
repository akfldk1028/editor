from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import run_generation_loop
from backend.app.schemas.mass import MassInput


def main() -> None:
    parser = argparse.ArgumentParser(prog="plan")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--input", required=True)
    generate.add_argument("--floor", required=True, type=int)
    generate.add_argument("--use-type", required=True)

    args = parser.parse_args()
    if args.command == "generate":
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        mass = MassInput(
            project_id=payload["project_id"],
            floors=int(payload["floors"]),
            footprint_polygon=[tuple(point) for point in payload["footprint_polygon"]],
            site_edges=list(payload.get("site_edges", [])),
            access_candidates=list(payload.get("access_candidates", [])),
            use_mix=dict(payload.get("use_mix", {})),
        )
        result = run_generation_loop(mass, floor_index=args.floor, use_type=args.use_type)
        print(json.dumps(to_jsonable(result), ensure_ascii=False))


if __name__ == "__main__":
    main()

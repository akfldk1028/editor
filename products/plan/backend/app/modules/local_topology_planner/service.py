from __future__ import annotations

from dataclasses import dataclass
import json
import math
import subprocess
from collections.abc import Iterable, Mapping

from backend.app.modules.local_topology_planner.contracts import (
    TopologyContractError,
    TopologyProposal,
    parse_topology_proposals_json,
    require_distinct_layout_sequences,
)
from backend.app.schemas.program import ProgramGraph


@dataclass(frozen=True)
class LocalTopologyPlannerClient:
    command: tuple[str, ...]
    timeout_seconds: float = 360.0

    def __post_init__(self) -> None:
        if not self.command or any(not part for part in self.command):
            raise ValueError("command must contain non-empty entries")
        if (
            not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")

    def propose(
        self,
        program: ProgramGraph,
        *,
        candidate_count: int,
        boundary: Iterable[tuple[float, float]],
        access_candidates: Iterable[Mapping[str, object]] = (),
        street_edge_indices: Iterable[int] = (),
        street_segments: Iterable[
            tuple[tuple[float, float], tuple[float, float]]
        ] = (),
    ) -> tuple[TopologyProposal, ...]:
        boundary_points_list = []
        for point in boundary:
            if (
                not isinstance(point, (tuple, list))
                or len(point) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    for value in point
                )
            ):
                raise ValueError(
                    "boundary points must be finite coordinate pairs"
                )
            boundary_points_list.append((float(point[0]), float(point[1])))
        boundary_points = tuple(boundary_points_list)
        if len(boundary_points) < 3 or any(
            not math.isfinite(coordinate)
            for point in boundary_points
            for coordinate in point
        ):
            raise ValueError("boundary must contain at least three finite points")
        edge_count = len(boundary_points)
        streets = tuple(street_edge_indices)
        if len(set(streets)) != len(streets) or any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= edge_count
            for index in streets
        ):
            raise ValueError("street edge indices must reference the floor boundary")
        entrances = []
        for item in access_candidates:
            candidate = dict(item)
            edge_index = candidate.get("edge_index")
            position = candidate.get("position")
            if (
                not isinstance(edge_index, int)
                or isinstance(edge_index, bool)
                or edge_index < 0
                or edge_index >= edge_count
            ):
                raise ValueError("access edge index must reference the floor boundary")
            if (
                isinstance(position, bool)
                or not isinstance(position, (int, float))
                or not math.isfinite(float(position))
                or not 0 <= float(position) <= 1
            ):
                raise ValueError("access position must be finite and in [0, 1]")
            entrances.append(candidate)
        core_nodes = [node for node in program.nodes if node.space_type == "core"]
        if len(core_nodes) != 1:
            raise ValueError("topology program must contain exactly one core")
        core = core_nodes[0]
        try:
            streets_geometry = [
                [
                    [float(start[0]), float(start[1])],
                    [float(end[0]), float(end[1])],
                ]
                for start, end in street_segments
            ]
        except (TypeError, ValueError, IndexError) as error:
            raise ValueError(
                "street segments must contain finite point pairs"
            ) from error
        if any(
            not math.isfinite(coordinate)
            for segment in streets_geometry
            for point in segment
            for coordinate in point
        ):
            raise ValueError("street segments must contain finite point pairs")
        request = {
            "schema_version": 1,
            "project_id": program.project_id,
            "floor_index": program.floor_index,
            "use_type": program.use_type,
            "candidate_count": candidate_count,
            "boundary": [list(point) for point in boundary_points],
            "street_edge_indices": list(streets),
            "street_segments": streets_geometry,
            "access_candidates": entrances,
            "core": {
                "node_id": core.node_id,
                "target_area": core.target_area,
                "min_area": core.min_area,
                "max_area": core.max_area,
                "geometry_status": "unresolved_pre_generation",
            },
            "nodes": [
                {
                    "node_id": node.node_id,
                    "space_type": node.space_type,
                    "zone": node.zone,
                    "target_area": node.target_area,
                    "min_area": node.min_area,
                    "max_area": node.max_area,
                    "frontage_required": node.frontage_required,
                    "min_width": node.min_width,
                    "max_aspect_ratio": node.max_aspect_ratio,
                    "tenant_id": node.tenant_id,
                }
                for node in program.nodes
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation": edge.relation,
                    "weight": edge.weight,
                }
                for edge in program.edges
            ],
        }
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"local topology worker failed: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "no stderr"
            raise RuntimeError(
                f"local topology worker exited with "
                f"{completed.returncode}: {detail}"
            )
        try:
            proposals = parse_topology_proposals_json(
                completed.stdout,
                allowed_node_ids=tuple(node.node_id for node in program.nodes),
                expected_count=candidate_count,
            )
            require_distinct_layout_sequences(
                proposals,
                layout_node_groups=_layout_node_groups(
                    program,
                    enforce_frontage=bool(streets),
                ),
            )
            return proposals
        except TopologyContractError:
            raise


def _layout_node_groups(
    program: ProgramGraph,
    *,
    enforce_frontage: bool,
) -> tuple[tuple[str, ...], ...]:
    support_types = {"pantry", "restroom", "it_storage"}
    return (
        tuple(
            node.node_id
            for node in program.nodes
            if enforce_frontage
            and node.frontage_required
            and node.space_type not in {"core", "open_work"}
        ),
        tuple(
            node.node_id
            for node in program.nodes
            if node.space_type in support_types
        ),
        tuple(
            node.node_id
            for node in program.nodes
            if node.space_type not in {"core", "open_work", *support_types}
            and not (enforce_frontage and node.frontage_required)
        ),
    )

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import subprocess

from backend.app.modules.local_topology_planner.contracts import (
    TopologyContractError,
    TopologyProposal,
    parse_topology_proposals_json,
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
    ) -> tuple[TopologyProposal, ...]:
        request = {
            "project_id": program.project_id,
            "floor_index": program.floor_index,
            "use_type": program.use_type,
            "candidate_count": candidate_count,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "space_type": node.space_type,
                    "zone": node.zone,
                }
                for node in program.nodes
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
            return parse_topology_proposals_json(
                completed.stdout,
                allowed_node_ids=tuple(node.node_id for node in program.nodes),
                expected_count=candidate_count,
            )
        except TopologyContractError:
            raise

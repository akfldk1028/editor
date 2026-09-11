"""Rank generated buildings on what the pipeline already measures.

GreenPlanner (2025) and the AiC 2025 accessibility work both put a
deterministic evaluator between the generator and the output and regenerate
whatever fails it.  This is that evaluator.  It computes nothing new: hard
violations come from the validator, form relaxations from the program
adjustment record, and area shortfall from room polygons measured against the
*baseline* program -- the fitted program has had its targets rewritten onto
whatever the rooms received and would report zero shortfall for everything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from backend.app.schemas.program import ProgramGraph
from backend.engine.geometry.polygon import polygon_area


@dataclass(frozen=True)
class LayoutScore:
    accepted: bool
    hard_violations: int
    area_shortfall: float
    relaxations: int
    worst_shortfall: tuple[str, float] | None

    def key(self) -> tuple[bool, int, float, int]:
        """Sort key; lower is better."""
        return (
            not self.accepted,
            self.hard_violations,
            self.area_shortfall,
            self.relaxations,
        )


def score_building(
    building,
    *,
    baseline_programs: Mapping[int, ProgramGraph],
) -> LayoutScore:
    accepted = True
    hard = 0
    shortfall_total = 0.0
    relaxations = 0
    # A starved room is what a repair can act on; an oversized one is usually
    # the residual absorbing what the starved rooms lost.  So the worst
    # *starved* room is reported whenever there is one, and an oversized room
    # only when nothing is short.  Ranking by |ratio| alone put a 2.3x
    # restroom first and left the rule proposer with nothing to propose.
    worst_starved: tuple[str, float] | None = None
    worst_oversized: tuple[str, float] | None = None
    for floor in building.floor_results:
        floor_index = floor.program.floor_index
        baseline = baseline_programs[floor_index]  # KeyError is the contract
        accepted = accepted and bool(floor.validation.accepted)
        hard += int(floor.validation.hard_violation_count)
        relaxations += len(getattr(floor.program, "form_relaxations", ()))
        areas = {
            room.room_id: polygon_area(room.polygon) for room in floor.layout.rooms
        }
        for node in baseline.nodes:
            got = areas.get(node.node_id)
            if got is None:
                continue
            target = float(node.target_area)
            low = float(node.min_area) if node.min_area else target * 0.85
            high = float(node.max_area) if node.max_area else target * 1.15
            if low - 1e-9 <= got <= high + 1e-9:
                continue
            ratio = (target - got) / target
            shortfall_total += abs(ratio)
            if ratio > 0:
                if worst_starved is None or ratio > worst_starved[1]:
                    worst_starved = (node.node_id, ratio)
            elif worst_oversized is None or ratio < worst_oversized[1]:
                worst_oversized = (node.node_id, ratio)
    return LayoutScore(
        accepted=accepted,
        hard_violations=hard,
        area_shortfall=shortfall_total,
        relaxations=relaxations,
        worst_shortfall=worst_starved or worst_oversized,
    )

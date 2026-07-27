from __future__ import annotations

from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.program import ProgramGraph


def generate_program_route(
    analysis: MassAnalysis,
    floor_index: int,
    use_type: str,
) -> ProgramGraph:
    return generate_program_graph(analysis, floor_index=floor_index, use_type=use_type)

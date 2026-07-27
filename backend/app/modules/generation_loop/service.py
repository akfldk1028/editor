from __future__ import annotations

from backend.app.modules.layout_generator.service import generate_baseline_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.mass import MassInput
from backend.app.schemas.result import GenerationResult


def run_generation_loop(
    mass: MassInput,
    floor_index: int,
    use_type: str,
) -> GenerationResult:
    analysis = analyze_mass(mass)
    program = generate_program_graph(analysis, floor_index=floor_index, use_type=use_type)
    layout = generate_baseline_layout(analysis, program)
    validation = validate_layout(layout, program, boundary=mass.footprint_polygon)
    return GenerationResult(
        mass=analysis,
        program=program,
        layout=layout,
        validation=validation,
    )

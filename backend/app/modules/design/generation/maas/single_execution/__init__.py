"""Fast, auditable execution boundary for exactly one MASS program."""

from backend.app.modules.design.generation.maas.single_execution.contracts import SingleMassExecutionResult
from backend.app.modules.design.generation.maas.single_execution.catalog import is_single_execution_run, single_execution_archive_manifest, single_execution_passport, single_execution_preview, single_execution_program, single_execution_run_id, single_execution_runs
from backend.app.modules.design.generation.maas.single_execution.pipeline import execute_single_mass
from backend.app.modules.design.generation.maas.single_execution.vlm_review import review_single_mass_with_vlm

__all__ = [
    "SingleMassExecutionResult",
    "execute_single_mass",
    "is_single_execution_run",
    "single_execution_archive_manifest",
    "single_execution_passport",
    "single_execution_preview",
    "single_execution_program",
    "single_execution_run_id",
    "single_execution_runs",
    "review_single_mass_with_vlm",
]

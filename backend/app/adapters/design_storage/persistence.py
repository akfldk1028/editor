"""Persist optimization results; failed writes must fail the owning execution."""
from backend.app.adapters.design_storage.models import OptimizationJob, DesignResult


def save_job(job_data: dict) -> OptimizationJob:
    return OptimizationJob.objects.create(**job_data)


def save_results(job: OptimizationJob, designs: list[dict]) -> int:
    return len(DesignResult.objects.bulk_create([DesignResult(job=job, **design) for design in designs]))

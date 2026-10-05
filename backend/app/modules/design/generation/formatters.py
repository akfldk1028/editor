"""
Response formatters for design optimization results.

Pure functions — no Django dependencies.
"""


def format_job_response(job) -> dict:
    """Format OptimizationJob for API response."""
    return {
        "id": str(job.id),
        "pnu": job.pnu,
        "address": job.address,
        "status": job.status,
        "generation_count": job.generation_count,
        "max_generations": job.max_generations,
        "population_size": job.population_size,
        "site_area_m2": job.site_area_m2,
        "constraints": job.constraints,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error": job.error,
    }


def format_design_response(design) -> dict:
    """Format DesignResult for API response."""
    return {
        "design_id": design.design_id,
        "generation": design.generation,
        "inputs": design.inputs,
        "outputs": design.outputs,
        "ranking": design.ranking,
        "crowding_distance": design.crowding_distance,
        "is_feasible": design.is_feasible,
        "is_pareto_optimal": design.is_pareto_optimal,
        "mass_geojson": design.mass_geojson,
    }


def format_pareto_front(designs) -> list[dict]:
    """Format Pareto-optimal designs for chart display."""
    return [
        {
            "design_id": d.design_id,
            "generation": d.generation,
            "outputs": d.outputs,
            "inputs": d.inputs,
        }
        for d in designs
    ]

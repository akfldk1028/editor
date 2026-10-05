from types import SimpleNamespace

from backend.app.modules.design.generation.formatters import format_job_response


def test_recovery_metadata_keeps_objective_order_and_ignores_constraints():
    job = SimpleNamespace(id='job', pnu='', address='', status='complete',
        generation_count=3, max_generations=3, population_size=4, site_area_m2=100,
        constraints=[], created_at=None, completed_at=None, error='', job_spec={
            'outputs': [
                {'name': 'floor_area', 'type': 'Objective', 'Goal': 'Maximize'},
                {'name': 'height', 'type': 'Constraint', 'Requirement': 'Less than', 'val': 12},
                {'name': 'daylight_score', 'type': 'Objective', 'Goal': 'Minimize'},
            ]})
    assert format_job_response(job)['objectives'] == [
        {'name': 'floor_area', 'goal': 'Maximize'},
        {'name': 'daylight_score', 'goal': 'Minimize'},
    ]

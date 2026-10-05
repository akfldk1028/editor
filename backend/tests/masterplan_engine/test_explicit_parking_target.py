"""An explicit total target is enforced even without a nested practice brief."""
import pytest

from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
from test_masterplan_engine import request


@pytest.mark.parametrize('required', [4, None])
def test_total_design_shortfall_closes_handoff_even_when_law_count_does_not_fail(required):
    data = request(required=required, strategy='ground_surface')
    data['options'].update(target_parking_stalls=6, max_surface_stalls=4)
    result = plan_site(data)
    assert result['metrics']['required_parking_stalls'] == required
    assert result['metrics']['planned_parking_stalls'] == 6
    assert result['metrics']['provided_parking_stalls'] == (4 if required is not None else 0)
    if required is not None:
        assert result['validation']['geometry_status'] == 'passed'
    assert result['status'] == 'needs_revision'
    assert result['handoff']['hard_pass'] is False
    assert any(s.startswith('parking shortfall:') and 'design target 6' in s for s in result['blocking'])


def test_met_total_target_does_not_create_a_design_shortfall():
    data = request(required=4, strategy='ground_surface')
    data['options'].update(target_parking_stalls=4, max_surface_stalls=4)
    result = plan_site(data)
    assert result['metrics']['provided_parking_stalls'] == 4
    assert result['validation']['geometry_status'] == 'passed'
    assert result['status'] != 'needs_revision'
    assert not any(s.startswith('parking shortfall:') for s in result['blocking'])

"""ramp_overhead: the engine rule SystemsAgent asks MasterPlan for, served as a planning operation."""
from backend.app.modules.design.generation.maas.masterplan_operations import digest, invoke


def test_ramp_overhead_measures_clearance_and_names_the_engine():
    arguments = {'ramp': {'width_m': 4, 'centerline': [[0, 0, 0], [30, 0, -3]]},
                 'occupied': {'type': 'Polygon', 'coordinates': [[[25, -3], [35, -3], [35, 3], [25, 3], [25, -3]]]},
                 'soffit_z_m': -0.4, 'required_height_m': 2.1}
    envelope = invoke({'operation': 'ramp_overhead', 'arguments': arguments})
    assert envelope['status'] == 'succeeded', envelope
    result = envelope['result']
    assert result['passed'] is True and abs(result['minimum_clearance_m'] - 2.1) < 1e-6
    assert result['engine']['callable'].endswith('.maas.masterplan.ramp_overhead.overhead_clearance')
    assert len(result['engine']['source_sha256']) == 64 and len(result['engine']['geometry_dependency_sha256']) == 64
    assert envelope['result_hash'] == digest(result)


def test_ramp_overhead_refuses_a_flat_centerline_without_a_width():
    envelope = invoke({'operation': 'ramp_overhead', 'arguments': {
        'ramp': {'centerline': [[0, 0], [30, 0]]},
        'occupied': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        'soffit_z_m': 0, 'required_height_m': 2.1}})
    assert envelope['status'] == 'failed' and envelope['code'] == 'owner_operation_refused'

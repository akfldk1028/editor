"""Unit tests for independent circulation geometry validation (B - validation).

Verifies:
1. Independent evidence schema with check_id, status, measured, required, geometry_hash.
2. Entry approach width, straight length, and corner clearance checks.
3. Ramp landing connections (upper & lower) independent measurement.
4. Detection of dead-end spur branches without stalls.
5. Deception test: False receipt claims (e.g. self-declared 'full_width_connected')
   are caught and rejected by independent re-measurement.
6. Design vehicle swept path returns 'unknown' when vehicle parameters are missing.
"""
import pytest
from shapely.geometry import box, LineString, Polygon, Point
from shapely.affinity import rotate

from backend.app.modules.design.generation.maas.masterplan.validation_circulation import (
    validate_circulation_geometry,
)

RULES = dict(stall_width_m=2.5, stall_length_m=5.0, accessible_width_m=3.3,
             accessible_length_m=5.0, aisle_width_m=6.0, ramp_width_m=6.0)


def test_independent_evidence_schema():
    """All checks adhere strictly to the evidence schema."""
    features = [
        {'properties': {'layer': 'site_boundary', 'level': 0},
         'geometry': box(0, 0, 50, 50).__geo_interface__},
        {'properties': {'layer': 'road_frontage', 'level': 0},
         'geometry': LineString([(0, 0), (50, 0)]).__geo_interface__},
        {'properties': {'layer': 'vehicular_access', 'role': 'surface_entry_connector', 'level': 0},
         'geometry': box(20, 0, 26, 8).__geo_interface__},
    ]
    report = validate_circulation_geometry(features, RULES, options={})
    assert 'checks' in report
    for c in report['checks']:
        assert 'check_id' in c
        assert c['status'] in ('passed', 'failed', 'unknown', 'not_applicable')
        assert 'measured' in c
        assert 'required' in c
        assert 'source' in c
        assert 'geometry_hash' in c


def test_corner_entry_caught_and_failed_by_validator():
    """A ramp or entry placed right at the parcel corner is flagged as failed."""
    features = [
        {'properties': {'layer': 'site_boundary', 'level': 0},
         'geometry': box(0, 0, 50, 50).__geo_interface__},
        {'properties': {'layer': 'road_frontage', 'level': 0},
         'geometry': LineString([(0, 0), (50, 0)]).__geo_interface__},
        # Entry at x=0 to 6 (offset 0, hugging corner)
        {'properties': {'layer': 'vehicular_access', 'role': 'surface_entry_connector', 'level': 0},
         'geometry': box(0, 0, 6, 8).__geo_interface__},
    ]
    report = validate_circulation_geometry(features, RULES, options={'corner_clearance_m': 4.0})
    corner_check = next((c for c in report['checks'] if c['check_id'] == 'entry_corner_clearance'), None)
    assert corner_check is not None
    assert corner_check['status'] == 'failed'
    assert corner_check['measured'] < 4.0


def test_deception_test_false_receipt_caught():
    """Even if metadata declares 'full_width_connected': True, a disconnected geometry fails."""
    features = [
        {'properties': {'layer': 'site_boundary', 'level': -1},
         'geometry': box(0, 0, 50, 50).__geo_interface__},
        # Ramp landing at (0, 0, 6, 6)
        {'properties': {'layer': 'vehicular_access', 'role': 'ramp_arrival', 'level': -1},
         'geometry': box(0, 0, 6, 6).__geo_interface__},
        # Disconnected aisle far away at (20, 20, 40, 26)
        {'properties': {'layer': 'parking_aisle', 'level': -1, 'receipt': {'full_width_connected': True}},
         'geometry': box(20, 20, 40, 26).__geo_interface__},
    ]
    report = validate_circulation_geometry(features, RULES, options={})
    landing_check = next((c for c in report['checks'] if c['check_id'] == 'ramp_lower_landing_connection:-1'), None)
    assert landing_check is not None
    assert landing_check['status'] == 'failed'


def test_dead_end_spur_detected():
    """A long dead-end aisle branch without stalls is detected and reported."""
    features = [
        {'properties': {'layer': 'site_boundary', 'level': -1},
         'geometry': box(0, 0, 50, 50).__geo_interface__},
        {'properties': {'layer': 'vehicular_access', 'role': 'ramp_arrival', 'level': -1},
         'geometry': box(0, 0, 6, 6).__geo_interface__},
        # Main aisle with stalls
        {'properties': {'layer': 'parking_aisle', 'level': -1},
         'geometry': box(0, 0, 30, 6).union(box(24, 6, 30, 35)).__geo_interface__},
        # Stalls only on horizontal section
        {'properties': {'layer': 'parking_stall', 'level': -1},
         'geometry': box(10, 6, 12.5, 11).__geo_interface__},
    ]
    report = validate_circulation_geometry(features, RULES, options={})
    spur_check = next((c for c in report['checks'] if c['check_id'] == 'dead_end_spurs_clean:-1'), None)
    assert spur_check is not None
    assert spur_check['status'] == 'failed'


def test_swept_path_returns_unknown_without_vehicle_parameters():
    """Without explicit design vehicle parameters, swept path returns unknown, not passed."""
    features = [
        {'properties': {'layer': 'site_boundary', 'level': 0},
         'geometry': box(0, 0, 50, 50).__geo_interface__},
    ]
    report = validate_circulation_geometry(features, RULES, options={})
    swept_check = next((c for c in report['checks'] if c['check_id'] == 'swept_path_design_vehicle'), None)
    assert swept_check is not None
    assert swept_check['status'] == 'unknown'
    assert 'requested_parameters' in swept_check

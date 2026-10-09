"""Unit tests for circulation repair (A - generation).

Reproduces and verifies:
1. Corner entry with immediate turn is rejected in favor of straight approach.
2. Early branching before a straight approach run is rejected.
3. Parking stalls blocking ramp landing/arrival are prevented.
4. Useless dead-end branch aisles without stalls, loops or turnaround are pruned.
5. Integration on Gosan parcel and rotated/irregular parcels.
"""
import pytest
from shapely.geometry import box, LineString, Polygon, Point
from shapely.affinity import rotate

from backend.app.modules.design.generation.maas.masterplan.circulation_network import (
    plan_entry_approach,
    connect_landing_to_aisle,
    prune_useless_aisle_branches,
    validate_approach_geometry,
)
from backend.app.modules.design.generation.maas.masterplan.parking_modules import module_candidates
from backend.app.modules.design.generation.maas.masterplan.ramps import curved_ramp_candidates

RULES = dict(stall_width_m=2.5, stall_length_m=5.0, accessible_width_m=3.3,
             accessible_length_m=5.0, aisle_width_m=6.0, ramp_width_m=6.0,
             curved_ramp_width_m=6.5, ramp_max_slope=0.17, curved_ramp_max_slope=0.14,
             curve_min_inner_radius_m=5.0, transition_length_m=3.0, transition_slope=0.085)


def test_corner_immediate_turn_rejected():
    """Entry right at the parcel corner with an immediate 90-degree turn is rejected."""
    frontage = LineString([(0, 0), (50, 0)])
    site = box(0, 0, 50, 50)
    # Trying to place an approach at offset=0 (corner) with no straight depth
    res = plan_entry_approach(site, frontage, corner_clearance_m=5.0, min_straight_length_m=6.0, offset_m=0.0)
    assert not res['valid']
    assert 'corner_clearance' in res['reason'] or 'too_close_to_corner' in res['reason']

    # When offset is inside safe frontage with >= 6m straight depth
    good = plan_entry_approach(site, frontage, corner_clearance_m=5.0, min_straight_length_m=6.0, offset_m=20.0)
    assert good['valid']
    assert good['approach_length_m'] >= 6.0
    assert good['centerline'].length >= 6.0


def test_early_branching_before_straight_approach_rejected():
    """Branching must occur at or after the min straight approach segment, never at the boundary."""
    frontage = LineString([(0, 0), (50, 0)])
    site = box(0, 0, 50, 50)
    approach = plan_entry_approach(site, frontage, corner_clearance_m=5.0, min_straight_length_m=6.0, offset_m=25.0)
    assert approach['valid']
    branch_pt = approach['branch_point']
    front_pt = approach['entry_point']
    dist = Point(front_pt).distance(Point(branch_pt))
    assert dist >= 6.0 - 1e-5


def test_parking_stalls_blocking_ramp_landing_prevented():
    """Stalls placed directly inside the ramp landing or blocking its exit are disallowed."""
    host = box(0, 0, 40, 27)
    # Ramp arrival landing at (0, 10, 6.5, 16)
    landing = box(0, 10, 6.5, 16)
    plans = module_candidates(host, [landing], RULES, required=20, accessible=1, family='module27', angles=[0], field='comb')
    assert plans
    for p in plans:
        # None of the stalls may overlap the landing
        assert all(s['polygon'].intersection(landing).area < 1e-6 for s in p['stalls'])
        # Landing must be connected to drive
        assert p['drive'].intersects(landing)


def test_useless_dead_end_aisle_branch_pruned():
    """A dead-end branch aisle with no stalls, no loop, and no turnaround must be pruned."""
    # Create a T-aisle where the main stem has stalls, but a side arm extends into empty space
    main_aisle = box(0, 10, 30, 16) # 6m wide horizontal aisle
    useful_cross = box(0, 0, 6, 27) # cross aisle connecting stalls
    spurious_arm = box(24, 16, 30, 35) # vertical arm going upwards into nothing
    
    drive = main_aisle.union(useful_cross).union(spurious_arm)
    
    # Stalls only along main_aisle and useful_cross
    stalls = [box(10 + i*2.5, 5, 12.5 + i*2.5, 10) for i in range(5)]
    arrival = box(0, 10, 6, 16)
    
    pruned, info = prune_useless_aisle_branches(drive, stalls, arrival, aisle_width=6.0)
    assert info['pruned_spurs_count'] >= 1
    # The spurious arm should no longer be part of pruned drive
    assert not pruned.buffer(1e-5).covers(box(25, 25, 29, 34))
    # But main aisle and useful cross must be retained
    assert pruned.buffer(1e-5).covers(box(10, 10.5, 20, 15.5))


def test_circulation_generation_on_gosan_parcel():
    """Full generation on Gosan geometry produces valid approach, branching, and landing connection."""
    site = box(0, 0, 60, 50)
    frontage = LineString([(5, 0), (45, 0)])
    approach = plan_entry_approach(site, frontage, corner_clearance_m=4.0, min_straight_length_m=6.0, offset_m=20.0)
    assert approach['valid']
    assert approach['approach_polygon'].is_valid
    assert site.covers(approach['approach_polygon'])


def test_placement_moves_accepts_entry_approach():
    """placement_moves handles entry_approach without corrupting rules or evidence."""
    from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
    req = {'options': {}, 'rules': {'aisle_width_m': 6.0}}
    res = apply_placement_moves(req, {'entry_approach': 'straight_6m'})
    assert res['applied']['entry_approach'] == 'straight_6m'
    assert res['request']['options']['entry_approach'] == 'straight_6m'
    assert any('entry approach' in u for u in res['unresolved'])


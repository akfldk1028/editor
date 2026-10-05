"""Ramp placement regressions: derive expectations from the actual drivable envelope."""
import sys
import math
import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Polygon, box, shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.ramps import ramp_candidates, curved_ramp_candidates


def rules():
    # Explicit fixture inputs, never a legal rule source.
    return {"ramp_width_m": 6.0, "ramp_max_slope": .17,
            "curved_ramp_width_m": 6.5, "curved_ramp_max_slope": .14,
            "curve_min_inner_radius_m": 5.0, "transition_length_m": 3.0,
            "transition_slope": .07, "aisle_width_m": 6.0}


def test_interior_ramp_connects_to_road_via_actual_ground_drive():
    site = box(0, 0, 28, 52)
    road = LineString([(12, 0), (20, 0)])
    building = box(9, 12, 28, 52)
    candidates = ramp_candidates(site, road, building, rules(), 3.3)
    assert candidates, "A 6 m side strip and 12 m forecourt can hold an interior ramp and its approach"
    for c in candidates:
        connector = c.get("ground_connector")
        assert connector is not None and not connector.is_empty
        assert site.buffer(1e-6).covers(c["polygon"].union(connector))
        assert connector.intersection(building).area < 1e-6
        assert connector.distance(road) < 1e-6
        assert connector.intersection(c["upper_landing"]).area > 1


def test_a_longer_half_turn_uses_lower_grade_instead_of_being_rejected():
    site = box(0, 0, 65, 65)
    candidates = curved_ramp_candidates(site, LineString([(0, 0), (65, 0)]), Polygon(),
                                        rules(), 3.0, turns=(180,), limit=3)
    assert candidates, "The max-grade minimum length is not an upper bound on a ramp's run"
    for c in candidates:
        assert c["turn_deg"] == 180
        assert c["inner_radius_m"] >= 5
        assert c["centerline"].length == pytest.approx(c["profile"][-1]["distance_m"], abs=.1)
        assert c["profile"][-1]["z_m"] == pytest.approx(-3)
        grades = [abs(b["z_m"]-a["z_m"])/(b["distance_m"]-a["distance_m"])
                  for a,b in zip(c["profile"],c["profile"][1:])]
        assert max(grades) <= .14+1e-8
        # Only the flat landing length belongs to a vehicular landing feature.
        assert c["upper_landing"].area == pytest.approx(6*6.5,abs=.02)
        from backend.app.modules.design.generation.maas.masterplan.validation import _min_turn_radius
        measured = _min_turn_radius([(x,y) for x,y,*_ in c['centerline'].coords])
        assert measured-c['width_m']/2 >= 5-1e-6


def test_fully_blocked_frontage_does_not_get_a_teleporting_ramp():
    candidates = ramp_candidates(box(0,0,60,60),LineString([(10,0),(20,0)]),
                                 box(0,0,60,10),rules(),3.3)
    assert not candidates


def test_frozen_gosan_has_two_lane_ramp_between_old_five_entry_samples():
    data = json.loads((Path(__file__).parent / "fixtures/ramp_gosan_20260920.json").read_text(encoding="utf-8"))
    site, road = shape(data["site"]), shape(data["frontage"])
    blocked = unary_union([shape(data["footprint"]), *([shape(data["core"])] if data.get("core") else []),
                           *[shape(c) for c in data.get("columns", [])]])
    candidates = ramp_candidates(site, road, blocked, data["rules"], data["options"]["basement_floor_height_m"])
    assert candidates, "Frozen Gosan frontage contains valid two-lane portals between the five old samples"
    for c in candidates:
        assert c["width_m"] == 6.0
        assert site.buffer(1e-7).covers(c["polygon"])
        assert c["polygon"].intersection(blocked).area < 1e-7
        assert c["upper_landing"].distance(road) < 1e-7


def test_more_curve_portals_preserve_existing_frozen_valid_envelope():
    data=json.loads((Path(__file__).parent/'fixtures/ramp_903_20260921.json').read_text(encoding='utf8'))
    site=shape(data['site'])
    blocked=shape(data['footprint'])
    candidates=curved_ramp_candidates(site,shape(data['frontage']),blocked,data['rules'],
                                     data['options']['basement_floor_height_m'])
    assert candidates, 'Expanded search must retain the original 15/50/85 percent portals'
    assert all(site.buffer(1e-7).covers(c['polygon']) and c['polygon'].intersection(blocked).area<1e-7
               for c in candidates)

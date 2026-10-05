"""Large-envelope adapter uses real connected row geometry with a bounded search."""
from __future__ import annotations

import sys
import time
import math
from pathlib import Path

from shapely.geometry import LineString, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]

from backend.app.modules.design.generation.maas.masterplan.bounded_packing import pack_level  # noqa: E402


RULES = {
    "stall_width_m": 2.5,
    "stall_length_m": 5.0,
    "accessible_width_m": 3.3,
    "accessible_length_m": 5.0,
    "aisle_width_m": 6.0,
}


def test_large_envelope_returns_bounded_connected_rows_at_the_supplied_road():
    host = box(0, 0, 240, 120)
    road = LineString([(0, 0), (240, 0)])
    started = time.perf_counter()

    result = pack_level(host, [road], RULES, 450, 4, preferred_angle=0)

    assert time.perf_counter() - started < 12
    assert result["provided"] >= 300
    assert result["accessible"] == 4
    assert result["bands"] >= 3
    assert result["cross_aisles"] >= 1
    assert result["drive"].geom_type == "Polygon"
    assert result["drive"].distance(road) < 1e-6
    assert all(host.buffer(1e-6).covers(s["polygon"]) for s in result["stalls"])
    assert all(result["drive"].buffer(1e-6).covers(s["front"]) for s in result["stalls"])
    assert all(s["polygon"].intersection(result["drive"]).area < 1e-6 for s in result["stalls"])


def test_small_envelope_keeps_original_packer_without_a_road_anchor():
    # Row search requires an anchor; the original packer can still serve a small
    # bounded interior envelope without one, preserving its established contract.
    result = pack_level(box(0, 0, 30, 20), [], RULES, 10, 0, preferred_angle=0)

    assert result["provided"] == 10
    assert result["drive"].area > 0


def test_disconnected_residual_ground_keeps_only_a_road_served_component():
    host = box(0,0,150,90).union(box(160,0,175,90))
    road = LineString([(0,0),(150,0)])
    result = pack_level(host, [road], RULES, 250, 2)
    assert result['provided'] > 0
    assert result['drive'].geom_type == 'Polygon'
    assert result['drive'].distance(road) < 1e-6
    assert host.buffer(1e-6).covers(result['drive'])
    assert all(box(0,0,150,90).buffer(1e-6).covers(s['polygon']) for s in result['stalls'])


def test_large_interior_floor_connects_to_polygon_landing():
    host = box(0, 0, 240, 120)
    landing = box(0, 0, 6, 6)

    result = pack_level(host, [landing], RULES, 300, 2)

    assert result["provided"] == 300
    assert result["drive"].distance(landing) < 1e-6
    assert all(result["drive"].buffer(1e-6).covers(s["front"]) for s in result["stalls"])


def test_narrow_neck_cannot_connect_a_large_floor_to_the_road():
    host = unary_union([box(0, 20, 150, 110), box(0, 0, 6, 5),
                        box(2.9, 5, 3.1, 20)])
    road = LineString([(0, 0), (6, 0)])

    result = pack_level(host, [road], RULES, 100)

    assert result["provided"] == 0
    assert result["drive"].is_empty


def test_exact_aisle_width_neck_serves_the_large_floor():
    host = unary_union([box(0, 20, 150, 110), box(0, 0, 6, 20)])
    road = LineString([(0, 0), (6, 0)])

    result = pack_level(host, [road], RULES, 100)

    assert result["provided"] == 100
    assert result["drive"].distance(road) < 1e-6


def test_small_packer_draws_expanded_bays_without_mutating_rule_snapshot():
    rules = {**RULES, "expanded_min_share": 0.3,
             "expanded_width_m": 2.6, "expanded_length_m": 5.2}
    before = dict(rules)

    result = pack_level(box(0, 0, 30, 20), [], rules, 10, 1)

    assert rules == before
    assert result["provided"] == 10
    assert result["accessible"] == 1
    for stall in result["stalls"]:
        coordinates = list(stall["polygon"].exterior.coords)
        edges = [math.dist(a, b) for a, b in zip(coordinates, coordinates[1:])]
        expected = (3.3, 5.0) if stall["type"] == "accessible" else (2.6, 5.2)
        assert abs(min(edges) - expected[0]) < 1e-6
        assert abs(max(edges) - expected[1]) < 1e-6
        assert stall["width_m"] == expected[0]
        assert stall["length_m"] == expected[1]
        if stall["type"] != "accessible":
            assert stall["type"] == "expanded"


def test_expanded_adapter_preserves_larger_standard_dimensions():
    rules = {**RULES, "stall_width_m": 2.8, "stall_length_m": 5.5,
             "expanded_min_share": 0.3, "expanded_width_m": 2.6,
             "expanded_length_m": 5.2}

    result = pack_level(box(0, 0, 30, 20), [], rules, 10)

    assert result["provided"] == 10
    assert all(s["type"] == "expanded" and s["width_m"] == 2.8 and s["length_m"] == 5.5
               for s in result["stalls"])

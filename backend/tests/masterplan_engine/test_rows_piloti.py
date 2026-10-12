"""Under a piloti the row scheme's road connector may pass beneath the upper floors.

Practice ALT1 (고산): the building stands on the main-road side and the parking rows and their
aisle run under its upper floors; the entrance corridor from the lesser road reaches the aisle
beneath the overhang. `row_candidates` receives the enclosed ground floor as `occupied_footprint`
but, until 2026-10-08, cut the corridor, the ramp's open part and the turn bay against the whole
footprint, so no candidate ever had an entrance: on 고산 with the practice building the planner
produced 0-12 surface stalls and a failing generic plan.
"""
from __future__ import annotations

from shapely.geometry import LineString, box

from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates

RULES = {"stall_width_m": 2.5, "stall_length_m": 5.0, "accessible_width_m": 3.3,
         "accessible_length_m": 5.0, "aisle_width_m": 6.0}

SITE = box(0, 0, 60, 60)
ROAD = LineString([(0, 0), (60, 0)])          # the only vehicle frontage, along the south edge
FOOTPRINT = box(0, 2, 60, 22)                 # upper floors span the whole width beside the road
ENCLOSED = box(0, 12, 40, 22)                 # the enclosed ground floor; x > 40 and y < 12 are piloti


def _candidates(occupied):
    ground = SITE.difference(ENCLOSED)        # what the planner passes: site minus the enclosed floor
    return row_candidates(SITE, ground, FOOTPRINT, None, ROAD, ROAD, RULES, 20, 1,
                          occupied_footprint=occupied, allowed_angles=[0.0], limit=6)


def test_entrance_corridor_passes_under_the_piloti_to_reach_the_road():
    rows = _candidates(ENCLOSED)
    served = [r for r in rows if r.get("entrance") is not None and r["provided"] > 0]
    assert served, "no row candidate found an entrance from the only road"
    best = max(served, key=lambda r: r["provided"])
    assert best["entrance"].distance(ROAD) <= 0.05
    # the corridor crosses the overhang (inside the footprint) but never the enclosed floor
    assert best["entrance"].intersection(FOOTPRINT).area > 1.0
    assert best["entrance"].intersection(ENCLOSED).area <= 1e-6
    assert best["drive"].intersection(ENCLOSED).area <= 1e-6


def test_without_a_piloti_the_whole_footprint_blocks_the_corridor():
    # Same ground, but the whole footprint is treated as enclosed: the corridor from the road has
    # to cross y 2..22 across the full width and no candidate gets an entrance.
    rows = _candidates(FOOTPRINT)
    assert not [r for r in rows if r.get("entrance") is not None and r["provided"] > 0]


def test_no_occupied_footprint_means_the_footprint_is_the_enclosed_floor():
    # Regression guard for every non-piloti request: occupied_footprint=None must equal passing
    # the footprint itself, stall for stall.
    a = _candidates(None)
    b = _candidates(FOOTPRINT)
    assert [(r["provided"], round(r["score"], 6)) for r in a] == [(r["provided"], round(r["score"], 6)) for r in b]


def test_validator_reads_the_drawn_ground_footprint_when_the_request_has_none():
    """An engine-generated piloti plan re-validated with the original request (no ground_footprint)."""
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request = {"site": mapping(SITE), "buildable": mapping(SITE), "frontage": mapping(ROAD), "rules": RULES,
               "options": {"planning_stage": "placement"}}
    def feat(layer, geom, **props):
        return {"type": "Feature", "geometry": mapping(geom), "properties": {"layer": layer, "level": 0, **props}}
    stall = box(45, 14, 47.5, 19)                     # under the overhang: inside FOOTPRINT, outside ENCLOSED
    aisle = box(0, 22, 60, 28)
    plan = {"features": [feat("site_boundary", SITE), feat("building_footprint", FOOTPRINT),
                         feat("building_ground_footprint", ENCLOSED), feat("parking_aisle", aisle, width_m=6.0),
                         feat("parking_stall", stall, stall_id="G-P001", type="standard_90deg", width_m=2.5, length_m=5.0)],
            "levels": [{"level": 0, "z_m": 0, "provided_spaces": 1}]}
    out = validate_plan(request, plan)
    status = {c["id"]: c["status"] for c in out["checks"]}
    assert status["stall_obstructions:G-P001"] == "passed"
    assert status["ground_footprint_containment"] == "passed"
    assert "piloti_structural_clearance_review" in out["pending_reviews"]

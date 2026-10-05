"""Row-and-aisle candidates (ARR masterplan/rows.py) on a synthetic parcel: one through aisle parallel to the
road, rows both sides, entrance on the road, ramp off the aisle, basement = plate + ramp clipped to the parcel."""
from __future__ import annotations

import sys
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, Polygon, box, shape

ROOT = Path(__file__).resolve().parents[1]

from backend.app.modules.design.generation.maas.masterplan.ramps import ramp_profile  # noqa: E402
from backend.app.modules.design.generation.maas.masterplan.rows import orientation_candidates, row_candidates  # noqa: E402

RULES = {"stall_width_m": 2.5, "stall_length_m": 5.0, "accessible_width_m": 3.3, "accessible_length_m": 5.0, "aisle_width_m": 6.0,
         "ramp_width_m": 6.0, "ramp_max_slope": 0.17, "transition_length_m": 3.0, "transition_slope": 0.085, "min_headroom_m": 2.3}
SITE = box(0, 0, 70, 50)
FOOTPRINT = box(10, 28, 60, 48)           # plate along the north; open ground 28 m deep to the south
ROAD = MultiLineString([LineString([(0, 0), (70, 0)]), LineString([(0, 0), (0, 50)])])  # south road (long) + west lane
FRONT = LineString([(10, 50), (60, 50)])  # the front is the north road; its 8 m strip is excluded from ground
GROUND = SITE.difference(FOOTPRINT).difference(FRONT.buffer(8.0))


def test_orientations_include_every_road_site_and_footprint_edge_direction():
    angles = orientation_candidates(SITE, FOOTPRINT, ROAD)
    assert 0.0 in angles and 90.0 in angles and len(angles) == 2


def test_surface_rows_form_one_aisle_parallel_to_the_road_with_rows_both_sides():
    # The single band is no longer automatically the top candidate: a closed aisle loop is now worth
    # `w_loop` cars in the score, so a tiled plan that carries the same 40 cars AND lets a driver come
    # round again outranks it - which is the point of scoring circulation. The contract this test
    # exists for is about the single band itself, so it is taken by name.
    cands = row_candidates(SITE, GROUND, FOOTPRINT, Polygon(), ROAD, FRONT, RULES, 40, 2)
    assert cands, "no candidate"
    best = next((c for c in cands if c["bands"] == 1), None)
    assert best is not None, "the one-band plan must still be on the table"
    assert best["angle_deg"] == 0.0 and best["provided"] == 40 and best["accessible"] == 2
    assert best["drive"].distance(ROAD) < 1e-6                   # the entrance corridor reaches the road
    ys = {round(s["polygon"].centroid.y) for s in best["stalls"]}
    assert len(ys) == 2                                          # two rows, one each side of the aisle
    assert all(GROUND.buffer(1e-6).covers(s["polygon"]) for s in best["stalls"])
    assert all(best["drive"].buffer(1e-6).covers(s["front"]) for s in best["stalls"])
    assert best["terms"]["parallel_to_longest_road_edge"] is True


def test_ramp_leaves_the_aisle_and_the_basement_is_the_plate_plus_ramp():
    spec = ramp_profile(RULES, 3.3)
    cands = row_candidates(SITE, GROUND, FOOTPRINT, Polygon(), ROAD, FRONT, RULES, 60, 2, ramp=spec)
    with_ramp = [c for c in cands if c["ramp"] is not None]
    assert with_ramp, "no ramp candidate"
    c = with_ramp[0]
    ramp = c["ramp"]["polygon"]
    assert ramp.distance(c["drive"]) < 1e-6                      # departs from the aisle
    assert c["ramp"]["share_under_footprint"] > 0.5              # runs under the plate
    assert SITE.buffer(1e-6).covers(c["basement"]) and c["basement"].covers(ramp) and c["basement"].covers(FOOTPRINT)
    assert c["basement"].area < 1.6 * FOOTPRINT.area             # plate + ramp hull, not the whole parcel (3,500 m2)
    assert all(s["polygon"].intersection(ramp).area < 1e-6 for s in c["stalls"])


def test_no_road_edge_means_no_candidate():
    assert row_candidates(SITE, GROUND, FOOTPRINT, Polygon(), MultiLineString([]), FRONT, RULES, 10, 0) == []


def test_expanded_stalls_are_placed_when_the_rules_ask_for_a_share():
    rules = {**RULES, "expanded_width_m": 2.6, "expanded_length_m": 5.2, "expanded_min_share": 0.3}
    cands = row_candidates(SITE, GROUND, FOOTPRINT, Polygon(), ROAD, FRONT, rules, 40, 2)
    best = cands[0]
    wide = [s for s in best["stalls"] if s["type"] == "expanded"]
    assert len(wide) >= 12 and all(s["width_m"] == 2.6 and s["length_m"] == 5.2 for s in wide)
    assert sum(s["type"] == "accessible" for s in best["stalls"]) == 2


# --- module tiling: a plate several modules deep must carry several bands ------------------------
# The parking module (stall + aisle + stall) is the unit a plate is sized in, and geometry.py already
# quantises plate depth to a whole number of them.  A packer that lays ONE band into a plate cut for
# three leaves two thirds of the excavation carrying nothing.  Xu Han-zhe et al., J. BUPT 42(4):102-108
# (2019) lay modules along every boundary edge first and then decompose the interior; CCDC's
# Parking Structure Design Guidelines put it as "overall width shall be a multiple of the bay width".

DEEP_SITE = box(0, 0, 80, 62)
DEEP_FRONT = LineString([(0, 62), (80, 62)])                      # the front road, whose strip is reserved
DEEP_ROAD = MultiLineString([LineString([(0, 0), (80, 0)])])      # the vehicle road the drive reaches
# 62 m minus the 8 m front reserve leaves 54 m of ground: 3 whole 16.0 m modules with 6 m to spare.
DEEP_GROUND = DEEP_SITE.difference(DEEP_FRONT.buffer(8.0))


def _bands(candidate):
    """Connected components of the aisle area, i.e. how many parking bands the candidate laid."""
    from shapely.ops import unary_union
    drive = unary_union([candidate["drive"]])
    return len(getattr(drive, "geoms", [drive]))


def test_a_plate_three_modules_deep_carries_three_bands_not_one():
    cands = row_candidates(DEEP_SITE, DEEP_GROUND, Polygon(), Polygon(), DEEP_ROAD, DEEP_FRONT,
                           RULES, 200, 2)
    assert cands, "no candidate"
    best = cands[0]
    assert best["bands"] >= 3, best.get("bands")
    # three double-loaded bands of ~80 m hold far more than one: the single band tops out near 60
    assert best["provided"] >= 120, best["provided"]


def test_the_bands_are_one_connected_drive_not_parallel_dead_ends():
    # IStructE Design Recommendations for Multi-Storey and Underground Car Parks 4th ed. 3.2.6/4.4:
    # the aisle graph has to be strongly connected so a driver who misses a space can come round again.
    # Whether that is one cross aisle (comb) or two (ring) is for the objective, not for this test.
    cands = row_candidates(DEEP_SITE, DEEP_GROUND, Polygon(), Polygon(), DEEP_ROAD, DEEP_FRONT,
                           RULES, 200, 2)
    best = cands[0]
    assert _bands(best) == 1, "the drive must be one piece"
    assert best["cross_aisles"] >= 1
    assert best["drive"].distance(DEEP_ROAD) < 1e-6


def test_every_stall_still_faces_the_drive_and_sits_inside_the_ground():
    cands = row_candidates(DEEP_SITE, DEEP_GROUND, Polygon(), Polygon(), DEEP_ROAD, DEEP_FRONT,
                           RULES, 200, 2)
    best = cands[0]
    assert all(DEEP_GROUND.buffer(1e-6).covers(s["polygon"]) for s in best["stalls"])
    assert all(best["drive"].buffer(1e-6).covers(s["front"]) for s in best["stalls"])
    assert all(s["polygon"].intersection(best["drive"]).area < 1e-6 for s in best["stalls"])


def test_tiling_beats_a_single_band_on_area_per_stall():
    # Area per stall is the metric the trade is judged on (Kavanagh, The Parking Professional, IPMI
    # 2015: 325 sf = 30.2 m2 is the planning constant).  Against the SAME excavated plate, tiling
    # must not be worse than one band; the single band leaves the rest of the plate empty.
    cands = row_candidates(DEEP_SITE, DEEP_GROUND, Polygon(), Polygon(), DEEP_ROAD, DEEP_FRONT,
                           RULES, 200, 2)
    tiled = next(c for c in cands if c["bands"] >= 3)
    plate = DEEP_GROUND.area
    assert plate / tiled["provided"] < 40.0, plate / tiled["provided"]   # 2x the 20.0 m2 ideal module


def test_a_shallow_plate_still_yields_the_single_band_it_did_before():
    # One module deep is the n=1 case of the same grammar: no regression on the original fixture.
    cands = row_candidates(SITE, GROUND, FOOTPRINT, Polygon(), ROAD, FRONT, RULES, 40, 2)
    assert cands and cands[0]["provided"] == 40
    single = [c for c in cands if c["bands"] == 1]
    assert single, "the one-band candidate must still be reachable"


def test_a_dead_end_run_longer_than_six_stalls_is_reported():
    # IStructE 4.4.2: a dead-end aisle should serve at most six bins, and beyond that a turning space
    # is needed.  Korean statute has no 회차 clause (임재문 외, 한국산학기술학회논문지 15(12):7403-7415,
    # 2014), so this is MEASURED and reported, never used to fail a plan here.
    cands = row_candidates(DEEP_SITE, DEEP_GROUND, Polygon(), Polygon(), DEEP_ROAD, DEEP_FRONT,
                           RULES, 200, 2)
    best = cands[0]
    assert "dead_end_stalls" in best["terms"]
    assert isinstance(best["terms"]["dead_end_stalls"], int)

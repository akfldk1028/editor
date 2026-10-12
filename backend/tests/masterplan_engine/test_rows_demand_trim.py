"""A level that keeps fewer bays than its plate holds keeps an aisle sized to the kept bays.

Measured on 고산 B1 (2026-10-11) at 20 of 28: the 확장형 zone sat at the far end of the 62 m
aisle, the nearest standard bays were taken from the near end, and the kept set spanned the
whole corridor - 14 bays on one side and 6 at the far end of the other, on the full-length drive.
"""
from __future__ import annotations

from shapely.geometry import LineString, Polygon, box

from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates

RULES = {"stall_width_m": 2.5, "stall_length_m": 5.0, "accessible_width_m": 3.3, "accessible_length_m": 5.0,
         "aisle_width_m": 6.0, "expanded_width_m": 2.6, "expanded_length_m": 5.2, "expanded_min_share": 0.3}
SITE = box(0, 0, 80, 17)                       # one 5.2 + 6 + 5.2 module (확장형 depth), 80 m long: 28 + 28 bays
ROAD = LineString([(0, 0), (0, 16)])           # the landing / entrance edge at the west end


def _best(required):
    rows = row_candidates(SITE, SITE, Polygon(), None, ROAD, ROAD, RULES, required, 2, allowed_angles=[0.0], limit=4)
    return max((r for r in rows if r["provided"] >= min(required, 20)), key=lambda r: r["score"])


def test_kept_bays_cluster_at_the_entrance_and_the_aisle_stops_after_them():
    full, part = _best(60), _best(20)
    assert full["provided"] >= 50 and part["provided"] == 20
    far = max(s["polygon"].bounds[2] for s in part["stalls"])
    assert far < 45, far                         # 10 bays a side with the 확장형 and accessible widths, not 80 m
    assert part["drive"].bounds[2] <= far + RULES["aisle_width_m"] + 1e-6
    assert part["drive"].area < 0.6 * full["drive"].area
    assert sum(s["type"] == "expanded" for s in part["stalls"]) >= 6     # the 30 % quota is still met
    assert sum(s["type"] == "accessible" for s in part["stalls"]) == 2

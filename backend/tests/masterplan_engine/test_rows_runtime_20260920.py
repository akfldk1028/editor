"""Large-site row search must stay bounded while returning measured geometry."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_large_road_served_site_finishes_with_connected_tiled_geometry():
    # 240 x 120 m (28,800 m²) represents the previously timed-out benchmark stratum.
    # A child process gives the search a hard wall-clock limit on Windows as well as Linux.
    program = """
import json, sys
sys.path.insert(0, '.')
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
from shapely.geometry import box, Polygon, LineString
site = box(0, 0, 240, 120)
footprint = box(70, 65, 170, 110)
ground = site.difference(footprint)
road = LineString([(0, 0), (240, 0)])
rules = {'stall_width_m': 2.5, 'stall_length_m': 5.0,
         'accessible_width_m': 3.3, 'accessible_length_m': 5.0,
         'aisle_width_m': 6.0}
candidates = row_candidates(site, ground, footprint, Polygon(), road, None,
                            rules, 450, 4, field='auto')
best = candidates[0]
print(json.dumps({
    'count': len(candidates),
    'provided': best['provided'],
    'bands': best['bands'],
    'cross_aisles': best['cross_aisles'],
    'search_count': best['search_count'],
    'road_reached': best['drive'].distance(road) < 1e-6,
    'drive_connected': best['drive'].geom_type == 'Polygon',
    'stalls_in_ground': all(ground.buffer(1e-6).covers(s['polygon']) for s in best['stalls']),
    'stalls_face_drive': all(best['drive'].buffer(1e-6).covers(s['front']) for s in best['stalls']),
}))
"""
    run = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", program],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    result = json.loads(run.stdout.strip())

    assert result["count"] > 0
    assert result["provided"] >= 300
    assert result["bands"] >= 3
    assert result["cross_aisles"] >= 1
    assert 0 < result["search_count"] <= 384
    assert result["road_reached"]
    assert result["drive_connected"]
    assert result["stalls_in_ground"]
    assert result["stalls_face_drive"]

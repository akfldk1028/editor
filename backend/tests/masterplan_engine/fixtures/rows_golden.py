"""Write the handoff's three frozen row outputs for byte-for-byte comparison."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from shapely.geometry import LineString, box
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
RULES = {"stall_width_m": 2.5, "stall_length_m": 5.0, "accessible_width_m": 3.3, "accessible_length_m": 5.0, "aisle_width_m": 6.0}
CASES = {
  'bounded': (box(0, 0, 240, 120), box(70, 65, 170, 110), LineString([(0, 0), (240, 0)]), 120, 2, {}),
  'piloti':  (box(0, 0, 60, 60),   box(0, 2, 60, 22),     LineString([(0, 0), (60, 0)]),   20, 1,
              {'occupied_footprint': box(0, 12, 40, 22), 'allowed_angles': [0.0]}),
  'rotated': (box(0, 0, 90, 70).buffer(0), box(30, 30, 60, 60), LineString([(0, 0), (90, 0)]), 40, 2, {'allowed_angles': [37.0]}),
}
out = {}
for name, (site, fp, road, need, acc, kw) in CASES.items():
    ground = site.difference(kw.get('occupied_footprint', fp))
    rows = row_candidates(site, ground, fp, None, road, road, RULES, need, acc, limit=6, **kw)
    out[name] = [{'provided': r['provided'], 'score': round(r['score'], 9), 'angle': round(r['angle_deg'], 6),
                  'stalls': [(s['polygon'].wkt, s['type']) for s in r['stalls']],
                  'drive': r['drive'].wkt, 'entrance': r['entrance'].wkt if r.get('entrance') is not None else None} for r in rows]
with open(sys.argv[1], 'w', encoding='utf-8') as output:
    json.dump(out, output, ensure_ascii=False, indent=0)

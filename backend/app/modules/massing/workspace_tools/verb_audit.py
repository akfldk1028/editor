"""Declared vs delivered, one verb at a time.

The sentence is the whole product: every gate, score, sheet and jury verdict
downstream reads a mass that a verb built from a number a person wrote. Nobody
was checking that the number arrives. It does not always:

    stack n=3     the three tiers are built INSIDE the body they stack on,
                  which is never removed - the delivered plan is a plain box
                  at every height but the top, and `grow: true` changes
                  nothing at all
    puncture n=2  at the default size the two cutters land 0.17 m apart and
                  merge, so the sentence that asked for two light wells is
                  judged as one

Neither is refused anywhere: a merged void is a lawful void and a box is a
lawful box, so the jury sees a building that does not contain the idea the
sentence wrote, and marks CONCEPT down without ever being told why.

Run it after any change to `execute.py`:

    python tools/verb_audit.py
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

import os, sys, json, math, django

ensure_design_runtime()
from pathlib import Path
T = _mass_paths.tools_root()
from backend.app.modules.design.generation.maas.massv2.execute import execute
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction
from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE
from shapely.ops import unary_union
from shapely.geometry import Polygon

site = load_legal_site(PNU, building_type=BUILDING_TYPE)
buildable = site.plan_at(0.0)
axis = site_open_side_direction(site) or (1.0, 0.0)
H = site.floor_height_m * 4

def build(ops, storeys=4):
    rec = {"name": "audit", "primary_language": "solid_body",
           "secondary_language": "audit", "formal_principle": "audit",
           "dominant_gesture": "audit", "reference_basis": "audit",
           "floor_height_m": 4.0, "ops": ops}
    parti = parti_from_record(rec)
    if parti is None: return None
    return execute(parti, buildable=buildable, axis=axis, height_m=H, storey_height_m=4.0)

def solids(form): return [p for p in form.placements if p.kind == "additive"]
def cutters(form): return [p for p in form.placements if p.kind == "subtractive"]
def plan(p):
    cs = p.corners(); return Polygon([(c[0], c[1]) for c in cs[:4]]).convex_hull
def span(p, i):
    cs = p.corners(); v = [c[i] for c in cs]; return max(v) - min(v)

EXT = {"op": "extrude", "height": 1.0, "storeys": 4, "profile": "square", "why": "base"}
rows = []

def check(label, declared, delivered, ok):
    rows.append((label, declared, delivered, ok))

# --- count verbs -----------------------------------------------------------
for n in (2, 3, 4, 5):
    f = build([EXT, {"op": "stack", "n": n, "contrast": 1.5, "why": "x"}])
    got = len(solids(f)) if f else 0
    check(f"stack n={n}", n, got, got == n)
for n in (2, 3, 4):
    f = build([EXT, {"op": "aggregate", "n": n, "spread": 1.5, "height": 0.6, "tie": 0.2, "why": "x"}])
    got = len(solids(f)) if f else 0
    check(f"aggregate n={n}", f"{n}+판", got, got >= n)
for n in (1, 2, 3):
    for s in (0.22, 0.15):
        f = build([EXT, {"op": "puncture", "size": s, "n": n, "why": "x"}])
        if not f: check(f"puncture n={n} size={s}", n, "실행실패", False); continue
        cs = cutters(f)
        merged = unary_union([plan(c) for c in cs])
        holes = len(getattr(merged, "geoms", [merged]))
        check(f"puncture n={n} size={s}", n, f"커터{len(cs)}→구멍{holes}", holes == n)

# --- ratio verbs -----------------------------------------------------------
for r in (0.35, 0.5, 0.62, 0.75):
    f = build([EXT, {"op": "split", "ratio": r, "along": "long", "first": "a",
                     "second": "b", "contrast": 1.0, "gap": 0, "why": "x"}])
    if not f or len(solids(f)) < 2: check(f"split ratio={r}", r, "부분<2", False); continue
    a, b = sorted(solids(f), key=lambda p: -plan(p).area)[:2]
    got = plan(a).area / (plan(a).area + plan(b).area)
    check(f"split ratio={r}", f"{max(r,1-r):.2f}", f"{got:.3f}", abs(got - max(r, 1 - r)) < 0.05)

for g in (0.10, 0.16, 0.25):
    f = build([EXT, {"op": "split", "ratio": 0.5, "along": "long", "first": "a",
                     "second": "b", "contrast": 1.0, "gap": g, "why": "x"}])
    if not f or len(solids(f)) < 2: check(f"split gap={g}", g, "부분<2", False); continue
    a, b = solids(f)[:2]
    got = plan(a).distance(plan(b))
    width = max(span(a, 0), span(a, 1))
    check(f"split gap={g}", f"{g:.2f}·W", f"{got:.2f}m ({got/max(width,1e-6):.3f}·W)", got > 0.5)

for r in (0.4, 0.6, 0.8):
    f = build([EXT, {"op": "taper", "ratio": r, "why": "x"}])
    if not f: check(f"taper ratio={r}", r, "실행실패", False); continue
    ss = solids(f)
    lo = min(ss, key=lambda p: p.z_span()[0]); hi = max(ss, key=lambda p: p.z_span()[1])
    got = max(span(hi, 0), span(hi, 1)) / max(max(span(lo, 0), span(lo, 1)), 1e-6)
    check(f"taper ratio={r}", r, f"{got:.3f}", abs(got - r) < 0.15)

for c in (0.15, 0.25, 0.4):
    f = build([EXT, {"op": "lift", "clearance": c, "why": "x"}])
    if not f: check(f"lift clearance={c}", c, "실행실패", False); continue
    ss = solids(f)
    base = min(p.z_span()[0] for p in ss if p.z_span()[0] > 1e-6) if any(p.z_span()[0] > 1e-6 for p in ss) else 0.0
    check(f"lift clearance={c}", f"{c:.2f}·H={c*H:.1f}m", f"{base:.2f}m", base > 0.5)

# --- angle verbs -----------------------------------------------------------
def bearing(p):
    cs = p.corners()[:4]
    return math.degrees(math.atan2(cs[1][1] - cs[0][1], cs[1][0] - cs[0][0]))
base_form = build([EXT])
base_bear = bearing(solids(base_form)[0]) if base_form else 0.0
for deg in (15, 30, 45):
    f = build([EXT, {"op": "rotate", "degrees": deg, "why": "x"}])
    if not f: check(f"rotate {deg}deg", deg, "실행실패", False); continue
    got = (bearing(solids(f)[0]) - base_bear) % 180
    got = min(got, 180 - got) if got > 90 else got
    check(f"rotate {deg}deg", deg, f"{got:.1f}deg", abs(got - deg) < 3)

w = max(len(r[0]) for r in rows)
bad = 0
for label, dec, got, ok in rows:
    if not ok: bad += 1
    print(f"{'OK ' if ok else '틀림'} {label:{w}}  선언 {str(dec):>12}   배달 {str(got):>18}")
print(f"\n{len(rows)}건 중 {bad}건 불일치")

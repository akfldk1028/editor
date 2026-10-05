"""How few lines explain where every part of a mass sits.

Akin & Moustapha watched six architects mass a building for two hours each
(Design Studies 25(1), 2004) and found one mechanism structuring all of it:
regulating elements - symmetry axes, centres of rotation, alignment lines. What
they let an architect do is add and remove masses freely while the underlying
structure survives, and that survival is what separates a composition from a
pile. `massing-study/our-gap.md` states the test this repo needs and never
built: *can a small set of axes explain the placement of every part-mass? Few
elements for many parts = composed. Many or none = a pile.*

This is that test. Every body's plan edges are clustered into lines by bearing
and offset, and the smallest set of lines that touches every body is found
greedily. The number reported is bodies per line: a composition where five
bodies all sit on two axes reads as one building, and five bodies needing five
axes is five buildings sharing a plot.

One-body masses are excluded rather than scored 1.0 - a single volume has
nothing to regulate, and counting it as perfectly composed would drown the
measure in the 65% of the corpus that delivers one body.

    python tools/regulating_audit.py <run> [sample]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import collections
import json
import math
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402  (django setup inside)
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2 import structure  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()

# Two edges are the same regulating line when they run within this angle and sit
# within this distance of one another. A degree is finer than any bearing this
# language sets, and half a metre is the joint clearance the corpus already
# holds - closer than that and two walls are one wall.
_SAME_BEARING_DEG = 2.0
_SAME_OFFSET_M = 0.5
# An edge shorter than this is a chamfer or a rounding artefact, not a wall that
# could align with anything.
_MIN_EDGE_M = 3.0


def _edges(polygon):
    ring = list(polygon.exterior.coords)[:-1]
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        length = math.hypot(x1 - x0, y1 - y0)
        if length < _MIN_EDGE_M:
            continue
        # A line as (bearing mod 180, signed distance from the origin), which is
        # the pair that makes two parallel walls one axis only when they are also
        # the same wall.
        bearing = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
        radians = math.radians(bearing)
        offset = -x0 * math.sin(radians) + y0 * math.cos(radians)
        yield bearing, offset, length


def _lines_of(parts) -> dict[tuple[int, int], set[int]]:
    """Candidate regulating lines, each with the parts that lie on one."""

    lines: dict[tuple[int, int], set[int]] = collections.defaultdict(set)
    for index, plan in enumerate(parts):
        for bearing, offset, _length in _edges(plan):
            key = (int(round(bearing / _SAME_BEARING_DEG)),
                   int(round(offset / _SAME_OFFSET_M)))
            lines[key].add(index)
    return lines


def distinct_parts(source) -> list:
    """A mass's part-plans, one per distinct footprint.

    `source.volumes` is a band per storey, so an eight-storey tower arrives as
    eight volumes carrying the same plan. Eight copies of one wall all sit on
    the same line and would score 8.00 - a single tower read as the most
    composed thing in the corpus. A part is a footprint, however many bands are
    stacked on it.
    """

    seen: dict[str, object] = {}
    for volume in source.volumes:
        plan = volume.footprint
        if plan is None or plan.is_empty:
            continue
        centre = plan.centroid
        key = (f"{centre.x:.1f}|{centre.y:.1f}|{plan.area:.1f}|"
               f"{plan.length:.1f}")
        seen.setdefault(key, plan)
    return list(seen.values())


def regulating_ratio(parts) -> tuple[int, int]:
    """(parts, lines needed to touch them all), greedily covered.

    Parts, not merged bodies. The first version counted `structure.bodies_of`,
    which unions volumes that touch - so aligning four objects onto one axis
    made them meet, merged them into two bodies, and the ratio *fell* from 2.00
    to 1.00 for a composition that had just become regulated. The test this
    implements asks whether a small set of lines explains the placement of every
    part-mass, and a part is what the sentence placed.
    """

    if len(parts) < 2:
        return len(parts), 0
    lines = _lines_of(parts)
    uncovered = set(range(len(parts)))
    used = 0
    while uncovered:
        best = max(lines.values(), key=lambda held: len(held & uncovered),
                   default=set())
        gained = best & uncovered
        if not gained:
            # Bodies with no edge long enough to align - each is its own line.
            used += len(uncovered)
            break
        uncovered -= gained
        used += 1
    return len(parts), used


def main(run: str, sample: str = "120") -> int:
    summary = json.loads((ROOT / "runs" / run / "massv2-summary.json")
                         .read_text(encoding="utf-8"))
    standing = [
        record for record in summary["records"]
        if (record.get("plausibility") or {}).get("occupiable")
        and ((record["plausibility"].get("structure") or {}).get("body_count") or 0) > 1
    ]
    book = corpus()
    schedule = schedule_of(run)
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    wanted = int(sample)
    step = max(1, len(standing) // wanted)
    rows = []
    for record in standing[::step][:wanted]:
        family = record["name"].split("~")[0].split("^")[0]
        parti = book.get(family)
        if parti is None:
            continue
        asked = max((float(op.get("storeys") or 0) for op in parti["ops"]),
                    default=0.0)
        source = rebuild(record["name"], book, site, buildable, axis,
                         max(base, asked * site.floor_height_m), schedule=schedule)
        if source is None:
            continue
        count, lines = regulating_ratio(distinct_parts(source))
        if lines:
            rows.append((family, count, lines, count / lines))

    if not rows:
        print("여러 동인 매스가 없다")
        return 0
    ratios = sorted(row[3] for row in rows)
    print(f"{run} · 두 동 이상인 매스 {len(standing)}개 중 {len(rows)}개 표본")
    print(f"{'축당 동 수':>10}  {'매스':>5}")
    buckets = collections.Counter()
    for ratio in ratios:
        buckets["1.0 (축마다 한 동 — 더미)" if ratio < 1.25
                else "1.25~2" if ratio < 2.0
                else "2~3" if ratio < 3.0 else "3 이상 (구성됨)"] += 1
    for label in ("1.0 (축마다 한 동 — 더미)", "1.25~2", "2~3", "3 이상 (구성됨)"):
        if buckets[label]:
            print(f"{label:<26} {buckets[label]:4d} ({100 * buckets[label] / len(rows):4.1f}%)")
    print(f"\n중앙 {ratios[len(ratios) // 2]:.2f} 동/축 · 최소 {ratios[0]:.2f} · 최대 {ratios[-1]:.2f}")
    worst = sorted(rows, key=lambda row: row[3])[:5]
    print("\n가장 두서없는 쪽")
    for family, count, lines, ratio in worst:
        print(f"   {family[:40]:<40} 동 {count:2d} · 축 {lines:2d} · {ratio:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))

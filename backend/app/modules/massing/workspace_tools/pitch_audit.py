"""Does a roof come out at the pitch the sentence declared?

`skew` was found declaring 24 degrees and building 38.7, because the verb handed
`degrees / 30` to a matrix whose amount is a tangent. `pitch` is the other number
in this language with a geometric meaning an architect can check - a slope, rise
per unit of run, 1.0 being 45 degrees - and it is capped on the way through:
`gable` and `mansard` both hold the roof to a storey or two, so a steep pitch
declared on a wide body is delivered shallower than it was written.

That cap is deliberate and this does not argue with it. It measures how far the
declared number and the built one have drifted apart, per sentence, so the
distance is a fact rather than an assumption.

    python tools/pitch_audit.py [pattern]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import math
import sys

from backend.app.modules.massing.workspace_tools.band_probe import corpus  # noqa: E402  (django setup inside)
from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOF_VERBS = ("gable", "mansard", "butterfly", "shed", "pitch")


def _span_along(corners, direction) -> float:
    """The volume's extent along a world direction, in metres."""

    return max(
        abs((c[0] - d[0]) * direction[0] + (c[1] - d[1]) * direction[1])
        for c in corners for d in corners
    )


def delivered_slope(item) -> float | None:
    """The steepest run of this volume's top, as rise over run in metres.

    A section is said two ways in this language and the first version of this
    read only one of them, so eight gables came back as "no roof". `mansard` and
    `butterfly` carry `top_profile`; `gable` carries `ridge_along` with
    `top_drop`, the ridge running through the plan centroid with the full drop
    at each eave - half the across-ridge width of run.
    """

    corners = item.corners()
    z0 = min(c[2] for c in corners)
    z1 = max(c[2] for c in corners)
    body = z1 - z0
    if body <= 1e-6:
        return None

    if item.ridge_along and item.top_drop:
        # Across the ridge, not along it.
        across_dir = (-item.ridge_along[1], item.ridge_along[0])
        run = _span_along(corners, across_dir) / 2.0
        return (item.top_drop * body / run) if run > 1e-6 else None

    if item.drop_toward and item.top_drop:
        run = _span_along(corners, item.drop_toward)
        return (item.top_drop * body / run) if run > 1e-6 else None

    profile = item.top_profile
    if not profile or len(profile) < 2:
        return None
    across = item.profile_across
    if not across:
        return None
    span = _span_along(corners, across)
    if span <= 1e-6:
        return None
    steepest = 0.0
    for (a0, v0), (a1, v1) in zip(profile, profile[1:]):
        run = abs(a1 - a0) * span
        rise = abs(v1 - v0) * body
        if run > 1e-6:
            steepest = max(steepest, rise / run)
    return steepest


def main(pattern: str = "") -> int:
    book = corpus()
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    rows = []
    for name, record in sorted(book.items()):
        if pattern and pattern not in name:
            continue
        declared = [
            (op.get("op"), float(op["pitch"]))
            for op in record["ops"]
            if op.get("pitch") is not None and op.get("op") in ROOF_VERBS
        ]
        if not declared:
            continue
        parti = parti_from_record(record)
        if parti is None:
            continue
        storey = float(parti.floor_height_m or site.floor_height_m)
        asked = max((float(o.get("storeys") or 0) for o in record["ops"]), default=0.0)
        form = execute_parti(
            parti, buildable=buildable, axis=axis,
            height_m=max(base, asked * site.floor_height_m), storey_height_m=storey)
        if form is None:
            continue
        steepest = None
        for item in form.placements:
            slope = delivered_slope(item)
            if slope is None:
                continue
            corners = item.corners()
            body = max(c[2] for c in corners) - min(c[2] for c in corners)
            if steepest is None or slope > steepest[0]:
                steepest = (slope, body, item.top_drop * body)
        if steepest is None:
            rows.append((name, declared[0][0], declared[0][1], None, ""))
            continue
        slope, body, drop = steepest
        # Which of the two ceilings the roof stopped at, so a shallow delivery
        # reads as a reason rather than as an alarm.
        cap_m = 1.5 * storey
        if slope >= declared[0][1] * 0.98:
            why = ""
        elif abs(drop - cap_m) < 0.2:
            why = f"지붕 상한 {cap_m:.1f} m"
        elif drop > 0.9 * body:
            why = f"몸이 {body:.1f} m뿐 (한 층)"
        else:
            why = ""
        rows.append((name, declared[0][0], declared[0][1], slope, why))

    print(f"{'문장':<38}{'동사':<10}{'선언도':>8}{'배달도':>8}  {'멈춘 이유'}")
    kept = 0
    for name, verb, want, got, why in rows:
        if got is None:
            print(f"{name[:38]:<38}{verb:<10}{math.degrees(math.atan(want)):>8.1f}{'-':>8}  지붕 없음")
            continue
        if got >= want * 0.7:
            kept += 1
        print(f"{name[:38]:<38}{verb:<10}{math.degrees(math.atan(want)):>8.1f}"
              f"{math.degrees(math.atan(got)):>8.1f}  {why}")
    print(f"\n{kept}/{len(rows)} 문장이 선언 경사의 70% 이상을 배달")
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2])))

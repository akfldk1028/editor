"""Two ways to spend area, and what each does to a declared gap.

`fill` brings a scheme back under its brief by scaling the whole composition
about one shared anchor (`_wider`, fill.py:492). That scales the distance between
volumes along with their size, so a lane declared in metres is spent as a
proportion: kr_uijeongbu_art_library declares 2.43 m and delivers 1.87.

Two alternatives, measured on that sentence rather than argued:

  - sliding the volumes apart, which the previous commit claimed costs no
    건축면적 because 건축면적 is a projection. On an unbounded plane that is
    true; on this parcel it is false. The volumes move out of the envelope and
    are clipped - 394 m2 falls to 363, 320, 330, and the ground gap goes to zero
    because a volume is clipped away entirely.

  - shrinking each volume where it stands, which spends the same area and widens
    the lane instead of closing it: x0.95 gives 355.8 m2 and a 2.35 m gap against
    the 1.87 m the shared anchor leaves, still lawful.

The second is the candidate. It is not a drop-in: scaling a volume about its own
centre breaks contact with whatever it rests on, which is the reason the shared
anchor is there. The scoped form is that a volume standing on the ground and
carrying nothing may shrink in place, and everything else keeps the anchor.

    python tools/trim_alternatives.py
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import sys
from dataclasses import replace
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402
from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402
from backend.app.modules.massing.workspace_tools.gap_trace import ground_gap  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import declared_stature, parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.compile import _plan  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal_fit import fit_to_site, projected_ground_area
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, translation_matrix4, validate_matrix4
from backend.app.modules.design.generation.maas.massv2.siting import OPEN_SIDE_SITINGS, SITINGS, site_open_side_direction, place_on_site
from backend.app.modules.design.generation.maas.massv2.variations import spread_across_coverage  # noqa: E402

FAMILY = "kr_uijeongbu_art_library_three_decks_one_room"


def exploded(form, distance: float):
    """Slide every volume away from the composition's centre by `distance`/2."""

    plans = [_plan(item) for item in form.additive()]
    if len(plans) < 2:
        return form
    xs = [p.centroid.x for p in plans]
    ys = [p.centroid.y for p in plans]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    moved = []
    for item in form.placements:
        plan = _plan(item)
        if plan.is_empty:
            moved.append(item)
            continue
        dx, dy = plan.centroid.x - cx, plan.centroid.y - cy
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            moved.append(item)
            continue
        step = distance / 2.0
        matrix = compose_matrix4(
            translation_matrix4((dx / length * step, dy / length * step, 0.0)),
            item.matrix,
        )
        moved.append(replace(item, matrix=validate_matrix4(matrix)))
    return replace(form, placements=tuple(moved))


def report(label, form, site, storey):
    fit = fit_to_site(form, site)
    src = compile_matrix_form(form, storey_height_m=storey, allowed_at=site.plan_at)
    print(f"{label:<22}{projected_ground_area(form, allowed_at=site.plan_at):>10.1f}"
          f"{fit.gross_floor_area_m2:>10.1f}{ground_gap(src) if src else 0:>9.2f}"
          f"   {'적법' if fit.satisfied else '위법'}")


def main() -> int:
    schedule = schedule_of("uij-aim")
    record = corpus()[FAMILY]
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    open_side = site_open_side_direction(site)
    sitings = OPEN_SIDE_SITINGS if open_side is not None else SITINGS

    parti = parti_from_record(record)
    storey = float(parti.floor_height_m or site.floor_height_m)
    asked = max((float(o.get("storeys") or 0) for o in record["ops"]), default=0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    form = execute_parti(parti, buildable=buildable, axis=axis,
                         height_m=max(base, asked * site.floor_height_m),
                         storey_height_m=storey)
    if asked > 0.0:
        form = replace(form, extra={**dict(form.extra), **declared_stature(record)})
    from backend.app.modules.design.generation.maas.massv2 import program as programme
    form = programme.resized_to(form, schedule, weight=1.0, storey_height_m=storey)
    copy = next(c for c in spread_across_coverage(
        form, ground_capacity_m2=site.ground_capacity_m2,
        far_capacity_m2=site.far_capacity_m2,
        floor_height_m=site.floor_height_m)
        if c.name.endswith("dispersed_ground"))
    moved = place_on_site(copy, buildable, sitings[0], open_side=open_side) or copy
    target = moved.extra.get("programme_target")
    grown = fill_to_site(
        moved, site,
        target_utilization=(float(target) / max(site.far_capacity_m2, 1e-9)
                            if target else None)).fit.form

    print(f"{'':<22}{'건축면적':>10}{'연면적':>10}{'지면 틈':>9}")
    report("성장 후", grown, site, storey)
    for distance in (0.5, 1.0, 1.5):
        report(f"벌림 +{distance:.1f} m", exploded(grown, distance), site, storey)
    # The other way to spend area: each volume shrinks where it stands, so the
    # space between them widens instead of the whole figure closing up.
    from backend.app.modules.design.generation.maas.massv2.legal_fit import _scaled_in_plan
    for factor in (0.95, 0.90, 0.85):
        shrunk = replace(grown, placements=tuple(
            _scaled_in_plan(item, factor,
                            (_plan(item).centroid.x, _plan(item).centroid.y))
            if not _plan(item).is_empty else item
            for item in grown.placements))
        report(f"제자리 축소 x{factor:.2f}", shrunk, site, storey)
    return 0


if __name__ == "__main__":
    sys.exit(main())

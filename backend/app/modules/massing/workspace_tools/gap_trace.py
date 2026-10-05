"""Where a declared gap goes, stage by stage.

Seven sentences are refused for a gap that closed before delivery, four of them
Korean, and `gap_survived`'s docstring names the growth loop and the legal clip
as the causes. The four Korean ones all declare 2.43 m and deliver 1.49, 1.70,
1.89 and 0.00 - ratios of 0.61 to 0.78 that look like a plan scale rather than a
clip, and the korea track shrinks every scheme to its 실별 소요면적표 before it
grows. This measures the gap after each stage instead of inferring it.

    python tools/gap_trace.py <run> <family>
    python tools/gap_trace.py uij-aim kr_anseong_bathhouse_makes_the_mass
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from dataclasses import replace
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402  (django setup inside)
from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.ablation import JOINT_CLEARANCE_M  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import declared_stature, parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal_fit import fit_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import OPEN_SIDE_SITINGS, SITINGS, site_open_side_direction, place_on_site
from backend.app.modules.design.generation.maas.massv2.variations import spread_across_coverage  # noqa: E402

ROOT = _mass_paths.workspace_root()


def widest_gap(source) -> float:
    """The widest narrowest-separation over the storeys, as `gap_survived` reads it."""

    widest = 0.0
    for volume in source.volumes:
        level = (volume.bottom_fraction + volume.top_fraction) / 2.0
        parts = [
            item.footprint
            for item in source.volumes
            if item.bottom_fraction - 1e-6 <= level <= item.top_fraction + 1e-6
        ]
        if len(parts) < 2:
            continue
        merged = unary_union(parts)
        pieces = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
        if len(pieces) < 2:
            continue
        widest = max(widest, min(
            float(one.distance(two))
            for index, one in enumerate(pieces)
            for two in pieces[index + 1:]
        ))
    return widest


def ground_gap(source) -> float:
    """The separation between what stands on the ground, which is what 골목 means."""

    parts = [
        volume.footprint for volume in source.volumes
        if volume.bottom_fraction <= 1e-6
    ]
    if len(parts) < 2:
        return 0.0
    merged = unary_union(parts)
    pieces = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
    if len(pieces) < 2:
        return 0.0
    return min(
        float(one.distance(two))
        for index, one in enumerate(pieces)
        for two in pieces[index + 1:]
    )


def main(run: str, family: str) -> int:
    schedule = schedule_of(run)
    record = corpus()[family]
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
    declared = min(
        (float(op.params.get("gap") or 0.0) * JOINT_CLEARANCE_M
         for op in parti.ops if float(op.params.get("gap") or 0.0) > 0.0),
        default=0.0)

    def read(form, label):
        src = compile_matrix_form(form, storey_height_m=storey,
                                  allowed_at=site.plan_at)
        if src is None:
            print(f"{label:<28}  컴파일 없음")
            return
        gap = widest_gap(src)
        # The gate's number is the widest of the per-storey narrowest gaps, and
        # it moves for reasons the lane does not: siting alone took this
        # sentence from 3.41 m to 8.48 m. The separation at the ground is the
        # one an architect means by 골목, so it is printed beside it.
        ground = ground_gap(src)
        print(f"{label:<28}{gap:>8.2f}{gap / declared if declared else 0:>9.2f}"
              f"{ground:>9.2f}{len(src.volumes):>6}")

    print(f"{family}   선언 {declared:.2f} m")
    print(f"{'단계':<28}{'게이트 m':>8}{'선언대비':>9}{'지면 m':>9}{'볼륨':>6}")

    form = execute_parti(
        parti, buildable=buildable, axis=axis,
        height_m=max(base, asked * site.floor_height_m), storey_height_m=storey)
    if form is None:
        print("실행 실패")
        return 1
    read(form, "1 execute")

    if asked > 0.0:
        form = replace(form, extra={**dict(form.extra), **declared_stature(record)})
    if schedule is not None:
        from backend.app.modules.design.generation.maas.massv2 import program as programme
        form = programme.resized_to(form, schedule, weight=1.0,
                                    storey_height_m=storey)
        read(form, "2 브리프 크기조정")

    for band in ("dispersed_ground", "full_ground"):
        copies = spread_across_coverage(
            form, ground_capacity_m2=site.ground_capacity_m2,
            far_capacity_m2=site.far_capacity_m2,
            floor_height_m=site.floor_height_m)
        copy = next((c for c in copies if c.name.endswith(band)), None)
        if copy is None:
            continue
        read(copy, f"3 밴드 {band[:9]}")
        moved = place_on_site(copy, buildable, sitings[0], open_side=open_side) or copy
        read(moved, f"3b 배치 {band[:9]}")
        # The legal clip on its own, with no growth of any kind in front of it.
        read(fit_to_site(moved, site).form, f"3c 법규만 {band[:9]}")
        target_gross = moved.extra.get("programme_target")
        grown = fill_to_site(
            moved, site,
            target_utilization=(float(target_gross) / max(site.far_capacity_m2, 1e-9)
                                if target_gross else None)).fit.form
        read(grown, f"4 성장+법규 {band[:9]}")
        # Plan growth is the one step that moves volumes toward each other; with
        # it off, whatever the gap still loses belongs to the legal clip.
        flat = fill_to_site(
            moved, site, allow_plan_growth=False,
            target_utilization=(float(target_gross) / max(site.far_capacity_m2, 1e-9)
                                if target_gross else None)).fit.form
        read(flat, f"5 평면성장 끔 {band[:9]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

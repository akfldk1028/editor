"""Does the coverage axis have a rung inside the winners' envelope?

Measured on runs/uij-aim: a sentence's variants sit on one curve, because the
composition's floor area is fixed and only the ground take moves. site_best_notch
delivers 386 m2 at 13.0 m on the dispersed band and 519 m2 at 9.0 m on the held
band - the envelope wants 400-800 m2 *and* 10-20 m, and the two rungs step over
it. 35 of 116 standing families show the same straddle.

The rungs are 0.45 / 0.65 / 0.85 / 1.00 of the certified 건폐 capacity, so the
step from the first to the second is 1.44x, and height moves inversely by the
same factor. This runs a family through extra rungs and prints what each one
actually delivers, so the axis can be re-spaced on measurement rather than on
the ratio arithmetic.

The run is named so the brief travels with the probe. Without it the first
version measured a 3,581 m2 building against a row describing 1,550 - the korea
edition sizes a scheme to its 실별 소요면적표 before the bands, and a probe that
skips that step is not measuring the grid's building.

    python tools/band_probe.py <run> <family> [fraction ...]
    python tools/band_probe.py uij-aim site_best_notch_extracted_corner 0.45 0.55
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from dataclasses import replace
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, BUILDING_TYPE  # noqa: E402  (django setup inside)

from backend.app.modules.design.generation.maas.design_space import CoverageBand  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import declared_stature, parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.measure import measure_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import OPEN_SIDE_SITINGS, SITINGS, site_open_side_direction, place_on_site
from backend.app.modules.design.generation.maas.massv2.variations import spread_across_coverage  # noqa: E402

ROOT = _mass_paths.workspace_root()

HEIGHT = (10.0, 20.0)
GROUND = (400.0, 800.0)

# The four rungs the axis ships with, so the probe can be checked against the
# run before its new numbers are believed.
SHIPPED = (0.45, 0.65, 0.85, 1.00)


def corpus() -> dict:
    out = {}
    # Sweep books live outside inputs/ so the authored canon stays clean,
    # but their sentences must still resolve once staged or juried.
    paths = sorted((ROOT / "inputs").glob("gen-*.json")) +         sorted((ROOT / "runs" / "sweeps").glob("*.json"))
    for path in paths:
        # A book the agent is mid-edit (or a probe someone half-wrote) must
        # not take every tool down with it: warn and skip, the way the
        # validator would refuse it.
        try:
            schemes = json.loads(path.read_text(encoding="utf-8"))["schemes"]
            if not all(isinstance(item, dict) and item.get("name") for item in schemes):
                raise ValueError("schemes must be records with names")
        except Exception as exc:  # noqa: BLE001
            import sys as _sys
            print(f"corpus: skipping {path.name} ({type(exc).__name__}: {exc})", file=_sys.stderr)
            continue
        for scheme in schemes:
            out[scheme["name"]] = scheme
    return out


def schedule_of(run: str):
    """The brief the grid sized these masses to, or None on the overseas track."""

    summary = json.loads((ROOT / "runs" / run / "massv2-summary.json")
                         .read_text(encoding="utf-8"))
    provenance = summary.get("provenance") or {}
    if provenance.get("track") != "korea":
        return None
    brief = provenance.get("programme")
    if not brief:
        return None
    from backend.app.modules.design.generation.maas.massv2 import program as programme
    book = json.loads((ROOT / "inputs" / "programs-korean.json")
                      .read_text(encoding="utf-8"))
    record = next((r for r in book["schedules"] if r.get("name") == brief), None)
    if record is None:
        return None
    return programme.schedule_from_record(
        record, shared_share_of_gross=book.get("shared_area_share_of_gross"))


def main(run: str, family: str, *fractions: str) -> int:
    schedule = schedule_of(run)
    record = corpus()[family]
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    open_side = site_open_side_direction(site)
    sitings = OPEN_SIDE_SITINGS if open_side is not None else SITINGS

    parti = parti_from_record(record)
    if parti is None:
        print("파싱 거부")
        return 1
    storey = float(parti.floor_height_m or site.floor_height_m)
    asked = max((float(o.get("storeys") or 0) for o in record["ops"]), default=0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))
    form = execute_parti(
        parti, buildable=buildable, axis=axis,
        height_m=max(base, asked * site.floor_height_m), storey_height_m=storey,
    )
    if form is None:
        print("실행 실패")
        return 1
    # Both steps the grid takes before the bands, in its order: the declared
    # storey stamp the growth loop reads, then the brief's own size.
    if asked > 0.0:
        form = replace(form, extra={**dict(form.extra), **declared_stature(record)})
    if schedule is not None:
        from backend.app.modules.design.generation.maas.massv2 import program as programme
        form = programme.resized_to(
            form, schedule, weight=1.0, storey_height_m=storey)

    wanted = [float(f) for f in fractions] or list(SHIPPED)
    bands = tuple(
        CoverageBand(f"probe_{int(round(f * 100)):03d}", f"{f:.2f}", "probe", f)
        for f in wanted
    )
    copies = spread_across_coverage(
        form,
        ground_capacity_m2=site.ground_capacity_m2,
        far_capacity_m2=site.far_capacity_m2,
        floor_height_m=site.floor_height_m,
        bands=bands,
    )

    print(f"{family}   건폐 용량 {site.ground_capacity_m2:.0f} ㎡")
    print(f"{'몫':>6}{'요구 ㎡':>9}{'바닥 ㎡':>9}{'높이 m':>8}{'연면적':>9}  {'봉투'}")
    for copy in copies:
        fraction = float(copy.extra.get("coverage_band", "probe_0").split("_")[-1]) / 100.0
        moved = place_on_site(copy, buildable, sitings[0], open_side=open_side) or copy
        # What holds the whole scheme to the brief is the growth loop's target,
        # passed as a share of the parcel's cap - `resized_to` only moves plan
        # between volumes.
        target_gross = moved.extra.get("programme_target")
        grown = fill_to_site(
            moved, site,
            target_utilization=(float(target_gross) / max(site.far_capacity_m2, 1e-9)
                                if target_gross else None),
        )
        src = compile_matrix_form(grown.fit.form, storey_height_m=storey,
                                  allowed_at=site.plan_at)
        if src is None:
            print(f"{fraction:>6.2f}  컴파일 없음")
            continue
        m = measure_form(src)
        fit = grown.fit
        good = (GROUND[0] <= fit.ground_area_m2 <= GROUND[1]
                and HEIGHT[0] <= m.height_m <= HEIGHT[1])
        print(f"{fraction:>6.2f}{site.ground_capacity_m2 * fraction:>9.0f}"
              f"{fit.ground_area_m2:>9.0f}{m.height_m:>8.1f}"
              f"{fit.gross_floor_area_m2:>9.0f}  {'O' if good else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

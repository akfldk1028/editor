"""Every stage of the pipeline, checked against something that would fail.

Not a smoke test. Each check states a property the stage claims and is written
so that a stage which quietly does nothing, or does something else, comes back
FAIL rather than passing by silence - which is how most of this package's bugs
survived.

    python tools/audit_pipeline.py
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE  # noqa: E402  (django setup inside)

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.execute import execute as execute_parti  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import mistyped_words, parti_from_record  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal_fit import fit_to_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2, measure_form  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.plausibility import assess, slenderness_limit  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import OPEN_SIDE_SITINGS, SITINGS, site_open_side_direction, place_on_site
from backend.app.modules.design.generation.maas.massv2.variations import spread_across_coverage  # noqa: E402

ROOT = _mass_paths.workspace_root()
RESULTS: list[tuple[str, str, str]] = []


def check(stage: str, claim: str):
    def wrap(fn):
        try:
            ok, note = fn()
        except Exception as exc:  # a stage that throws is a failing stage
            ok, note = False, f"{type(exc).__name__}: {exc}"
        RESULTS.append((stage, "PASS" if ok else "FAIL", f"{claim} — {note}"))
        return fn
    return wrap


def corpus() -> dict:
    out = {}
    for path in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            out[s["name"]] = s
    return out


CORPUS = corpus()
SITE = load_legal_site(PNU, building_type=BUILDING_TYPE)
BUILDABLE = SITE.plan_at(0.0)
AXIS = site_open_side_direction(SITE) or (1.0, 0.0)
BUDGET = SITE.floor_height_m * max(
    1, int(SITE.far_capacity_m2 // max(1.0, SITE.ground_capacity_m2)))


def _form(name: str):
    rec = CORPUS[name]
    parti = parti_from_record(rec)
    storey = float(parti.floor_height_m or SITE.floor_height_m)
    asked = max((float(o.get("storeys") or 0) for o in rec["ops"]), default=0.0)
    budget = max(BUDGET, asked * SITE.floor_height_m)
    return execute_parti(parti, buildable=BUILDABLE, axis=AXIS,
                         height_m=budget, storey_height_m=storey), storey, budget


@check("관1 문법", "코퍼스 전 문장이 파싱되고, 잘못 쓴 인자는 거부된다")
def _grammar():
    bad = [n for n, s in CORPUS.items() if parti_from_record(s) is None]
    typos = {n: mistyped_words(s) for n, s in CORPUS.items() if mistyped_words(s)}
    ok = not bad and not typos
    return ok, f"파싱 실패 {len(bad)}개, 오타 인자 {len(typos)}개 / 전체 {len(CORPUS)}"


@check("관2 실행", "같은 문장은 같은 형상을 낸다 (결정성)")
def _determinism():
    name = "a_one_bend"
    a, _, _ = _form(name)
    b, _, _ = _form(name)
    sig = lambda f: tuple(tuple(round(v, 9) for row in p.matrix for v in row)
                          for p in f.placements)
    return sig(a) == sig(b), f"{name} 두 번 실행 비교, 조각 {len(a.placements)}개"


@check("관2 실행", "`on:` 은 그 조각만 건드린다")
def _scoping():
    rec = {"name": "t", "primary_language": "solid_body", "ops": [
        {"op": "split", "ratio": 0.5, "along": "cross", "first": "a", "second": "b", "gap": 3.0},
        {"op": "taper", "ratio": 0.5, "on": "a"},
    ]}
    parti = parti_from_record(rec)
    form = execute_parti(parti, buildable=BUILDABLE, axis=AXIS,
                         height_m=BUDGET, storey_height_m=3.0)
    touched = {p.role.split("_")[0] for p in form.placements}
    b_pieces = [p for p in form.placements if p.role.startswith("b")]
    return len(b_pieces) == 1, f"역할 {sorted(touched)}, b 조각 {len(b_pieces)}개(1이어야)"


@check("관3 침묵", "아무 일도 안 하는 단어는 잡힌다")
def _silence():
    # `idle` is not on the form - `ablation.ablate` re-runs the pipeline once
    # per word and reports which ones the delivered mass does not miss. Looking
    # for it on `form.extra` was this check's own bug on the first pass.
    from backend.app.modules.design.generation.maas.massv2 import ablation as ablate_module
    rec = {"name": "t", "primary_language": "solid_body", "ops": [
        {"op": "extrude", "height": 0.5},
        {"op": "taper", "ratio": 0.95, "on": "nowhere"},
    ]}
    parti = parti_from_record(rec)
    torn = ablate_module.ablate(parti, buildable=BUILDABLE, axis=AXIS,
                                height_m=BUDGET, site=SITE, storey_height_m=3.0)
    return "taper" in torn.idle, f"declared={list(torn.declared)} idle={list(torn.idle)}"


@check("관4 변형", "건폐율 변형은 실제로 접지면을 바꾼다")
def _coverage_spread():
    form, storey, _ = _form("a_one_bend")
    variants = spread_across_coverage(
        form, ground_capacity_m2=SITE.ground_capacity_m2,
        far_capacity_m2=SITE.far_capacity_m2, floor_height_m=SITE.floor_height_m)
    areas = []
    for v in [form] + list(variants):
        src = compile_matrix_form(v, storey_height_m=storey, allowed_at=SITE.plan_at)
        if src is not None:
            areas.append(round(measure_form(src).footprint_area_m2))
    return len(set(areas)) == len(areas) and len(areas) > 2, f"접지면 {areas}"


@check("관4 배치", "배치 변형은 서로 다른 자리에 놓고, 자리가 없으면 None을 낸다")
def _siting():
    # `place_on_site` returns None when the scheme has no room to move, on
    # purpose - an unmoved copy is a duplicate in the archive, not a variant.
    # Counting those as "did not move" was this check's own bug: a mass that
    # fills its site legitimately has one position. Use a small mass so the
    # sitings have somewhere to go, and read the compiled centroid rather than
    # a matrix translation, which is not the centre once anything scales.
    rec = {"name": "t", "primary_language": "solid_body",
           "ops": [{"op": "extrude", "height": 0.3, "storeys": 2}]}
    parti = parti_from_record(rec)
    form = execute_parti(parti, buildable=BUILDABLE, axis=AXIS,
                         height_m=BUDGET, storey_height_m=3.0)
    from backend.app.modules.design.generation.maas.massv2.variations import spread_across_coverage
    small = min(
        [form] + list(spread_across_coverage(
            form, ground_capacity_m2=SITE.ground_capacity_m2,
            far_capacity_m2=SITE.far_capacity_m2,
            floor_height_m=SITE.floor_height_m)),
        key=lambda f: compile_matrix_form(
            f, storey_height_m=3.0, allowed_at=SITE.plan_at).footprint.area)
    open_side = site_open_side_direction(SITE)
    sitings = OPEN_SIDE_SITINGS if open_side is not None else SITINGS
    centres, refused = set(), 0
    for s in sitings:
        moved = place_on_site(small, BUILDABLE, s, open_side=open_side)
        if moved is None:
            refused += 1
            continue
        src = compile_matrix_form(moved, storey_height_m=3.0, allowed_at=SITE.plan_at)
        c = src.footprint.centroid
        centres.add((round(c.x, 2), round(c.y, 2)))
    return len(centres) + refused == len(sitings) and len(centres) > 1, (
        f"서로 다른 자리 {len(centres)}, 자리 없음 {refused} / 배치 {len(sitings)}")


@check("관5 성장", "성장 뒤에도 법규 상한을 넘지 않는다")
def _fill_lawful():
    over = []
    for name in list(CORPUS)[:25]:
        form, storey, _ = _form(name)
        if form is None:
            continue
        grown = fill_to_site(form, SITE)
        fit = grown.fit
        if fit.satisfied and (fit.gross_floor_area_m2 > SITE.far_capacity_m2 * 1.001
                              or fit.ground_area_m2 > SITE.ground_capacity_m2 * 1.001):
            over.append(name)
    return not over, f"25문장 중 상한 초과 {len(over)}개"


@check("관6 법규맞춤", "satisfied=True 면 실제로 두 상한 안이다")
def _fit_honest():
    lies = []
    for name in list(CORPUS)[:25]:
        form, storey, _ = _form(name)
        if form is None:
            continue
        fit = fit_to_site(form, SITE)
        if fit.satisfied and (fit.gross_floor_area_m2 > SITE.far_capacity_m2 * 1.001
                              or fit.ground_area_m2 > SITE.ground_capacity_m2 * 1.001):
            lies.append(name)
    return not lies, f"25문장 중 거짓 satisfied {len(lies)}개"


@check("관7 측정", "연면적을 재는 두 경로가 같은 답을 낸다 (배관만)")
def _one_measure():
    """⚠️ 이 검사의 한계 — 역검증으로 확인됨.

    `legal_fit._gross_floor_area` 와 리포트가 **같은 `gross_floor_area_m2`를
    부른다.** 그래서 그 규칙 자체를 바꿔치기해도 양쪽이 함께 바뀌어 이 검사는
    0.0%로 통과한다(실제로 storeys_in을 실수 층수로 바꿔 확인). 잡을 수 있는
    것은 "한 경로가 compile을 빠뜨린다" 같은 배관 오류 — 이 패키지가 실제로
    겪었던 버그 — 이고, 규칙이 틀린 경우는 관9(과거 기록 vs 지금 그림)가 잡는다.
    같은 변조에서 관9는 2% 초과 12개·최대 19.2%로 FAIL했다.
    """

    worst, name_worst = 0.0, ""
    for name in list(CORPUS)[:20]:
        form, storey, _ = _form(name)
        if form is None:
            continue
        fit = fit_to_site(form, SITE)
        src = compile_matrix_form(fit.form, storey_height_m=storey,
                                  allowed_at=SITE.plan_at)
        if src is None:
            continue
        reported = gross_floor_area_m2(src, floor_height_m=storey)
        gap = abs(reported - fit.gross_floor_area_m2) / max(fit.gross_floor_area_m2, 1.0)
        if gap > worst:
            worst, name_worst = gap, name
    return worst <= 0.01, f"최대 차이 {worst:.1%} ({name_worst})"


@check("관8 물리", "막대와 뜬 몸은 잡힌다")
def _physics_fires():
    from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, place
    lim = slenderness_limit(far_capacity_m2=SITE.far_capacity_m2,
                            ground_capacity_m2=SITE.ground_capacity_m2)
    stick = MatrixForm(name="stick", primary_language="t",
                       placements=(place("body", size=(4.0, 4.0, 60.0)),))
    src = compile_matrix_form(stick, storey_height_m=3.0)
    v = assess(src, parcel_area_m2=SITE.parcel_area_m2, max_slenderness=lim,
               floor_height_m=3.0, building_type=BUILDING_TYPE)
    return not v.occupiable, f"세장비 {v.slenderness:.1f} > {lim:.1f}, 판정 {v.occupiable}"


@check("관9 시트", "타일과 숫자는 같은 건물이다")
def _sheet_matches():
    run = "uij-brief"
    summ = json.loads((ROOT / "runs" / run / "massv2-summary.json").read_text(encoding="utf-8"))
    recs = {r["name"]: r for r in summ["records"]}
    picks = json.loads((ROOT / "runs" / f"{run}-pick" / "picks.json")
                       .read_text(encoding="utf-8"))["picks"]
    from backend.app.modules.design.generation.maas.massv2 import program as programme
    book = json.loads((ROOT / "inputs" / "programs-korean.json").read_text(encoding="utf-8"))
    sched = None
    if summ["provenance"].get("programme"):
        sched = programme.schedule_from_record(
            next(r for r in book["schedules"]
                 if r["name"] == summ["provenance"]["programme"]),
            shared_share_of_gross=book.get("shared_area_share_of_gross"))
    worst, n = 0.0, 0
    for p in picks:
        rec = CORPUS.get(scheme_of(p["name"]))
        if rec is None:
            continue
        asked = max((float(o.get("storeys") or 0) for o in rec["ops"]), default=0.0)
        storey = float(rec.get("floor_height_m") or SITE.floor_height_m)
        src = rebuild(p["name"], CORPUS, SITE, BUILDABLE, AXIS,
                      max(BUDGET, asked * SITE.floor_height_m), schedule=sched)
        if src is None:
            continue
        drawn = gross_floor_area_m2(src, floor_height_m=storey)
        said = float(recs[p["name"]].get("gfa_m2") or 0.0)
        gap = abs(drawn - said) / max(said, 1.0)
        worst = max(worst, gap)
        n += gap > 0.02
    return worst <= 0.10, f"2% 초과 {n}개, 최대 {worst:.1%}"


def main() -> int:
    width = max(len(s) for s, _, _ in RESULTS)
    for stage, verdict, note in RESULTS:
        print(f"{verdict}  {stage:<{width}}  {note}")
    bad = sum(1 for _, v, _ in RESULTS if v == "FAIL")
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

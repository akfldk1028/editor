"""Why a sentence is not on the sheet, and by how much it misses.

Authoring against the gates by guessing costs a grid run per guess, and the
guesses have been wrong: raising 층수 on c_thrust_ramp moved it from 8 m to
25 m, straight past the band it was short of. This reads the run that already
happened and says, per family, which gate is binding and what the nearest
variant's number actually is - so the next edit is aimed rather than tried.

    python tools/why_absent.py <run> [pattern]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from pathlib import Path

ROOT = _mass_paths.workspace_root()

HEIGHT = (10.0, 20.0)      # 당선작 15건이 앉은 높이 대역
GROUND = (400.0, 800.0)    # 같은 조사의 footprint 대역
# 비움은 더 이상 봉투 조건이 아니다 - 시트가 셀마다 한 자리를 마당에 예약할
# 뿐이라, 여기서 요구하면 통과할 문장을 막힌 것으로 보고하게 된다.
VOID = 0.0


def family(name: str) -> str:
    return name.split("~")[0].split("^")[0]


def main(run: str, pattern: str = "") -> int:
    summary = json.loads((ROOT / "runs" / run / "massv2-summary.json")
                         .read_text(encoding="utf-8"))
    refused = summary.get("refused") or {}
    upstream = {}
    for kind, rows in refused.items():
        for row in rows:
            upstream.setdefault(family(row["name"]), []).append(
                f"{kind}:{','.join(row.get('words') or []) or row.get('declared_m', '')}")

    by_family: dict[str, list] = {}
    for record in summary["records"]:
        by_family.setdefault(family(record["name"]), []).append(record)

    rows = []
    for name in sorted(set(by_family) | set(upstream)):
        if pattern and pattern not in name:
            continue
        records = by_family.get(name) or []
        if not records:
            rows.append((name, 0, 0, "앞단 거부", "; ".join(upstream[name][:2])))
            continue
        standing = [r for r in records
                    if (r.get("plausibility") or {}).get("occupiable")]
        if not standing:
            reasons: dict[str, int] = {}
            for r in records:
                for why in ((r.get("plausibility") or {}).get("reasons") or []):
                    reasons[why] = reasons.get(why, 0) + 1
            worst = max(reasons.items(), key=lambda kv: kv[1])[0] if reasons else "?"
            rows.append((name, len(records), 0, "물리", worst[:44]))
            continue

        def height(r):
            return (r.get("measurement") or {}).get("height_m") or 0.0

        def ground(r):
            return (r.get("legal_fit") or {}).get("ground_area_m2") or 0.0

        def void(r):
            return (r.get("measurement") or {}).get("plan_void_ratio") or 0.0

        inside = [r for r in standing
                  if HEIGHT[0] <= height(r) <= HEIGHT[1]
                  and GROUND[0] <= ground(r) <= GROUND[1]]
        if inside:
            rows.append((name, len(records), len(standing), "통과",
                         f"봉투 안 {len(inside)}"))
            continue

        # Which single axis is furthest out, at the variant that is closest
        # overall. Reporting the whole range hides which number to move.
        def miss(r):
            h, g, v = height(r), ground(r), void(r)
            dh = max(HEIGHT[0] - h, h - HEIGHT[1], 0.0) / HEIGHT[1]
            dg = max(GROUND[0] - g, g - GROUND[1], 0.0) / GROUND[1]
            dv = 0.0
            return dh + dg + dv, (h, g, v, dh, dg, dv)

        best = min(standing, key=lambda r: miss(r)[0])
        _total, (h, g, v, dh, dg, dv) = miss(best)
        worst_axis = max((dh, "높이"), (dg, "바닥"), (dv, "비움"))[1]
        note = f"최근접 h={h:.1f} 바닥={g:.0f} 비움={v:.2f} → {worst_axis}"
        rows.append((name, len(records), len(standing), worst_axis, note))

    order = {"앞단 거부": 0, "물리": 1, "높이": 2, "바닥": 3, "비움": 4, "통과": 5}
    rows.sort(key=lambda r: (order.get(r[3], 9), r[0]))
    print(f"{'문장':<38}{'변형':>4}{'물리':>4}  {'막는 곳':<9}근거")
    for name, n, ok, blocker, note in rows:
        print(f"{name[:38]:<38}{n:>4}{ok:>4}  {blocker:<9}{note}")
    stuck = sum(1 for r in rows if r[3] != "통과")
    print(f"\n{len(rows) - stuck}/{len(rows)} 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], *(sys.argv[2:3] or [])))

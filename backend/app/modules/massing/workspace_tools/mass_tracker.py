"""Every sentence in the corpus, what it delivered, and how that changed.

The grid reports totals - forms, standing, refusals - and a sheet shows six
masses. Neither answers the question an author actually has: *what happened to
my sentence?* A sentence can go silent, lose its gap, drop out of selection or
quietly halve its coverage between two runs and none of the numbers that get
printed would say so.

So this is one row per sentence, across as many runs as are named, and the
columns are the things that decide whether it survives: whether it stood at
all, what it delivered, whether it was refused and why, and whether the
selector took it. The last column is the change against the first run named,
which is the column to read.

    python tools/mass_tracker.py <run> [<earlier-run> ...]
    python tools/mass_tracker.py uij-grid uij-fin uij-head

Writes `runs/<run>/tracker.html`, which is a page rather than a table dump
because the point is to be looked at repeatedly.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import collections
import html
import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus  # noqa: E402  (django setup inside)

ROOT = _mass_paths.workspace_root()


def _family(name: str) -> str:
    return str(name).split("~")[0].split("^")[0]


def read_run(run: str) -> dict:
    """One run, reduced to what a sentence's author would ask about it."""

    path = ROOT / "runs" / run / "massv2-summary.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    parcel = float(data["site"]["parcel_area_m2"]) or 1.0
    chosen = {_family(n) for n in (data.get("selection") or {}).get("chosen_names") or ()}

    refused: dict[str, str] = {}
    for reason, rows in (data.get("refused") or {}).items():
        for row in rows or ():
            refused[_family(row.get("name") if isinstance(row, dict) else row)] = reason

    out: dict[str, dict] = collections.defaultdict(
        lambda: {"variants": 0, "standing": 0, "coverage": [], "storeys": [],
                 "section": [], "refused": None, "chosen": False})
    for record in data["records"]:
        family = _family(record["name"])
        row = out[family]
        row["variants"] += 1
        if not (record.get("plausibility") or {}).get("occupiable"):
            continue
        row["standing"] += 1
        fit = record.get("legal_fit") or {}
        ground = float(fit.get("ground_area_m2") or 0.0)
        gross = float(fit.get("gross_floor_area_m2") or 0.0)
        if ground > 0.0:
            row["coverage"].append(ground / parcel * 100.0)
            row["storeys"].append(gross / ground)
        row["section"].append(
            float((record.get("measurement") or {}).get("section_change") or 0.0))
    # A sentence refused before it compiled has no records at all, so seeding
    # the table only from `records` drops exactly the rows worth reading. Four
    # sentences went silent between two runs and the first version of this
    # printed them as blank lines with no reason attached.
    for family in refused:
        out[family]
    for family, row in out.items():
        row["refused"] = refused.get(family)
        row["chosen"] = family in chosen
    return dict(out)


def _mid(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


_CSS = """
:root{--ink:#1B1815;--paper:#FBFAF8;--panel:#F2EFEA;--rule:#DCD6CC;
 --good:#5C7F55;--bad:#9E3B2C;--muted:#6C6862;--star:#C4763A}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
 --ink:#E9E5DE;--paper:#141311;--panel:#1E1C19;--rule:#332F2A;
 --good:#8FB187;--bad:#C4553F;--muted:#9B958B;--star:#D98C4C}}
:root[data-theme=dark]{--ink:#E9E5DE;--paper:#141311;--panel:#1E1C19;--rule:#332F2A;
 --good:#8FB187;--bad:#C4553F;--muted:#9B958B;--star:#D98C4C}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
 font-family:"Noto Sans KR",system-ui,sans-serif;font-size:15px;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto;padding:2.5rem 1.2rem 5rem}
h1{font-family:Archivo,sans-serif;font-size:1.9rem;margin:.2rem 0 .4rem;letter-spacing:-.01em}
.eyebrow{font-family:Archivo,sans-serif;font-size:.72rem;letter-spacing:.16em;
 text-transform:uppercase;color:var(--muted);margin:0}
.lede{color:var(--muted);margin:.4rem 0 1.8rem;max-width:60ch}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:4px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;
 font-size:.87rem;min-width:52rem}
th,td{padding:.42rem .6rem;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:20rem}
thead th{position:sticky;top:0;background:var(--panel);font-family:Archivo,sans-serif;
 font-weight:600;font-size:.72rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
tbody tr:hover{background:var(--panel)}
.up{color:var(--good)}.down{color:var(--bad)}.zero{color:var(--muted)}
.star{color:var(--star);font-weight:700}
.tag{font-size:.72rem;padding:.06em .4em;border-radius:2px;background:var(--panel);color:var(--bad)}
.legend{margin:1.4rem 0 0;font-size:.83rem;color:var(--muted)}
code{font-family:Archivo,ui-monospace,monospace;font-size:.9em}
"""


def main(*runs: str) -> int:
    if not runs:
        print(__doc__)
        return 1
    latest, *earlier = runs
    now = read_run(latest)
    if not now:
        print(f"{latest} 요약 없음")
        return 1
    then = read_run(earlier[0]) if earlier else {}
    book = corpus()

    rows = []
    for family in sorted(set(now) | set(then)):
        cur = now.get(family) or {}
        old = then.get(family) or {}
        rows.append({
            "name": family,
            "in_book": family in book,
            "standing": cur.get("standing", 0),
            "was": old.get("standing", 0),
            "variants": cur.get("variants", 0),
            "coverage": _mid(cur.get("coverage") or []),
            "storeys": _mid(cur.get("storeys") or []),
            "section": _mid(cur.get("section") or []),
            "refused": cur.get("refused"),
            "chosen": cur.get("chosen", False),
        })
    # Worst news first: refused, then what lost the most, then the rest.
    rows.sort(key=lambda r: (r["refused"] is None, r["standing"] - r["was"], -r["standing"]))

    body = []
    for r in rows:
        delta = r["standing"] - r["was"]
        cls = "up" if delta > 0 else "down" if delta < 0 else "zero"
        mark = "★ " if r["chosen"] else ""
        tag = f' <span class="tag">{html.escape(r["refused"])}</span>' if r["refused"] else ""
        body.append(
            f'<tr><td>{mark}{html.escape(r["name"])}{tag}</td>'
            f'<td>{r["standing"]}/{r["variants"]}</td>'
            f'<td class="{cls}">{delta:+d}</td>'
            f'<td>{r["coverage"]:.1f}%</td>'
            f'<td>{r["storeys"]:.1f}</td>'
            f'<td>{r["section"]:.2f}</td></tr>')

    standing = sum(r["standing"] for r in rows)
    chosen = sum(1 for r in rows if r["chosen"])
    refused = sum(1 for r in rows if r["refused"])
    lost = [r for r in rows if r["standing"] < r["was"]]
    gained = [r for r in rows if r["standing"] > r["was"]]

    page = f"""<title>매스 추적 · {html.escape(latest)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600&family=Noto+Sans+KR:wght@400;700&display=swap">
<style>{_CSS}</style>
<div class="wrap">
<p class="eyebrow">massv2 · {html.escape(latest)}{" vs " + html.escape(earlier[0]) if earlier else ""}</p>
<h1>매스 추적</h1>
<p class="lede">문장 {len(rows)}개 · 물리통과 {standing}안 · 선발 {chosen} · 거부 {refused}.
나쁜 소식 먼저 — 거부된 것, 그다음 가장 많이 잃은 것 순.
{f"잃은 문장 {len(lost)}개, 얻은 문장 {len(gained)}개." if earlier else ""}</p>
<div class="scroll"><table>
<thead><tr><th>문장</th><th>물리통과</th><th>변화</th><th>건폐율</th><th>층수</th><th>단면</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>
<p class="legend">★ = 선발됨 · 변화는 {html.escape(earlier[0]) if earlier else "이전 런"} 대비 물리통과 변이 수 ·
건폐율·층수·단면은 그 문장의 변이들 중앙값 · <code>tools/mass_tracker.py</code></p>
</div>
"""
    out = ROOT / "runs" / latest / "tracker.html"
    out.write_text(page, encoding="utf-8")
    print(f"{len(rows)}문장 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

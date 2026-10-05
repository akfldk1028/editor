"""Bookkeeping for a VLM critique round. The subagents look; this counts.

Two findings from the literature review shape it. A VLM asked to score a mass
gives numbers that do not survive being asked twice, but asked which of two
images is better it is stable - so the unit is a PAIR, not a sheet. And a
critique loop past about two rounds stops paying, so the caller caps rounds
rather than iterating to convergence.

    plan   run   -> pairs.json + manifest, for the subagents to work from
    tally  run   -> ranking from whatever verdicts came back
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

RUNS = _mass_paths.workspace_root() / 'runs'
# Each alternative meets this many others. Full round-robin on twelve is 66
# comparisons; a rotating subset gives every candidate the same number of
# outings for a fraction of the looking.
MEETINGS = 4


def manifest(run: str) -> list[dict]:
    folder = RUNS / run
    alts = json.loads((folder / "alts.json").read_text(encoding="utf-8"))
    summary = json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))
    records = {r["name"]: r for r in summary["records"] if r.get("status") == "compiled"}
    parcel = summary["site"]["parcel_area_m2"]
    out = []
    for item in alts["alternatives"]:
        record = records.get(item["name"])
        if record is None:
            continue
        fit = record["legal_fit"]
        out.append({
            "id": f"alt-{item['index']:02d}",
            "png": str((folder / item["png"]).resolve()),
            "scheme": item["name"],
            "cell": item["cell"],
            "bcr_pct": round(fit["ground_area_m2"] / parcel * 100, 1),
            "far_pct": round(fit["gross_floor_area_m2"] / parcel * 100, 1),
            "height_m": record["measurement"]["height_m"],
            "principle": (record.get("language") or {}).get("formal_principle", ""),
        })
    return out


def plan(run: str) -> None:
    cards = manifest(run)
    n = len(cards)
    if n < 2:
        raise SystemExit("need at least two alternatives")
    # Rotating pairing: every card meets the ones MEETINGS steps around the ring,
    # so nobody is judged only against its neighbours in the sheet order.
    pairs = []
    for step in range(1, min(MEETINGS, n - 1) + 1):
        for i in range(n):
            j = (i + step) % n
            if i < j:
                pairs.append([cards[i]["id"], cards[j]["id"]])
    folder = RUNS / run
    (folder / "vlm-manifest.json").write_text(
        json.dumps({"run": run, "cards": cards}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (folder / "vlm-pairs.json").write_text(
        json.dumps({"run": run, "pairs": pairs}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"{n} alternatives, {len(pairs)} pairs "
          f"({len(pairs)*2/n:.1f} outings each)")
    print(f"wrote {folder/'vlm-manifest.json'}")
    print(f"wrote {folder/'vlm-pairs.json'}")


def tally(run: str) -> None:
    folder = RUNS / run
    cards = {c["id"]: c for c in json.loads(
        (folder / "vlm-manifest.json").read_text(encoding="utf-8"))["cards"]}
    verdicts = []
    for path in sorted(folder.glob("vlm-verdict-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        verdicts.extend(payload.get("verdicts") or [])
    if not verdicts:
        raise SystemExit("no vlm-verdict-*.json found")

    wins: Counter = Counter()
    outings: Counter = Counter()
    faults: dict[str, Counter] = defaultdict(Counter)
    for v in verdicts:
        a, b, winner = v.get("a"), v.get("b"), v.get("winner")
        if a not in cards or b not in cards:
            continue
        outings[a] += 1
        outings[b] += 1
        if winner in (a, b):
            wins[winner] += 1
        for who, tags in (("a", v.get("a_faults")), ("b", v.get("b_faults"))):
            target = a if who == "a" else b
            for tag in tags or ():
                faults[target][str(tag)] += 1

    # Per-criterion tallies. The rubric is Sun & Fu, Buildings 16(6):1265,
    # Appendix B - published anchors instead of tags the judges invent, because
    # letting them invent their own is what made two rounds incomparable.
    criteria = ("legibility", "intent_match", "alignment", "aesthetics")
    per = {name: Counter() for name in criteria}
    seen = {name: Counter() for name in criteria}
    for v in verdicts:
        a, b = v.get("a"), v.get("b")
        if a not in cards or b not in cards:
            continue
        for name in criteria:
            pick = v.get(name)
            if pick in (a, b):
                seen[name][a] += 1
                seen[name][b] += 1
                per[name][pick] += 1

    print(f"{len(verdicts)} comparisons over {len(outings)} alternatives\n")
    ranked = sorted(cards.values(),
                    key=lambda c: -(wins[c["id"]] / max(outings[c["id"]], 1)))
    for rank, card in enumerate(ranked, 1):
        cid = card["id"]
        rate = wins[cid] / max(outings[cid], 1)
        top = ", ".join(f"{k}×{n}" for k, n in faults[cid].most_common(3)) or "-"
        print(f"{rank:2d}. {card['scheme'][:34]:36s} {wins[cid]:2d}/{outings[cid]:2d} "
              f"= {rate:.0%}  건폐율 {card['bcr_pct']:4.1f}%  용적률 {card['far_pct']:5.1f}%")
        print(f"    지적: {top}")

    scored = [name for name in criteria if sum(seen[name].values())]
    if scored:
        print()
        print("기준별 승률 (Buildings 16(6):1265 Appendix B anchors)")
        print("%-34s%s" % ("scheme", "".join("%11s" % n[:9] for n in scored)))
        for card in ranked:
            cid = card["id"]
            row = "".join(
                ("%10.0f%% " % (100 * per[n][cid] / seen[n][cid])) if seen[n][cid] else "%11s" % "-"
                for n in scored
            )
            print("%-34s%s" % (card["scheme"][:32], row))
        print()

    everything = Counter()
    for counter in faults.values():
        everything += counter
    print("\n가장 많이 지적된 결함:")
    for tag, n in everything.most_common(10):
        print(f"   {tag:34s} {n}")
    (folder / "vlm-ranking.json").write_text(json.dumps({
        "run": run,
        "per_criterion": {n: {c: {"wins": per[n][c], "outings": seen[n][c]} for c in cards} for n in criteria if sum(seen[n].values())},
        "ranking": [{"id": c["id"], "scheme": c["scheme"],
                     "wins": wins[c["id"]], "outings": outings[c["id"]],
                     "faults": dict(faults[c["id"]])} for c in ranked],
        "faults_overall": dict(everything),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {folder/'vlm-ranking.json'}")


if __name__ == "__main__":
    mode, run = sys.argv[1], sys.argv[2]
    {"plan": plan, "tally": tally}[mode](run)

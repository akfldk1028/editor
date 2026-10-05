"""Which measurable objective tracks what the judges actually rank.

The selector's balance criterion (`select._balance_keys`) needs more than one
objective to mean anything, and the last two it had were removed because their
correlation with judged quality flipped sign between rounds: `far` at -0.23 then
+0.33, `shape_work` similarly, while `spoken_force` held at +0.67 and +0.48.
So a candidate axis is not accepted for being plausible. It has to survive two
rounds with the same sign and a usable size.

Judging is pairwise, not scored. MLLM-as-a-Judge (ICML 2024) reports pairwise
agreement with human ranking at 0.773 Pearson against 0.490 for absolute
scoring, and this package has watched a scoring round invert itself. Groups of
four give six implicit pairs each and stay close to pairwise reliability.

The prompt is written once, stored in `prompts.json`, and reused verbatim in
every round. ⚠️ A previous comparison was ruined by editing the prompt between
rounds - the judges' vocabulary went from 51 tags to 17 and the two rounds were
no longer measuring the same thing. Do not change the judge while comparing
judgements.

⚠️⚠️ And judge a sample that was not selected on the thing being tested. Run
against the delivered shortlist - which `choose` picks by `spoken_force` - two
independent rounds agreed that `spoken_force` correlates -0.39 and -0.32 with
judged quality, and that `slenderness` correlates +0.43 and +0.61. Run against
a sample drawn evenly across the whole compiled pool, with the identical prompt,
the same measurements came back +0.43 and -0.33. Both signs inverted.

That is selection, not disagreement: inside the winners of a contest decided by
X, the remaining variation in X is what the other criteria had to overcome, so
X reads as a handicap. Two rounds holding their sign proves the judges are
consistent. It does not prove the sample is.

`sample_pool.py` draws the unselected sample this tool should be pointed at.

    python tmp_mass_check/_massv2/tools/judge_fit.py runs/vlm-uij
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import re
import sys
from pathlib import Path


def read_rankings(path: Path) -> dict[str, list[int]]:
    """Every group's RANKING line, best first."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for key, text in raw.items():
        match = re.search(r"RANKING:\s*([0-9,\s]+)", text)
        if not match:
            continue
        order = [int(v) for v in re.findall(r"\d+", match.group(1))]
        if order:
            out[key] = order
    return out


def win_rates(rankings: dict[str, list[int]]) -> dict[int, tuple[float, int]]:
    """Share of implicit pairwise contests each option won, and how many it had."""

    won: dict[int, int] = {}
    played: dict[int, int] = {}
    for order in rankings.values():
        for i, better in enumerate(order):
            for worse in order[i + 1:]:
                won[better] = won.get(better, 0) + 1
                played[better] = played.get(better, 0) + 1
                played[worse] = played.get(worse, 0) + 1
                won.setdefault(worse, 0)
    return {k: (won[k] / played[k], played[k]) for k in played if played[k]}


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, so ties do not invent an ordering."""

    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    """Tie-corrected Spearman, which is Pearson on the average ranks."""

    if len(a) < 3:
        return 0.0
    ra, rb = _ranks(a), _ranks(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da > 1e-12 and db > 1e-12 else 0.0


def main() -> int:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/vlm-uij")
    objectives = json.loads((base / "objectives.json").read_text(encoding="utf-8"))
    by_index = {row["index"]: row for row in objectives}
    verdicts = json.loads((base / "verdicts.json").read_text(encoding="utf-8"))

    fields = [
        key for key in objectives[0]
        if key not in ("index", "png", "name", "cell", "thesis")
        and not isinstance(objectives[0][key], str)
        and len({row[key] for row in objectives if row[key] is not None}) > 2
    ]

    per_round = {}
    for round_name in sorted({k.split("-")[0] for k in verdicts}):
        picked = {k: v for k, v in verdicts.items() if k.startswith(round_name)}
        rates = win_rates(read_rankings_from(picked))
        shared = sorted(set(rates) & set(by_index))
        per_round[round_name] = {
            "rates": rates,
            "correlation": {
                field: spearman(
                    [rates[i][0] for i in shared],
                    [float(by_index[i][field] or 0.0) for i in shared],
                )
                for field in fields
            },
            "n": len(shared),
        }

    print("%-24s %s" % ("objective", "  ".join("%-9s" % r for r in per_round)))
    stable = []
    for field in fields:
        values = [per_round[r]["correlation"][field] for r in per_round]
        line = "  ".join("%+9.3f" % v for v in values)
        # ⚠️ Both halves need the round count. Written without the parentheses
        # this read as `(len > 1 and all positive) or (all negative)`, so a
        # single round of all-negative correlations was reported as holding its
        # sign across rounds - which is the one thing this tool exists to test.
        agree = len(values) > 1 and (
            all(v > 0.15 for v in values) or all(v < -0.15 for v in values)
        )
        print("%-24s %s %s" % (field, line, "  <- same sign, usable" if agree else ""))
        if agree:
            stable.append((min(abs(v) for v in values), field, values))
    print()
    for _size, field, values in sorted(stable, reverse=True):
        print("stable: %-22s %s" % (field, ["%+0.3f" % v for v in values]))
    if not stable:
        print("nothing held its sign across rounds")
    return 0


def read_rankings_from(raw: dict[str, str]) -> dict[str, list[int]]:
    out = {}
    for key, text in raw.items():
        match = re.search(r"RANKING:\s*([0-9,\s]+)", text)
        if not match:
            continue
        order = [int(v) for v in re.findall(r"\d+", match.group(1))]
        if order:
            out[key] = order
    return out


if __name__ == "__main__":
    sys.exit(main())

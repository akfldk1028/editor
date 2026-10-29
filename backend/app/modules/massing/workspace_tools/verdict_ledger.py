"""What the judges keep saying, gathered where the next author must read it.

The refusal ledger feeds gate lessons back to authors; the juries' words
went nowhere - '규모 과대' was written eleven times before anyone put it in
a brief. This walks every judged round (runs/vlm-*/ with key.json and
r*.txt), joins tiles back to sentences, and emits a per-sentence digest of
the weakest axis with the judges' own clauses, plus the round VERDICTs.
make_brief includes the result verbatim; nothing here is hand-typed.

    python tools/verdict_ledger.py            # -> runs/board/verdict-ledger.md
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = _mass_paths.workspace_root()
# Both rulers' axes: the Korean rubric scores AESTHETICS / FEASIBILITY /
# COMPLIANCE / EDITABILITY, the international one CONCEPT / FEASIBILITY /
# SITE / EDITABILITY. A sentence's digest carries whichever axes its
# rounds used; an axis never scored stays empty.
AXES = ("CONCEPT", "AESTHETICS", "FEASIBILITY", "SITE", "COMPLIANCE", "EDITABILITY")


def main() -> int:
    per_sentence: dict[str, dict] = defaultdict(
        lambda: {axis: [] for axis in AXES} | {"reasons": defaultdict(list)})
    verdicts: list[tuple[str, str]] = []

    # Newest verdict wins per sentence: a ring answered in round three must
    # not carry round one's complaint into every future brief - the board's
    # scores are era-corrected and the feedback channel owes the same rule.
    latest: dict[str, float] = {}
    rounds = []
    for round_dir in sorted(ROOT.glob("runs/vlm-*")):
        key_path = round_dir / "key.json"
        sheets = sorted(round_dir.glob("r*.txt"))
        if not key_path.exists() or not sheets:
            continue
        stamp = max(p.stat().st_mtime for p in sheets)
        rounds.append((stamp, round_dir, key_path, sheets))
        for row in json.loads(key_path.read_text(encoding="utf-8")):
            sentence = row["name"].split("~")[0].split("^")[0]
            latest[sentence] = max(latest.get(sentence, 0.0), stamp)
    for stamp, round_dir, key_path, sheets in sorted(rounds):
        key = {row["tile"]: row["name"]
               for row in json.loads(key_path.read_text(encoding="utf-8"))}
        for sheet in sheets:
            text = sheet.read_text(encoding="utf-8")
            for block in re.split(r"(?=TILE\s)", text):
                match = re.match(r"TILE\s+t?0*(\d+)", block)
                if not match:
                    continue
                tile = f"t{int(match.group(1)):02d}"
                name = key.get(tile)
                if name is None:
                    continue
                sentence = name.split("~")[0].split("^")[0]
                if stamp < latest.get(sentence, 0.0):
                    continue
                entry = per_sentence[sentence]
                for axis in AXES:
                    hit = re.search(
                        axis + r"\s+(\d)\s*\|\s*(.+)", block)
                    if hit:
                        entry[axis].append(int(hit.group(1)))
                        if int(hit.group(1)) <= 2:
                            entry["reasons"][axis].append(
                                hit.group(2).strip()[:110])
            verdict = re.search(r"VERDICT:\s*(.+)", text, re.S)
            if verdict:
                verdicts.append((round_dir.name,
                                 verdict.group(1).strip().split("\n")[0][:300]))

    lines = [
        "## 심판 판정 원장 (기계 집계 - 손 복제 없음)",
        "저작할 때 이 목록의 문장을 되풀이하면 같은 축에서 같은 점수를 받는다.", ""]
    scored = []
    for sentence, entry in per_sentence.items():
        means = {axis: statistics.mean(v) for axis, v in entry.items()
                 if axis in AXES and v}
        if not means:
            continue
        worst = min(means, key=means.get)
        scored.append((means[worst], sentence, worst, means, entry))
    for worst_score, sentence, worst, means, entry in sorted(scored)[:20]:
        quotes = entry["reasons"].get(worst, [])[:2]
        summary = " / ".join(quotes) if quotes else "-"
        lines.append(
            f"- **{sentence}** — 최약축 {worst} {worst_score:.1f}"
            f" (전축 {', '.join(f'{a[0]}{m:.1f}' for a, m in means.items())})"
            f" : {summary}")
    lines += ["", "### 라운드 총평"]
    for round_name, verdict in verdicts[-8:]:
        lines.append(f"- [{round_name}] {verdict}")

    out = ROOT / "runs" / "board" / "verdict-ledger.md"
    # A fresh workspace has no runs/board yet: the first brief of an editor selection failed here
    # (FileNotFoundError, Mass cycle editor-2adfa67bd8 on 684-1, 2026-10-29).
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(scored)} sentences, {len(verdicts)} verdicts -> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

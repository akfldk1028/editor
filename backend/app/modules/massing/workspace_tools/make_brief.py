"""Assemble an author brief from its owners - no hand-typed numbers, no
hand-picked exemplars.

The brief is derived, per the one-owner rule: trap numbers come from
trap_ledger (which reads the gate constants), the vocabulary and canon are
included verbatim from their files, and the board section lists the current
board's sentences from the curator's own key - so the "differ from all of
these at the level of formal principle" demand (NoveltyBench's best-in-class
regeneration, canon §10) always names today's board, not a remembered one.

    python tools/make_brief.py <track> <out.md> [assignment-text-file]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import os
import sys
from pathlib import Path

ROOT = _mass_paths.workspace_root()


def board_section(track: str) -> str:
    key_path = ROOT / "runs" / "board" / "board-key.json"
    # A new era archives its key before the first author brief is made.
    # There are no currently evaluated seats until that era's first bake.
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.exists() else []
    book_only = os.environ.get('BOOK_ONLY') == '1'
    if book_only:
        key = [row for row in key if str(row.get('name', '')).startswith('book:')]
    book = {}
    for path in ([] if book_only else sorted((ROOT / "inputs").glob("gen-*.json"))):
        for scheme in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            book[scheme["name"]] = scheme
    lines = ["## Current board: differ from every entry at the level of formal principle",
             "The common curator reserves one seat per family, not per renamed parameter variation.", ""]
    if not key:
        lines.append("No judged and baked seats exist in the current era yet.")
    for row in key:
        if not row["label"].startswith(track):
            continue
        family = row["name"].split("~")[0].split("^")[0]
        scheme = book.get(family) or {}
        line = (scheme.get("secondary_language")
                or scheme.get("formal_principle") or family)
        lines.append(f"- {row['label']} ({row['score']:.2f}): {line}")
    return "\n".join(lines)


def champion_section() -> str:
    """Developments that beat their parent in front of a blind jury.

    The development loop's one real output is a champion, and champion.json
    was read by nothing - so a mutation a jury had already preferred was
    invisible to the next author, who could propose the parent's value again
    with no way of knowing it had been tried and beaten. Read from the
    develop runs' own files, never typed here, and it names the juror count
    because a one-juror round is one opinion, not a consensus.
    """

    lines = []
    for path in sorted(ROOT.glob("runs/develop-*/champion.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        # A champion.json written before the scorer counted jurors cannot say
        # how many voted, and the brief must not claim a consensus it has no
        # evidence for. Re-score that round and it appears.
        if not record.get("champion") or "jurors" not in record:
            continue
        lines.append(
            f"- **{record['champion']}** — {record.get('champion_change', '-')}"
            f" : all {record.get('jurors', 0)} independent juror sessions preferred this variant"
            f" to parent {record['parent']} in a blind pairwise comparison")
    if not lines:
        return ""
    return "\n".join(
        ["## Development champions already carried into the corpus",
         "These comparisons were judged. Treat them as specific evidence, not a guarantee for a different design.",
         ""] + lines)


def book_development_section() -> str:
    """Return recent completed BOOK outcomes, including unsuccessful changes."""
    paths = sorted(ROOT.glob('runs/develop-*/champion.json'), key=lambda p: p.stat().st_mtime)
    records = [(p, json.loads(p.read_text(encoding='utf8'))) for p in paths]
    records = [(p, r) for p, r in records if str(r.get('parent', '')).startswith('book:')
               and r.get('jurors') == 3 and r.get('feedback_written')][-3:]
    if not records:
        return ''
    lines = ['## Recent BOOK development evidence',
             'These are local pairwise judgments, not permit or structural approval. Read failures as well as winners.']
    for path, record in records:
        outcome = f"child selected: {record['champion']}" if record.get('champion') else 'parent retained; no unanimous improvement'
        lines += [f"- Parent {record['parent']}: {outcome}. Evidence: {path}"]
        for child in record.get('children', []):
            lines.append(f"  Child {child.get('name')}: votes {child.get('votes', 'not judged')}; delivered {child.get('delivered', 'unknown')}")
        for ballot in sorted((path.parent / 'pairs').glob('r[123].txt')):
            lines += [f'  Attributed critique ({ballot.name}):', ballot.read_text(encoding='utf8')[:6000]]
    return '\n'.join(lines)


def _sentence_line(scheme: dict) -> str:
    """One reference scheme as a line: name, principle, and its words with their numbers."""
    ops = []
    for op in scheme.get("ops") or ():
        params = ", ".join(f"{k}={v}" for k, v in op.items()
                           if k not in ("op", "why") and not isinstance(v, (dict, list)))
        ops.append(f"{op.get('op')}({params})" if params else str(op.get("op")))
    principle = str(scheme.get("formal_principle") or scheme.get("dominant_gesture") or "").strip()
    return f"- **{scheme.get('name')}** — {principle} — `{' → '.join(ops)}`"


def reference_section(track: str) -> str:
    """How the reference offices are said in this language - all of them.

    The corpus files are the owner (inputs/corpus-*.json, 32 works of BIG,
    OMA and SANAA plus the Korean set); this lists every sentence, so the
    author reads the offices' partis in the same words it is about to write
    in. The bar the architect set is those offices; a brief that never showed
    them asked for the standard without stating it.
    """

    offices = ("korea",) if track == "K" else ("big", "oma", "sanaa")
    lines = ["## Reference sentences: how the reference offices are said in this language",
             "Read these as partis, not as templates: the demand below is to differ from "
             "every board entry at the level of formal principle, and these show what a "
             "principle looks like when it is stated in one sentence."]
    for office in offices:
        path = ROOT / "inputs" / f"corpus-{office}.json"
        if not path.exists():
            continue
        schemes = json.loads(path.read_text(encoding="utf-8")).get("schemes") or []
        lines += ["", f"### {office.upper()} ({len(schemes)})"]
        lines += [_sentence_line(scheme) for scheme in schemes]
    return "\n".join(lines)


def sayable_words() -> str:
    """Every verb the executor knows, with its parameters and ranges - derived.

    VOCABULARY.md is prose about meaning and is hand-written; it has fallen
    behind twice (no `shape`, no `crown`), so an author working from it alone
    could not say what the engine can build. The validator derives this table
    from the executor's own source and is the correctness owner; the brief
    prints it so the two can never disagree.
    """

    import backend.app.modules.massing.workspace_tools.validate_authored as va  # noqa: E402  (derives from the executor)
    lines = ["## Sayable words, derived from the executor (the validator's own table)",
             "Verb: parameters. Ranges are the validator's; enum values are listed. "
             "A word not here does not exist, whatever the prose above or below says.",
             ""]
    for verb in sorted(va.VERBS):
        params = sorted(va.VERBS[verb] - va._UNIVERSAL)
        cells = []
        for key in params:
            lo_hi = va.PER_VERB_RANGES.get((verb, key), va.RANGES.get(key))
            if key == "profile":
                cells.append("profile in {" + ", ".join(sorted(va.PROFILES)) + "}")
            elif verb == "crown" and key == "form":
                cells.append("form in {" + ", ".join(sorted(va.CROWN_FORMS)) + "}")
            elif lo_hi:
                cells.append(f"{key} {lo_hi[0]}..{lo_hi[1]}")
            else:
                cells.append(key)
        lines.append(f"- **{verb}**: {', '.join(cells) if cells else '(no parameters)'}")
    lines += ["", f"Universal on every verb: {', '.join(sorted(va._UNIVERSAL))}."]
    # The opening, from the same owner. It is scheme-level rather than a verb
    # parameter, so the table above never carried it and this brief never showed
    # it: 901 of 901 authored sentences opened on the silent default `1/1`,
    # every mass began as the whole parcel, and the jury kept writing "an object
    # on a site rather than a site". The words were sayable the whole time.
    lines += [
        "",
        "## The opening - what this mass is cut from, said once at the top of the scheme",
        "The BOOK's grammar is three parts and this is the first: choose a body, perform",
        "one action on it, explore its bounded variations. Two scheme-level keys, beside",
        "`name` and `floor_height_m`:",
        "",
    ]
    for field, allowed in va.OPENING.items():
        lines.append("- **{}**: {}".format(field, " | ".join(allowed)))
    lines += [
        "",
        "`base_volume` is how much of the parcel seed the mass starts as and",
        "`base_orientation` is which axis carries the fraction: `1/4` + `vertical` is a",
        "low wide plate over the whole plot, `1/4` + `long_axis` is a bar a quarter of",
        "its length. A fraction shorter than one storey is refused rather than quietly",
        "rounded up to the next one.",
        "Omitting both opens on `1/1`, the whole parcel, which is what every sentence in",
        "the corpus does. Say it deliberately.",
        "",
        "The opening has two more parts, both already in the table above and both just as",
        "unused. `profile` on the first verb sets the base PLAN for the whole scheme - ten",
        "are built and 83.6% of delivered bodies are square. A section verb said early -",
        "gable, mansard, butterfly, vault, fold - gives the base SECTION; 84.4% of",
        "delivered bodies are flat-topped. A section is a base shape, not an assembly, and",
        "no matrix turns a square into a circle. Choose all four.",
    ]
    return "\n".join(lines)


def main(track: str, out_path: str, assignment: str = "") -> int:
    from backend.app.modules.massing.workspace_tools.trap_ledger import ledger  # django setup inside
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import policy_for
    from backend.app.modules.massing.workspace_tools.finalists import PNU

    count = os.environ.get("MASS_AUTHOR_COUNT")
    count_instruction = f"Exactly {int(count)} schemes." if count else "Use the scheme count requested by this cycle."

    parts = [
        "# Architectural massing author brief - assembled from canonical owners",
        "",
        f"Return only one {{\"schemes\":[...]}} JSON object. {count_instruction} Required scheme keys: name,",
        "primary_language, secondary_language, formal_principle (one Korean sentence for the final sheet),",
        "dominant_gesture, reference_basis (verified facts or original authorship), floor_height_m,",
        "base_volume and base_orientation (the opening - see its section below; omitting them opens on the whole parcel),",
        "ops (each with op, supported parameters, and a concise why: input -> operation -> visible change -> function -> limitation).",
        "Use the live grammar's parameter units and ranges. Start with extrude|loop|aggregate|stack.",
        "Operational authoring instructions are in English; user-facing sheet descriptions may be Korean.",
        "Design architectural masses: positive-volume hierarchy, section, articulation, joining/separation and carved voids.",
        "A courtyard is a void organizing building volumes; planting or landscape composition does not substitute for a massing proposition.",
        "",
        "## Programme first; compare density as a design decision",
        "Legal upper bounds are hard limits, not automatic design targets.",
        "Meet explicit required programme and area using the supplied definitions and tolerances; disclose infeasibility instead of silently reducing the brief.",
        "If required programme or target area is absent, keep it unknown; do not invent a maximum-FAR target or claim programme compliance.",
        "Compare distinct height, density and solid-void organizations that address the same supplied requirements; do not reduce alternatives to scaled copies.",
        "Lower FAR needs a visible spatial benefit in delivered mass, plan or section; prose alone is not evidence and lower density is not automatically superior.",
        "Initial authored height is revisable when the spatial proposition benefits, while explicit per-alternative growth constraints remain meaningful and must not be silently overridden.",
        "Do not invent rooms, circulation or structural proof from an attractive silhouette. State what the supplied geometry establishes and what remains unverified.",
        "Choose only the supported principles and operations needed for each proposition; operator count is not a quality target.",
        "",
        "## Brief design rationale required for each scheme",
        "1) State one conflict supported by the supplied site/programme evidence; label a provisional question when that evidence is missing.",
        "2) State one architectural massing principle that addresses it.",
        "3) Explain how that principle differs from the current board entries below.",
        "4) Express it with supported operators and state the resulting limitations.",
        "Provide concise decisions and evidence, not hidden deliberation.",
        "",
    ]
    book_only = os.environ.get('BOOK_ONLY') == '1'
    if book_only:
        start = parts.index('## Programme first; compare density as a design decision')
        parts = [parts[0], '',
                 'Author using the frozen BOOK author schema, context and PROMPT.txt supplied by the cycle.',
                 'Those files own output format and the supported geometry grammar.',
                 'This brief owns project facts, policy and historical critique; do not infer missing requirements.',
                 'Historical critiques may use different rubrics; use their observations as attributed evidence, not comparable scores.',
                 '', *parts[start:]]
    policy = policy_for(PNU)
    if policy:
        parts += ["## Confirmed parcel planning constraints derived from the code owner",
                  "Storey count and metric height are different constraints. Do not mark unverified items as passed.",
                  "```json", json.dumps(policy, ensure_ascii=False, indent=2), "```", ""]
    if assignment:
        parts += ["## Assigned authoring territory", assignment.strip(), ""]
    verdicts = ROOT / "runs" / "board" / "verdict-ledger.md"
    if verdicts.exists():
        # What the juries keep refusing, in their own clauses - generated by
        # verdict_ledger.py from every judged round, never typed here.
        parts += [verdicts.read_text(encoding="utf-8"), ""]
    champions = book_development_section() if book_only else champion_section()
    if champions:
        parts += [champions, ""]
    # The reference offices, in this language. Every sentence of every
    # reference corpus for the track - derived, never picked - so the author
    # sees how BIG, OMA and SANAA are said before writing. The header stood
    # here for a season over the trap ledger with no reference under it.
    if book_only:
        parts += ['## Geometry validation',
                  'The live BOOK schema and canonical importer own geometry rules. '
                  'Do not apply parameter rules from another massing language. '
                  'Delivered site, geometry and dimensional measurements remain mandatory.',
                  '', board_section(track)]
    else:
        parts += [reference_section(track), "",
              ledger(), "", board_section(track), "",
              "---", "",
              sayable_words(), "", "---", "",
              (ROOT / "inputs" / "VOCABULARY.md").read_text(encoding="utf-8"),
              "", "---", "",
              (ROOT / "inputs" / "AUTHORING-CANON.md").read_text(encoding="utf-8")]
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")
    print(f"brief -> {out_path} ({Path(out_path).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    track = sys.argv[1] if len(sys.argv) > 1 else "O"
    out = sys.argv[2] if len(sys.argv) > 2 else "brief.md"
    text = Path(sys.argv[3]).read_text(encoding="utf-8") if len(sys.argv) > 3 else ""
    sys.exit(main(track, out, text))

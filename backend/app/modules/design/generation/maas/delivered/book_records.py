"""Tracked BOOK delivery helper extracted unchanged from the legacy owner tools.

No registry discovery, jury scheduling, or runtime CLI import belongs here.
"""
import json
from pathlib import Path


def records_of(book_dir: Path) -> list[dict]:
    """Every BOOK record in a run directory, whichever era wrote it.

    The exploration command has two output shapes. The older run wrote one
    `maas-book-exact-geometry-artifacts.json` holding records with a
    `geometry_artifact`; the current one writes a portfolio plus one JSON per
    candidate, each with its `geometry_program` directly. Both are BOOK masses
    and the board judges both, so the reader takes either.
    """

    old = book_dir / "maas-book-exact-geometry-artifacts.json"
    if old.exists():
        return list(json.loads(old.read_text(encoding="utf-8")).get("records") or [])
    portfolio = book_dir / "maas-creative-portfolio.json"
    if not portfolio.exists():
        return []
    entries = json.loads(portfolio.read_text(encoding="utf-8")).get("candidates") or []
    records = []
    for entry in entries:
        path = book_dir / str(entry.get("candidate_json") or "")
        if not path.exists():
            continue
        candidate = json.loads(path.read_text(encoding="utf-8"))
        program = candidate.get("geometry_program")
        if not program:
            continue
        floors = (candidate.get("storey_evidence") or {}).get("actual_floor_areas_m2")
        if not floors:
            # Without the book's own plan size the shared compile fits the
            # plan to the legal host, which is how a 209 m2 book was once
            # staged at 705 m2. Skipped loudly rather than judged at a size
            # nobody authored.
            import sys as _sys
            print(f"  skip {entry.get('candidate_id')}: no floor areas",
                  file=_sys.stderr)
            continue
        # The portfolio's own words for what this candidate is: the family it
        # came from and the BOOK principle it was assigned. That is the thesis
        # a juror reads, and without it the tile carries a hash.
        assignment = (program.get("metadata") or {}).get(
            "creative_book_assignment") or {}
        principle = str(assignment.get("principle_id") or "")
        verbs = ", ".join(str(v) for v in (assignment.get("execution_verbs") or ()))
        family = str(candidate.get("family") or entry.get("family") or "")
        records.append({
            # The run id is part of the identity. Candidate ids restart at
            # creative-001 every exploration, so without it two runs mint the
            # same sixty keys and the registry - a flat merge of every
            # runs/books/*.json - hands the baker whichever sorted last.
            "trace_sequence_name":
                f"{book_dir.name}:{family}:{entry.get('candidate_id')}",
            "thesis": (
                f"{family.replace('_', ' ')} - "
                f"{verbs or 'base'}"
                + (f" ({principle.split(':')[-1]})" if principle else "")
            ),
            "geometry_artifact": {
                'storeyEvidence': dict(candidate.get('storey_evidence') or {}),
                "authoredGeometryProgram": program,
                # The portfolio states the physical height as the top of the
                # mesh bounds and the storeys it was cut into; the older
                # artifact carried a certificate instead. Both are the book's
                # own account of how tall it is, which is what the height
                # dialect below needs - without one every book mass measured
                # 0.0 m and drew flat.
                "projectedVisualCertificate": {
                    "physical_height_m": float(
                        ((candidate.get("mesh_evidence") or {}).get("bounds")
                         or [[0, 0, 0], [0, 0, 0]])[1][2] or 0.0),
                },
                "hardGates": {"projectedMetrics": {
                    "footprint_area_m2": float(
                        ((candidate.get("storey_evidence") or {}).get(
                            "actual_floor_areas_m2") or [0.0])[0] or 0.0),
                    # The book's own gross, summed over its own floors at its
                    # own storey height. Left unset, the caption fell back to
                    # measuring the delivered bands at the parcel's storey -
                    # the very reading the height dialect below exists to
                    # avoid - and all sixty tiles went to the jury with a
                    # 용적률 taken on the wrong ruler.
                    "floor_area_m2": float(sum(
                        (candidate.get("storey_evidence") or {}).get(
                            "actual_floor_areas_m2") or ())),
                }},
            },
        })
    return records

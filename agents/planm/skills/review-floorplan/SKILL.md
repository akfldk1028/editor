---
name: review-floorplan
description: Render and verify PLANM alternatives as architectural SVG, PNG, HTML, and review evidence. Use after alternatives are generated.
---

# Review Floorplan

1. Read `planm-state.json` and require accepted alternative identifiers.
2. Run `python skills/review-floorplan/scripts/run.py` against the same state.
3. Reject missing layers, unresolved label collisions, blank PNGs, and render mismatches.
4. Retain canonical review artifacts and hashes.
5. Continue only when internal and render validation both pass.

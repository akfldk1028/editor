---
name: deliver-planm-package
description: Package accepted PLANM alternatives, validation status, unresolved facts, and canonical artifacts into the final manifest. Use after review-floorplan succeeds.
---

# Deliver PLANM Package

1. Read `planm-state.json` and require stage `reviewed` with status `success`.
2. Run `python skills/deliver-planm-package/scripts/run.py` against the same state.
3. Verify every manifest artifact exists and matches its SHA-256 hash.
4. Report regulatory `not_checked` and BIM blockers explicitly.
5. Return the final `planm-manifest.json` only when package checks pass.

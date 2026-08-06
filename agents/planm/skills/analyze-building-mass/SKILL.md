---
name: analyze-building-mass
description: Analyze normalized PLANM mass geometry and persist typed planning evidence. Use after normalize-plan-request succeeds.
---

# Analyze Building Mass

1. Read `planm-state.json` and require stage `normalized` with status `success`.
2. Run `python skills/analyze-building-mass/scripts/run.py` against the same state.
3. Continue only when the returned status is `success`.
4. Preserve the analysis artifact path and hash in workflow state.
5. Stop on `blocked`; do not approximate unsupported geometry.

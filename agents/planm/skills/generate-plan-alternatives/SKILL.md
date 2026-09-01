---
name: generate-plan-alternatives
description: Generate and rank geometrically distinct validated PLANM building alternatives. Use after analyze-building-mass succeeds.
---

# Generate Plan Alternatives

1. Read `planm-state.json` and require stage `analyzed` with status `success`.
2. Run `python skills/generate-plan-alternatives/scripts/run.py` against the same state.
3. Require at least two accepted semantic alternatives when the mass is supported.
4. Pass structured hard violations to a bounded repair path when status is `retryable`.
5. Never re-evaluate a fingerprint already recorded in state.

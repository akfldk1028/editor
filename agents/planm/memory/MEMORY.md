# PLANM Memory

## Product objective

Execute versioned PLANM skills from normalized building requirements through
validated alternatives, visual review, bounded repair, and delivery evidence.

## Stable boundaries

- GitAgent is the generic runtime.
- `agents/planm` owns PLANM product behavior.
- PLAN Python modules own deterministic domain behavior.
- Skills communicate through persisted versioned JSON contracts.

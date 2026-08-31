# PLAN product

PLAN converts a building mass and program into validated, visually reviewed floor
plan alternatives, requires human approval, and produces a CAD handoff.

## Owned directories

- `frontend`: PLAN product shell and planning UI
- `backend`: API, deterministic geometry engine, run state, validation, and CAD handoff
- `agents/planm`: PLANM identity, contracts, workflow, skills, and process host
- `infra`: PLAN-specific container definitions
- `docs`: PLAN architecture, research decisions, and retained evidence
- `resources`: datasets, experiments, research, and scripts

Python commands run from this directory so the stable import namespace remains
`backend.app`. Repository-wide commands and cross-product E2E tests run from the
workspace root.

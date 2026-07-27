# PLAN Module Map

PLAN is organized around a replaceable `Mass -> Program -> Precedent -> Layout -> Validation` loop.

## Runtime Boundary

- `backend/app/schemas`: stable data contracts.
- `backend/app/modules`: application services that orchestrate one capability each.
- `engine`: reusable geometry, graph, constraint, metric, and IO primitives.
- `backend/app/api`: thin route wrappers. V1 keeps them framework-neutral.
- `backend/app/cli.py`: CLI entrypoint for running the V1 loop.

## Research Boundary

- `research/papers`: grouped paper sources and notes.
- `datasets/raw`: untouched inputs.
- `datasets/processed`: normalized images, vectors, graphs, and program data.
- `experiments`: isolated experiment outputs and configs.

## V1 Principle

The baseline generator is intentionally simple. The important contract is that future Graph2Plan, HouseDiffusion, DiffPlanner, FMLM, or RLVR modules can replace it without changing schemas.

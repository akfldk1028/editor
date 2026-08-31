# Product-First Monorepo Migration Plan

> Execute in small verified batches. Do not weaken PLAN acceptance gates or DWG
> public-boundary tests to make the migration pass.

**Goal:** Convert the current mixed PLAN checkout into merge-safe product capsules
without changing existing product behavior.

**Architecture:** `products/plan` owns PLAN, `products/dwg` owns DWG,
`platform/agent-runtimes` owns generic runtimes, and root integration owns only
composition. Cross-product communication uses versioned public contracts.

## Task 1: Lock the target layout with tests

- Add a root structure test asserting canonical directories exist and legacy
  `agents/dwg`, `agents/runtimes`, root `backend`, and root `frontend` do not.
- Add forbidden dependency checks for product-to-product private imports.
- Run the new tests and confirm they fail before moving files.

## Task 2: Move independent products and platform runtime

- Move `agents/dwg` to `products/dwg`.
- Move `agents/runtimes/gitagent` to `platform/agent-runtimes/gitagent`.
- Update root commands and PLAN adapter paths.
- Run PLANM host tests and DWG boundary tests.

## Task 3: Move the PLAN capsule

- Move `backend`, `frontend`, `agents/planm`, `resources`, and PLAN documentation
  under `products/plan`.
- Preserve `backend.app` Python imports by making `products/plan` the Python
  project root.
- Keep root integration tests and compose files at root.
- Update package, pytest, Playwright, and development-runner paths.

## Task 4: Split product-local and root integration infrastructure

- Put PLAN and DWG Dockerfiles beside their products.
- Keep only cross-product compose, proxy, development launcher, and end-to-end
  orchestration under root `infra`.
- Build each image from a clean context.

## Task 5: Establish the PLAN-DWG public contract

- Add versioned schemas under `shared/contracts/plan-dwg`.
- Make PLAN Backend and DWG validate the shared payloads.
- Remove frontend Docker source copies from DWG internals.
- Run contract and live handoff tests.

## Task 6: Complete PLANM execution semantics

- Validate request, state, and result schemas at runtime.
- Persist attempts, leases, history, and terminal status.
- Implement bounded deterministic repair commands and optional LLM proposals.
- Test retry, exhaustion, duplicate execution, interruption, and resume.

## Task 7: Full verification

- Run PLAN backend, PLANM, root infra, frontend build, and Playwright suites.
- Run DWG Node, .NET, build, and E2E suites sequentially.
- Run the live product handoff and inspect retained screenshots.
- Run all 48 PLAN cases and report accepted counts without changing gates.

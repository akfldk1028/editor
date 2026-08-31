# Product-First Monorepo Design

**Date:** 2026-08-31
**Status:** Approved

## Goal

Make PLAN safe to merge with other repositories that also contain `frontend`,
`backend`, `agents`, `infra`, and `docs` without overlaying unrelated products or
creating private cross-product imports.

## Decision

Use product-first ownership. Product code lives under `products/<product>`;
repository-wide runtimes live under `platform`; deliberately shared contracts
live under `shared`; root `infra` and `docs` contain only cross-product concerns.

```text
ROOT/
|-- products/
|   |-- plan/
|   |   |-- frontend/
|   |   |-- backend/
|   |   |-- agents/planm/
|   |   |-- infra/
|   |   |-- docs/
|   |   `-- resources/
|   `-- dwg/
|       |-- apps/
|       |-- modules/
|       |-- packages/
|       |-- skills/
|       |-- infra/
|       `-- docs/
|-- platform/agent-runtimes/gitagent/
|-- shared/contracts/plan-dwg/
|-- infra/
`-- docs/
```

## Ownership and dependency rules

- PLAN Frontend calls PLAN Backend only.
- PLAN Backend owns run, retry, approval, and handoff state.
- PLANM is the only PLAN agent and may call the deterministic PLAN engine only
  through its declared skills.
- PLANM uses deterministic execution by default. An LLM may propose a bounded
  repair command after a typed failure; it never bypasses validation or approval.
- DWG is an independent product. PLAN consumes only its HTTP/MCP/public contract
  surfaces and never imports DWG internals.
- `platform` cannot import product code.
- `shared` contains versioned DTOs and schemas only; it cannot import a product.
- Root integration code may compose products but cannot become a business-logic
  owner.

## Runtime reliability

Each PLANM stage validates input, state, and result against JSON Schema. Backend
persists stage attempts and owns a maximum of three attempts. Duplicate execution
must be idempotent, an interrupted run must be resumable, and every repair proposal
must be retained with provenance. Human approval remains mandatory before CAD
handoff.

## Migration strategy

The migration is mechanical first and behavioral second:

1. Add executable boundary tests for the target layout.
2. Move DWG and GitAgent without changing their internal APIs.
3. Move PLAN as one product capsule while preserving Python import names.
4. Update root orchestration, Docker build contexts, npm prefixes, and tests.
5. Establish the shared PLAN-DWG contract surface; remove private source copying.
6. Add durable retries and runtime schema validation with focused TDD.

No compatibility symlink is committed. All callers must use canonical paths.

## Verification gates

- repository layout and forbidden-import tests
- PLAN backend full test suite
- PLANM/GitAgent tests
- DWG Node and .NET verification, sequentially
- PLAN frontend production build and Playwright tests
- live PLAN Backend -> approval -> DXF -> DWG inspection flow
- 48-case alternative sweep with retained summaries and PNG inspection

Moving files alone is not completion; all canonical commands and container builds
must work from a clean checkout.

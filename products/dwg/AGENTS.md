# AGENTS.md

These instructions apply to the entire repository.

## First actions

1. Read `README.md`, `docs/handoff/repo-memory.md`,
   `docs/architecture/ai-clone-handoff.md`,
   `docs/architecture/module-boundaries.md`, and
   `docs/architecture/integration-contract.md`.
2. Run `git status --short`, `git branch --show-current`, and `git remote -v`.
3. Treat checkout-specific commits, ports, OAuth state, and test totals as
   stale until verified locally.
4. Run `npm run verify` before changing module boundaries.

## Non-negotiable architecture

- `packages/contracts` is the only TypeScript package shared by browser and
  CAD runtime code. It must stay free of React, Node, HTTP, CLI, and parser code.
- `modules/cad-runtime` must not import `apps/workspace`; `apps/workspace`
  must not import `modules/cad-runtime`.
- `apps/workspace/src/shared` must not import features. Feature folders must
  not import one another. Cross-feature wiring belongs in `apps/workspace/src/app`.
- `apps/workspace/src/app/useWorkspaceControls.ts` owns global browser controls;
  `useWorkspacePreferences.ts` owns persisted theme, panel width, and sidebar
  section preferences.
- Parsers return versioned contract DTOs. Never leak ACadSharp, DXF parser, SVG,
  subprocess, or provider implementation types across a public boundary.
- OAuth providers use existing Codex/Claude CLI login state. Do not add API-key
  fallbacks or persist credentials.
- DWG/DXF sources are read-only. AI conclusions must cite deterministic
  handles/layers/types/bboxes instead of claiming visual geometry from the LLM.

## Supported integration surfaces

- `@dwg/contracts`
- `@dwg/skill-contracts`
- loopback `/api`
- MCP stdio
- whole apps/workspace composition

`modules/cad-runtime/src/**`, `apps/workspace/src/features/**`, the CAD
capability modules (`@dwg/cad-document`, `@dwg/cad-edit`, `@dwg/cad-query`,
`@dwg/cad-export`, `@dwg/cad-io-acadsharp`, `@dwg/cad-capabilities`,
`@dwg/skill-runtime`), and parser internals are not deep-import APIs. A
`packages/**` surface taken into a host repository must carry the dependencies
its own manifest declares.

## Verification

Run Node and .NET suites sequentially on Windows to avoid parser assembly
locking:

```powershell
npm test
npm run test:dotnet
npm run build:frontend
```

For browser verification, use isolated ports and inspect retained PNGs:

```powershell
$env:DWG_FRONTEND_PORT='4308'
$env:DWG_GATEWAY_PORT='4452'
npm run test:e2e
```

Documentation captures use separate variables:

```powershell
$env:DWG_DOCS_FRONTEND_PORT='4310'
$env:DWG_DOCS_GATEWAY_PORT='4454'
npm run capture:docs
```

Required before handoff:

- `npm run verify`
- module-boundary tests remain green
- relevant Playwright scenarios pass
- `docs/ui-captures/00-overview.png` is inspected after UI changes
- public contract changes document compatibility and update both consumers
- commit only scoped files; do not merge, push, or delete worktrees without an
  explicit integration choice

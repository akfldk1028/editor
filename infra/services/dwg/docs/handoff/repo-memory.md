# Repository memory

This file is the sanitized, version-controlled memory for DWG Intelligence. It
records stable decisions that should survive a clone or submodule checkout.
Personal agent history, credentials, local paths, and transient test results do
not belong here.

## Product invariant

DWG Intelligence is a local-first DWG/DXF inspection and controlled-editing
workspace. Parsers produce versioned CAD contract data. AI may reason over that
data, but object-level conclusions must cite deterministic handles, layers,
types, and bounding boxes. The model must not claim that it decoded or saw raw
CAD geometry.

Input DWG/DXF files are read-only. An edit is a deterministic proposal with a
preview and approval step, applied to the in-memory document and persisted only
through Save As. Chat analysis alone does not mutate the drawing.

## Supported reuse surfaces

Choose one boundary for a host integration:

- `@dwg/contracts`
- `@dwg/skill-contracts`
- loopback `/api`
- MCP stdio
- the complete `apps/workspace` composition

Do not deep-import parser internals, `modules/cad-runtime/src/**`, individual
workspace features, or CAD capability module internals. A package copied or
linked into a host must retain every dependency declared by its own manifest.
The detailed contract is in
[`../architecture/integration-contract.md`](../architecture/integration-contract.md).

## Ownership rules

- `packages/contracts` is the only TypeScript package shared by browser and CAD
  runtime code; it stays free of React, Node, HTTP, CLI, and parser types.
- `modules/cad-runtime` and `apps/workspace` do not import one another.
- Workspace features do not import other features; composition belongs in
  `apps/workspace/src/app`.
- Parsers expose versioned DTOs, never ACadSharp, DXF parser, SVG, subprocess,
  or provider implementation types.
- The active drawing session owns chat context, inspection state, edit history,
  and export behavior. Switching drawings must not retain drawing-owned state.

## Save As and AI behavior

Save As writes a new file and verifies the result against the active document;
it never overwrites the source. Supported verified pairs are DWG to DWG, DWG to
DXF, and DXF to DXF. DXF to DWG remains withheld until the versioned entity
models can be compared safely.

Codex and Claude providers reuse their existing CLI OAuth sessions. Do not add
API-key fallbacks, store tokens, or commit provider state. AI analysis and edit
proposals remain grounded in the deterministic CAD index. Natural-language chat
is not yet wired directly to the edit-proposal workflow.

## Verification and known limits

Run Node and .NET suites sequentially on Windows, then build the frontend. Run
Playwright on isolated ports for browser-affecting work and inspect retained
captures rather than relying only on an exit code. Use the commands in
[`../../AGENTS.md`](../../AGENTS.md); verify current totals locally.

Automated tests cover the browser file route and external-file Save As flow, but
the native Windows file/folder chooser still requires an interactive manual
check. Claude features also require a valid local `claude` CLI login.

## Keep local

Never commit `.claude/settings.local.json`, `.codex/`, `.remember/`, `.env*`
secrets, OAuth sessions, ad hoc source drawings, absolute user paths, or stale
claims about commits, ports, and test totals. `.gitignore` protects these local
artifacts; this file is the portable replacement for project-relevant memory.

For a one-folder host integration, follow
[`embedding-as-submodule.md`](embedding-as-submodule.md).

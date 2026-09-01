# Skill-First CAD Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a modular, skill-first CAD workspace with deterministic editing, readable navigation, verified Save As, and report exports.

**Architecture:** Execute five separately reviewable plans in dependency order. Each plan leaves `master` green and exposes only public package entrypoints so later plans do not reach into earlier module internals.

**Tech Stack:** TypeScript 5.8, Node 24 test runner, React 19, Vite 8, Playwright 1.62, .NET 9, ACadSharp 3.6.35, Zod 3, MCP SDK 1.30.

## Global Constraints

- Never overwrite the source DWG or DXF.
- Every AI-proposed edit becomes a validated deterministic command.
- Use only public package entrypoints; reject cross-module deep imports.
- Ground entity results in handle, type, layer, layout, and bbox.
- Save As succeeds only after reopening and verifying the output.
- Retain no provider prompt, response, session identifier, credential, or raw CAD bytes in failure artifacts.
- Run Node and .NET parser tests sequentially.
- Run live OAuth verification last and retain only redacted evidence.

## Package Dependency Direction

Every listed edge is declared in the consumer's `package.json`; no reverse or
deep-import edge is allowed.

```text
apps/workspace -> @dwg/contracts
modules/cad-document -> @dwg/contracts
modules/cad-edit -> @dwg/contracts, @dwg/cad-document
modules/cad-query -> @dwg/contracts
modules/cad-export -> @dwg/contracts, @dwg/cad-document, @dwg/cad-edit
modules/cad-io-acadsharp -> @dwg/contracts, @dwg/cad-edit
modules/cad-capabilities -> @dwg/contracts, @dwg/cad-document,
                            @dwg/cad-edit, @dwg/cad-query,
                            @dwg/cad-export, @dwg/cad-io-acadsharp
modules/skill-runtime -> @dwg/contracts, @dwg/skill-contracts,
                         @dwg/cad-capabilities
packages/test-kit -> @dwg/contracts
packages/skill-contracts -> @dwg/contracts
```

`modules/cad-runtime` remains the root-owned composition adapter and declares
its workspace dependencies in the root `package.json`; it is not imported by
any reusable module.

---

## Plan Order

1. [Capability Foundation](2026-07-30-cad-capability-foundation.md)
2. [Deterministic Edit Engine](2026-07-30-cad-edit-engine.md)
3. [Skill Runtime and Built-in Skills](2026-07-30-cad-skill-runtime.md)
4. [Workspace Navigation and Change Review](2026-07-30-cad-workspace-ui.md)
5. [Verified Save As and Exports](2026-07-30-cad-save-export.md)

## Program Gates

- [ ] **Gate 1: Foundation**

Run: `npm run verify:all`

Expected: all existing tests plus new package-boundary and capability tests pass.

- [ ] **Gate 2: Editing**

Run: `npm run test:edit && npm run verify:all`

Expected: command preview, atomic apply, diff, undo, and redo pass without writing a CAD file.

- [ ] **Gate 3: Skills**

Run: `npm run test:skills && npm run verify:all`

Expected: every built-in skill passes manifest, permission, schema, and capability conformance.

- [ ] **Gate 4: Workspace**

Run: `npm run verify:all && npm run capture:docs`

Expected: Project, Sessions, Skills, Changes, and Export UI tests pass and the retained contact sheet is visually reviewed.

- [ ] **Gate 5: Save and Export**

Run: `npm run verify:release`

Expected: immutable source hashes, corrupted/proxy/XREF/font/codepage fixtures,
DXF round trip, allowlisted DWG round trip, multi-skill approval workflow,
report exports, CLI/MCP, browser, and redacted live OAuth tests all pass.

## Integration Rule

Do not start a later plan until the prior plan is committed, independently
reviewed, and green. A plan may use a worktree, but generated output from one
worktree must not be accepted as verification evidence for another checkout.

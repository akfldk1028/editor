# Real Inspection Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the simulated frontend inspection with a real, deterministic DWG inspection run whose drawing, events, findings, evidence, and warnings all come from the gateway.

**Architecture:** The gateway owns the selected drawing path and exposes its index plus a path-free inspection endpoint. Shared contracts define the browser/server boundary. The frontend owns only presentation state and invokes the inspection endpoint through a feature-local hook; it never supplies an arbitrary local path.

**Tech Stack:** TypeScript, Node HTTP, React 19, ACadSharp parser bridge, Playwright, shared `@dwg/contracts`.

## Global Constraints

- Keep deterministic `cad-index/v0.1` evidence separate from LLM explanations.
- Do not expose arbitrary local filesystem paths to the browser.
- Keep `packages/contracts`, `agent`, and frontend feature boundaries explicit.
- Use one server-owned drawing source for both viewer and inspection.
- Every behavior change follows RED, GREEN, REFACTOR.
- Visual completion requires Playwright screenshots inspected as PNG.

---

## File Structure

- `packages/contracts/src/inspection.ts`: Public inspection request, event, evidence, issue, and result contracts plus payload validation.
- `packages/contracts/src/index.ts`: Public export only.
- `agent/src/http/drawingWorkspace.ts`: Resolve and contain server-owned drawing paths.
- `agent/src/http/providerGateway.ts`: HTTP routes for the current drawing and inspection.
- `agent/src/http/gateway.ts`: Composition root wiring parser and orchestrator to gateway dependencies.
- `agent/src/orchestration/orchestrator.ts`: Reuse shared inspection result contracts.
- `frontend/src/shared/api/drawingIndexClient.ts`: Load the current index from the gateway.
- `frontend/src/shared/api/inspectionGatewayClient.ts`: Submit bounded inspection checks.
- `frontend/src/features/inspection-results/useInspectionRun.ts`: Own run/loading/error/cancel state.
- `frontend/src/features/agent-chat/AgentWorkspace.tsx`: Render real orchestration events.
- `frontend/src/features/inspection-results/InspectionDock.tsx`: Render real findings, evidence, and warnings.
- `frontend/src/app/App.tsx`: Wire the current drawing and real inspection feature.

### Task 1: Public inspection contract

**Files:**
- Create: `packages/contracts/src/inspection.ts`
- Modify: `packages/contracts/src/index.ts`
- Modify: `agent/src/orchestration/orchestrator.ts`
- Test: `agent/tests/contracts/public-contracts.test.ts`

**Interfaces:**
- Consumes: `CadPointBox` from `@dwg/contracts`.
- Produces: `InspectionCheck`, `InspectionPayload`, `InspectionEvent`, `InspectionFinding`, `InspectionIssue`, `InspectionRun`, `isInspectionPayload(value)`.

- [ ] **Step 1: Write the failing contract test**

```ts
assert.equal(isInspectionPayload({
  checks: [{ kind: "layer", value: "0" }]
}), true);
assert.equal(isInspectionPayload({
  checks: [{ kind: "text", value: "(", regex: true }]
}), true);
assert.equal(isInspectionPayload({
  checks: Array.from({ length: 9 }, () => ({ kind: "layer", value: "0" }))
}), false);
assert.equal(isInspectionPayload({
  path: "../../secret.dwg",
  checks: [{ kind: "layer", value: "0" }]
}), false);
```

- [ ] **Step 2: Run `node --import tsx --test agent/tests/contracts/public-contracts.test.ts` and verify it fails because the inspection export does not exist**

- [ ] **Step 3: Implement the shared types and validator**

```ts
export type InspectionCheck =
  | { kind: "layer"; value: string }
  | { kind: "type"; value: string }
  | { kind: "text"; value: string; regex?: boolean };

export interface InspectionPayload {
  checks: InspectionCheck[];
}
```

The validator accepts 1–8 checks, values of 1–200 characters, known keys only, and `regex` only for text checks.

- [ ] **Step 4: Import the result types into `orchestrator.ts` and run the contract and orchestrator tests**

- [ ] **Step 5: Commit the independently passing contract change**

### Task 2: Server-owned drawing workspace and gateway routes

**Files:**
- Create: `agent/src/http/drawingWorkspace.ts`
- Modify: `agent/src/http/providerGateway.ts`
- Modify: `agent/src/http/gateway.ts`
- Test: `agent/tests/providers/provider-gateway.test.ts`
- Test: `agent/tests/http/drawing-workspace.test.ts`

**Interfaces:**
- Consumes: `InspectionPayload`, `InspectionRun`, `CadEntityIndex`.
- Produces: `createDrawingWorkspace(workspace, configuredPath)` with `getIndex()` and `inspect(checks)`.

- [ ] **Step 1: Write a failing path-containment test**

```ts
assert.throws(
  () => createDrawingWorkspace(workspace, "../outside.dwg"),
  /outside workspace/i
);
```

- [ ] **Step 2: Run the focused test and verify the missing module failure**

- [ ] **Step 3: Implement canonical containment**

```ts
const relativePath = relative(workspaceRoot, resolvedDrawing);
if (relativePath.startsWith("..") || isAbsolute(relativePath)) {
  throw new Error("Drawing path is outside workspace");
}
```

- [ ] **Step 4: Add failing gateway tests for `GET /api/drawing` and `POST /api/inspections`**

```ts
assert.deepEqual(await drawingResponse.json(), fixtureIndex);
assert.deepEqual(await inspectionResponse.json(), fixtureRun);
```

The inspection request contains checks only and rejects `path`, empty checks, invalid regex fields, and more than eight checks.

- [ ] **Step 5: Add gateway dependencies `getDrawing()` and `inspect(payload)` and wire the real orchestrator**

- [ ] **Step 6: Run gateway, workspace, orchestrator, and full Node tests**

- [ ] **Step 7: Commit the gateway slice**

### Task 3: Real frontend inspection state

**Files:**
- Modify: `frontend/src/shared/api/drawingIndexClient.ts`
- Create: `frontend/src/shared/api/inspectionGatewayClient.ts`
- Create: `frontend/src/features/inspection-results/useInspectionRun.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/features/agent-chat/AgentWorkspace.tsx`
- Modify: `frontend/src/features/inspection-results/InspectionDock.tsx`
- Modify: `frontend/src/features/cad-viewer/CadViewer.tsx`
- Test: `frontend/tests/e2e/inspection-run.spec.ts`

**Interfaces:**
- Consumes: `GET /api/drawing`, `POST /api/inspections`.
- Produces: `useInspectionRun()` returning `{ run, loading, error, start, cancel, reset }`.

- [ ] **Step 1: Write a failing Playwright test that intercepts `/api/inspections`**

```ts
await page.getByRole("button", { name: "Run agents" }).click();
await expect(page.getByText("5개 주요 객체")).toBeVisible();
await expect(page.locator('[data-handle="23D"]')).toHaveClass(/highlighted/);
```

The fixture result uses five findings so the old hardcoded four-result UI cannot pass.

- [ ] **Step 2: Run the focused Playwright test and verify failure on the hardcoded output**

- [ ] **Step 3: Implement the client and hook, and make `Run agents` invoke `{ checks: [{ kind: "layer", value: "0" }] }`**

- [ ] **Step 4: Render tool steps from `run.events`, finding counts from `run.findings`, warnings from `run.warnings`, and selected evidence from the matching current-index handle**

- [ ] **Step 5: Remove hardcoded handles and scenario-derived verification**

- [ ] **Step 6: Run focused Playwright, full Node tests, TypeScript, and frontend build**

- [ ] **Step 7: Commit the real frontend slice**

### Task 4: Browser and PNG verification loop

**Files:**
- Modify: `frontend/tests/e2e/workspace.spec.ts`
- Create: `tests/visual/real-inspection-1440x900.png`
- Modify: `docs/dwg-intelligence-harness-loop.md`

**Interfaces:**
- Consumes: Real gateway inspection endpoint.
- Produces: A retained 1440×900 visual artifact and updated regression expectations.

- [ ] **Step 1: Replace simulated scenario assertions with real run assertions**

- [ ] **Step 2: Run `npx playwright test tests/e2e/inspection-run.spec.ts --project chromium` from `frontend`**

- [ ] **Step 3: Capture the completed inspection at 1440×900**

```ts
await page.screenshot({
  path: "../tests/visual/real-inspection-1440x900.png",
  fullPage: true
});
```

- [ ] **Step 4: Inspect the PNG and record any clipping, overlap, illegible evidence, or stale count**

- [ ] **Step 5: Fix each observed defect through a focused failing Playwright assertion, then recapture and reinspect**

- [ ] **Step 6: Run the entire Playwright suite and commit verified visual artifacts**

### Task 5: Next hardened loops

**Files:**
- Plan separately after Task 4 evidence is green.

**Interfaces:**
- Consumes: Real inspection gateway delivered by Tasks 1–4.
- Produces: Independent plans for geometry fidelity, OAuth tool orchestration, upload/drawing sessions, and dependency/process security.

- [ ] **Step 1: Plan `cad-index/v0.2` geometry, block attributes, layouts, and paper space against real DWG fixtures**

- [ ] **Step 2: Plan provider response evidence validation and CAD-tool orchestration beyond the first 200 entities**

- [ ] **Step 3: Plan secure imported-drawing sessions keyed by drawing ID rather than local paths**

- [ ] **Step 4: Plan process-tree cancellation, module graph enforcement, and MCP SDK upgrade**

## Self-Review

- Spec coverage: Real orchestrator, single drawing truth, filesystem containment, real findings/evidence/warnings, Playwright and PNG inspection are covered.
- Intentional split: Geometry fidelity and OAuth tool orchestration remain separate because each changes a different trust boundary and needs its own fixtures.
- Placeholder scan: No implementation step uses TBD, TODO, or unspecified error handling.
- Type consistency: Browser payload is `InspectionPayload`; server returns `InspectionRun`; the browser never sends `path`.

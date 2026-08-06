# Deterministic CAD Edit Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic command preview, atomic apply, diff, undo, and redo without writing CAD files.

**Architecture:** Public command DTOs live in contracts; `cad-edit` applies them to cloned `cad-document` snapshots. `cad-capabilities` owns session and approval flow while writers remain absent from this phase.

**Tech Stack:** TypeScript 5.8, Node 24 test runner, Zod 3, UUIDs, existing cad-index/v0.2 geometry.

## Global Constraints

- No command accepts code, parser objects, provider values, or arbitrary paths.
- Unsupported entity types fail before mutation.
- Transactions are atomic.
- Revision mismatch returns a structured conflict.
- The source snapshot and fixture bytes remain unchanged.
- The `cad-edit` README documents its public entrypoint, dependency on
  `cad-document` and contracts, forbidden writer access, and `npm run
  test:edit`.

---

### Task 1: Define Versioned Edit Contracts

**Files:**
- Create: `packages/contracts/src/edit.ts`
- Modify: `packages/contracts/src/index.ts`
- Create: `packages/contracts/tests/edit-contracts.test.ts`

**Interfaces:**
- Produces:

```ts
type CadEditCommand =
  | { kind: "layer.create"; layerId: string; name: string; color: number }
  | { kind: "layer.update"; layerId: string; name?: string; color?: number; visible?: boolean; locked?: boolean }
  | { kind: "text.replace"; handle: string; text: string }
  | { kind: "entity.move"; handles: string[]; delta: CadPoint3 }
  | { kind: "entity.copy"; handles: string[]; delta: CadPoint3 }
  | { kind: "entity.delete"; handles: string[] };

interface CadCommandProposal {
  commandId: string;
  expectedRevision: number;
  origin:
    | { kind: "user"; id: string }
    | { kind: "skill"; id: string; skillVersion: string; runId: string };
  preconditions: Array<{
    target: string;
    field: "exists" | "type" | "layer" | "text";
    equals: string | boolean;
  }>;
  operation: CadEditCommand;
}

interface CadEditBatch {
  schemaVersion: "cad-edit/v1";
  transactionId: string;
  documentId: string;
  expectedRevision: number;
  commands: CadCommandProposal[];
}

interface CadResolvedCommand {
  proposal: CadCommandProposal;
  before: unknown;
  result: unknown;
  warnings: string[];
}
interface CadEntityChangeState {
  id: string;
  handle: string | null;
  type: string;
  layer: string;
  bbox: CadPointBox | null;
  text: string | null;
}
interface CadLayerChangeState {
  id: string;
  name: string;
  color: number | null;
  visible: boolean;
  frozen: boolean;
  locked: boolean | null;
}
type CadChange =
  | {
      commandId: string;
      kind: "layer.create" | "layer.update";
      targetId: string;
      before: CadLayerChangeState | null;
      after: CadLayerChangeState | null;
    }
  | {
      commandId: string;
      kind: "text.replace" | "entity.move" | "entity.copy" | "entity.delete";
      targetId: string;
      before: CadEntityChangeState | null;
      after: CadEntityChangeState | null;
    };
interface CadEditPreviewResponse {
  previewId: string;
  documentId: string;
  transactionId: string;
  baseRevision: number;
  nextRevision: number;
  changes: CadChange[];
  warnings: string[];
}
interface CadEditApplyResponse {
  documentId: string;
  revision: number;
  transactionId: string;
  changeCount: number;
}
interface CadEditPreviewRequest {
  batch: CadEditBatch;
}
interface CadEditApplyRequest {
  previewId: string;
  documentId: string;
  expectedRevision: number;
  approved: true;
}
interface CadEditHistoryRequest {
  documentId: string;
  expectedRevision: number;
  approved: true;
}
```

- [ ] **Step 1: Write strict validation tests**

Accept one example per command. Reject empty batches, duplicate handles,
zero-length handle strings, non-finite deltas, layer colors outside
`1..255`, invalid layer IDs, unknown keys, and text over 16,384 characters.
Layer IDs must match `layer:(?:imported|created):[A-Za-z0-9_-]+`.
Command, transaction, and skill run IDs are UUIDs. A command with an
unsatisfied precondition or an `expectedRevision` different from its batch is
rejected before mutation. Export all response DTOs from `@dwg/contracts`; UI
packages must not redeclare them.
Validate all request DTOs strictly; `approved` must be literal `true`. Public
diffs contain only the typed layer/entity evidence above, never engine objects
or arbitrary `unknown` values.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test packages/contracts/tests/edit-contracts.test.ts`

Expected: FAIL because edit contracts are absent.

- [ ] **Step 3: Implement DTOs and `parseCadEditBatch(value)`**

Use strict Zod discriminated unions and export types inferred from schemas.

- [ ] **Step 4: Run tests and contracts typecheck**

Run: `node --import tsx --test packages/contracts/tests/edit-contracts.test.ts && npx tsc -p packages/contracts/tsconfig.json --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/contracts/src/edit.ts packages/contracts/src/index.ts packages/contracts/tests/edit-contracts.test.ts
git commit -m "feat: define deterministic CAD edit commands"
```

### Task 2: Implement Command Application and Diff

**Files:**
- Create: `modules/cad-edit/package.json`
- Create: `modules/cad-edit/tsconfig.json`
- Create: `modules/cad-edit/README.md`
- Create: `modules/cad-edit/src/index.ts`
- Create: `modules/cad-edit/src/applyBatch.ts`
- Create: `modules/cad-edit/src/commandHandlers.ts`
- Create: `modules/cad-edit/src/diff.ts`
- Create: `modules/cad-edit/src/errors.ts`
- Create: `modules/cad-edit/tests/apply-batch.test.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Consumes: `CadDocumentSnapshot`, `CadEditBatch`.
- Produces:

```ts
interface CadEditPreview {
  transactionId: string;
  baseRevision: number;
  nextRevision: number;
  changes: CadChange[];
  resolvedCommands: CadResolvedCommand[];
  warnings: string[];
  snapshot: CadDocumentSnapshot;
}
function previewEditBatch(snapshot: CadDocumentSnapshot, batch: CadEditBatch): CadEditPreview;
```

- [ ] **Step 1: Write failing command tests**

Cover layer create/update, TEXT/MTEXT replace, LINE/CIRCLE/ARC/LWPOLYLINE
move/copy/delete, duplicate target rejection, unsupported type rejection,
revision conflict, and rollback when command 2 of 3 fails.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-edit/tests/apply-batch.test.ts`

Expected: FAIL because `previewEditBatch` is absent.

- [ ] **Step 3: Implement handlers against a cloned snapshot**

Translate supported geometry coordinates by the exact delta. Copy commands
set `handle: null`, generate stable temporary IDs
`copy:<transactionId>:<commandId>:<entityIndex>`, and leave final CAD
handles to the writer.

- [ ] **Step 4: Run focused tests**

Run: `node --import tsx --test modules/cad-edit/tests/apply-batch.test.ts`

Expected: PASS; failed transactions leave the input snapshot deeply equal to
its pre-run value.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-edit/package.json modules/cad-edit/tsconfig.json modules/cad-edit/README.md modules/cad-edit/src/index.ts modules/cad-edit/src/applyBatch.ts modules/cad-edit/src/commandHandlers.ts modules/cad-edit/src/diff.ts modules/cad-edit/src/errors.ts modules/cad-edit/tests/apply-batch.test.ts package.json package-lock.json tsconfig.json
git commit -m "feat: preview atomic CAD edit batches"
```

### Task 3: Add Transaction History, Undo, and Redo

**Files:**
- Create: `modules/cad-edit/src/history.ts`
- Create: `modules/cad-edit/tests/history.test.ts`
- Modify: `modules/cad-edit/src/index.ts`
- Modify: `package.json`

**Interfaces:**
- Produces:

```ts
interface CadEditHistory {
  current(): CadDocumentSnapshot;
  preview(batch: CadEditBatch): CadEditPreview;
  apply(preview: CadEditPreview): CadDocumentSnapshot;
  undo(expectedRevision: number): CadDocumentSnapshot;
  redo(expectedRevision: number): CadDocumentSnapshot;
  entries(): readonly CadHistoryEntry[];
  getCommittedTransaction(transactionId: string): CadCommittedTransaction | null;
  getSaveState(documentId: string, expectedRevision: number): CadSaveState | null;
}
interface CadHistoryEntry {
  transactionId: string;
  batch: CadEditBatch;
  beforeRevision: number;
  afterRevision: number;
  changeCount: number;
}
interface CadCommittedTransaction {
  status: "applied" | "undone" | "superseded";
  batch: CadEditBatch;
  before: CadDocumentSnapshot;
  after: CadDocumentSnapshot;
  resolvedCommands: CadResolvedCommand[];
  changes: CadChange[];
}
interface CadCommittedTransactionStore {
  getCommittedTransaction(transactionId: string): CadCommittedTransaction | null;
  getSaveState(documentId: string, expectedRevision: number): CadSaveState | null;
}
interface CadSaveState {
  documentId: string;
  revision: number;
  source: CadDocumentSnapshot;
  current: CadDocumentSnapshot;
  lineage: readonly CadCommittedTransaction[];
}
function createCadEditHistory(initial: CadDocumentSnapshot, limit?: number): CadEditHistory;
```

- [ ] **Step 1: Write history tests**

Assert preview does not change state, apply increments revision once, undo and
redo each create a new monotonic revision, stale revisions fail, a new apply
after undo clears redo, and the default UI history retains 100 transactions.
Assert `getSaveState` returns a contiguous active lineage from revision 0 to
the requested current revision, excludes undone/superseded branches, and
returns null for stale or incomplete lineage.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-edit/tests/history.test.ts`

Expected: FAIL because history is absent.

- [ ] **Step 3: Implement immutable bounded history**

Store before/after snapshots per entry. Never decrement revision; undo and redo
restore document content while assigning `current.revision + 1`.
`getCommittedTransaction` and `getSaveState` return defensive clones. Keep the
UI history window at 100 entries while retaining a separate active command
lineage capped at 10,000 commands; reject further edits with
`EDIT_LINEAGE_LIMIT_REACHED` rather than losing Save As reproducibility.

- [ ] **Step 4: Add and run the edit script**

Add:

```json
"test:edit": "node --import tsx --test \"modules/cad-edit/**/*.test.ts\""
```

Run: `npm run test:edit`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-edit/src/history.ts modules/cad-edit/tests/history.test.ts modules/cad-edit/src/index.ts package.json
git commit -m "feat: add CAD edit undo and redo"
```

### Task 4: Expose Preview, Apply, Undo, and Redo Capabilities

**Files:**
- Create: `modules/cad-capabilities/src/editCapabilities.ts`
- Create: `modules/cad-capabilities/tests/edit-capabilities.test.ts`
- Modify: `modules/cad-capabilities/package.json`
- Modify: `package-lock.json`
- Modify: `modules/cad-capabilities/src/index.ts`
- Modify: `modules/cad-capabilities/src/contracts.ts`

**Interfaces:**
- Adds:

```text
edit.preview
edit.apply
edit.undo
edit.redo
```

`edit.preview` returns a server-owned `previewId`, bounded change summary, and
warnings. `edit.apply` accepts only that preview ID and matching revision.

```ts
interface CadEditCapabilityComposition {
  module: CadCapabilityModule;
  transactions: CadCommittedTransactionStore;
}
function createEditCapabilityComposition(
  history: CadEditHistory,
): CadEditCapabilityComposition;
```

- [ ] **Step 1: Write capability authorization and lifecycle tests**

Test unknown preview, reused preview, stale revision, rejected preview,
successful apply, undo, redo, and cross-document preview denial. Prove the
exported `transactions` store observes the exact apply/undo/redo operations
performed through the paired `runtime`; creating a second hidden history is
forbidden.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-capabilities/tests/edit-capabilities.test.ts`

Expected: FAIL because editing capabilities are absent.

- [ ] **Step 3: Implement an in-memory preview store**

Use random UUIDs, a 10-minute expiration, single use on apply, and a maximum of
20 previews per document. Do not include full before/after documents in API
responses. Declare `@dwg/cad-edit` in
`modules/cad-capabilities/package.json`, run `npm install --package-lock-only`,
and consume only its public entrypoint.

- [ ] **Step 4: Run edit and full verification**

Run: `npm run test:edit && npm run verify:all`

Expected: PASS with no CAD output files created.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-capabilities/src/editCapabilities.ts modules/cad-capabilities/tests/edit-capabilities.test.ts modules/cad-capabilities/package.json modules/cad-capabilities/src/index.ts modules/cad-capabilities/src/contracts.ts package-lock.json
git commit -m "feat: expose reviewed CAD edit capabilities"
```

### Task 5: Add Edit HTTP Endpoints Before the Workspace UI

**Files:**
- Modify: `modules/cad-runtime/src/http/gateway.ts`
- Create: `modules/cad-runtime/src/http/editGateway.ts`
- Create: `modules/cad-runtime/src/application/createCadApplication.ts`
- Modify: `modules/cad-runtime/src/mcp/stdio.ts`
- Create: `modules/cad-runtime/tests/http/edit-gateway.test.ts`
- Create: `modules/cad-runtime/tests/application/cad-application-composition.test.ts`
- Modify: `packages/contracts/src/edit.ts`

**Interfaces:**
- Adds loopback routes:

```text
POST /api/edit/preview
POST /api/edit/apply
POST /api/edit/undo
POST /api/edit/redo
```

Requests and responses use `CadEditBatch`, `CadEditPreviewResponse`,
`CadEditApplyResponse`, `CadEditPreviewRequest`, `CadEditApplyRequest`, and
`CadEditHistoryRequest` from `@dwg/contracts`. The gateway forwards one
`AbortSignal` into `CadCapabilityRuntime.execute`.

- [ ] **Step 1: Write gateway contract tests**

Test malformed batch, preview success, apply success, reused preview, stale
revision, undo, redo, oversized body, cancellation, and response validation.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-runtime/tests/http/edit-gateway.test.ts`

Expected: FAIL because edit routes are absent.

- [ ] **Step 3: Implement typed loopback handlers**

Set a 1 MiB request ceiling. Return bounded structured error codes and never
serialize document snapshots, command before-state, or provider content.
In `gateway.ts`, compose the existing read/query module with the one
`CadEditCapabilityComposition.module`; pass the resulting single runtime to
read, edit, MCP, and later skill adapters. Retain the paired
`transactions` store for later Save/report injection.
Own that wiring in `createCadApplication.ts`, returning
`{ capabilities, transactions }`. Both `gateway.ts` and `mcp/stdio.ts` call
this root-owned factory with their process configuration; neither constructs a
legacy CAD tool runtime directly. The composition test starts both adapters
with injected fakes and proves they expose the same capability-name set and
forward cancellation.

- [ ] **Step 4: Run HTTP, edit, and full suites**

Run: `node --import tsx --test modules/cad-runtime/tests/http/edit-gateway.test.ts modules/cad-runtime/tests/application/cad-application-composition.test.ts && npm run test:edit && npm run verify:all`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-runtime/src/http/gateway.ts modules/cad-runtime/src/http/editGateway.ts modules/cad-runtime/src/application/createCadApplication.ts modules/cad-runtime/src/mcp/stdio.ts modules/cad-runtime/tests/http/edit-gateway.test.ts modules/cad-runtime/tests/application/cad-application-composition.test.ts packages/contracts/src/edit.ts
git commit -m "feat: expose loopback CAD edit review"
```

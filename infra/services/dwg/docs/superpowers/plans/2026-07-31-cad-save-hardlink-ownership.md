# CAD Save Hard-Link Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject every observed unowned hard-link alias, neutralize the owned inode on failure, and make source and output hashing promptly abortable without leaking file descriptors.

**Architecture:** The save coordinator owns a temporary output only while its inode has exactly one link, observes the atomic publication transition `1 -> 2`, removes the temporary alias, and commits only after observing `2 -> 1`. The retained read/write descriptor is the authority used to neutralize bytes on every post-open failure; unknown alias paths are never removed. Both path and handle hashing use bounded asynchronous chunks and the request `AbortSignal`.

**Tech Stack:** TypeScript, Node.js filesystem APIs, `node:test`, ACadSharp round-trip integration.

## Global Constraints

- Preserve DWG/DXF sources as read-only.
- Do not delete unknown hard-link aliases; truncate and flush only through the owned descriptor.
- Return `CAD_SAVE_CLEANUP_FAILED` when any alias remains after owned-path cleanup.
- Run Node and .NET suites sequentially on Windows.
- Commit only scoped files; do not merge or push.

---

### Task 1: Hard-link ownership state machine

**Files:**
- Modify: `modules/cad-capabilities/tests/save-coordinator.test.ts`
- Modify: `modules/cad-capabilities/src/saveCoordinator.ts`

**Interfaces:**
- Consumes: `CadSaveFileIdentity.nlink`, `CadSaveReadHandle.identity()`, `CadSaveReadHandle.sanitize()`
- Produces: enforced link-count transitions `1 -> 2 -> 1`

- [x] **Step 1: Write failing real-filesystem tests**

Add tests that create an external hard link during writer return, after output hashing, and after publication. Each test asserts rejection, no stored verification, zero bytes through the unknown alias, and that the alias itself still exists. Keep the existing normal save test as the success case.

- [x] **Step 2: Run tests to verify RED**

Run:

```powershell
node --import tsx --test modules/cad-capabilities/tests/save-coordinator.test.ts
```

Expected: external-alias cases either pass incorrectly, leave bytes, or return a non-cleanup error.

- [x] **Step 3: Implement the ownership checks**

Require both initial path and handle identities to have `nlink === "1"`. Revalidate that exact count before publication. Require the atomic link result to have exactly two links, observe two links immediately before known temporary-path cleanup, and require exactly one link afterward and at final commit.

On any failure after opening the temporary output, call `temporaryHandle.sanitize()` before cleaning known paths. Count only proven quarantined known aliases; if the retained descriptor reports any remaining link beyond those aliases, override the original error with `CAD_SAVE_CLEANUP_FAILED`.

- [x] **Step 4: Run tests to verify GREEN**

Run the focused command from Step 2 and require zero failures.

### Task 2: Abortable path and handle hashing

**Files:**
- Modify: `modules/cad-capabilities/src/contracts.ts`
- Modify: `modules/cad-capabilities/src/saveCoordinator.ts`
- Modify: `modules/cad-capabilities/tests/save-coordinator.test.ts`

**Interfaces:**
- Produces: `CadSaveFileSystem.sha256(path: string, signal?: AbortSignal): Promise<string>`
- Preserves: `CadSaveReadHandle.sha256(signal?: AbortSignal): Promise<string>`

- [x] **Step 1: Write failing cancellation tests**

Add a pre-aborted path-hash test and 64 MiB source tests that abort during the initial and prepublication hashes. Assert `AbortError`, bounded completion, no writer for the initial phase, no final file for the later phase, and successful source rename afterward as the descriptor-close probe.

- [x] **Step 2: Run tests to verify RED**

Run:

```powershell
node --import tsx --test modules/cad-capabilities/tests/save-coordinator.test.ts
```

Expected: the path-hash signature does not accept the signal or the real hash ignores mid-read cancellation.

- [x] **Step 3: Implement bounded cancellation**

Check the signal before opening, immediately after opening, before and after each 64 KiB read, and before returning the digest. Close the path descriptor in `finally`. Pass the same request signal to every coordinator source and output hash.

- [x] **Step 4: Run tests to verify GREEN**

Run the focused command from Step 2 and require zero failures.

### Task 3: Failure probes, documentation, and final verification

**Files:**
- Modify: `modules/cad-capabilities/tests/save-coordinator.test.ts`
- Modify: `modules/cad-capabilities/README.md`

**Interfaces:**
- Verifies: sanitize failure still attempts descriptor close; close failure is reported as cleanup failure
- Documents: hard-link ownership and cancellation assumptions

- [x] **Step 1: Add sanitize and close failure probes**

Wrap the real read handle with deterministic `sanitize()` and `close()` failures. Trigger a post-open failure and assert `CAD_SAVE_CLEANUP_FAILED`, no passed verification, and that close is attempted even when sanitize fails.

- [x] **Step 2: Update the threat model**

Document the exact link-count state machine, unknown-alias neutralization behavior, bounded asynchronous hash cancellation points, and the remaining native-syscall race limit.

- [x] **Step 3: Run complete verification**

Run sequentially:

```powershell
node --import tsx --test modules/cad-capabilities/tests/save-coordinator.test.ts tests/roundtrip/dxf-roundtrip.test.ts
npm run verify
node --import tsx --test modules/cad-runtime/tests/architecture/module-boundaries.test.ts scripts/package-dependencies.test.mjs
npm run test:fixtures
npm audit --audit-level=high
git diff --check
```

- [x] **Step 4: Commit the scoped change**

Stage only the coordinator contracts, implementation, tests, README, and this plan. Create a new commit without amending, merging, or pushing.

# Runtime and DWG Ownership Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave `agents/` with only the PLANM product agent while moving GitAgent to `infra/runtimes/gitagent` and DWG to `infra/services/dwg` without changing behavior.

**Architecture:** Preserve PLANM, GitAgent, Backend, and DWG process boundaries; only filesystem ownership and path consumers change. Backend continues to own approval and invoke the independent DWG service. Git history records tracked moves, while ignored dependencies/build outputs are rebuilt at the new paths.

**Tech Stack:** PowerShell, Git, Node.js/TypeScript, Python/FastAPI/Pytest, Vite/Playwright, .NET 9, Docker Compose

**Spec:** `docs/superpowers/specs/2026-09-01-runtime-and-dwg-ownership-layout-design.md`

## Global Constraints

- `agents/` contains exactly one direct product child: `planm/`.
- GitAgent lives at `infra/runtimes/gitagent`; DWG lives at `infra/services/dwg`.
- PLANM and Backend do not import DWG internals; Backend invokes DWG through the existing process adapter.
- No validation gate, workflow order, state ownership, or public contract changes.
- Do not bulk-format unrelated files or rewrite completed historical plans/specifications.
- Use recoverable moves for ignored old-path remnants after verifying Git tracks nothing below them.

---

### Task 1: Lock the New Ownership Boundary with a Failing Structure Test

**Files:**
- Modify: `infra/dev/structure.test.mjs`
- Test: `infra/dev/structure.test.mjs`

**Interfaces:**
- Consumes: repository-root filesystem paths.
- Produces: an executable ownership gate used by `npm run test:dev`.

- [ ] **Step 1: Change the ownership test before moving source**

Replace the expected old roots with:

```js
for (const path of [
  "frontend",
  "backend/app",
  "agents/planm",
  "infra/runtimes/gitagent",
  "infra/services/dwg",
  "infra/dev",
]) {
  assert.equal(await exists(resolve(repositoryRoot, path)), true, `${path} must exist`);
}
for (const path of ["agent", "agents/runtimes", "agents/dwg"]) {
  assert.equal(await exists(resolve(repositoryRoot, path)), false, `${path} must not exist`);
}
```

- [ ] **Step 2: Run the structure test and verify RED**

Run: `node --test infra/dev/structure.test.mjs`

Expected: FAIL because `infra/runtimes/gitagent` and `infra/services/dwg` do not exist yet. This catches a migration that leaves runtime/service code classified as agents.

---

### Task 2: Move GitAgent and Update Runtime Consumers

**Files:**
- Move: `agents/runtimes/gitagent/**` -> `infra/runtimes/gitagent/**`
- Modify: `package.json`
- Modify: `backend/app/adapters/planm_agent.py`
- Modify: `agents/planm/tests/planm-skills.test.ts`
- Modify: `agents/planm/tests/planm-workflow.test.ts`
- Modify: `agents/planm/tests/runtime-boundary.test.ts`
- Modify: `infra/docker/backend.Dockerfile`
- Modify: active root/architecture/integration guidance listed in Task 4

**Interfaces:**
- Consumes: `PLANM_GITAGENT_RUNTIME_ENTRY` and GitAgent public `dist/exports.js`.
- Produces: the same runtime exports at `infra/runtimes/gitagent/dist/exports.js`.

- [ ] **Step 1: Verify exact source and destination paths**

Run:

```powershell
$repo = (Resolve-Path '.').Path
$source = (Resolve-Path 'agents/runtimes/gitagent').Path
$destination = Join-Path $repo 'infra/runtimes/gitagent'
if (-not $source.StartsWith($repo + [IO.Path]::DirectorySeparatorChar)) { throw 'unsafe source' }
if (Test-Path -LiteralPath $destination) { throw 'destination exists' }
```

- [ ] **Step 2: Move the tracked/runtime tree**

Create `infra/runtimes` if absent and move the exact `gitagent` directory with PowerShell `Move-Item`. Do not copy or delete.

- [ ] **Step 3: Update runtime path consumers**

Use these exact new paths:

```text
npm --prefix infra/runtimes/gitagent run build
repository_root / "infra" / "runtimes" / "gitagent" / "dist" / "exports.js"
../../../infra/runtimes/gitagent/src/   # from agents/planm/tests
```

Update the Backend Docker build/install/check commands to the same root.

- [ ] **Step 4: Reinstall and build ignored runtime outputs**

Run:

```powershell
npm --prefix infra/runtimes/gitagent ci
npm --prefix infra/runtimes/gitagent run build
Test-Path -LiteralPath 'infra/runtimes/gitagent/dist/exports.js'
```

Expected: install/build exit 0 and the final expression returns `True`.

---

### Task 3: Move DWG and Update Service Consumers

**Files:**
- Move: `agents/dwg/**` -> `infra/services/dwg/**`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `infra/dev/runtime.mjs`
- Modify: `infra/dev/runtime.test.mjs`
- Modify: `infra/docker/backend.Dockerfile`
- Modify: `infra/docker/dwg.Dockerfile`
- Modify: `infra/docker/frontend.Dockerfile`
- Modify: `infra/e2e/product.config.cjs`

**Interfaces:**
- Consumes: DWG gateway commands, `@click-around/workspace`, and `@dwg/contracts`.
- Produces: unchanged packages and service commands rooted at `infra/services/dwg`.

- [ ] **Step 1: Verify exact source and destination paths**

Resolve `agents/dwg` beneath the repository and assert that `infra/services/dwg` does not exist.

- [ ] **Step 2: Move the exact DWG tree**

Create `infra/services` if absent and move `agents/dwg` to `infra/services/dwg` with PowerShell `Move-Item`.

- [ ] **Step 3: Update runtime, Docker, E2E, and frontend dependency paths**

Use `infra/services/dwg` for root commands and Docker copies. From `frontend/package.json`, use:

```json
"@click-around/workspace": "file:../infra/services/dwg/apps/workspace",
"@dwg/contracts": "file:../infra/services/dwg/packages/contracts"
```

- [ ] **Step 4: Regenerate local dependency state from lockfiles**

Run:

```powershell
npm --prefix infra/services/dwg ci
npm --prefix frontend install --package-lock-only
npm --prefix frontend ci
```

Expected: exit 0; `frontend/package-lock.json` resolves both local packages through `../infra/services/dwg`.

- [ ] **Step 5: Run the ownership test and verify GREEN**

Run: `node --test infra/dev/structure.test.mjs`

Expected: both tests pass, including absence of `agents/runtimes` and `agents/dwg`.

---

### Task 4: Reconcile Active Documentation and Scan Retired Paths

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `.remember/remember.md`
- Modify: `docs/architecture/module_map.md`
- Modify: `docs/architecture/repository_layout.md`
- Modify: `docs/integrations/deployment.md`
- Modify: `docs/integrations/dwg-intelligence.md`
- Modify: `docs/integrations/gitagent-runtime.md`
- Preserve as historical: `docs/superpowers/plans/**`, `docs/superpowers/specs/**`

**Interfaces:**
- Consumes: target ownership model from the approved spec.
- Produces: current operator/developer guidance with no retired active paths.

- [ ] **Step 1: Update current guidance**

Describe exactly one agent (`agents/planm`), one generic runtime (`infra/runtimes/gitagent`), and one independent CAD service (`infra/services/dwg`). Update all executable examples.

- [ ] **Step 2: Scan active code and guidance for retired paths**

Run:

```powershell
git grep -n -I -E 'agents/runtimes/gitagent|agents/dwg' -- backend agents frontend infra package.json README.md CLAUDE.md docs/architecture docs/integrations .remember/remember.md
```

Expected: no output. Historical plans/specs are excluded intentionally.

- [ ] **Step 3: Check Git recognizes moves and no source was lost**

Run tracked counts for old/new roots. Expected: old roots `0`; new GitAgent count `94`; new DWG count `458` before any intentional tracked edits change counts.

---

### Task 5: Run Full Verification and Create the Implementation Commit

**Files:**
- Verify: all changed files and moved trees

**Interfaces:**
- Consumes: all new ownership paths.
- Produces: one reviewed migration commit and retained test evidence in command output.

- [ ] **Step 1: Run fast gates**

```powershell
git diff --check
python -m ruff check backend
npm run test:dev
npm run test:agent
npm --prefix frontend run build
npm --prefix frontend run test:boundaries
docker compose config --quiet
```

Expected: every command exits 0.

- [ ] **Step 2: Run product and module suites**

```powershell
python -m pytest -q
npm run test:frontend
npm run test:product
npm --prefix infra/services/dwg run verify:all
```

Expected current baselines: Python `937 passed, 2 skipped`; frontend `24/24`; product `1/1`; DWG Playwright `63/63`, with all enclosing DWG verification steps passing.

- [ ] **Step 3: Inspect final tree and ignored remnants**

Confirm `agents` has only `planm`. Confirm retired tracked roots are empty. If ignored remnants exist at either retired root, verify their resolved paths and move them recoverably under `C:\DK\PLAN-local-archive-20260901\ownership-migration-generated-<timestamp>`.

- [ ] **Step 4: Commit the migration**

```powershell
git add --all
git diff --cached --check
git commit -m "refactor: separate agent runtime and DWG service ownership"
```

- [ ] **Step 5: Verify post-commit state**

Run `git status --short --branch`, `git log -1 --oneline`, the structure test, and retired-path scan again. Expected: clean worktree, migration commit at HEAD, structure `2/2`, and no retired active references.

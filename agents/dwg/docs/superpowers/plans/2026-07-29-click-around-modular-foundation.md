# Click Around Modular Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the proven DWG workspace, CAD runtime, and .NET parser into explicit top-level modules with one npm lockfile, stable fixture paths, and enforceable dependency boundaries while preserving all current behavior.

**Architecture:** This is the first independently releasable sub-project from the Click Around Desktop design. Existing subtrees move intact before internal domain extraction; repository-relative paths are resolved from module locations rather than the process working directory, and composition scripts remain available from the repository root.

**Tech Stack:** Node.js 24, TypeScript 5.8, npm workspaces, React 19, Vite 8, Playwright 1.62, .NET 8-compatible SDK, xUnit, ACadSharp 3.6.35

## Global Constraints

- Product name is `Click Around`; the internal CAD engine name remains `DWG Intelligence`.
- Preserve `cad-index/v0.2`, legacy DXF compatibility, the eight read-only MCP tools, loopback `/api`, and current provider session contracts.
- Preserve the real DWG source SHA-256 `B60B4A7242E43B34CA35561B105B2DDA30F2E373602AB5A12900EBC25B1E499B`.
- Preserve the DXF fixture SHA-256 `86BE7BBDF2CA52E4343F0914E2986229229A2DB90DB9350453F7FC21C17B97B6`.
- Do not add Electron, SQLite, domain extraction, cloud code, or provider behavior changes in this plan.
- Do not modify fixture bytes or regenerate tracked visual baselines as a side effect of moving files.
- Use one root `package-lock.json`; delete the nested workspace lockfile only after the root lock resolves every workspace dependency.
- Use `git mv` for existing subtrees and keep moves separate from behavior edits.
- Root commands remain stable: `verify`, `verify:all`, `test:dotnet`, `test:e2e`, `capture:docs`, `mcp`, `gateway`, and `providers:smoke`.
- Run Node and .NET parser tests sequentially to avoid Windows `CS2012` file locking.
- Normal and documentation Playwright servers use isolated current-checkout processes with `reuseExistingServer: false`.
- Generated screenshots and traces go under ignored test-result directories; tracked baselines change only through an explicit visual-baseline review.

---

## Locked file structure

This plan produces:

```text
apps/
  workspace/
    package.json
    index.html
    public/
    scripts/
    src/
    tests/
    playwright.config.ts
    playwright.docs.config.ts
    playwright.live.config.ts
    tsconfig.json
    vite.config.ts
modules/
  cad-runtime/
    contracts/
    harness/
    skills/
    src/
    tests/
  dwg-parser/
    src/
    tests/
packages/
  contracts/
tests/
  fixtures/
    manifest.json
    dwg/
    dxf/
  harness/
    scenarios/
  visual/
docs/
scripts/
package.json
package-lock.json
tsconfig.json
```

Ownership after this plan:

- `apps/workspace`: browser UI, browser state, Playwright browser tests, and documentation captures.
- `modules/cad-runtime`: TypeScript CAD query runtime, parser adapters, provider CLI adapters, gateways, MCP, and their tests.
- `modules/dwg-parser`: .NET DWG executable and xUnit tests.
- `packages/contracts`: stable CAD, inspection, and provider DTOs only.
- `tests/fixtures`: immutable cross-module CAD inputs and their hashes.
- `tests/harness/scenarios`: product-neutral deterministic CAD scenarios.
- root scripts: composition and verification only.

---

### Task 1: Freeze the migration baseline

**Files:**
- Create: `tests/fixtures/manifest.json`
- Create: `scripts/verify-fixture-hashes.mjs`
- Create: `scripts/verify-fixture-hashes.test.mjs`
- Modify: `package.json`
- Modify: `.gitignore`
- Modify: `.gitattributes`

**Interfaces:**
- Consumes: the existing DWG and DXF fixture files.
- Produces: `verifyFixtureManifest(manifestPath: string): Promise<void>` and root command `test:fixtures`.

- [ ] **Step 1: Write the failing fixture-integrity test**

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { verifyFixtureManifest } from "./verify-fixture-hashes.mjs";

test("checked-in CAD fixtures match the migration baseline", async () => {
  await assert.doesNotReject(() =>
    verifyFixtureManifest("tests/fixtures/manifest.json")
  );
});
```

- [ ] **Step 2: Run the test and verify the missing verifier failure**

Run:

```powershell
node --test scripts/verify-fixture-hashes.test.mjs
```

Expected: FAIL because `scripts/verify-fixture-hashes.mjs` does not exist.

- [ ] **Step 3: Pin CAD fixture checkout bytes and add the immutable manifest**

Add:

```gitattributes
*.dwg binary
*.dxf binary
```

If an existing Windows checkout was converted to CRLF, restore only the
tracked DXF worktree file from `HEAD` after this attribute is present. Do not
rewrite or regenerate CAD contents.

```json
{
  "version": 1,
  "fixtures": [
    {
      "id": "dwg.export-sample",
      "path": "tests/fixtures/dwg/export_sample.dwg",
      "bytes": 94819,
      "sha256": "b60b4a7242e43b34ca35561b105b2dda30f2e373602ab5a12900ebc25b1e499b"
    },
    {
      "id": "dxf.minimal-architectural",
      "path": "agent/fixtures/minimal-architectural.dxf",
      "bytes": 512,
      "sha256": "86be7bbdf2ca52e4343f0914e2986229229a2db90db9350453f7fc21c17b97b6"
    }
  ]
}
```

- [ ] **Step 4: Implement the manifest verifier**

```js
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

export async function verifyFixtureManifest(manifestPath) {
  const manifest = JSON.parse(
    await readFile(resolve(repositoryRoot, manifestPath), "utf8")
  );
  for (const fixture of manifest.fixtures) {
    const bytes = await readFile(resolve(repositoryRoot, fixture.path));
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    if (bytes.byteLength !== fixture.bytes || sha256 !== fixture.sha256) {
      throw new Error(`Fixture integrity mismatch: ${fixture.id}`);
    }
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await verifyFixtureManifest(
    process.argv[2] ?? "tests/fixtures/manifest.json"
  );
}
```

- [ ] **Step 5: Add the root fixture command and ignored diagnostic outputs**

Add to root scripts:

```json
"test:fixtures": "node --test scripts/verify-fixture-hashes.test.mjs"
```

Append `"scripts/**/*.test.mjs"` to the root `test` command so the default
Node gate includes the integrity test.

Ensure `.gitignore` contains:

```gitignore
tests/visual/test-results/
test-results/
playwright-report/
```

- [ ] **Step 6: Prove fixture integrity and capture the pre-move gate**

Run sequentially:

```powershell
npm run test:fixtures
npm test
npm run test:dotnet
npm run build:frontend
npm run test:e2e
git diff --check
```

Expected: fixture verifier PASS; Node 72/72; .NET 9/9; frontend build PASS;
Playwright 33/33; no whitespace errors. If totals have legitimately increased
on the current branch, record the higher totals in the commit message body and
do not lower coverage to match these numbers.

- [ ] **Step 7: Commit the baseline guard**

```powershell
git add .gitignore package.json scripts/verify-fixture-hashes.mjs scripts/verify-fixture-hashes.test.mjs tests/fixtures/manifest.json
git commit -m "test: freeze CAD fixture baseline"
```

---

### Task 2: Establish one npm workspace lockfile

**Files:**
- Modify: `package.json`
- Modify: `frontend/package.json`
- Modify: `package-lock.json`
- Delete: `frontend/package-lock.json`

**Interfaces:**
- Consumes: current root, frontend, and contracts package manifests.
- Produces: npm workspaces named `@click-around/workspace` and `@dwg/contracts`, resolved by one root lockfile.

- [ ] **Step 1: Add a failing workspace-layout assertion**

Add to `agent/tests/architecture/module-boundaries.test.ts`:

```ts
test("repository uses one root npm lockfile", async () => {
  const root = JSON.parse(await readFile("package.json", "utf8"));
  assert.deepEqual(root.workspaces, ["frontend", "packages/*"]);
  await assert.rejects(() => access("frontend/package-lock.json"));
});
```

Add these imports:

```ts
import { access, readFile } from "node:fs/promises";
```

- [ ] **Step 2: Run the assertion and verify the current two-lock failure**

Run:

```powershell
node --import tsx --test agent/tests/architecture/module-boundaries.test.ts
```

Expected: FAIL because `workspaces` is absent and the nested lockfile exists.

- [ ] **Step 3: Configure the transitional workspaces**

Set the root package identity and workspace list:

```json
{
  "name": "click-around",
  "private": true,
  "workspaces": [
    "frontend",
    "packages/*"
  ]
}
```

Rename the frontend package:

```json
{
  "name": "@click-around/workspace",
  "private": true
}
```

Keep `@dwg/contracts` as the contracts package name. Replace the frontend
contract dependency with:

```json
"@dwg/contracts": "0.1.0"
```

npm resolves the matching private `@dwg/contracts@0.1.0` workspace locally and
symlinks it during installation.

- [ ] **Step 4: Rebuild the single root lock**

Run:

```powershell
Remove-Item -LiteralPath frontend/package-lock.json
npm install
npm ls --workspaces --depth=0
```

Expected: one root `package-lock.json`; both workspaces resolve; exit code 0.
The explicit nested lockfile removal is safe here because it is tracked,
recreated in root form by `npm install`, and this task has a clean pre-task
commit.

- [ ] **Step 5: Run workspace and compatibility commands**

Run:

```powershell
npm run test:fixtures
npm test
npm run test:dotnet
npm run build:frontend
npm run test:e2e
git diff --check
```

Expected: every command remains green with the existing root command names.

- [ ] **Step 6: Commit the workspace lock migration**

```powershell
git add package.json package-lock.json frontend/package.json frontend/package-lock.json agent/tests/architecture/module-boundaries.test.ts
git commit -m "build: use one npm workspace lock"
```

---

### Task 3: Move existing subtrees intact

**Files:**
- Move: `frontend` to `apps/workspace`
- Move: `agent` to `modules/cad-runtime`
- Move: `backend` to `modules/dwg-parser`
- Modify: `package.json`
- Modify: `tsconfig.json`
- Modify: `apps/workspace/package.json`
- Modify: `apps/workspace/tsconfig.json`

**Interfaces:**
- Consumes: the transitional npm workspace and every existing root command.
- Produces: stable coarse module roots without internal code reshaping.

- [ ] **Step 1: Update the structure assertion before moving files**

Replace the transitional workspace assertion with:

```ts
test("repository exposes explicit application and module roots", async () => {
  const root = JSON.parse(await readFile("package.json", "utf8"));
  assert.deepEqual(root.workspaces, ["apps/*", "packages/*"]);
  await access("apps/workspace/package.json");
  await access("modules/cad-runtime/src");
  await access("modules/dwg-parser/src");
  await assert.rejects(() => access("frontend"));
  await assert.rejects(() => access("agent"));
  await assert.rejects(() => access("backend"));
});
```

- [ ] **Step 2: Run the structure test and verify it fails on old roots**

Run:

```powershell
node --import tsx --test agent/tests/architecture/module-boundaries.test.ts
```

Expected: FAIL because `apps/workspace` and `modules/*` do not exist.

- [ ] **Step 3: Move only the three whole subtrees**

Run:

```powershell
New-Item -ItemType Directory -Path apps -Force | Out-Null
New-Item -ItemType Directory -Path modules -Force | Out-Null
git mv frontend apps/workspace
git mv agent modules/cad-runtime
git mv backend modules/dwg-parser
```

Do not rename or split files inside those subtrees in this step.

- [ ] **Step 4: Update root composition scripts mechanically**

Use these exact path replacements in `package.json`:

```text
backend/  -> modules/dwg-parser/
frontend  -> apps/workspace
agent/    -> modules/cad-runtime/
```

The resulting entry commands must be:

```json
"build:parser": "dotnet build modules/dwg-parser/src/DwgIntelligence.DwgParser/DwgIntelligence.DwgParser.csproj --nologo",
"build:frontend": "npm --workspace @click-around/workspace run build",
"test": "node --import tsx --test \"modules/cad-runtime/**/*.test.ts\" \"apps/workspace/tests/unit/**/*.test.ts\"",
"test:dotnet": "dotnet test modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo",
"test:e2e": "npm --workspace @click-around/workspace run test:e2e --",
"capture:docs": "npm --workspace @click-around/workspace run capture:docs --",
"harness": "tsx modules/cad-runtime/harness/run-case.ts",
"mcp": "tsx modules/cad-runtime/src/mcp/stdio.ts",
"gateway": "tsx modules/cad-runtime/src/http/gateway.ts",
"providers:smoke": "tsx modules/cad-runtime/harness/provider-smoke.ts"
```

Set root workspaces to:

```json
"workspaces": ["apps/*", "packages/*"]
```

- [ ] **Step 5: Update TypeScript project roots**

Set root `tsconfig.json` include:

```json
"include": [
  "modules/cad-runtime/**/*.ts",
  "scripts/**/*.mjs"
]
```

In `apps/workspace/tsconfig.json`, keep the current compiler options and include
all three Playwright configs:

```json
"include": [
  "src",
  "vite.config.ts",
  "playwright.config.ts",
  "playwright.docs.config.ts",
  "playwright.live.config.ts"
]
```

- [ ] **Step 6: Repair workspace dependency paths and root lock**

Keep the workspace dependency:

```json
"@dwg/contracts": "0.1.0"
```

Run:

```powershell
npm install
npm ls --workspaces --depth=0
```

Expected: `@click-around/workspace` and `@dwg/contracts` resolve from their new
locations with one root lockfile.

- [ ] **Step 7: Run the smallest move-sensitive checks**

Run:

```powershell
npm run test:fixtures
node --import tsx --test --test-name-pattern "repository exposes explicit application" modules/cad-runtime/tests/architecture/module-boundaries.test.ts
npm run build:parser
npm run build:frontend
```

Expected: structure test PASS and both builds locate their moved sources.
Other path-sensitive tests may still fail until Tasks 4 and 5.

- [ ] **Step 8: Commit the pure subtree move**

```powershell
git add package.json package-lock.json tsconfig.json apps modules
git commit -m "refactor: establish app and engine modules"
```

---

### Task 4: Remove repository current-working-directory assumptions

**Files:**
- Create: `modules/cad-runtime/src/platform/repositoryPaths.ts`
- Create: `modules/cad-runtime/tests/platform/repository-paths.test.ts`
- Modify: `modules/cad-runtime/src/parsers/dwg/acadSharpIndexer.ts`
- Modify: `modules/cad-runtime/src/http/gateway.ts`
- Modify: `modules/cad-runtime/src/mcp/stdio.ts`
- Modify: `modules/cad-runtime/harness/provider-smoke.ts`
- Modify: `modules/cad-runtime/src/architecture/moduleBoundaryChecker.ts`
- Modify: `modules/cad-runtime/tests/architecture/module-boundaries.test.ts`
- Modify: `modules/cad-runtime/tests/contracts/cad-index-contract.test.ts`
- Modify: `modules/cad-runtime/harness/harness.test.ts`
- Modify: `modules/cad-runtime/harness/run-case.ts`
- Modify: `modules/cad-runtime/harness/cases/*.json`
- Modify: `modules/cad-runtime/tests/integration/dwg-runtime.test.ts`
- Modify: `modules/cad-runtime/tests/integration/mcp-server.test.ts`
- Modify: `modules/cad-runtime/tests/orchestration/orchestrator.test.ts`
- Modify: `apps/workspace/scripts/generate-fixture.mjs`
- Modify: `apps/workspace/playwright.config.ts`
- Modify: `apps/workspace/playwright.docs.config.ts`
- Modify: `apps/workspace/playwright.live.config.ts`

**Interfaces:**
- Consumes: a module URL or explicit root override.
- Produces: `findRepositoryRoot(fromUrl?: string): string` and `createRepositoryPaths(repositoryRoot: string): RepositoryPaths`.

Define:

```ts
export interface RepositoryPaths {
  repositoryRoot: string;
  parserProject: string;
  fixturesRoot: string;
  defaultDrawing: string;
}
```

- [ ] **Step 1: Write path-resolution tests from unrelated working directories**

```ts
import assert from "node:assert/strict";
import { chdir, cwd } from "node:process";
import test from "node:test";

import {
  createRepositoryPaths,
  findRepositoryRoot
} from "../../src/platform/repositoryPaths.js";

test("repository paths do not depend on process.cwd", () => {
  const original = cwd();
  try {
    chdir(process.env.TEMP ?? "C:\\Windows\\Temp");
    const root = findRepositoryRoot(import.meta.url);
    const paths = createRepositoryPaths(root);
    assert.match(paths.parserProject, /modules[\\/]dwg-parser[\\/]src/);
    assert.match(paths.defaultDrawing, /tests[\\/]fixtures[\\/]dwg/);
  } finally {
    chdir(original);
  }
});
```

- [ ] **Step 2: Run the path test and verify the missing module failure**

Run:

```powershell
node --import tsx --test modules/cad-runtime/tests/platform/repository-paths.test.ts
```

Expected: FAIL because `repositoryPaths.ts` does not exist.

- [ ] **Step 3: Implement repository root discovery**

```ts
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export interface RepositoryPaths {
  repositoryRoot: string;
  parserProject: string;
  fixturesRoot: string;
  defaultDrawing: string;
}

export function findRepositoryRoot(fromUrl = import.meta.url): string {
  let cursor = dirname(fileURLToPath(fromUrl));
  while (true) {
    const packagePath = join(cursor, "package.json");
    if (existsSync(packagePath)) {
      const manifest = JSON.parse(readFileSync(packagePath, "utf8"));
      if (manifest.name === "click-around") return cursor;
    }
    const parent = dirname(cursor);
    if (parent === cursor) {
      throw new Error("Click Around repository root was not found");
    }
    cursor = parent;
  }
}

export function createRepositoryPaths(repositoryRoot: string): RepositoryPaths {
  const root = resolve(repositoryRoot);
  return {
    repositoryRoot: root,
    parserProject: resolve(
      root,
      "modules/dwg-parser/src/DwgIntelligence.DwgParser/DwgIntelligence.DwgParser.csproj"
    ),
    fixturesRoot: resolve(root, "tests/fixtures"),
    defaultDrawing: resolve(root, "tests/fixtures/dwg/export_sample.dwg")
  };
}
```

- [ ] **Step 4: Inject the parser project path**

Change `buildIndexFromDwgFile` to accept:

```ts
export interface DwgIndexerOptions {
  parserProject?: string;
}

export async function buildIndexFromDwgFile(
  path: string,
  options: DwgIndexerOptions = {}
): Promise<CadEntityIndexV02>
```

Resolve the default from:

```ts
const defaultParserProject = createRepositoryPaths(
  findRepositoryRoot(import.meta.url)
).parserProject;
```

Pass `options.parserProject ?? defaultParserProject` into `runDwgParser`.
Do not read `process.cwd()` in this adapter.

- [ ] **Step 5: Replace entrypoint defaults with module-derived paths**

In gateway, MCP stdio, and provider smoke composition entrypoints, use:

```ts
const paths = createRepositoryPaths(findRepositoryRoot(import.meta.url));
const workspace = resolve(process.env.DWG_WORKSPACE ?? paths.repositoryRoot);
```

Use `paths.defaultDrawing` only as the default fixture. Preserve explicit
`DWG_WORKSPACE` and `DWG_DRAWING_PATH` overrides.

- [ ] **Step 6: Resolve Playwright commands from their config directory**

In all three Playwright configs:

```ts
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(workspaceRoot, "../..");
```

Set gateway `cwd: repositoryRoot`, workspace `cwd: workspaceRoot`, and output
directories with `resolve(repositoryRoot, "tests/visual/test-results/...")`.
Keep `reuseExistingServer: false` in normal, docs, and live configurations.

- [ ] **Step 7: Make fixture generation independent of cwd**

From `apps/workspace/scripts/generate-fixture.mjs`, compute:

```js
const workspaceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(workspaceRoot, "../..");
const parserProject = resolve(
  repositoryRoot,
  "modules/dwg-parser/src/DwgIntelligence.DwgParser"
);
const source = resolve(
  repositoryRoot,
  "tests/fixtures/dwg/export_sample.dwg"
);
```

Keep the destination inside `apps/workspace/public/data`.

- [ ] **Step 8: Run from repository and unrelated working directories**

Before running the complete Node gate, mechanically replace stale coarse-move
paths so current files are readable:

```text
agent/contracts/ -> modules/cad-runtime/contracts/
agent/fixtures/ -> modules/cad-runtime/fixtures/
agent/harness/cases/ -> modules/cad-runtime/harness/cases/
agent/src -> modules/cad-runtime/src
frontend/src -> apps/workspace/src
```

This step only restores the existing boundary rules and fixture behavior at
their moved locations. Task 5 performs the final fixture/scenario move and
Task 6 adds package-alias and dynamic-import boundary rules.

Run:

```powershell
npm test
node --import tsx --test modules/cad-runtime/tests/platform/repository-paths.test.ts
npm run build:frontend
```

Expected: unit tests PASS; the path test changes to an unrelated temporary
working directory internally and still resolves the repository; frontend build
PASS.

- [ ] **Step 9: Commit path hardening**

```powershell
git add modules/cad-runtime apps/workspace
git commit -m "refactor: resolve runtime paths from modules"
```

---

### Task 5: Consolidate fixtures and deterministic scenarios

**Files:**
- Move: `modules/cad-runtime/fixtures/minimal-architectural.dxf` to `tests/fixtures/dxf/minimal-architectural.dxf`
- Move: `modules/cad-runtime/harness/cases/*.json` to `tests/harness/scenarios/`
- Modify: `tests/fixtures/manifest.json`
- Modify: `modules/cad-runtime/harness/harness.test.ts`
- Modify: `modules/cad-runtime/harness/run-case.ts`
- Modify: `modules/cad-runtime/tests/orchestration/orchestrator.test.ts`
- Modify: `modules/cad-runtime/tests/integration/dwg-runtime.test.ts`
- Modify: `modules/cad-runtime/tests/integration/mcp-server.test.ts`
- Modify: `modules/cad-runtime/tests/integration/mcp-stdio.test.ts`
- Modify: `modules/cad-runtime/tests/providers/provider-gateway.test.ts`
- Modify: `apps/workspace/src/features/agent-chat/useProviderChat.ts`
- Modify: `apps/workspace/tests/unit/workspace-session-store.test.ts`
- Modify: `apps/workspace/tests/e2e/workspace.spec.ts`
- Modify: `modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj`

**Interfaces:**
- Consumes: `RepositoryPaths.fixturesRoot`.
- Produces: fixture IDs `dwg.export-sample` and `dxf.minimal-architectural` from one immutable manifest.

- [ ] **Step 1: Change the manifest to the final DXF path and verify failure**

Set:

```json
"path": "tests/fixtures/dxf/minimal-architectural.dxf"
```

Run:

```powershell
npm run test:fixtures
```

Expected: FAIL because the DXF has not moved.

- [ ] **Step 2: Move fixtures and scenarios with history**

Run:

```powershell
New-Item -ItemType Directory -Path tests/fixtures/dxf -Force | Out-Null
New-Item -ItemType Directory -Path tests/harness/scenarios -Force | Out-Null
git mv modules/cad-runtime/fixtures/minimal-architectural.dxf tests/fixtures/dxf/minimal-architectural.dxf
git mv modules/cad-runtime/harness/cases/find-layer-a-wall.json tests/harness/scenarios/find-layer-a-wall.json
git mv modules/cad-runtime/harness/cases/find-text-room.json tests/harness/scenarios/find-text-room.json
```

- [ ] **Step 3: Replace all fixture string literals**

Use these final repository-relative paths:

```text
tests/fixtures/dwg/export_sample.dwg
tests/fixtures/dxf/minimal-architectural.dxf
tests/harness/scenarios/find-layer-a-wall.json
tests/harness/scenarios/find-text-room.json
```

For runtime code, derive absolute paths through `RepositoryPaths`; serialized
session and contract examples may retain repository-relative strings.

- [ ] **Step 4: Update the .NET linked fixture path**

From the parser test project directory, use:

```xml
<None Include="../../../../tests/fixtures/dwg/export_sample.dwg">
  <Link>Fixtures/export_sample.dwg</Link>
  <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
</None>
```

- [ ] **Step 5: Prove no obsolete fixture roots remain**

Run:

```powershell
rg -n "agent/fixtures|modules/cad-runtime/fixtures|harness/cases|backend/src|frontend/" modules apps tests package.json tsconfig.json
```

Expected: no matches referring to old repository roots. Legitimate prose in
historical design documents is outside this command's scope.

- [ ] **Step 6: Run fixture, parser, harness, and UI gates**

Run sequentially:

```powershell
npm run test:fixtures
npm test
npm run test:dotnet
npm run harness -- tests/harness/scenarios/find-layer-a-wall.json
npm run harness -- tests/harness/scenarios/find-text-room.json
npm run build:frontend
```

Expected: all commands PASS and both fixture hashes remain unchanged.

- [ ] **Step 7: Commit fixture consolidation**

```powershell
git add tests modules apps package.json
git commit -m "test: centralize CAD fixtures and scenarios"
```

---

### Task 6: Enforce final coarse module boundaries

**Files:**
- Modify: `modules/cad-runtime/src/architecture/moduleBoundaryChecker.ts`
- Modify: `modules/cad-runtime/tests/architecture/module-boundaries.test.ts`
- Modify: `docs/architecture/module-boundaries.md`
- Modify: `docs/architecture/integration-contract.md`
- Modify: `docs/architecture/ai-clone-handoff.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: TypeScript source roots and package aliases.
- Produces: `scanWorkspaceModuleBoundaries(repositoryRoot: string)` covering relative imports, package aliases, static dynamic imports, and re-exports.

Final violation rules:

```ts
type ModuleBoundaryRule =
  | "contracts-are-runtime-independent"
  | "workspace-does-not-import-runtime"
  | "runtime-does-not-import-workspace"
  | "workspace-shared-does-not-import-features"
  | "workspace-features-do-not-cross-import"
  | "cross-module-import-uses-public-entrypoint";
```

- [ ] **Step 1: Write failures for new roots, aliases, and dynamic imports**

Add table cases:

```ts
[
  {
    importer: "apps/workspace/src/shared/types.ts",
    specifier: "../../../modules/cad-runtime/src/providers/contracts",
    rule: "workspace-does-not-import-runtime"
  },
  {
    importer: "modules/cad-runtime/src/http/gateway.ts",
    specifier: "../../../apps/workspace/src/shared/types",
    rule: "runtime-does-not-import-workspace"
  },
  {
    importer: "apps/workspace/src/features/cad-viewer/CadViewer.tsx",
    specifier: "../drawing-explorer/useDrawingIndex",
    rule: "workspace-features-do-not-cross-import"
  },
  {
    importer: "apps/workspace/src/app/App.tsx",
    specifier: "@dwg/contracts/src/cad",
    rule: "cross-module-import-uses-public-entrypoint"
  }
]
```

Add an extraction test:

```ts
test("extracts static dynamic imports", () => {
  assert.deepEqual(
    extractImportSpecifiers('const module = import("@dwg/contracts/src/cad")'),
    ["@dwg/contracts/src/cad"]
  );
});
```

- [ ] **Step 2: Run the boundary tests and verify new cases fail**

Run:

```powershell
node --import tsx --test modules/cad-runtime/tests/architecture/module-boundaries.test.ts
```

Expected: FAIL because the checker still recognizes old roots and ignores
package deep imports and dynamic imports.

- [ ] **Step 3: Update source roots and normalized module resolution**

Scan:

```ts
const sourceRoots = [
  "packages/contracts/src",
  "modules/cad-runtime/src",
  "apps/workspace/src"
];
```

Resolve relative specifiers against the importer. Resolve
`@dwg/contracts` to `packages/contracts/src/index.ts`; reject every
`@dwg/contracts/` deep path. Ignore external packages that do not belong to
this repository.

- [ ] **Step 4: Extend import extraction**

Keep the existing static import/export matcher and add:

```ts
const dynamicImportPattern = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;
```

Export `extractImportSpecifiers` for direct testing. Deduplicate returned
specifiers with `new Set`.

- [ ] **Step 5: Implement final root rules**

Use `apps/workspace/` and `modules/cad-runtime/` in place of old root names.
Retain the shared-to-feature and feature-to-feature rules under
`apps/workspace/src`. Treat only `packages/contracts/src/index.ts` as the
public contracts implementation entrypoint.

- [ ] **Step 6: Update handoff documentation**

Document exactly these supported reuse surfaces:

```text
@dwg/contracts
loopback /api
MCP stdio
whole apps/workspace composition
```

State that `modules/cad-runtime/src/**`, `apps/workspace/src/features/**`, and
parser internals are not deep-import APIs. Update every current file-tree
example and root command to the new paths.

- [ ] **Step 7: Run boundary and stale-path checks**

Run:

```powershell
node --import tsx --test --test-name-pattern "module|boundary|repository" modules/cad-runtime/tests/architecture/module-boundaries.test.ts
rg -n "frontend/src|agent/src|backend/src" README.md AGENTS.md docs/architecture package.json tsconfig.json apps modules
```

Expected: boundary tests PASS. The stale-path search returns no active path
instructions; migration-history prose may explicitly label old paths as
historical.

- [ ] **Step 8: Commit enforced module ownership**

```powershell
git add modules/cad-runtime/src/architecture modules/cad-runtime/tests/architecture README.md AGENTS.md docs/architecture
git commit -m "refactor: enforce Click Around module ownership"
```

---

### Task 7: Verify the migrated foundation end to end

**Files:**
- Modify: `package.json`

**Interfaces:**
- Consumes: all outputs from Tasks 1 through 6.
- Produces: `verify:foundation` and a clean verified commit for the next domain-extraction plan.

- [ ] **Step 1: Add the foundation gate**

Add:

```json
"verify:foundation": "npm run test:fixtures && npm test && npm run test:dotnet && npm run build:frontend && npm run test:e2e"
```

Keep `verify` and `verify:all` as compatibility commands.

- [ ] **Step 2: Run deterministic verification sequentially**

Run:

```powershell
npm run verify:foundation
npm audit --audit-level=high
git diff --check
```

Expected: fixture hashes PASS; Node tests at least 72/72 after the new integrity
test; .NET 9/9; frontend build PASS; Playwright at least 33/33; audit has zero
high or critical vulnerabilities; diff check clean.

- [ ] **Step 3: Regenerate documentation captures without changing baselines**

Run:

```powershell
npm run capture:docs
```

Expected: 2/2 capture tests PASS on isolated ports. Inspect
`docs/ui-captures/00-overview.png`, `01-workspace-loaded.png`,
`02-inspection-complete.png`, `03-layer-hidden.png`,
`04-claude-selected.png`, and `05-dark-theme.png`. Confirm the three-panel
layout, drawing tree, layer-hidden state, Artifact panel, and Claude selection
remain visually intact. Do not stage PNG changes caused only by timestamps,
session text, or other nondeterministic content.

- [ ] **Step 4: Run opt-in live OAuth only after deterministic gates**

Run:

```powershell
npm --workspace @click-around/workspace run test:live-oauth-browser
```

Expected: Codex and Claude each start or resume an authenticated installed-CLI
session; 2/2 PASS; no console or page errors. If either local subscription is
not authenticated, record `environment-blocked` for that provider and do not
alter deterministic code to hide it.

- [ ] **Step 5: Prove the final tree and clean state**

Run:

```powershell
Get-ChildItem apps,modules,packages,tests -Depth 2 | Select-Object FullName
git status --short
git diff --check
```

Expected: only the package script is pending; no old `frontend`, `agent`, or
`backend` root exists; no generated test artifacts are staged.

- [ ] **Step 6: Commit the verified foundation**

```powershell
git add package.json
git commit -m "build: add modular foundation gate"
```

---

## Subsequent independent plans

After this plan is green, write and execute these plans in order:

1. `Click Around domain ports and adapters`: extract drawing, inspection, and
   conversation ports; remove concrete defaults; add one composition root per
   execution mode and shared adapter contract suites.
2. `Click Around local persistence`: add profile, project, conversation,
   inspection, preference, transaction ports and the `better-sqlite3` adapter
   with migration, corruption, and restart tests.
3. `Click Around Electron desktop`: add Forge main/preload, typed allowlisted
   IPC, native folder selection, renderer bridge, packaged parser sidecar, and
   installed-CLI discovery.
4. `Click Around Windows release harness`: add Electron Playwright, deterministic
   PNG hashing and inspection, package smoke, Squirrel install/uninstall, and
   opt-in live OAuth release evidence.

Each later plan starts from a clean, green commit produced by the previous
plan. Supabase, hosted model APIs, cloud accounts, and pure-web filesystem
access remain outside these four desktop plans.

# CAD Capability Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish independent contracts, document, test-kit, and capability packages while preserving all current read-only behavior.

**Architecture:** Add npm workspaces for reusable modules and make `cad-capabilities` the public application API. The existing MCP runtime becomes an adapter over that API; parsers remain private.

**Tech Stack:** TypeScript 5.8, Node 24 test runner, Zod 3, npm workspaces, existing DWG/DXF parsers.

## Global Constraints

- Existing `cad-index/v0.1` and `cad-index/v0.2` inputs remain compatible.
- No behavior or fixture-byte changes.
- `modules/cad-runtime` must not deep-import new module source files.
- Every package exposes one public `src/index.ts`.
- Every created README names the public entrypoint, allowed dependencies,
  forbidden deep imports, ownership, and exact focused test command.
- `npm install` from the repository root remains the only install command.

---

### Task 1: Register Independent Workspaces and Boundary Rules

**Files:**
- Modify: `package.json`
- Modify: `tsconfig.json`
- Modify: `modules/cad-runtime/src/architecture/moduleBoundaryChecker.ts`
- Modify: `modules/cad-runtime/tests/architecture/module-boundaries.test.ts`
- Create: `scripts/package-entrypoints.test.mjs`
- Create: `scripts/package-dependencies.test.mjs`

**Interfaces:**
- Consumes: current root npm workspace configuration.
- Produces: workspace discovery for `apps/*`, `packages/*`, and `modules/*`; enforced public-entrypoint imports.
- Replaces the root unit script with:

```json
"test": "node --import tsx --test \"packages/**/*.test.ts\" \"modules/**/*.test.ts\" \"apps/workspace/tests/unit/**/*.test.ts\" \"scripts/**/*.test.mjs\""
```

- [ ] **Step 1: Write the failing workspace and boundary tests**

Add assertions that root workspaces equal:

```json
["apps/*", "packages/*", "modules/*"]
```

Add fixtures that reject:

```ts
import { x } from "@dwg/cad-document/src/model";
import { y } from "../../cad-edit/src/transaction";
```

and accept:

```ts
import { x } from "@dwg/cad-document";
import { y } from "@dwg/cad-edit";
```

`scripts/package-entrypoints.test.mjs` enumerates only directories that already
contain a `package.json`; for each discovered package it requires the declared
entrypoint file to exist. It does not require future plan packages before
their creation task.
`scripts/package-dependencies.test.mjs` loads every discovered workspace
manifest and enforces the exact dependency graph in the program plan,
including `packages/skill-contracts -> @dwg/contracts`. It rejects reverse
edges, undeclared `@dwg/*` edges, and reusable modules importing the
root-owned `cad-runtime`.
Add a script assertion that the root `test` command includes every existing
package/module `*.test.ts` plus workspace unit and script tests. A newly added
workspace test that is not discovered must fail this architecture test.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-runtime/tests/architecture/module-boundaries.test.ts scripts/package-entrypoints.test.mjs scripts/package-dependencies.test.mjs`

Expected: FAIL because `modules/*` is not a workspace, the checker accepts the
synthetic forbidden imports, and root tests do not discover all workspaces.

- [ ] **Step 3: Implement workspace and boundary discovery**

Extend the checker so any import matching `@dwg/<package>/src/` or a relative
path crossing from one top-level module into another module's `src` returns
`cross-module-import-uses-public-entrypoint`.
Encode the program dependency table as data in
`scripts/package-dependencies.test.mjs`; update it in the same commit whenever
an allowed edge is introduced by a later task.

- [ ] **Step 4: Run focused and clean-install verification**

Run: `npm install && node --import tsx --test modules/cad-runtime/tests/architecture/module-boundaries.test.ts scripts/package-entrypoints.test.mjs scripts/package-dependencies.test.mjs`

Expected: PASS and `git diff -- package-lock.json` contains only workspace metadata.

- [ ] **Step 5: Commit**

```powershell
git add package.json package-lock.json tsconfig.json modules/cad-runtime/src/architecture/moduleBoundaryChecker.ts modules/cad-runtime/tests/architecture/module-boundaries.test.ts scripts/package-entrypoints.test.mjs scripts/package-dependencies.test.mjs
git commit -m "build: register reusable CAD modules"
```

### Task 2: Add Skill Contracts

**Files:**
- Create: `packages/skill-contracts/package.json`
- Create: `packages/skill-contracts/tsconfig.json`
- Create: `packages/skill-contracts/README.md`
- Create: `packages/skill-contracts/src/index.ts`
- Create: `packages/skill-contracts/src/manifest.ts`
- Create: `packages/skill-contracts/src/permissions.ts`
- Create: `packages/skill-contracts/tests/manifest.test.ts`
- Create: `packages/contracts/src/skill.ts`
- Modify: `packages/contracts/src/index.ts`
- Modify: `package.json`
- Modify: `package-lock.json`

**Interfaces:**
- Produces:

```ts
interface CadSkillManifest {
  id: string;
  version: string;
  purpose: string;
  capabilityContract: "cad-capabilities/v1";
  permissions: SkillPermission[];
  capabilities: string[];
  formats: Array<"dwg" | "dxf">;
  entityTypes: string[];
  failureCodes: string[];
  limitationCodes: string[];
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
}
function parseCadSkillManifest(value: unknown): CadSkillManifest;
```

`SkillPermission` is a serialized public type exported from
`@dwg/contracts`. `@dwg/skill-contracts` imports and re-exports that type while
owning only manifest validation; browser code never imports
`@dwg/skill-contracts`.

- [ ] **Step 1: Write manifest validation tests**

Test a valid manifest and reject a blank purpose, duplicate permissions,
path-bearing IDs, unknown permissions, non-semver versions, invalid
failure/limitation codes, and unknown properties.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test packages/skill-contracts/tests/manifest.test.ts`

Expected: FAIL because `@dwg/skill-contracts` does not exist.

- [ ] **Step 3: Implement strict Zod schemas and public exports**

Use `.strict()`, `z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)`, and a
semantic-version regex. Validate failure and limitation codes with
`/^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$/`, require nonempty unique code arrays, and
return `schema.parse(value)` from `parseCadSkillManifest`.

- [ ] **Step 4: Run tests and package typecheck**

Run: `node --import tsx --test packages/skill-contracts/tests/manifest.test.ts && npx tsc -p packages/skill-contracts/tsconfig.json --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/skill-contracts/package.json packages/skill-contracts/tsconfig.json packages/skill-contracts/README.md packages/skill-contracts/src/index.ts packages/skill-contracts/src/manifest.ts packages/skill-contracts/src/permissions.ts packages/skill-contracts/tests/manifest.test.ts packages/contracts/src/skill.ts packages/contracts/src/index.ts package.json package-lock.json
git commit -m "feat: add versioned skill contracts"
```

### Task 3: Add Shared Test Kit

**Files:**
- Create: `packages/test-kit/package.json`
- Create: `packages/test-kit/tsconfig.json`
- Create: `packages/test-kit/README.md`
- Create: `packages/test-kit/src/index.ts`
- Create: `packages/test-kit/src/fixtures.ts`
- Create: `packages/test-kit/src/roundtrip.ts`
- Create: `packages/test-kit/tests/fixtures.test.ts`
- Modify: `package.json`
- Modify: `package-lock.json`

**Interfaces:**
- Produces:

```ts
interface FixtureDescriptor {
  id: string;
  path: string;
  sha256: string;
  kind: "dwg" | "dxf";
}
interface CadIndexInvariantSummary {
  schemaVersion: CadEntityIndex["schemaVersion"];
  entityCount: number;
  layerCount: number;
  unsupportedCount: number;
  handles: string[];
}
function loadFixtureManifest(repositoryRoot: string): Promise<FixtureDescriptor[]>;
function assertFileHash(path: string, expectedSha256: string): Promise<void>;
function summarizeIndex(index: CadEntityIndex): CadIndexInvariantSummary;
```

- [ ] **Step 1: Write tests against `tests/fixtures/manifest.json`**

Assert both official fixtures load, paths remain within `tests/fixtures`, and
the current hashes match.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test packages/test-kit/tests/fixtures.test.ts`

Expected: FAIL because the test-kit package is absent.

- [ ] **Step 3: Implement manifest, containment, hash, and summary helpers**

Use `realpath`, `relative`, and SHA-256. Reject absolute paths and any relative
result beginning with `..`.

- [ ] **Step 4: Run tests**

Run: `node --import tsx --test packages/test-kit/tests/fixtures.test.ts scripts/verify-fixture-hashes.test.mjs`

Expected: PASS with the existing DWG and DXF hashes unchanged.

- [ ] **Step 5: Commit**

```powershell
git add packages/test-kit/package.json packages/test-kit/tsconfig.json packages/test-kit/README.md packages/test-kit/src/index.ts packages/test-kit/src/fixtures.ts packages/test-kit/src/roundtrip.ts packages/test-kit/tests/fixtures.test.ts package.json package-lock.json
git commit -m "test: add reusable CAD fixture kit"
```

### Task 4: Extract the Engine-Neutral Document Package

**Files:**
- Create: `modules/cad-document/package.json`
- Create: `modules/cad-document/tsconfig.json`
- Create: `modules/cad-document/README.md`
- Create: `modules/cad-document/src/index.ts`
- Create: `modules/cad-document/src/snapshot.ts`
- Create: `modules/cad-document/src/clone.ts`
- Create: `modules/cad-document/tests/snapshot.test.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Consumes: `CadEntityIndex` from `@dwg/contracts`.
- Produces:

```ts
interface CadDocumentSnapshot {
  documentId: string;
  revision: number;
  sourceSha256: string;
  drawingVersion: string | null;
  units: string | null;
  index: CadEntityIndexV02;
  layers: Array<{
    id: string;
    name: string;
    color: number | null;
    visible: boolean;
    frozen: boolean;
    locked: boolean | null;
  }>;
}
function normalizeEditableIndex(index: CadEntityIndex): CadEntityIndexV02;
function createDocumentSnapshot(index: CadEntityIndex, sourceSha256: string): CadDocumentSnapshot;
function cloneDocumentSnapshot(snapshot: CadDocumentSnapshot): CadDocumentSnapshot;
```

- [ ] **Step 1: Write immutable snapshot tests**

Prove the constructor normalizes v0.1 entities to explicit `bbox` or
`unavailable` v0.2 geometry, rejects invalid hashes, duplicate non-null
handles, and non-finite geometry. Prove clone mutation does not mutate the
source. Prove the checked-in DXF can create a snapshot for layer and text
editing without claiming typed move geometry.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-document/tests/snapshot.test.ts`

Expected: FAIL because the package is absent.

- [ ] **Step 3: Implement snapshot validation and `structuredClone` isolation**

Set `revision: 0`; use the drawing ID as `documentId`; normalize the SHA-256 to
uppercase. Give imported layers stable IDs
`layer:imported:<base64url(utf8Name)>`. Initialize drawing version, units,
layer color, and layer lock state to null when the read-only index does not
expose those values. Preserve null as unknown evidence; never substitute CAD
defaults such as color 7 or unlocked.
For v0.1 entities, use `geometry: { kind: "bbox", reason: "legacy-v0.1" }`
when bbox exists and `geometry: { kind: "unavailable", reason:
"legacy-v0.1-no-bbox" }` otherwise.

- [ ] **Step 4: Run tests and typecheck**

Run: `node --import tsx --test modules/cad-document/tests/snapshot.test.ts && npx tsc -p modules/cad-document/tsconfig.json --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-document/package.json modules/cad-document/tsconfig.json modules/cad-document/README.md modules/cad-document/src/index.ts modules/cad-document/src/snapshot.ts modules/cad-document/src/clone.ts modules/cad-document/tests/snapshot.test.ts package.json package-lock.json tsconfig.json
git commit -m "feat: add engine-neutral CAD document"
```

### Task 5: Extract the ACadSharp Read Adapter

**Files:**
- Create: `modules/cad-io-acadsharp/README.md`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIntelligence.CadIo.csproj`
- Move: `modules/dwg-parser/src/DwgIntelligence.DwgParser/DwgIndexBuilder.cs` to `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIndexBuilder.cs`
- Move: `modules/dwg-parser/src/DwgIntelligence.DwgParser/EntityGeometryExtractor.cs` to `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/EntityGeometryExtractor.cs`
- Move: `modules/dwg-parser/src/DwgIntelligence.DwgParser/GeometryModels.cs` to `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/GeometryModels.cs`
- Move: `modules/dwg-parser/src/DwgIntelligence.DwgParser/IndexModels.cs` to `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/IndexModels.cs`
- Move: `modules/dwg-parser/src/DwgIntelligence.DwgParser/InsertAttributeExtractor.cs` to `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/InsertAttributeExtractor.cs`
- Move: `modules/dwg-parser/src/DwgIntelligence.DwgParser/LayoutEntityEnumerator.cs` to `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/LayoutEntityEnumerator.cs`
- Modify: `modules/dwg-parser/src/DwgIntelligence.DwgParser/DwgIntelligence.DwgParser.csproj`
- Modify: `modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj`
- Create: `scripts/acadsharp-ownership.test.mjs`

**Interfaces:**
- `DwgIntelligence.CadIo` is the sole owner of ACadSharp document-to-index
  mapping.
- `DwgIntelligence.DwgParser` remains the thin read executable and references
  the class library.

- [ ] **Step 1: Add an ownership test**

Add a repository test that finds exactly one definition each of
`DwgIndexBuilder`, `EntityGeometryExtractor`, and `LayoutEntityEnumerator`,
all below `modules/cad-io-acadsharp`.

- [ ] **Step 2: Run the ownership test and verify RED**

Run: `node --test scripts/acadsharp-ownership.test.mjs`

Expected: FAIL because mapping still belongs to `dwg-parser`.

- [ ] **Step 3: Move the mapping files and add project references**

Use `git mv`. Keep `Program.cs` in `dwg-parser`; update namespaces to
`DwgIntelligence.CadIo`; reference the class library from parser and parser
tests. Do not change serialized output.

- [ ] **Step 4: Run parser parity tests sequentially**

Run: `npm run test:dotnet`

Expected: 9/9 PASS and the official DWG index summary equals the pre-move
fixture.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-io-acadsharp/README.md modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIntelligence.CadIo.csproj modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIndexBuilder.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/EntityGeometryExtractor.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/GeometryModels.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/IndexModels.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/InsertAttributeExtractor.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/LayoutEntityEnumerator.cs modules/dwg-parser/src/DwgIntelligence.DwgParser/DwgIntelligence.DwgParser.csproj modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj scripts/acadsharp-ownership.test.mjs
git commit -m "refactor: isolate the ACadSharp read adapter"
```

### Task 6: Publish Real Layer Color and Lock Evidence

**Files:**
- Modify: `packages/contracts/src/cad.ts`
- Modify: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/IndexModels.cs`
- Modify: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIndexBuilder.cs`
- Modify: `modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIndexBuilderTests.cs`
- Modify: `apps/workspace/public/data/export_sample.index.json`
- Modify: `modules/cad-document/src/snapshot.ts`
- Modify: `modules/cad-document/tests/snapshot.test.ts`

**Interfaces:**
- Extends the root drawing index and `CadLayerIndexItem` compatibly:

```ts
interface CadDrawingMetadata {
  fileVersion: string | null;
  units: string | null;
}
interface CadLayerIndexItem {
  name: string;
  entityCount: number;
  visible: boolean;
  frozen: boolean;
  color?: number | null;
  locked?: boolean | null;
}
```

`CadEntityIndexV02` gains `drawing?: CadDrawingMetadata`. New DWG parser output
always supplies actual file version, units, color, and lock evidence. Legacy
v0.1/v0.2 JSON without the fields remains readable and normalizes every missing
value to null, not fabricated values.

- [ ] **Step 1: Write parser and normalization tests**

Assert the official DWG's exact file version, units, layer color, and lock
values, legacy omission compatibility, and snapshot preservation of null
versus false.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
dotnet test modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo
node --import tsx --test packages/contracts/tests/*.test.ts modules/cad-document/tests/*.test.ts
```

Expected: both commands FAIL because drawing metadata and layer evidence are
absent.

- [ ] **Step 3: Extract actual ACadSharp layer table values**

Serialize the source database version and insertion units. Serialize AutoCAD
color index when representable; use null for unsupported true-color modes while
retaining a warning. Serialize the actual locked flag. Regenerate only the
browser index JSON from the immutable DWG.

- [ ] **Step 4: Run parser, contract, document, and fixture tests**

Run sequentially:

```powershell
npm run test:dotnet
node --import tsx --test packages/contracts/tests/*.test.ts modules/cad-document/tests/*.test.ts
npm run test:fixtures
```

Expected: PASS and source fixture hashes remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add packages/contracts/src/cad.ts modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/IndexModels.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIndexBuilder.cs modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIndexBuilderTests.cs apps/workspace/public/data/export_sample.index.json modules/cad-document/src/snapshot.ts modules/cad-document/tests/snapshot.test.ts
git commit -m "feat: expose real CAD layer metadata"
```

### Task 7: Add Read-Only Capability API and Migrate MCP

**Files:**
- Create: `modules/cad-capabilities/package.json`
- Create: `modules/cad-capabilities/tsconfig.json`
- Create: `modules/cad-capabilities/README.md`
- Create: `modules/cad-capabilities/src/index.ts`
- Create: `modules/cad-capabilities/src/contracts.ts`
- Create: `modules/cad-capabilities/src/readCapabilities.ts`
- Create: `modules/cad-capabilities/tests/read-capabilities.test.ts`
- Modify: `packages/contracts/src/cad.ts`
- Modify: `modules/cad-runtime/src/application/cad-tools/runtime.ts`
- Modify: `modules/cad-runtime/src/mcp/createServer.ts`
- Modify: `modules/cad-runtime/tests/integration/mcp-server.test.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Produces:

```ts
type CadCapabilityName =
  | "document.open"
  | "document.describe"
  | "query.layers"
  | "query.entities"
  | "query.text";
interface CadCapabilityRuntime {
  execute(name: CadCapabilityName, input: unknown, signal?: AbortSignal): Promise<unknown>;
}
interface CadCapabilityModule {
  names: readonly CadCapabilityName[];
  execute(name: CadCapabilityName, input: unknown, signal?: AbortSignal): Promise<unknown>;
}
interface ReadCapabilityDependencies {
  open(path: string, signal?: AbortSignal): Promise<CadEntityIndex>;
  get(drawingId: string): CadEntityIndex | null;
}
function createReadCapabilityModule(deps: ReadCapabilityDependencies): CadCapabilityModule;
function composeCadCapabilityModules(
  modules: readonly CadCapabilityModule[],
): CadCapabilityRuntime;
```

Move the existing private `CadToolMatch` shape into
`packages/contracts/src/cad.ts` as a public `CadEntityMatch` and re-export the
old private name only as a temporary alias. Capability and query packages use
`CadEntityMatch`.

- [ ] **Step 1: Write parity tests**

For the official DXF fixture, call the capability API and existing MCP tools.
Assert equal drawing IDs, layer counts, text handles, and unsupported
summaries. Assert composed routing, duplicate capability-name rejection,
unknown capability rejection, and preservation of the same `AbortSignal`
through the composer into the selected module.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-capabilities/tests/read-capabilities.test.ts modules/cad-runtime/tests/integration/mcp-server.test.ts`

Expected: FAIL because the capability runtime does not exist.

- [ ] **Step 3: Implement capabilities and make MCP names adapters**

Map:

```text
cad.open_drawing             -> document.open
cad.build_index              -> document.describe
cad.get_layers               -> query.layers
cad.find_entities_by_layer   -> query.entities
cad.find_entities_by_type    -> query.entities
cad.find_text                -> query.text
cad.get_entity               -> query.entities
cad.list_unsupported         -> document.describe
```

Keep all existing MCP request and response shapes stable. MCP receives the
single runtime returned by `composeCadCapabilityModules`.

- [ ] **Step 4: Run focused and full verification**

Run: `node --import tsx --test modules/cad-capabilities/tests/read-capabilities.test.ts modules/cad-runtime/tests/integration/*.test.ts && npm run verify:all`

Expected: focused tests and the entire existing suite pass.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-capabilities/package.json modules/cad-capabilities/tsconfig.json modules/cad-capabilities/README.md modules/cad-capabilities/src/index.ts modules/cad-capabilities/src/contracts.ts modules/cad-capabilities/src/readCapabilities.ts modules/cad-capabilities/tests/read-capabilities.test.ts packages/contracts/src/cad.ts modules/cad-runtime/src/application/cad-tools/runtime.ts modules/cad-runtime/src/mcp/createServer.ts modules/cad-runtime/tests/integration/mcp-server.test.ts package.json package-lock.json tsconfig.json
git commit -m "refactor: route CAD tools through capabilities"
```

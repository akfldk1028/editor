# ACadSharp DWG Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse real local DWG files with ACadSharp 3.6.35 into the existing `cad-index/v0.1` contract and make the TypeScript CAD runtime choose the DWG adapter automatically.

**Architecture:** A .NET 9 console process reads one DWG and writes one normalized JSON document to stdout. Entity conversion isolates bbox and entity failures, records unsupported counts, and never writes the source. A TypeScript adapter spawns the parser, validates the result shape, and plugs it into the existing runtime by file extension.

**Tech Stack:** .NET 9, C# 13, ACadSharp 3.6.35, System.Text.Json, TypeScript 5.8, Node test runner.

## Global Constraints

- The DWG source is opened read-only and its SHA-256 hash must remain unchanged.
- Parser stdout contains JSON only; diagnostics use stderr.
- Product code cannot reference `clone/`.
- Proxy, unknown, AEC, invalid bbox, and bbox exceptions become warnings and unsupported summaries.
- Handles use uppercase hexadecimal without a prefix.
- Stable entity IDs use `h:<HANDLE>`.
- The output validates as `cad-index/v0.1`.

---

### Task 1: .NET DWG Indexer And Real Fixture Test

**Files:**
- Create: `backend/src/DwgIntelligence.DwgParser/DwgIntelligence.DwgParser.csproj`
- Create: `backend/src/DwgIntelligence.DwgParser/Program.cs`
- Create: `backend/src/DwgIntelligence.DwgParser/DwgIndexBuilder.cs`
- Create: `backend/src/DwgIntelligence.DwgParser/IndexModels.cs`
- Create: `backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj`
- Create: `backend/tests/DwgIntelligence.DwgParser.Tests/DwgIndexBuilderTests.cs`
- Copy: `tests/fixtures/dwg/export_sample.dwg`
- Create: `tests/fixtures/dwg/README.md`

**Interfaces:**
- Produces: `CadIndex DwgIndexBuilder.Build(string path)`
- Produces CLI: `dotnet run --project backend/src/DwgIntelligence.DwgParser -- index <path>`

- [ ] **Step 1: Create projects with pinned dependencies**

Parser project references:

```xml
<TargetFramework>net9.0</TargetFramework>
<PackageReference Include="ACadSharp" Version="3.6.35" />
```

Test project references `Microsoft.NET.Test.Sdk` 17.14.1, xunit 2.9.3,
`xunit.runner.visualstudio` 3.1.4, and the parser project.

- [ ] **Step 2: Copy and attribute the MIT sample**

Copy `clone/ACadSharp/samples/svg/export_sample.dwg` to
`tests/fixtures/dwg/export_sample.dwg`. Record source repository, original
path, MIT license, and unchanged test-only usage in the README.

- [ ] **Step 3: Write the failing real-DWG test**

```csharp
string path = FixturePath("export_sample.dwg");
string before = Sha256(path);
CadIndex index = DwgIndexBuilder.Build(path);
string after = Sha256(path);

Assert.Equal("cad-index/v0.1", index.SchemaVersion);
Assert.Equal("dwg", index.Source.Kind);
Assert.Equal("acadsharp@3.6.35", index.Source.Parser);
Assert.NotEmpty(index.Entities);
Assert.Contains(index.Entities, entity =>
    entity.Handle is not null && entity.Id == $"h:{entity.Handle}");
Assert.Equal(before, after);
```

- [ ] **Step 4: Run and verify RED**

Run:

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests
```

Expected: FAIL because `DwgIndexBuilder` does not exist.

- [ ] **Step 5: Implement normalized DTOs and builder**

Use `DwgReader.Read(path)`, `doc.Entities`, `doc.Layers`, `Entity.Handle`,
`Entity.Layer.Name`, `Entity.ObjectName`, `IText.Value`, and
`Entity.GetBoundingBox()`.

Bbox conversion succeeds only when all six coordinates are finite. Catch
`NotImplementedException` as `bbox-not-implemented` and other entity-level
exceptions as `bbox-error:<ExceptionType>`. Null/invalid bounds become
`bbox-unavailable`. Group unsupported entries by type and reason.

- [ ] **Step 6: Implement JSON-only CLI**

`Program.cs` accepts exactly `index <existing .dwg path>`, serializes camelCase
JSON, writes one document to stdout, and returns exit code 2 with stderr for
usage or parser errors.

- [ ] **Step 7: Run focused verification**

Run:

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests
dotnet run --project backend/src/DwgIntelligence.DwgParser -- index tests/fixtures/dwg/export_sample.dwg > tests/fixtures/dwg/latest-index.json
```

Parse `latest-index.json` with PowerShell `ConvertFrom-Json` and confirm the
schema version and nonzero entity count, then remove the generated JSON.

- [ ] **Step 8: Commit**

```powershell
git add backend tests/fixtures/dwg
git commit -m "feat: index real DWG files with ACadSharp"
```

### Task 2: TypeScript DWG Adapter And Runtime Selection

**Files:**
- Create: `agent/src/parsers/dwg/acadSharpIndexer.ts`
- Create: `agent/tests/integration/dwg-runtime.test.ts`
- Modify: `agent/src/application/cad-tools/runtime.ts`

**Interfaces:**
- Produces: `buildIndexFromDwgFile(path: string): Promise<CadEntityIndex>`
- Changes: `cad.open_drawing` selects DXF or DWG by lowercase extension.

- [ ] **Step 1: Write a failing runtime integration test**

```ts
const runtime = createCadToolRuntime();
const before = await sha256("tests/fixtures/dwg/export_sample.dwg");
const opened = await runtime.call("cad.open_drawing", {
  path: "tests/fixtures/dwg/export_sample.dwg"
});
const built = await runtime.call("cad.build_index", {
  drawingId: opened.drawingId
});
const after = await sha256("tests/fixtures/dwg/export_sample.dwg");

assert.equal(opened.source.kind, "dwg");
assert.ok(built.summary.entityCount > 0);
assert.equal(before, after);
```

Add a `.pdf` test that rejects with `Unsupported drawing format: .pdf`.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/integration/dwg-runtime.test.ts
```

Expected: FAIL because the current runtime reads DWG bytes as UTF-8 DXF.

- [ ] **Step 3: Implement the child-process adapter**

Spawn:

```text
dotnet run --project backend/src/DwgIntelligence.DwgParser --no-launch-profile -- index <absolute-path>
```

Capture stdout and stderr separately, reject nonzero exit codes, parse JSON,
and check `schemaVersion === "cad-index/v0.1"` and `source.kind === "dwg"`.

- [ ] **Step 4: Refactor runtime opening by extension**

DXF continues using the existing TypeScript indexer. DWG awaits the ACadSharp
adapter. Other extensions fail before reading the file. Store the normalized
index in the existing drawing session map so all eight `cad.*` tools work
unchanged.

- [ ] **Step 5: Run full verification**

Run:

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests
node --import tsx --test agent/tests/integration/dwg-runtime.test.ts
npm test
npm run harness -- agent/harness/cases/find-layer-a-wall.json
npm run harness -- agent/harness/cases/find-text-room.json
npx tsc --noEmit
```

Expected: .NET, DWG runtime, MCP, orchestration, DXF harness, and TypeScript
checks all pass.

- [ ] **Step 6: Commit**

```powershell
git add agent/src/parsers/dwg agent/src/application/cad-tools/runtime.ts agent/tests/integration/dwg-runtime.test.ts
git commit -m "feat: route DWG sessions through local parser"
```

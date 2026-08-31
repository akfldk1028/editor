# CAD Index v0.2 Geometry Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit typed geometry, insert attributes, and real Model/Paper Space ownership from DWG files, then render that evidence as accurate SVG primitives with retained Playwright PNG proof.

**Architecture:** `packages/contracts` defines a backward-compatible v0.1/v0.2 union and strict v0.2 geometry validator. The .NET parser traverses layout-owned block records and delegates geometry and INSERT extraction to focused modules. The React viewer narrows the schema version, converts only typed geometry to SVG, and keeps explicit bbox fallback for legacy and unsupported entities.

**Tech Stack:** TypeScript 5.8, Node.js 24 test runner, AJV 8, .NET 9, xUnit 2.9, ACadSharp 3.6.35, React 19, SVG, Playwright 1.62.

## Global Constraints

- Keep deterministic CAD evidence separate from LLM explanations.
- The DWG parser emits `cad-index/v0.2`; the DXF parser may continue emitting `cad-index/v0.1`.
- Consumers accept v0.1 during migration and must narrow `schemaVersion` before reading typed geometry.
- All coordinates use drawing units and three-number tuples; all angles use radians.
- Do not flatten block definitions or claim nested INSERT geometry fidelity.
- Do not import or copy implementation from `clone/`; ACadSharp and other repositories are read-only references.
- No arbitrary 3D projection: normals not parallel to positive or negative Z use explicit bbox fallback.
- Every behavior change follows RED, GREEN, REFACTOR.
- Run Node and .NET suites sequentially.
- Browser completion requires isolated Playwright ports, retained 1440x900 PNGs, and direct image inspection.

---

## File Structure

- `packages/contracts/src/cad.ts`: Public v0.1/v0.2 index union, geometry discriminants, type guards, and runtime validation.
- `agent/contracts/cad-index.schema.json`: JSON Schema union with strict v0.2 geometry branches and retained v0.1 acceptance.
- `agent/tests/contracts/cad-index-contract.test.ts`: AJV and shared-validator acceptance/rejection tests.
- `backend/src/DwgIntelligence.DwgParser/GeometryModels.cs`: Serializable .NET geometry records only.
- `backend/src/DwgIntelligence.DwgParser/EntityGeometryExtractor.cs`: ACadSharp entity-to-geometry conversion and deterministic geometry warnings.
- `backend/src/DwgIntelligence.DwgParser/LayoutEntityEnumerator.cs`: Model/Paper layout traversal and handle de-duplication.
- `backend/src/DwgIntelligence.DwgParser/InsertAttributeExtractor.cs`: INSERT tag/value extraction and duplicate-tag warnings.
- `backend/src/DwgIntelligence.DwgParser/IndexModels.cs`: v0.2 index records wired to `CadEntityGeometry`.
- `backend/src/DwgIntelligence.DwgParser/DwgIndexBuilder.cs`: Parser composition, counts, fallbacks, and v0.2 output.
- `backend/tests/DwgIntelligence.DwgParser.Tests/EntityGeometryExtractorTests.cs`: Focused primitive extraction tests.
- `backend/tests/DwgIntelligence.DwgParser.Tests/LayoutEntityEnumeratorTests.cs`: In-memory Model/Paper ownership and duplicate tests.
- `backend/tests/DwgIntelligence.DwgParser.Tests/InsertAttributeExtractorTests.cs`: Attribute extraction tests.
- `backend/tests/DwgIntelligence.DwgParser.Tests/DwgIndexBuilderTests.cs`: Real DWG literal evidence and source-integrity tests.
- `agent/src/parsers/dwg/acadSharpIndexer.ts`: v0.2 parser-result validation through the shared contract.
- `frontend/scripts/generate-fixture.mjs`: Regenerate the committed frontend index from the unchanged real DWG.
- `frontend/public/data/export_sample.index.json`: Generated v0.2 browser fixture.
- `frontend/src/features/cad-viewer/geometry/geometryMath.ts`: React-free arc and bulge SVG math.
- `frontend/src/features/cad-viewer/geometry/EntityGeometry.tsx`: Version-correlated primitive/fallback dispatch.
- `frontend/src/features/cad-viewer/geometry/ArcGeometry.tsx`: ARC path renderer.
- `frontend/src/features/cad-viewer/geometry/PolylineGeometry.tsx`: Straight/bulged/closed LWPOLYLINE renderer.
- `frontend/src/features/cad-viewer/geometry/TextGeometry.tsx`: Upright TEXT/MTEXT renderer.
- `frontend/src/features/cad-viewer/geometry/BboxFallback.tsx`: Legacy, unsupported, and INSERT fallback renderer.
- `frontend/src/features/cad-viewer/CadViewer.tsx`: Viewer composition, layout status, and feature renderer delegation.
- `frontend/src/features/cad-viewer/styles.css`: Geometry/text/fallback presentation only.
- `frontend/tests/unit/geometry-math.test.ts`: Exact path and rejection tests.
- `frontend/tests/e2e/geometry-fidelity.spec.ts`: Geometry DOM, fallback, highlight, and layer behavior.
- `frontend/tests/e2e/workspace.spec.ts`: Dynamic entity totals and updated visual baselines.
- `frontend/tests/e2e/layer-visibility.spec.ts`: Generated-index layer totals instead of v0.1 constants.
- `tests/visual/artifacts/geometry-loaded-1440x900.png`: Retained loaded drawing evidence.
- `tests/visual/artifacts/geometry-inspection-1440x900.png`: Retained highlighted inspection evidence.
- `docs/architecture/module-boundaries.md`: Public contract version and module ownership update.
- `agent/skills/dwg-intelligence/references/entity-index-schema.md`: Agent-facing v0.2 evidence reference.

### Task 1: Backward-Compatible Typed CAD Contract

**Files:**
- Modify: `packages/contracts/src/cad.ts`
- Modify: `packages/contracts/src/index.ts`
- Modify: `agent/contracts/cad-index.schema.json`
- Create: `agent/tests/contracts/cad-index-contract.test.ts`

**Interfaces:**
- Consumes: Existing `CadPointBox`, source, summary, layer, and unsupported DTOs.
- Produces: `CadPoint3`, `CadEntityGeometry`, `CadEntityIndexItemV01`, `CadEntityIndexItemV02`, `CadEntityIndexV01`, `CadEntityIndexV02`, `CadEntityIndex`, `isCadEntityIndex(value)`, and `isCadEntityIndexV02(value)`.

- [ ] **Step 1: Write the failing shared-contract tests**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";

import {
  isCadEntityIndex,
  isCadEntityIndexV02
} from "@dwg/contracts";

const base = {
  drawingId: "dwg:test",
  source: { kind: "dwg", displayName: "test.dwg", parser: "acadsharp@3.6.35" },
  summary: {
    entityCount: 1,
    layerCount: 1,
    unsupportedCount: 0,
    modelSpaceCount: 1,
    paperSpaceCount: 0
  },
  layers: [{ name: "0", entityCount: 1, visible: true, frozen: false }],
  unsupported: []
};

const lineV02 = {
  ...base,
  schemaVersion: "cad-index/v0.2",
  entities: [{
    id: "h:1",
    handle: "1",
    type: "LINE",
    layer: "0",
    space: "model",
    layout: "Model",
    bbox: { min: [0, 0, 0], max: [10, 5, 0] },
    text: null,
    blockName: null,
    attributes: {},
    geometry: { kind: "line", start: [0, 0, 0], end: [10, 5, 0] },
    warnings: []
  }]
} as const;

test("accepts strict v0.2 and identifies typed geometry", () => {
  assert.equal(isCadEntityIndex(lineV02), true);
  assert.equal(isCadEntityIndexV02(lineV02), true);
});

test("retains v0.1 input compatibility", () => {
  const legacy = {
    ...lineV02,
    schemaVersion: "cad-index/v0.1",
    entities: [{ ...lineV02.entities[0], geometry: {} }]
  };
  assert.equal(isCadEntityIndex(legacy), true);
  assert.equal(isCadEntityIndexV02(legacy), false);
});

test("rejects malformed v0.2 geometry", () => {
  assert.equal(isCadEntityIndex({
    ...lineV02,
    entities: [{
      ...lineV02.entities[0],
      geometry: { kind: "line", start: [0, 0], end: [10, 5, 0] }
    }]
  }), false);
  assert.equal(isCadEntityIndex({
    ...lineV02,
    entities: [{
      ...lineV02.entities[0],
      geometry: { kind: "invented", value: 1 }
    }]
  }), false);
});

test("JSON Schema and shared validator agree", () => {
  const schema = JSON.parse(
    readFileSync("agent/contracts/cad-index.schema.json", "utf8")
  );
  const validate = new Ajv2020({ strict: true }).compile(schema);
  assert.equal(validate(lineV02), true);
  assert.equal(validate({ ...lineV02, schemaVersion: "cad-index/v9" }), false);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/contracts/cad-index-contract.test.ts
```

Expected: FAIL because `isCadEntityIndex` and v0.2 geometry exports do not exist.

- [ ] **Step 3: Define the public discriminated geometry and versioned index types**

Implement the geometry union exactly as specified in
`docs/superpowers/specs/2026-07-28-cad-index-v02-geometry-design.md`.
Keep compatibility aliases:

```ts
export type CadEntityIndexItem =
  | CadEntityIndexItemV01
  | CadEntityIndexItemV02;
export type CadEntityIndex =
  | CadEntityIndexV01
  | CadEntityIndexV02;
export type CadEntity = CadEntityIndexItem;
export type CadIndex = CadEntityIndex;
```

Build validation from small exhaustive helpers:

```ts
function isPoint3(value: unknown): value is CadPoint3 {
  return Array.isArray(value)
    && value.length === 3
    && value.every((item) => typeof item === "number" && Number.isFinite(item));
}

export function isCadEntityIndexV02(
  value: unknown
): value is CadEntityIndexV02 {
  return isCadIndexEnvelope(value)
    && value.schemaVersion === "cad-index/v0.2"
    && value.entities.every(isCadEntityIndexItemV02);
}
```

Reject unknown keys inside every v0.2 geometry branch by comparing
`Object.keys(value).sort()` with the exact branch key set.

- [ ] **Step 4: Replace the schema with a v0.1/v0.2 `oneOf`**

Use `$defs` for shared envelopes and one branch per geometry kind. Set
`additionalProperties: false` for every v0.2 geometry definition. Keep the
legacy v0.1 geometry object open so existing DXF fixtures remain valid.

- [ ] **Step 5: Run contract, public-contract, typecheck, and full Node tests**

Run sequentially:

```powershell
node --import tsx --test agent/tests/contracts/cad-index-contract.test.ts
node --import tsx --test agent/tests/contracts/public-contracts.test.ts
npx tsc --noEmit
npm test
```

Expected: all PASS; existing DXF v0.1 tests remain green.

- [ ] **Step 6: Commit the contract slice**

```powershell
git add packages/contracts/src/cad.ts packages/contracts/src/index.ts agent/contracts/cad-index.schema.json agent/tests/contracts/cad-index-contract.test.ts
git commit -m "feat: define cad index v0.2 geometry contract"
```

### Task 2: Primitive Geometry Extraction

**Files:**
- Create: `backend/src/DwgIntelligence.DwgParser/GeometryModels.cs`
- Create: `backend/src/DwgIntelligence.DwgParser/EntityGeometryExtractor.cs`
- Modify: `backend/src/DwgIntelligence.DwgParser/IndexModels.cs`
- Create: `backend/tests/DwgIntelligence.DwgParser.Tests/EntityGeometryExtractorTests.cs`

**Interfaces:**
- Consumes: ACadSharp `Line`, `Circle`, `Arc`, `LwPolyline`, `Point`, `TextEntity`, `MText`, and `Insert`.
- Produces: `GeometryExtraction(CadEntityGeometry Geometry, IReadOnlyList<string> Warnings)` and `EntityGeometryExtractor.Extract(Entity entity, CadBoundingBox? bbox)`.

- [ ] **Step 1: Write failing focused extractor tests**

```csharp
using ACadSharp.Entities;
using CSMath;
using Xunit;

namespace DwgIntelligence.DwgParser.Tests;

public sealed class EntityGeometryExtractorTests
{
    [Fact]
    public void ExtractsLineCircleAndArcInRadians()
    {
        var line = new Line(new XYZ(1, 2, 0), new XYZ(8, 5, 0));
        var circle = new Circle { Center = new XYZ(5, 6, 0), Radius = 4 };
        var arc = new Arc {
            Center = new XYZ(10, 20, 0),
            Radius = 5,
            StartAngle = Math.PI / 4,
            EndAngle = Math.PI
        };

        var lineGeometry = Assert.IsType<LineGeometry>(
            EntityGeometryExtractor.Extract(line, null).Geometry);
        Assert.Equal([1, 2, 0], lineGeometry.Start);
        Assert.Equal([8, 5, 0], lineGeometry.End);

        var circleGeometry = Assert.IsType<CircleGeometry>(
            EntityGeometryExtractor.Extract(circle, null).Geometry);
        Assert.Equal([5, 6, 0], circleGeometry.Center);
        Assert.Equal(4, circleGeometry.Radius);
        Assert.Equal([0, 0, 1], circleGeometry.Normal);
        Assert.Equal(
            Math.PI / 4,
            Assert.IsType<ArcGeometry>(
                EntityGeometryExtractor.Extract(arc, null).Geometry
            ).StartAngle,
            12);
    }

    [Fact]
    public void PreservesLwPolylineBulgeWidthsClosureAndElevation()
    {
        var polyline = new LwPolyline {
            IsClosed = true,
            Elevation = 7
        };
        polyline.Vertices.Add(new LwPolyline.Vertex(0, 0) {
            Bulge = 0.5,
            StartWidth = 2,
            EndWidth = 3
        });
        polyline.Vertices.Add(new LwPolyline.Vertex(10, 0));

        var geometry = Assert.IsType<LwPolylineGeometry>(
            EntityGeometryExtractor.Extract(polyline, null).Geometry
        );
        Assert.True(geometry.Closed);
        Assert.Equal([0, 0, 7], geometry.Vertices[0].Point);
        Assert.Equal(0.5, geometry.Vertices[0].Bulge);
        Assert.Equal(2, geometry.Vertices[0].StartWidth);
        Assert.Equal(3, geometry.Vertices[0].EndWidth);
    }

    [Fact]
    public void UsesExplicitFallbackForUnsupportedAndNonPlanarGeometry()
    {
        var ellipse = new Ellipse();
        var box = new CadBoundingBox([0, 0, 0], [4, 2, 0]);
        var unsupported = EntityGeometryExtractor.Extract(ellipse, box);
        Assert.Equal("bbox", unsupported.Geometry.Kind);
        Assert.Contains("geometry-fallback:ELLIPSE", unsupported.Warnings);

        var line = new Line { Normal = XYZ.AxisX };
        var nonPlanar = EntityGeometryExtractor.Extract(line, box);
        Assert.Equal("bbox", nonPlanar.Geometry.Kind);
        Assert.Contains("non-planar-geometry", nonPlanar.Warnings);
    }
}
```

- [ ] **Step 2: Run the extractor tests and verify RED**

Run:

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --filter EntityGeometryExtractorTests --nologo
```

Expected: compile failure because geometry records and extractor do not exist.

- [ ] **Step 3: Add serializable geometry records**

Use one base record and exact derived properties:

```csharp
public abstract record CadEntityGeometry(string Kind);
public sealed record LineGeometry(
    string Kind, double[] Start, double[] End) : CadEntityGeometry(Kind);
public sealed record CircleGeometry(
    string Kind, double[] Center, double Radius, double[] Normal)
    : CadEntityGeometry(Kind);
public sealed record ArcGeometry(
    string Kind, double[] Center, double Radius,
    double StartAngle, double EndAngle, double[] Normal)
    : CadEntityGeometry(Kind);
```

Add equally exact records for LWPOLYLINE vertices, point, text, insert, bbox,
and unavailable geometry. Change `CadEntityItem.Geometry` from a dictionary to
`CadEntityGeometry`.

- [ ] **Step 4: Implement the exhaustive extractor**

Map ACadSharp properties directly:

```csharp
return entity switch
{
    Line line => Result(new LineGeometry(
        "line", Point(line.StartPoint), Point(line.EndPoint))),
    Arc arc => Result(new ArcGeometry(
        "arc", Point(arc.Center), arc.Radius,
        arc.StartAngle, arc.EndAngle, Point(arc.Normal))),
    Circle circle => Result(new CircleGeometry(
        "circle", Point(circle.Center), circle.Radius, Point(circle.Normal))),
    LwPolyline polyline => ExtractPolyline(polyline),
    Point point => Result(new PointGeometry("point", Point(point.Location))),
    TextEntity text => ExtractText(text),
    MText text => ExtractMText(text),
    Insert insert => ExtractInsert(insert),
    _ => Fallback(entity, bbox)
};
```

Check every emitted number with `double.IsFinite`, require positive
radius/height, and return `UnavailableGeometry` with
`geometry-invalid:<TYPE>` on invalid supported data. Check
`Math.Abs(Math.Abs(normal.Z) - 1) <= 1e-9` with near-zero X/Y before planar
rendering.

- [ ] **Step 5: Run focused and full .NET tests**

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --filter EntityGeometryExtractorTests --nologo
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo
```

Expected: extractor tests PASS and the existing real-DWG source-integrity test
still passes.

- [ ] **Step 6: Commit the primitive extractor**

```powershell
git add backend/src/DwgIntelligence.DwgParser/GeometryModels.cs backend/src/DwgIntelligence.DwgParser/EntityGeometryExtractor.cs backend/src/DwgIntelligence.DwgParser/IndexModels.cs backend/tests/DwgIntelligence.DwgParser.Tests/EntityGeometryExtractorTests.cs
git commit -m "feat: extract typed dwg geometry"
```

### Task 3: Layout Ownership and INSERT Attributes

**Files:**
- Create: `backend/src/DwgIntelligence.DwgParser/LayoutEntityEnumerator.cs`
- Create: `backend/src/DwgIntelligence.DwgParser/InsertAttributeExtractor.cs`
- Create: `backend/tests/DwgIntelligence.DwgParser.Tests/LayoutEntityEnumeratorTests.cs`
- Create: `backend/tests/DwgIntelligence.DwgParser.Tests/InsertAttributeExtractorTests.cs`

**Interfaces:**
- Consumes: `CadDocument.Layouts`, `Layout.AssociatedBlock.Entities`, `Layout.IsPaperSpace`, `Insert.Attributes`.
- Produces: `LocatedCadEntity(Entity Entity, string Space, string Layout, int EncounterIndex)`, `LayoutEnumerationResult`, and `InsertAttributeResult`.

- [ ] **Step 1: Write the failing in-memory layout tests**

```csharp
using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.Objects;
using CSMath;
using Xunit;

namespace DwgIntelligence.DwgParser.Tests;

public sealed class LayoutEntityEnumeratorTests
{
    [Fact]
    public void EnumeratesModelAndPaperOwnersWithoutFlatteningBlockDefinitions()
    {
        var document = new CadDocument();
        document.Entities.Add(new Line(XYZ.Zero, new XYZ(10, 0, 0)));

        var sheet = new Layout("A101");
        document.Layouts.Add(sheet);
        sheet.AssociatedBlock.Entities.Add(
            new Line(new XYZ(1, 1, 0), new XYZ(2, 2, 0))
        );

        var definition = new ACadSharp.Tables.BlockRecord("DoorDefinition");
        definition.Entities.Add(new Circle { Radius = 3 });
        document.BlockRecords.Add(definition);

        LayoutEnumerationResult result =
            LayoutEntityEnumerator.Enumerate(document);

        Assert.Contains(result.Entities,
            item => item.Space == "model" && item.Layout == "Model");
        Assert.Contains(result.Entities,
            item => item.Space == "paper" && item.Layout == "A101");
        Assert.DoesNotContain(result.Entities,
            item => ReferenceEquals(item.Entity, definition.Entities.Single()));
    }
}
```

Add a second test against
`LayoutEntityEnumerator.Deduplicate(IEnumerable<LocatedCadEntity>,
Func<Entity, string?> identity)`:

```csharp
[Fact]
public void KeepsFirstStableIdentityAndReportsDuplicate()
{
    var first = new LocatedCadEntity(new Line(), "model", "Model", 0);
    var second = new LocatedCadEntity(new Circle(), "paper", "A101", 1);

    LayoutEnumerationResult result = LayoutEntityEnumerator.Deduplicate(
        [first, second],
        entity => entity is Line ? "h:AA" : "h:AA"
    );

    Assert.Equal([first], result.Entities);
    Assert.Equal(1, result.DuplicateHandles["h:AA"]);
}
```

The production overload passes the actual nonzero entity handle as `h:<HEX>`;
the injected identity overload exists only to make collision policy
deterministic without mutating ACadSharp internal handle state.

- [ ] **Step 2: Write the failing INSERT attribute tests**

```csharp
[Fact]
public void KeepsFirstDuplicateInsertAttributeAndWarns()
{
    var block = new ACadSharp.Tables.BlockRecord("TitleBlock");
    var insert = new Insert(block);
    insert.Attributes.Add(new AttributeEntity { Tag = "SHEET", Value = "A101" });
    insert.Attributes.Add(new AttributeEntity { Tag = "SHEET", Value = "A102" });

    InsertAttributeResult result = InsertAttributeExtractor.Extract(insert);

    Assert.Equal("A101", result.Attributes["SHEET"]);
    Assert.Equal(
        ["duplicate-insert-attribute:SHEET"],
        result.Warnings
    );
}
```

- [ ] **Step 3: Run both focused classes and verify RED**

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --filter "FullyQualifiedName~LayoutEntityEnumeratorTests|FullyQualifiedName~InsertAttributeExtractorTests" --nologo
```

Expected: compile failure because both extractor modules are missing.

- [ ] **Step 4: Implement layout traversal**

Order layouts deterministically with Model first, then `TabOrder`, then name:

```csharp
IEnumerable<Layout> layouts = document.Layouts
    .OrderBy(layout => layout.IsPaperSpace ? 1 : 0)
    .ThenBy(layout => layout.TabOrder)
    .ThenBy(layout => layout.Name, StringComparer.Ordinal);
```

Yield only `layout.AssociatedBlock.Entities`. Track nonzero handles in a
`HashSet<ulong>`. Record duplicate-handle summaries instead of yielding the
same stable identity twice. Preserve layout-local encounter order for
handle-less generated IDs.

- [ ] **Step 5: Implement INSERT attribute extraction**

Trim tags only for emptiness checks but preserve the original non-empty tag.
Use `StringComparer.Ordinal`; keep the first duplicate. Use `attribute.Value`
for single-line attributes and `attribute.MText?.PlainText` when multi-line
content exists.

- [ ] **Step 6: Run focused and full .NET tests**

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --filter "FullyQualifiedName~LayoutEntityEnumeratorTests|FullyQualifiedName~InsertAttributeExtractorTests" --nologo
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo
```

- [ ] **Step 7: Commit the ownership slice**

```powershell
git add backend/src/DwgIntelligence.DwgParser/LayoutEntityEnumerator.cs backend/src/DwgIntelligence.DwgParser/InsertAttributeExtractor.cs backend/tests/DwgIntelligence.DwgParser.Tests/LayoutEntityEnumeratorTests.cs backend/tests/DwgIntelligence.DwgParser.Tests/InsertAttributeExtractorTests.cs
git commit -m "feat: index layout ownership and insert attributes"
```

### Task 4: Integrate v0.2 into the Real DWG Runtime

**Files:**
- Modify: `backend/src/DwgIntelligence.DwgParser/DwgIndexBuilder.cs`
- Modify: `backend/tests/DwgIntelligence.DwgParser.Tests/DwgIndexBuilderTests.cs`
- Modify: `agent/src/parsers/dwg/acadSharpIndexer.ts`
- Modify: `agent/tests/integration/dwg-runtime.test.ts`
- Modify: `frontend/scripts/generate-fixture.mjs`
- Modify: `frontend/public/data/export_sample.index.json`

**Interfaces:**
- Consumes: `LayoutEntityEnumerator`, `EntityGeometryExtractor`, `InsertAttributeExtractor`, and `isCadEntityIndexV02`.
- Produces: Real `export_sample.dwg` as `cad-index/v0.2` through parser CLI, gateway, MCP, and committed browser fixture.

- [ ] **Step 1: Expand the real-DWG test with literal evidence assertions**

```csharp
[Fact]
public void BuildsV02GeometryFromRealDwgWithoutChangingSource()
{
    string path = FixturePath("export_sample.dwg");
    string before = Sha256(path);

    CadIndex index = DwgIndexBuilder.Build(path);

    Assert.Equal("cad-index/v0.2", index.SchemaVersion);
    Assert.Equal(before, Sha256(path));

    var line = Assert.Single(index.Entities, entity => entity.Handle == "23D");
    var lineGeometry = Assert.IsType<LineGeometry>(line.Geometry);
    Assert.Equal([25, 50, 0], lineGeometry.Start);
    Assert.Equal([75, 50, 0], lineGeometry.End);

    var circle = Assert.Single(index.Entities, entity => entity.Handle == "23C");
    var circleGeometry = Assert.IsType<CircleGeometry>(circle.Geometry);
    Assert.Equal([50, 50, 0], circleGeometry.Center);
    Assert.Equal(50, circleGeometry.Radius, 10);

    var text = Assert.Single(index.Entities, entity => entity.Handle == "591");
    Assert.Equal("Hello", text.Text);
    Assert.IsType<TextGeometry>(text.Geometry);

    var insert = Assert.Single(index.Entities, entity => entity.Handle == "3B6");
    Assert.Equal("my_block", insert.BlockName);
    Assert.IsType<InsertGeometry>(insert.Geometry);

    Assert.Contains(index.Entities,
        entity => entity.Handle == "347"
            && entity.Geometry is BboxGeometry
            && entity.Warnings.Contains("geometry-fallback:HATCH"));
}
```

Compare the two exact LINE endpoints as an unordered pair because direction is
not part of this fixture assertion:

```csharp
double[][] endpoints = [lineGeometry.Start, lineGeometry.End];
Assert.Contains(endpoints, point => point.SequenceEqual([25d, 50d, 0d]));
Assert.Contains(endpoints, point => point.SequenceEqual([75d, 50d, 0d]));
```

- [ ] **Step 2: Run the real-DWG test and verify RED**

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --filter DwgIndexBuilderTests --nologo
```

Expected: FAIL because the builder still emits v0.1, Model-only ownership, and
empty geometry/attributes.

- [ ] **Step 3: Compose the three backend modules**

Replace `document.Entities` traversal with `LayoutEntityEnumerator`. For each
located entity:

1. compute the existing finite bbox;
2. extract typed geometry;
3. extract INSERT attributes;
4. merge warnings in stable ordinal order without duplicates;
5. add fallback, malformed, missing-handle, and duplicate-handle reasons to
   the unsupported summary;
6. use located `space` and `layout`;
7. compute model and paper counts from emitted entities.

Emit `cad-index/v0.2`. Keep `drawingId`, source hash behavior, and
`acadsharp@3.6.35` unchanged.

- [ ] **Step 4: Make the Node DWG adapter require the shared v0.2 validator**

```ts
import {
  isCadEntityIndexV02,
  type CadEntityIndexV02
} from "@dwg/contracts";

const indexByPath = new Map<string, Promise<CadEntityIndexV02>>();

export async function buildIndexFromDwgFile(
  path: string
): Promise<CadEntityIndexV02> {
  const fullPath = resolve(path);
  const existing = indexByPath.get(fullPath);
  if (existing) return existing;
  const pending = runDwgParser(fullPath).catch((error) => {
    indexByPath.delete(fullPath);
    throw error;
  });
  indexByPath.set(fullPath, pending);
  return pending;
}

if (!isCadEntityIndexV02(parsed) || parsed.source.kind !== "dwg") {
  throw new Error("DWG parser returned an incompatible cad-index document");
}
```

Do not change the DXF indexer's v0.1 output in this task.

- [ ] **Step 5: Update runtime integration assertions**

Assert:

```ts
assert.equal(index.schemaVersion, "cad-index/v0.2");
assert.equal(index.source.kind, "dwg");
assert.ok(index.entities.some(
  (entity) => entity.geometry.kind === "arc"
));
assert.ok(index.entities.some(
  (entity) => entity.space === "paper"
));
```

Assert the real paper-space entities exactly as ACadSharp returns them. For the
fixture's paper layout, use:

```ts
const paper = index.entities.filter((entity) => entity.space === "paper");
assert.equal(paper.length, index.summary.paperSpaceCount);
assert.ok(paper.every((entity) => entity.layout !== "Model"));
assert.ok(paper.some((entity) => entity.type === "VIEWPORT"));
```

- [ ] **Step 6: Regenerate the browser fixture from the unchanged DWG**

Change `generate-fixture.mjs` to require v0.2 and validate entity totals using
the parser summary:

```js
if (
  index.schemaVersion !== "cad-index/v0.2"
  || index.source?.kind !== "dwg"
  || index.entities?.length !== index.summary?.entityCount
) {
  throw new Error("Generated fixture does not match the verified DWG index contract");
}
```

Run:

```powershell
npm --prefix frontend run generate:fixture
```

- [ ] **Step 7: Run all parser and Node integration tests sequentially**

```powershell
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo
npm test
```

Expected: .NET and Node tests PASS; v0.1 DXF harness remains green.

- [ ] **Step 8: Commit the real runtime integration**

```powershell
git add backend/src/DwgIntelligence.DwgParser/DwgIndexBuilder.cs backend/tests/DwgIntelligence.DwgParser.Tests/DwgIndexBuilderTests.cs agent/src/parsers/dwg/acadSharpIndexer.ts agent/tests/integration/dwg-runtime.test.ts frontend/scripts/generate-fixture.mjs frontend/public/data/export_sample.index.json
git commit -m "feat: publish real dwg index v0.2"
```

### Task 5: SVG Geometry Math and Focused Renderers

**Files:**
- Create: `frontend/src/features/cad-viewer/geometry/geometryMath.ts`
- Create: `frontend/src/features/cad-viewer/geometry/ArcGeometry.tsx`
- Create: `frontend/src/features/cad-viewer/geometry/PolylineGeometry.tsx`
- Create: `frontend/src/features/cad-viewer/geometry/TextGeometry.tsx`
- Create: `frontend/src/features/cad-viewer/geometry/BboxFallback.tsx`
- Create: `frontend/src/features/cad-viewer/geometry/EntityGeometry.tsx`
- Create: `frontend/tests/unit/geometry-math.test.ts`

**Interfaces:**
- Consumes: `CadEntityIndexItem`, `CadEntityGeometry`, and existing entity class/highlight semantics.
- Produces: `arcPath(geometry)`, `polylinePath(geometry)`, `isPlanarNormal(normal)`, and `<EntityGeometry entity highlighted />`.

- [ ] **Step 1: Write failing pure geometry tests**

```ts
import assert from "node:assert/strict";
import test from "node:test";

import {
  arcPath,
  bulgeSegment,
  polylinePath
} from "../../src/features/cad-viewer/geometry/geometryMath.js";

test("arc path uses actual endpoints and large-arc flag", () => {
  assert.equal(
    arcPath({
      kind: "arc",
      center: [0, 0, 0],
      radius: 10,
      startAngle: 0,
      endAngle: Math.PI * 1.5,
      normal: [0, 0, 1]
    }),
    "M 10 0 A 10 10 0 1 1 0 -10"
  );
});

test("bulge one produces a semicircle instead of a line", () => {
  assert.deepEqual(
    bulgeSegment([0, 0, 0], [10, 0, 0], 1),
    { radius: 5, largeArc: 0, sweep: 1 }
  );
});

test("closed polyline emits its last-to-first segment", () => {
  const path = polylinePath({
    kind: "lwpolyline",
    vertices: [
      { point: [0, 0, 0], bulge: 0, startWidth: 0, endWidth: 0 },
      { point: [10, 0, 0], bulge: 0, startWidth: 0, endWidth: 0 },
      { point: [10, 10, 0], bulge: 0, startWidth: 0, endWidth: 0 }
    ],
    closed: true,
    elevation: 0,
    normal: [0, 0, 1]
  });
  assert.equal(path, "M 0 0 L 10 0 L 10 10 L 0 0 Z");
});
```

- [ ] **Step 2: Run the unit test and verify RED**

```powershell
node --import tsx --test frontend/tests/unit/geometry-math.test.ts
```

Expected: missing-module failure.

- [ ] **Step 3: Implement deterministic SVG math**

Normalize sweep to `[0, 2π)`. For a bulge `b`, use:

```ts
const includedAngle = 4 * Math.atan(Math.abs(b));
const chord = Math.hypot(end[0] - start[0], end[1] - start[1]);
const radius = chord / (2 * Math.sin(includedAngle / 2));
return {
  radius,
  largeArc: includedAngle > Math.PI ? 1 : 0,
  sweep: b > 0 ? 1 : 0
};
```

Return `null` for non-finite values, zero chord, nonpositive radius, or
non-planar normal. Format path numbers with a helper that rounds to 12 decimal
places and converts `-0` to `0`.

- [ ] **Step 4: Implement focused primitive components**

Define version-correlated props so TypeScript cannot pair v0.2 with a legacy
entity:

```tsx
type EntityGeometryProps =
  | {
      schemaVersion: "cad-index/v0.1";
      entity: CadEntityIndexItemV01;
      highlighted: boolean;
    }
  | {
      schemaVersion: "cad-index/v0.2";
      entity: CadEntityIndexItemV02;
      highlighted: boolean;
    };

export function EntityGeometry(props: EntityGeometryProps) {
  const { entity, highlighted } = props;
  const className = `cad-entity ${highlighted ? "highlighted" : ""}`;

  if (props.schemaVersion === "cad-index/v0.1") {
    return (
      <BboxFallback
        entity={props.entity}
        className={className}
        kind="legacy"
      />
    );
  }

  return renderV02(props.entity, className);
}
```

`renderV02` must use an exhaustive switch:

```tsx
switch (entity.geometry.kind) {
  case "line":
    return (
      <line
        className={className}
        data-handle={entity.handle}
        data-geometry-kind="line"
        x1={entity.geometry.start[0]}
        y1={entity.geometry.start[1]}
        x2={entity.geometry.end[0]}
        y2={entity.geometry.end[1]}
      />
    );
  case "circle":
    return (
      <circle
        className={className}
        data-handle={entity.handle}
        data-geometry-kind="circle"
        cx={entity.geometry.center[0]}
        cy={entity.geometry.center[1]}
        r={entity.geometry.radius}
      />
    );
  case "arc":
    return (
      <ArcGeometry
        geometry={entity.geometry}
        className={className}
        handle={entity.handle}
      />
    );
  case "lwpolyline":
    return (
      <PolylineGeometry
        geometry={entity.geometry}
        className={className}
        handle={entity.handle}
      />
    );
  case "point":
    return <circle data-geometry-kind="point" r={1.8} />;
  case "text":
    return (
      <TextGeometry
        geometry={entity.geometry}
        text={entity.text ?? ""}
        className={className}
        handle={entity.handle}
      />
    );
  case "insert":
    return <BboxFallback entity={entity} className={className} kind="insert" />;
  case "bbox":
  case "unavailable":
    return <BboxFallback entity={entity} className={className} kind={entity.geometry.kind} />;
}
```

Do not add a fabricated version field to each entity.

`TextGeometry` applies:

```tsx
transform={`translate(${x} ${y}) rotate(${-rotationDegrees}) scale(1 -1)`}
```

so text remains upright under the parent world Y inversion.

- [ ] **Step 5: Run geometry unit tests and frontend typecheck**

```powershell
node --import tsx --test frontend/tests/unit/geometry-math.test.ts
npm --prefix frontend run typecheck
```

- [ ] **Step 6: Commit the renderer modules**

```powershell
git add frontend/src/features/cad-viewer/geometry frontend/tests/unit/geometry-math.test.ts
git commit -m "feat: add typed svg geometry renderers"
```

### Task 6: Viewer Integration, Browser Loop, and Documentation

**Files:**
- Modify: `frontend/src/features/cad-viewer/CadViewer.tsx`
- Modify: `frontend/src/features/cad-viewer/styles.css`
- Create: `frontend/tests/e2e/geometry-fidelity.spec.ts`
- Modify: `frontend/tests/e2e/workspace.spec.ts`
- Modify: `frontend/tests/e2e/layer-visibility.spec.ts`
- Create: `tests/visual/artifacts/geometry-loaded-1440x900.png`
- Create: `tests/visual/artifacts/geometry-inspection-1440x900.png`
- Modify: `docs/architecture/module-boundaries.md`
- Modify: `agent/skills/dwg-intelligence/references/entity-index-schema.md`

**Interfaces:**
- Consumes: `<EntityGeometry>`, generated v0.2 index, existing hidden-layer and highlight sets.
- Produces: Real geometry in the workspace, explicit fallbacks, correct layout status, and retained visual evidence.

- [ ] **Step 1: Write the failing geometry Playwright test**

```ts
import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const artifacts = resolve("../tests/visual/artifacts");

test("renders real v0.2 geometry and explicit fallbacks", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/providers", (route) =>
    route.fulfill({ contentType: "application/json", body: '{"providers":[]}' })
  );
  await page.goto("/");

  await expect(page.locator('[data-handle="23D"]'))
    .toHaveAttribute("data-geometry-kind", "line");
  await expect(page.locator('[data-handle="23E"]'))
    .toHaveAttribute("data-geometry-kind", "arc");
  await expect(page.locator('[data-handle="239"]'))
    .toHaveAttribute("data-geometry-kind", "lwpolyline");
  await expect(page.locator('[data-handle="591"]'))
    .toHaveAttribute("data-geometry-kind", "text");
  await expect(page.locator('[data-handle="347"]'))
    .toHaveAttribute("data-geometry-kind", "bbox");
  await expect(page.locator('[data-handle="3D6"]'))
    .toHaveAttribute("data-geometry-kind", "bbox");

  await mkdir(artifacts, { recursive: true });
  await page.screenshot({
    path: resolve(artifacts, "geometry-loaded-1440x900.png"),
    fullPage: true
  });
});
```

Add a second test that clicks the `0` layer eye, asserts every displayed Model
entity on that layer disappears, restores it, selects handle `23E`, and asserts
the ARC receives `highlighted`.

- [ ] **Step 2: Run focused Playwright on isolated ports and verify RED**

```powershell
$env:DWG_FRONTEND_PORT='4174'
$env:DWG_GATEWAY_PORT='4318'
npm --prefix frontend exec playwright test tests/e2e/geometry-fidelity.spec.ts --project chromium
```

Expected: FAIL because the current viewer has no `data-geometry-kind` and still
uses bbox approximations.

- [ ] **Step 3: Replace `EntityShape` with the feature renderer**

The current slice has no layout switcher. Keep Paper Space in the index and AI
evidence, but display only the `Model` layout so paper viewports are not
overlaid on Model geometry. Narrow the index before mapping so the props remain
correlated:

```tsx
const renderedEntities = index.schemaVersion === "cad-index/v0.2"
  ? index.entities
      .filter((entity) =>
        entity.layout === "Model" && !hiddenLayers.has(entity.layer)
      )
      .map((entity) => (
        <EntityGeometry
          key={entity.id}
          schemaVersion="cad-index/v0.2"
          entity={entity}
          highlighted={Boolean(
            entity.handle && highlightSet.has(entity.handle)
          )}
        />
      ))
  : index.entities
      .filter((entity) =>
        entity.layout === "Model" && !hiddenLayers.has(entity.layer)
      )
      .map((entity) => (
        <EntityGeometry
          key={entity.id}
          schemaVersion="cad-index/v0.1"
          entity={entity}
          highlighted={Boolean(
            entity.handle && highlightSet.has(entity.handle)
          )}
        />
      ));
```

Remove the old bbox/type switch from `CadViewer.tsx`. Keep bbox aggregation for
fit view using Model-layout boxes only. The status remains `Model space`; do
not introduce an inert layout selector.

- [ ] **Step 4: Style real text and explicit fallbacks**

Keep the existing white/light workspace. Add distinct, subtle fallback
dashing without changing highlight visibility:

```css
.cad-entity.geometry-fallback {
  stroke-dasharray: 2 1.5;
  opacity: 0.72;
}

.cad-text {
  fill: #334d5b;
  stroke: none;
  font-family: "Segoe UI", sans-serif;
  pointer-events: visiblePainted;
}

.cad-text.highlighted {
  fill: #00a6c8;
}
```

Keep the existing entity colors `#334d5b` and `#00a6c8`; do not introduce a
second feature color token.

- [ ] **Step 5: Remove hardcoded v0.1 entity totals from browser tests**

Read `summary.modelSpaceCount` from the generated fixture instead of assuming
22. Keep exact handle checks for stable real entities. Paper Space count is
tested at the index/runtime boundary, not as overlaid SVG. Update screenshot
baselines only after semantic assertions pass.

- [ ] **Step 6: Run focused browser tests and capture inspection evidence**

```powershell
$env:DWG_FRONTEND_PORT='4174'
$env:DWG_GATEWAY_PORT='4318'
npm --prefix frontend exec playwright test tests/e2e/geometry-fidelity.spec.ts tests/e2e/layer-visibility.spec.ts tests/e2e/inspection-run.spec.ts --project chromium
```

Capture the highlighted inspection state to
`tests/visual/artifacts/geometry-inspection-1440x900.png`.

- [ ] **Step 7: Inspect both PNGs directly**

Open both files with the image viewer and check:

- ARC endpoints and sweep are visibly not full ellipses;
- circles remain circular;
- LWPOLYLINE closure and bulges are continuous;
- `Hello`, `Goodbye`, and MTEXT are upright;
- HATCH and ELLIPSE remain visibly explicit fallbacks;
- layer hide/restore leaves no orphan geometry;
- selected geometry highlight is readable;
- no clipping, overflow, overlap, or dark-theme regression.

For each observed defect, first add a failing geometry-math or Playwright
assertion, then fix, recapture, and reinspect.

- [ ] **Step 8: Update architecture and agent evidence documentation**

Document:

- v0.2 typed geometry kinds and v0.1 migration acceptance;
- parser/layout/frontend ownership;
- radians, drawing units, and stable handles;
- INSERT transform/attribute evidence without block expansion;
- Model/Paper Space fields;
- explicit `bbox` and `unavailable` limitations.

- [ ] **Step 9: Run the complete sequential verification matrix**

```powershell
npm test
npx tsc --noEmit
npm --prefix frontend run typecheck
npm --prefix frontend run build
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo
$env:DWG_FRONTEND_PORT='4174'
$env:DWG_GATEWAY_PORT='4318'
npm --prefix frontend exec playwright test --project chromium
npm audit --audit-level=high
git diff --check
git status --short
```

Expected:

- all Node tests pass;
- both TypeScript checks pass;
- frontend production build passes;
- all .NET tests pass;
- all Playwright tests pass on isolated ports;
- audit reports zero high/critical vulnerabilities;
- no whitespace errors;
- only intentional v0.2 files and retained PNGs are modified.

- [ ] **Step 10: Commit the verified browser loop**

```powershell
git add frontend/src/features/cad-viewer/CadViewer.tsx frontend/src/features/cad-viewer/styles.css frontend/tests/e2e/geometry-fidelity.spec.ts frontend/tests/e2e/workspace.spec.ts frontend/tests/e2e/layer-visibility.spec.ts tests/visual/artifacts/geometry-loaded-1440x900.png tests/visual/artifacts/geometry-inspection-1440x900.png docs/architecture/module-boundaries.md agent/skills/dwg-intelligence/references/entity-index-schema.md
git commit -m "feat: render and verify real cad geometry"
```

## Self-Review

- Spec coverage: typed supported primitives, POINT, TEXT/MTEXT, INSERT
  transform/attributes, Model/Paper Space traversal, stable identity,
  non-planar rejection, explicit ELLIPSE/HATCH fallback, AI evidence
  boundaries, layer behavior, Playwright, PNG inspection, and full regression
  commands each map to a task.
- Intentional exclusions: block expansion, nested block rendering, ELLIPSE,
  HATCH interiors, DIMENSION, table cells, layout switching, and arbitrary 3D
  projection are not implemented by any task.
- Type consistency: the .NET and TypeScript geometry kinds and property names
  match the approved spec; the Node DWG adapter returns v0.2 while the public
  `CadEntityIndex` remains a v0.1/v0.2 union.
- Test integrity: real-DWG expectations use stable handles and literal CAD
  values; geometry-math expectations are independent analytic results; browser
  totals are no longer coupled to the former 22-model-entity assumption.
- Boundary integrity: contracts contain DTOs and validators only, backend
  modules contain ACadSharp knowledge only, and frontend geometry modules
  contain SVG knowledge only.
- Placeholder scan: the plan contains no unspecified implementation or error
  handling step.

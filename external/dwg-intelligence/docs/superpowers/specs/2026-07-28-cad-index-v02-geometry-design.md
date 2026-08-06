# CAD Index v0.2 Geometry Fidelity Design

## Goal

Make a real DWG directly understandable to both the browser viewer and AI
inspection runtime by publishing deterministic, typed geometry, text, insert
attributes, and Model/Paper Space membership in `cad-index/v0.2`.

## Scope

This pass adds typed evidence and real SVG rendering for:

- `LINE`;
- `ARC`;
- `CIRCLE`;
- `LWPOLYLINE`, including bulge segments;
- `POINT`;
- `TEXT` and `MTEXT`;
- `INSERT` position, rotation, scale, block name, and attribute values.

It also enumerates entities through their associated layouts and identifies
Model Space versus Paper Space.

`ELLIPSE`, `HATCH`, `DIMENSION`, table-cell extraction, block-reference
expansion, nested block rendering, and arbitrary 3D projection remain outside
this pass. Unsupported entities retain their deterministic bounding boxes and
receive an explicit fallback geometry kind and warning; the parser must not
invent missing geometry.

## Chosen Approach

Publish `cad-index/v0.2` as a strict discriminated geometry contract while
keeping the TypeScript reader compatible with existing `cad-index/v0.1`
fixtures during migration.

The rejected alternatives are:

1. filling the existing untyped v0.1 `geometry` object, which would conceal a
   contract change and preserve unsafe runtime casts;
2. publishing a second geometry sidecar, which would duplicate drawing,
   entity, cache, and session identities before they provide independent
   value.

The parser produces v0.2 only. Consumers accept the v0.1 and v0.2 index union,
then narrow by `schemaVersion`. The viewer renders typed v0.2 geometry first
and uses bounding-box fallback only for v0.1 or an explicitly unsupported v0.2
entity.

## Contract

All coordinates use drawing units. Angles use radians. Three-dimensional
points remain three-tuples even though this viewer renders the XY plane.

```ts
type CadPoint3 = [number, number, number];

type CadEntityGeometry =
  | { kind: "line"; start: CadPoint3; end: CadPoint3 }
  | {
      kind: "circle";
      center: CadPoint3;
      radius: number;
      normal: CadPoint3;
    }
  | {
      kind: "arc";
      center: CadPoint3;
      radius: number;
      startAngle: number;
      endAngle: number;
      normal: CadPoint3;
    }
  | {
      kind: "lwpolyline";
      vertices: Array<{
        point: CadPoint3;
        bulge: number;
        startWidth: number;
        endWidth: number;
      }>;
      closed: boolean;
      elevation: number;
      normal: CadPoint3;
    }
  | { kind: "point"; position: CadPoint3 }
  | {
      kind: "text";
      insertionPoint: CadPoint3;
      alignmentPoint: CadPoint3 | null;
      height: number;
      rotation: number;
      width: number | null;
    }
  | {
      kind: "insert";
      insertionPoint: CadPoint3;
      rotation: number;
      scale: CadPoint3;
      normal: CadPoint3;
    }
  | { kind: "bbox"; reason: string }
  | { kind: "unavailable"; reason: string };
```

`CadEntityIndexItemV02` keeps the stable v0.1 evidence fields: `id`, `handle`,
`type`, `layer`, `space`, `layout`, `bbox`, `text`, `blockName`, `attributes`,
and `warnings`. Its `geometry` is `CadEntityGeometry` instead of an arbitrary
object. `CadEntityIndexV02.schemaVersion` is exactly `cad-index/v0.2`.

`CadEntityIndexV01` remains available only as a legacy input type.
`CadEntityIndex` is the public v0.1/v0.2 union. New code must narrow the union
before reading typed geometry.

For `TEXT` and `MTEXT`, the human-readable value remains in the top-level
`text` property so search and AI evidence do not depend on renderer details.
For `INSERT`, the referenced block remains in `blockName` and attribute tags
and values remain in the top-level `attributes` map.

## Parser Architecture

`DwgIndexBuilder` remains the composition root and delegates focused work:

```text
DwgIndexBuilder
  -> LayoutEntityEnumerator
  -> EntityGeometryExtractor
  -> InsertAttributeExtractor
  -> CadIndex v0.2 serializer
```

`LayoutEntityEnumerator` iterates each ACadSharp layout's associated block
record and yields an entity with its normalized space and layout name.
Model-layout entities become `space: "model", layout: "Model"`. Entities in
paper layouts become `space: "paper"` with the actual layout name.

The enumerator de-duplicates repeated references by stable handle. A
handle-less entity uses one parser-run identity based on layout and encounter
order. Block-definition contents are not emitted as top-level drawing
entities; only entities owned by a Model/Paper layout are indexed.

`EntityGeometryExtractor` uses an exhaustive type switch for the supported
ACadSharp entities. It returns a typed geometry value plus zero or more
warnings. It never reads frontend types and never performs SVG conversion.

`InsertAttributeExtractor` maps non-empty attribute tags to their text values.
Duplicate tags are deterministic: the first value is retained and a
`duplicate-insert-attribute:<tag>` warning is added.

## Geometry Rules

- Every numeric value must be finite.
- Circle and arc radii and text heights must be greater than zero.
- A malformed supported entity produces `kind: "unavailable"` and a specific
  warning instead of partial or fabricated coordinates.
- Unsupported entity types with a finite bounding box produce
  `kind: "bbox"` and `geometry-fallback:<TYPE>`.
- Unsupported entity types without a finite bounding box produce
  `kind: "unavailable"` and the existing bounding-box warning.
- Planar rendering supports normals parallel to positive or negative Z.
  Other normals preserve their raw evidence but receive
  `non-planar-geometry` and render with the bounding-box fallback.
- LWPOLYLINE bulges are preserved in the contract. Zero bulge is a straight
  segment; nonzero bulge is converted by a pure frontend geometry helper.
- A closed LWPOLYLINE includes a final segment from the last vertex to the
  first vertex.
- INSERT geometry describes its transform and attributes, not expanded block
  contents. The viewer renders the existing finite bounding box plus an
  insertion marker so it does not falsely claim nested-block fidelity.

## Frontend Architecture

The CAD viewer delegates geometry rendering:

```text
CadViewer
  -> EntityGeometry
       -> ArcGeometry
       -> PolylineGeometry
       -> TextGeometry
       -> BboxFallback
```

`EntityGeometry` owns schema-version narrowing, shared entity classes,
`data-handle`, `data-geometry-kind`, highlighting, and fallback selection.
Primitive components receive typed geometry only.

`geometryMath.ts` is a React-free module for:

- normalizing clockwise/counter-clockwise arc sweep;
- converting arc geometry to one SVG path;
- converting a bulge segment to SVG arc parameters;
- rejecting non-finite or non-planar inputs.

The existing world-to-SVG Y-axis inversion remains in one parent `<g>`
transform. Text receives a local inverse-Y transform so glyphs remain upright
while its insertion point stays in drawing coordinates.

Layer visibility filters the entity list before geometry rendering, so every
new primitive follows the existing layer-eye behavior without a second state
store. Selection, search highlights, inspection evidence, and stable handles
remain independent of visual geometry.

The status bar reports the active layout and Model/Paper Space instead of
hardcoding Model Space. Layout switching is not added in this pass; the first
available Model layout remains the displayed default.

## AI Evidence Flow

The deterministic index remains the source of truth:

```text
DWG
  -> ACadSharp
  -> cad-index/v0.2
       -> browser SVG
       -> inspection checks
       -> provider attachment/context
```

An AI provider receives coordinates, text, block attributes, space, layout,
handle, layer, and warnings through the same serialized index. It does not
infer geometry from a screenshot and it does not receive parser objects.
Provider explanations remain separate from deterministic CAD evidence.

## Error Handling

- Layout traversal failure names the layout and fails the parser process; it
  must not silently relabel Paper Space as Model Space.
- A single malformed entity remains indexable when its handle, layer, and
  bounding box are available.
- Geometry fallback increments `unsupportedCount` with a stable reason.
- Duplicate handles across layouts keep the first entity and add an
  unsupported summary entry for the duplicate.
- Contract validation rejects unknown v0.2 geometry kinds, wrong tuple sizes,
  non-finite numbers, and missing required fields.
- The frontend never throws for a valid `bbox` or `unavailable` geometry;
  unavailable entities remain searchable and inspectable.

## Module Boundaries

- `packages/contracts` owns serializable CAD DTOs and validators only.
- `backend` owns ACadSharp types, layout traversal, extraction, and warnings.
- `frontend/features/cad-viewer` owns SVG conversion and presentation.
- `frontend/shared/api` transports the index without geometry interpretation.
- inspection and provider modules consume public contracts and may not import
  parser or viewer internals.
- No module imports from `clone/`; local reference repositories are research
  evidence only.

## Verification

### Parser and contract

- Real `export_sample.dwg` tests assert exact representative LINE, ARC,
  CIRCLE, LWPOLYLINE, POINT, TEXT/MTEXT, and INSERT values.
- A generated or checked-in multi-layout fixture proves Model/Paper Space
  classification and prevents duplicate indexing.
- INSERT tests assert block name, position, rotation, XYZ scale, and attribute
  tag/value extraction.
- Contract tests accept a known v0.1 fixture and a valid v0.2 fixture and
  reject malformed discriminated geometry.

### Viewer

- Unit tests assert large-arc and sweep flags for ARC paths.
- Unit tests assert straight, bulged, and closed LWPOLYLINE paths.
- Component or Playwright assertions verify `data-geometry-kind`, stable
  handles, upright text, highlights, and layer hide/restore.
- The fixture's supported entities no longer render from bounding-box
  approximations.
- ELLIPSE and HATCH visibly retain explicit fallback behavior.

### Full loop

1. run focused RED/GREEN tests for each slice;
2. run all Node tests;
3. run TypeScript typecheck and frontend production build;
4. run the .NET parser suite against real DWG fixtures;
5. run Playwright on isolated ports;
6. capture the 1440x900 loaded and inspection states;
7. inspect both PNGs for incorrect arcs, inverted text, clipping, overlap,
   layer-toggle regressions, and fallback leakage;
8. fix every visual defect through a failing assertion before recapture.

## Completion Criteria

- The parser emits `cad-index/v0.2`.
- The shared contract provides typed v0.2 geometry and explicit v0.1 input
  compatibility.
- Model and Paper Space counts come from real layout ownership.
- Supported fixture entities expose finite, typed geometry.
- INSERT exposes its transform and attribute values without pretending that
  nested block geometry was expanded.
- The viewer renders LINE, ARC, CIRCLE, LWPOLYLINE, POINT, TEXT, and MTEXT from
  geometry rather than bounding boxes.
- Layer visibility, search, selection, findings, and evidence continue to use
  stable indexed entities.
- All automated suites pass and retained 1440x900 PNGs are manually inspected.

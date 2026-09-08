# Skill-First CAD Editing, Export, and Workspace Design

## Goal

Evolve Click Around from a read-only DWG intelligence companion into a
maintainable, skill-first CAD workspace that can inspect, propose, preview,
approve, save, and verify deterministic drawing changes.

The product keeps its Claude-style three-panel workspace, makes the left
navigation readable at real project scale, and exposes the same CAD
capabilities to the browser, CLI, MCP, and future agent protocols.

## Product Principles

1. Skills orchestrate stable capabilities; they do not contain CAD engine
   internals.
2. Every AI-proposed change becomes a typed deterministic command before it
   can affect a document.
3. The original DWG or DXF is never overwritten. Editing produces a new file
   through Save As.
4. A saved drawing is not considered valid until the product reopens and
   verifies it.
5. Module consumers use public package entrypoints and versioned contracts,
   never another module's private source tree.
6. UI, CLI, MCP, and agents execute the same application capabilities and
   receive the same evidence.
7. Entity-level results remain grounded in handle, type, layer, layout, and
   bounding box rather than language-model geometry claims.

## Scope

### Editing MVP

- create and update layer name, color, visibility, and lock state;
- replace TEXT and MTEXT content;
- move, copy, and delete LINE, CIRCLE, ARC, and LWPOLYLINE entities;
- preview command batches before application;
- show before/after diffs;
- support transaction-level undo and redo;
- save a verified copy as supported DWG or DXF;
- export JSON, CSV, PDF, and SVG reports.

### Skill MVP

- inspect a drawing;
- extract a schedule or table-like result;
- compare two drawings;
- edit layers;
- edit text;
- transform supported entities;
- export a drawing or report.

### Workspace MVP

- resizable and collapsible left sidebar;
- Project, Sessions, and Skills navigation tabs;
- readable drawing, layout, layer, and entity-type hierarchy;
- right-side Preview, Findings, Changes, and Export tabs;
- approval and verification status visible before Save As.

## Deferred Scope

- in-place source-file overwrite;
- direct DIMENSION, HATCH, BLOCK-definition, XREF, proxy-object, or arbitrary
  3D editing;
- collaborative cloud editing;
- cloud CAD storage;
- automatic destructive agent execution;
- treating ACadSharp objects as public contracts;
- bundling provider credentials or OAuth session data.

Deferred entity types remain inspectable when the index contains evidence, but
editing commands targeting them fail before mutation with an explicit
unsupported-capability result.

## Chosen Architecture

Use a command-centered, skill-first architecture:

```text
Agent or UI
  -> Skill Registry
    -> Skill Workflow
      -> CAD Capability API
        -> Query or EditCommand
          -> CadDocument transaction
            -> Preview and approval
              -> writer adapter
                -> reopen and verify
```

Rejected alternatives:

1. Directly editing ACadSharp `CadDocument` objects from UI or skills would
   couple every consumer to one writer and make undo, testing, and future
   engine replacement difficult.
2. Sidecar-only overlays are safe but cannot satisfy the requirement to
   produce a modified CAD file.
3. A single large CAD runtime package would preserve the current coupling and
   prevent modules from being extracted into other repositories.

## Repository Structure

```text
apps/
  workspace/                    Browser UI and composition only

packages/
  contracts/                    Public CAD and application DTOs
  skill-contracts/              Skill manifest, permission, input/output DTOs
  test-kit/                     Shared fixture and conformance helpers

modules/
  cad-document/                 Engine-neutral editable document model
  cad-query/                    Search, extraction, quantity, and comparison
  cad-edit/                     Commands, transactions, diff, undo, redo
  cad-export/                   JSON, CSV, PDF, and SVG exports
  cad-capabilities/             Stable application-facing capability API
  cad-io-acadsharp/             Private ACadSharp reader/writer adapter
  skill-runtime/                Skill discovery, validation, and execution
  cad-runtime/                  Provider, HTTP, MCP, and orchestration adapters
  dwg-parser/                   Transitional existing .NET parser host

skills/
  inspect-drawing/
  extract-schedule/
  compare-drawings/
  edit-layers/
  edit-text/
  transform-entities/
  export-drawing/

tests/
  fixtures/
  contracts/
  skills/
  integration/
  roundtrip/
  visual/
```

Every independently reusable TypeScript module has its own `package.json`,
public `src/index.ts`, README, unit tests, and explicit dependency list. A
.NET module has the equivalent `.csproj`, public process contract, README, and
tests. The existing repository boundary checker rejects deep imports into
another module's `src/**`. `packages/contracts` and
`packages/skill-contracts` contain serializable types and validators only.

The current `modules/dwg-parser` is not a second long-term CAD engine. During
migration it remains the compatibility process host while its ACadSharp
reading code moves behind `cad-io-acadsharp`. After all parser and writer
entrypoints use the adapter, `dwg-parser` becomes a thin executable host or is
removed. There must never be two independent ACadSharp mapping
implementations. The .NET boundary remains a process and serialized-contract
boundary rather than a TypeScript source import.

## Domain and Command Model

`cad-document` owns an engine-neutral document snapshot containing:

- document identity and source fingerprint;
- drawing version and units;
- layouts and spaces;
- layers and table records required by the MVP;
- supported entities with stable handle identity;
- warnings for unsupported or partially preserved content.

`cad-edit` owns typed commands:

```ts
type CadEditCommand =
  | CreateLayerCommand
  | UpdateLayerCommand
  | ReplaceTextCommand
  | MoveEntityCommand
  | CopyEntityCommand
  | DeleteEntityCommand;
```

Every command includes:

- command and transaction UUIDs;
- target document revision;
- target handles or stable layer identity;
- validated parameters in drawing units;
- expected preconditions;
- actor and originating skill metadata;
- reversible before-state required for undo;
- deterministic result and warning records.

Commands never accept arbitrary code, parser objects, filesystem paths, or
provider session values. A transaction either applies every command to a
working document clone or applies none.

## Capability API

`cad-capabilities` is the only application layer used by UI and skills. Its
initial surface is:

```text
document.open
document.describe
query.layers
query.entities
query.text
query.schedule
query.compare
edit.preview
edit.apply
edit.undo
edit.redo
export.report
export.drawing
verification.get
```

MCP names may retain the existing `cad.*` convention, but MCP is an adapter
over capabilities rather than the capability implementation. A future agent
protocol can add another adapter without changing editing or export modules.

## Skill Packages

Each skill directory contains:

```text
<skill-name>/
  SKILL.md
  manifest.json
  workflows/
  tests/
  examples/
```

The manifest declares:

- stable skill ID and semantic version;
- human-readable purpose;
- compatible capability-contract version;
- required capabilities;
- input and output JSON Schemas;
- required permissions;
- supported CAD formats and entity types;
- failure and limitation codes.

Skill permissions are:

- `read`;
- `propose-edit`;
- `write-copy`;
- `export`.

Skills cannot import module internals or call ACadSharp directly. Editing
skills produce a proposed command batch. The runtime validates the manifest,
input, capability availability, command batch, permissions, and output.

## Save As and Verification

```text
Open source read-only
  -> fingerprint source
  -> apply commands to working snapshot
  -> generate preview and diff
  -> obtain approval
  -> write unique temporary sibling file
  -> flush and close writer
  -> reopen output with an independent reader instance
  -> verify invariants and intended changes
  -> move temporary file to user-selected destination
```

The writer never receives the source path as its output path. Existing output
paths require an explicit replace decision outside the MVP.

Verification checks:

- output format and version are readable;
- source fingerprint is unchanged;
- output document identity and units are valid;
- intended layer and entity changes are present;
- unaffected indexed handles retain type, layer, and finite bbox evidence;
- entity-count deltas match the command batch;
- no new unsupported or parser warnings appear unless explicitly allowed;
- output can be indexed through the normal runtime.

Failure closes the writer, quarantines or removes the temporary output, keeps
the command transaction and diagnostic summary, and reports no successful
save. Raw CAD bytes and provider responses are not placed in error logs.

Because ACadSharp supports DWG writing for specific versions and has had
version-specific compatibility defects, supported output versions are an
allowlist proven by repository fixtures. DXF is the fallback Save As format
when a source DWG version is not yet allowlisted.

## Export Architecture

`cad-export` consumes public document, query, diff, and verification DTOs.

- JSON: versioned complete evidence or change report;
- CSV: flattened schedules, quantities, layers, or entity selections;
- PDF: review report with drawing metadata, findings, changes, and warnings;
- SVG: current supported 2D preview with explicit fallback markers;
- DWG/DXF: delegated exclusively to `cad-io-acadsharp`.

Report export and drawing export are separate capabilities. Downloading an
index JSON is not labeled as downloading a drawing.

## Workspace Layout

The application retains three primary panels:

```text
Left navigation 280-420 px | Conversation min 500 px | Artifact 420 px-flex
```

The left panel has top-level tabs:

- Project: drawing, layout, layer, and entity-type hierarchy;
- Sessions: sessions grouped by project and drawing;
- Skills: installed skills, compatibility, permissions, and recent runs.

Project behavior:

- sticky search;
- resizable width persisted as a preference;
- full collapse to a compact rail;
- visible indentation and active-row treatment;
- eye, lock, color, and entity count aligned per layer row;
- ellipsis and tooltip for long names;
- independent scroll area that does not overlap Recents or the footer;
- compact overlay drawer at narrow widths.

The right artifact panel has:

- Preview;
- Findings;
- Changes;
- Export.

Changes owns command-batch review, before/after evidence, warning display,
undo, redo, approval, and rejection. Export shows available formats, selected
output version, destination, and post-write verification result.

The conversation panel explains and proposes operations but does not own CAD
mutation state.

## Error Handling

- Schema, permission, revision, and target checks happen before mutation.
- Missing or ambiguous handles fail with structured evidence.
- Unsupported entities fail the relevant command without degrading them to
  approximate geometry.
- Concurrent edits use optimistic document revisions; stale transactions must
  be previewed again.
- A transaction is atomic in memory and in command history.
- Undo and redo fail safely if the target revision no longer matches.
- Writer and verification errors expose bounded, sanitized summaries.
- Cancellation propagates from UI or agent through capability execution.
- Skill incompatibility is visible before the skill can run.

## Testing Strategy

### Contracts and boundaries

- validate every CAD command, result, manifest, permission, and export DTO;
- reject deep imports and forbidden dependency directions;
- prove UI, CLI, MCP, and skill runtime share the same capability contracts;
- install every skill independently in the conformance harness.

### Module tests

- command preconditions, atomicity, diff, undo, and redo;
- layer and supported-entity mutations;
- schedule, quantity, and comparison determinism;
- export formatting and formula-injection-safe CSV;
- path containment and output-name validation;
- skill discovery, version negotiation, and permission denial.

### Real CAD round trips

- preserve immutable source SHA-256;
- edit checked-in DXF and DWG copies;
- reopen every written result;
- compare expected handle, type, layer, layout, count, text, and bbox changes;
- test each allowlisted DWG version separately;
- reject unsupported versions before writing;
- exercise corrupted, proxy, XREF, font, and codepage warning cases;
- verify output with both the writer adapter and normal indexing path.

### Integration and agent tests

- run capability workflows through CLI and MCP;
- run every skill against real fixtures;
- prove agent output alone cannot bypass command validation or approval;
- test multi-skill inspect, edit, verify, and export workflows;
- cap stdout, stderr, prompt, response, and artifact retention as in the
  existing OAuth privacy controls.

### Browser and visual loop

- exercise Project, Sessions, and Skills tabs;
- verify layer visibility, lock display, hierarchy, resize, collapse, and
  responsive overlay;
- preview a command batch and inspect before/after evidence;
- approve, reject, undo, redo, Save As, and export;
- capture loaded, skill-selected, change-preview, save-verified,
  layer-hidden, narrow, and dark-theme PNGs;
- inspect retained PNGs for clipping, overlap, unreadable hierarchy, incorrect
  CAD changes, and sensitive content;
- convert every discovered regression into an automated assertion before
  recapture.

## Delivery Sequence

1. Freeze contracts, package boundaries, fixture hashes, and legacy behavior.
2. Create `skill-contracts`, `test-kit`, and boundary enforcement.
3. Extract engine-neutral `cad-document` and place existing ACadSharp mapping
   behind `cad-io-acadsharp` without duplicating `dwg-parser` behavior.
4. Add the read-only `cad-capabilities` surface and migrate existing tools.
5. Add `cad-edit` command, transaction, diff, undo, redo, and write
   capabilities.
6. Add `skill-runtime`, read-only skills, and their loopback listing endpoint.
7. Add the left-panel Project, Sessions, and Skills layout.
8. Add edit preview, Changes UI, and a disabled capability-driven Export
   shell without file writing.
9. Add DXF Save As and round-trip verification.
10. Add allowlisted DWG Save As after fixture proof.
11. Add report exports and enable the Export UI.
12. Add editing skills and full agent approval workflows.
13. Run the complete automated, CLI, MCP, OAuth, real-CAD, and PNG review
    loop before each integration milestone.

Each sequence item is independently gated and must leave the repository green.
Folder moves, contract changes, writer behavior, and UI changes are not bundled
into one unreviewable commit.

## Completion Criteria

- The repository exposes the documented packages and modules with enforced
  public boundaries.
- Skills are discoverable, versioned, permissioned, independently testable,
  and composed only from stable capabilities.
- The left sidebar remains readable and functional at supported widths.
- All MVP commands support deterministic preview, diff, atomic apply,
  undo, and redo.
- The original CAD fixture bytes never change.
- DXF and allowlisted DWG Save As outputs pass independent reopen and
  invariant verification.
- JSON, CSV, PDF, and SVG exports are correctly labeled and validated.
- UI, CLI, MCP, and agent workflows use the same capabilities.
- Real drawing tests and Playwright tests pass.
- Retained PNGs are manually inspected and contain no sensitive live-provider
  content.

## Technical References

- ACadSharp official repository and supported reader/writer matrix:
  <https://github.com/DomCR/ACadSharp>
- ACadSharp DWG writer compatibility history:
  <https://github.com/DomCR/ACadSharp/issues/315>
- ezdxf official repository as a DXF interoperability reference:
  <https://github.com/mozman/ezdxf>
- MCP TypeScript SDK capabilities and form elicitation:
  <https://github.com/modelcontextprotocol/typescript-sdk/blob/v1.29.0/docs/capabilities.md>

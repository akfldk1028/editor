# DWG Intelligence Product Design

Date: 2026-07-27

## Goal

Build a local-first AI CAD drawing checker for Korean architecture offices.
The product reads real DXF/DWG objects, creates a stable object index, lets an
agent call deterministic CAD tools, and links every conclusion to drawing
evidence such as entity ID, handle, layer, type, layout, and bounding box.

The language model must not estimate geometry or invent drawing contents.
Parsing, search, measurements, and rule evaluation are handled by CAD code.

## Product Loop

```text
open DXF/DWG
  -> parse locally
  -> build cad-index/v0.1
  -> run deterministic checks
  -> orchestrator selects specialist agents and CAD tools
  -> return evidence-backed findings
  -> select/highlight/zoom matching entities
  -> save a sidecar inspection report
```

The source drawing remains read-only. Results are stored as sidecar JSON and
viewer overlay state.

## Architecture

### Frontend

The frontend is a desktop-oriented light workspace:

```text
+---------------------------------------------------------------+
| project | drawing | index status | layout | search             |
+----------------+------------------------------+----------------+
| drawing tree   |                              | agent tabs     |
| layers         |          CAD viewer          | conversation   |
| layouts        |                              | tool activity  |
| objects        |                              | subagent state |
+----------------+------------------------------+----------------+
| findings | evidence | warnings | unsupported | report          |
+---------------------------------------------------------------+
```

The center viewer receives the most space. The left panel navigates drawings,
layouts, layers, and indexed objects. The right panel follows the Claudian
interaction model: multiple conversations, explicit tool activity, file and
agent mentions, and visible specialist-agent status. Clicking a finding selects
and zooms its entities. The bottom evidence panel shows handles, layers, types,
bounds, rule inputs, warnings, and source layout.

The UI uses a white background, restrained neutral colors, compact controls,
Lucide icons, resizable panels, and no marketing landing page.

### Agent Orchestration

The product exposes logical specialist agents behind one orchestrator:

- `orchestrator`: decomposes the request and owns the final response.
- `drawing-index-agent`: ensures the requested drawing and index are ready.
- `search-agent`: performs layer, type, block, text, and object lookup.
- `rule-check-agent`: runs deterministic drawing checks and measurements.
- `evidence-agent`: rejects unsupported claims and attaches entity evidence.
- `viewer-agent`: converts evidence IDs into selection, highlight, and zoom.
- `report-agent`: writes the inspection sidecar and limitations.

Specialists communicate using typed task and result envelopes. Independent
checks may run concurrently, but parsing, index construction, evidence
validation, and final reporting remain ordered. Specialist agents never parse
geometry themselves and never modify source drawings.

The first implementation uses the same process and shared runtime. Separate
processes are deferred until profiling shows isolation is necessary.

### CAD Core

The normalized contract remains `cad-index/v0.1`.

- DXF adapter: TypeScript and `dxf-parser`.
- DWG adapter: local .NET service using `ACadSharp`.
- Viewer adapter: initially DXF-compatible, behind a selection/zoom interface.
- MCP adapter: TypeScript SDK v1 over stdio for local process-spawned clients.

The Node MCP process owns drawing sessions and calls parser adapters. The .NET
DWG adapter outputs the same normalized index used by the DXF adapter.

Unsupported, proxy, AEC, XRef, missing-font, codepage, invalid-bbox, and
partial-parse conditions are data in the result, not silent failures.

## Repository Structure

```text
DWG/
|-- frontend/
|   |-- src/
|   |   |-- app/
|   |   |-- features/
|   |   |   |-- drawing-explorer/
|   |   |   |-- cad-viewer/
|   |   |   |-- agent-chat/
|   |   |   |-- inspection-results/
|   |   |   `-- evidence-panel/
|   |   `-- shared/
|   `-- tests/
|-- agent/
|   |-- src/
|   |   |-- orchestration/
|   |   |   |-- orchestrator.ts
|   |   |   `-- agents/
|   |   |-- application/cad-tools/
|   |   |-- domain/cad-index/
|   |   |-- parsers/dxf/
|   |   `-- mcp/
|   |-- harness/
|   |-- fixtures/
|   `-- tests/
|-- backend/
|   |-- src/DwgIntelligence.DwgParser/
|   `-- tests/DwgIntelligence.DwgParser.Tests/
|-- contracts/
|   |-- cad-index/
|   |-- cad-tools/
|   |-- agent-events/
|   `-- inspection-report/
|-- tests/
|   |-- fixtures/dxf/
|   |-- fixtures/dwg/
|   |-- golden/
|   |-- agent-evals/
|   |-- visual/
|   `-- e2e/
|-- docs/
|   |-- architecture/
|   |-- research/
|   |-- ref/
|   `-- specs/
`-- clone/
```

`clone/` is research-only and excluded from Git and IDE indexing. Product code
must not import packages by relative path from `clone/`.

## MCP Surface

Initial tools:

- `cad.open_drawing`
- `cad.build_index`
- `cad.get_layers`
- `cad.find_entities_by_layer`
- `cad.find_entities_by_type`
- `cad.find_text`
- `cad.get_entity`
- `cad.list_unsupported`

Viewer tools are added after the viewer session contract is working:

- `cad.select_entities`
- `cad.zoom_to_entities`

Tools return both MCP text content and structured content. Expected user errors
return `isError: true` with a stable error code. Indexes and inspection reports
are exposed as `cad://` resources after the tool contract passes integration
tests.

## Frontend Playwright PNG Loop

Every frontend slice uses this mandatory loop:

```text
implement one visible behavior
  -> start the real development server
  -> load deterministic fixture data
  -> drive the UI with Playwright
  -> assert semantic state
  -> capture full-page and focused-panel PNG files
  -> inspect the PNG files directly
  -> fix layout, clipping, contrast, blank canvas, or state errors
  -> repeat until semantic and visual checks pass
```

Required screenshot states:

1. Empty workspace.
2. DXF loaded with layer tree and nonblank canvas.
3. Agent tool call in progress.
4. Layer search with matching entities highlighted.
5. Finding selected with evidence panel and zoomed viewport.
6. Unsupported-object warning state.
7. Narrow desktop layout at 1280x800.
8. Standard desktop layout at 1440x900.
9. Wide desktop layout at 1920x1080.

Playwright uses `toHaveScreenshot()` for stable baselines. Animations and carets
are disabled during capture. Dynamic timestamps and request durations are
masked. Actual, expected, and diff PNG files remain test artifacts. Canvas
tests also verify that rendered pixels are not uniformly blank.

Screenshots are not accepted only because pixel comparison passes. Each loop
also checks:

- no overlapping controls or clipped text;
- center viewer retains the primary area;
- panels resize without layout shift;
- selected entities visibly differ from unselected entities;
- evidence and warnings remain readable;
- all backgrounds stay within the light-theme palette;
- loading, empty, error, and partial-data states are visible.

## Test Strategy

### Contract

- Validate every index and tool result against JSON Schema.
- Ensure TypeScript and .NET serializers produce the same contract.
- Reject missing evidence fields in findings.

### Parser

- DXF unit fixtures for lines, polylines, text, blocks, layouts, and malformed
  entities.
- Sanitized real DWG fixtures for supported versions.
- Korean text and codepage fixtures.
- Proxy, AEC, XRef, missing bbox, and unsupported entity fixtures.
- Golden index comparisons with stable handles and bounds.

### MCP

- In-process MCP client/server tests over linked memory transports.
- `tools/list` name and schema assertions.
- End-to-end calls for all `cad.*` tools.
- Invalid argument, missing drawing, missing entity, parser failure, and
  partial-index behavior.
- A spawned stdio smoke test to catch transport and stdout contamination.

### Agent

- Natural-language cases mapped to expected tool sequences.
- Evidence-agent rejection tests for ungrounded claims.
- Independent-check concurrency tests.
- Cancellation, timeout, and partial-result tests.
- Final answers must cite entity evidence and limitations.

### Frontend

- Component tests for panels and result rendering.
- Playwright workflow tests for open, query, select, highlight, zoom, and
  report export.
- PNG baselines and direct visual inspection after each visible change.
- Browser console and page error assertions.

### Safety And Performance

- Hash source drawings before and after every inspection run.
- Verify all writes stay in sidecar and artifact directories.
- Large-drawing time and memory budgets.
- Index cache invalidation when source size or modification time changes.

## Delivery Phases

1. Normalize folders and preserve current passing behavior.
2. Wrap the runtime in a tested stdio MCP server.
3. Add the ACadSharp DWG adapter and shared contract tests.
4. Add orchestrator and specialist-agent evaluation harness.
5. Build the light CAD workspace and complete the Playwright PNG loop.
6. Connect viewer selection, highlight, and zoom.
7. Add sidecar reports, real anonymized fixtures, and performance gates.

Each phase must leave all earlier tests green. New UI work cannot be marked
complete without current PNG artifacts and direct visual inspection.

## References

- YouTube reference: https://www.youtube.com/watch?v=ItW-ielFvGg
- Claudian: https://github.com/YishenTu/claudian
- MCP TypeScript SDK: https://ts.sdk.modelcontextprotocol.io/server
- ToolCAD: https://arxiv.org/abs/2604.07960
- CAD-HLLM: https://proceedings.mlr.press/v304/zuo26a.html
- ACadSharp: https://github.com/DomCR/ACadSharp
- MLightCAD cad-viewer: https://github.com/mlightcad/cad-viewer

## Acceptance

The first complete product loop is accepted only when a real fixture can be
opened, indexed, queried through MCP, explained with stable entity evidence,
highlighted and zoomed in the frontend, exported to a sidecar report, and
verified by unit, integration, agent evaluation, Playwright workflow, and PNG
visual checks without changing the source drawing.

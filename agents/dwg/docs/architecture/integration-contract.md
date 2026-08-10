# Cross-repository integration contract

This document defines how another repository may consume DWG Intelligence
without coupling itself to implementation folders.

## Choose exactly one boundary

### 1. Contract package

Use `@dwg/contracts` when both repositories live in one workspace or when this
repository is vendored/submoduled:

```json
{
  "dependencies": {
    "@dwg/contracts": "file:../DWG/packages/contracts"
  }
}
```

The package exports CAD index, inspection, provider DTOs, validators, and
message limits from `packages/contracts/src/index.ts`. It intentionally exports
TypeScript source and is currently private; it is not a published npm package.
Import only `@dwg/contracts`: `@dwg/contracts/*` is not a public entrypoint.

Compatibility rule:

- the DWG producer emits strict `cad-index/v0.2`;
- the legacy DXF adapter may still emit `cad-index/v0.1`;
- cross-repository consumers accept the explicit v0.1/v0.2 union until the DXF
  migration is complete;
- additive optional fields are compatible;
- removing/renaming fields or changing validator behavior requires a version
  change and coordinated consumer updates.

`CadScheduleQuery` requires `drawingId`, `yTolerance`, and the bounded
`matches` returned by the preceding `query.text` capability. The schedule
capability revalidates those matches against the current drawing index and
extracts rows only from grounded matching handles. The former two-field query
shape is rejected; the built-in workflow and capability consumer are updated
together in this change.

### 2. Loopback HTTP gateway

Use loopback `/api` when the other repository is a UI, desktop shell, or
service that should not import Node implementation code.

| Method | Route | Contract |
|---|---|---|
| `GET` | `/api/health` | Gateway readiness |
| `GET` | `/api/drawing` | `CadEntityIndex` |
| `POST` | `/api/inspections` | `InspectionPayload` -> `InspectionRun` |
| `GET` | `/api/providers` | `{ providers: ProviderStatus[] }` |
| `POST` | `/api/chat` | `ProviderChatPayload` -> `ProviderChatResult` |
| `POST` | `/api/edit/preview` | `CadEditPreviewRequest` -> `CadEditPreviewResponse` |
| `POST` | `/api/edit/apply` | `CadEditApplyRequest` -> `CadEditApplyResponse` |
| `POST` | `/api/edit/undo` | `CadEditHistoryRequest` -> `CadEditApplyResponse` |
| `POST` | `/api/edit/redo` | `CadEditHistoryRequest` -> `CadEditApplyResponse` |
| `GET` | `/api/skills` | `SkillListResponse` |
| `POST` | `/api/skills/run` | `SkillRunRequest` -> `SkillRunResponse` |
| `GET` | `/api/export/capabilities` | `ExportCapabilitiesResponse` |

The gateway binds to `127.0.0.1`, rejects malformed/oversized input, rejects
browser `Origin` values outside localhost/loopback, and passes browser
cancellation through one `AbortSignal`. Requests without `Origin` remain
available to local CLI and MCP adapters. Do not expose the gateway publicly
without adding authentication and a separate threat-model review.

`GET /api/drawing` returns the active in-memory document snapshot for the
gateway's paired application. Its optional `drawing.revision` is the current
edit revision (zero for an unedited snapshot); parser-only indexes may omit it.
This additive metadata does not modify or rewrite the source DWG/DXF.
The v0.2 `drawing` object remains strict: `fileVersion` and `units` are
required nullable strings, `revision` is an optional non-negative integer, and
unknown drawing metadata keys are rejected. Omitting `revision` remains
backward-compatible.

Within one assembled application process, drawing, inspection, query, skill,
and chat reads resolve through the same active edit snapshot. Applying,
undoing, or redoing a change therefore updates every read surface without
reopening or modifying the configured source file. MCP and CLI entrypoints
create independent application processes and do not share edit history.
After a drawing-session switch, inspection uses the active application's
canonical source path and chat ignores the browser's legacy `drawingPath` as a
data-selection authority. A drawing opened outside the repository still uses
the repository-owned CAD I/O host project for verified Save As.

#### Export capability contract

`GET /api/export/capabilities` returns every supported report (`json`, `csv`,
`pdf`, `svg`) and drawing (`dxf`, `dwg`) format as typed capability items.
Report formats are available for every active drawing. Same-format drawing
copies are available, as is a verified DXF copy from a DWG source. A DWG copy
from a DXF source is withheld because its legacy `cad-index/v0.1` source model
cannot be compared with the ACadSharp `cad-index/v0.2` reopened copy. The
endpoint itself does not create files or modify source drawings. Adding
optional capability metadata is compatible. Enabling another format pairing
requires a coordinated Save and Export implementation that preserves source
read-only behavior and independently reopens the written output.

#### Workspace edit proposal ingest

The workspace `Changes` tab can create a move proposal only from the currently
selected, grounded contract entity. The user supplies a finite non-zero delta;
the feature builds and validates a `CadEditBatch`, then publishes it through
the versioned browser proposal inbox. The inbox starts preview only. Approval
remains a separate explicit action, and event publication can never apply an
edit.

#### CAD skill document scope

`POST /api/skills/run` requires a primary `documentId`. It may also carry
`relatedDocumentIds`, a unique list of at most three document IDs that must not
contain the primary ID. Omitting the optional list preserves the existing
single-document request shape and behavior. The skill list and run response
shapes are unchanged.

The runtime treats `{ documentId, ...relatedDocumentIds }` as an exact
allowlist. Every workflow value named `drawingId`, `documentId`,
`beforeDrawingId`, or `afterDrawingId`, and every `document.open` result, must
belong to that allowlist. A `compare-drawings` request therefore declares the
before drawing as `documentId` and the after drawing in `relatedDocumentIds`;
missing authorization and any unrelated third drawing are rejected before the
comparison capability runs.

The checked-in standalone inspection example runs from the repository root:

```powershell
npm run skill -- --skill inspect-drawing --input skills/inspect-drawing/examples/input.json
```

Its input matches the public skill schema with the retained
repository-relative DXF `path` and `A-WALL` layer.

The standalone CLI preloads comparison sources by path because every invocation
creates a fresh in-memory CAD application:

```powershell
npm run skill -- --skill compare-drawings --input <input.json> --before <before.dwg> --after <after.dwg>
```

`--before` and `--after` are required together, only for `compare-drawings`,
and must identify distinct sources inside `DWG_WORKSPACE`. The CLI opens both
through the root `document.open` capability, uses only the returned drawing IDs
for workflow input and the exact primary/related allowlist, and forwards one
`AbortSignal` through both opens and skill execution. Caller-supplied
`--document-id` or `--related-document-id` cannot be combined with comparison
preloads. One-sided, duplicate, mixed, and non-comparison preload flags are
usage errors. Output remains the single bounded summary and never includes
source paths or raw open results.

#### CAD edit review contract

The four edit routes use the strict shared `@dwg/contracts` validators for
both requests and responses. Consumers must import the DTOs from the package
entrypoint rather than copying their JSON shapes. Adding an optional field is
compatible; removing or renaming a field, relaxing strict validation, or
changing approval or revision behavior requires coordinated consumers and a
versioned contract change.

`POST /api/edit/preview` accepts a `CadEditPreviewRequest` containing one
`cad-edit/v1` batch. The batch and every command carry the same
`expectedRevision`. A successful response assigns a server-owned `previewId`
and returns only bounded typed change evidence. `changeCount` and
`warningCount` are exact totals; `changesTruncated` and `warningsTruncated`
state whether the response omitted entries. At most 200 changes and 100
warnings are returned.

Apply, undo, and redo require the literal `approved: true` and an
`expectedRevision` matching the current document transition:

- apply also requires the matching document and server-owned `previewId`;
- a preview is single use, expires after ten minutes, and each document keeps
  at most 20 active previews;
- stale, expired, evicted, reused, unknown, or cross-document previews fail
  without committing a transaction;
- undo and redo restore content while assigning a new monotonic revision.

Each edit request has a hard 1 MiB body ceiling, including streamed bodies.
The gateway forwards the same `AbortSignal` through the composed application.
A pre-aborted preview, apply, undo, or redo fails before preview lifecycle or
transaction state changes.

Edit failures use the strict, bounded, redacted `CadEditErrorResponse`.
Generic failures remain `{ error: { code, message } }`.
`EDIT_PREVIEW_STALE` additionally requires the authoritative non-negative
`currentRevision`; the browser may rebuild the same validated batch at that
revision, changing only the batch and command `expectedRevision` fields. It
must preserve operations, preconditions, and handles so stale recovery cannot
silently retarget an edit. This additive stale variant is coordinated between
the runtime producer and workspace consumer; generic failure compatibility is
unchanged.

Responses and errors never expose document snapshots, resolved-command
before-state, provider content, request payloads, or internal engine objects.
The preview `changes` array contains only the contract-owned typed entity/layer
evidence required for user review. While apply, undo, or redo is in flight, the
workspace disables its proposal composer and ignores newly published proposals
so a preview cannot abort or replace a committed mutation request.

All routes operate inside a single loopback trust boundary. Health, read,
provider, chat, inspection, and edit use the same process. It binds only to
`127.0.0.1`, accepts browser origins only from loopback hosts, has no
public-network authentication, and must not be exposed beyond that boundary
without a separate threat model.
This edit-review phase does not write DWG or DXF files; its state remains in memory.
MCP remains read-only and exposes no edit tools.

| Variable | Meaning | Default |
|---|---|---|
| `DWG_WORKSPACE` | Canonical root allowed for drawing access | Repository root |
| `DWG_DRAWING_PATH` | Drawing path relative to the workspace | Test DWG fixture |
| `DWG_GATEWAY_PORT` | Loopback gateway port | `4317` |
| `DWG_FRONTEND_PORT` | Workspace Vite port | `4173` |
| `DWG_EXPORT_ROOT` | Directory that verified copies and report downloads are written into | `tests/visual/test-results/export-roots/gateway-<pid>` |

A host repository must set `DWG_EXPORT_ROOT`. The default resolves inside this
repository's local test-results directory, which is gitignored and per-process.
It is the destination whenever no host dialog is supplied, which is every
headless and test run; with a dialog the operator chooses the directory and
`DWG_EXPORT_ROOT` is unused.
`DWG_EXPORT_MODE` is not part of this contract; it selects which export root
the Playwright harness prepares and is read only by the browser test setup.

### 3. MCP stdio

Use MCP stdio through `npm run mcp` for agent hosts. The supported read-only
tool surface is:

- `cad.open_drawing`
- `cad.build_index`
- `cad.get_layers`
- `cad.find_entities_by_layer`
- `cad.find_entities_by_type`
- `cad.find_text`
- `cad.get_entity`
- `cad.list_unsupported`

`cad.open_drawing` returns the `drawingId` used by later calls.
`cad.build_index` also returns that `drawingId` so chained harness steps can use
`$last.drawingId`. Viewer-only actions and write actions are not MCP tools.

MCP drawing paths use the same canonical `DWG_WORKSPACE` boundary as loopback
`/api`. Absolute paths, `..` traversal, and Windows junctions cannot escape
that root.

### 4. Whole apps/workspace composition

Use the whole apps/workspace composition when merging the three-panel product
UI. `apps/workspace/src/app` is its composition root. Its feature folders are
internal, independently owned modules rather than a component library.

If a host needs reusable UI packages, extract them deliberately in a separate
change with public entrypoints and contract tests. Do not deep-import
`apps/workspace/src/features/**` from another repository.

## Ownership and conflict zones

| Change | Required owner location |
|---|---|
| Public JSON shape/validation | `packages/contracts` |
| DWG parsing | `modules/dwg-parser` or `modules/cad-runtime/src/parsers` |
| CAD query behavior | `modules/cad-runtime/src/application/cad-tools` |
| Delegation/evidence policy | `modules/cad-runtime/src/orchestration` |
| OAuth process behavior | `modules/cad-runtime/src/providers` |
| HTTP transport/security | `modules/cad-runtime/src/http` |
| Drawing tree/layer state | `apps/workspace/src/features/drawing-explorer` |
| SVG geometry/view state | `apps/workspace/src/features/cad-viewer` |
| Chat/session state | `apps/workspace/src/features/agent-chat` |
| Inspection presentation | `apps/workspace/src/features/inspection-results` |
| Cross-feature layout/wiring | `apps/workspace/src/app` |

`modules/cad-runtime/src/**`, `apps/workspace/src/features/**`, and parser
internals are not deep-import APIs. Resolve merge conflicts at the owner
location without copying feature hooks or creating duplicate DTOs.

## Merge checklist

1. Preserve repository-relative paths; no absolute Windows path belongs in
   runtime code.
2. Install root workspace dependencies.
3. Point contract dependencies at one canonical `packages/contracts`.
4. Decide whether the host uses loopback `/api`, MCP stdio, or whole
   apps/workspace composition; do not mix deep imports with a process boundary.
5. Configure a canonical `DWG_WORKSPACE` and keep source drawings read-only.
6. Verify `npm run verify`; its default Node suite includes fixture hash
   integrity checks.
7. Run browser tests on isolated ports when apps/workspace is included.
8. Inspect `docs/ui-captures/00-overview.png` after layout changes.
9. Verify live OAuth separately; default automated tests use deterministic
   fakes and do not prove current Codex/Claude login state.

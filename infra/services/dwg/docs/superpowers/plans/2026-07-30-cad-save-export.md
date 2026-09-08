# Verified CAD Save As and Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce verified DXF and allowlisted DWG copies plus JSON, CSV, PDF, and SVG reports without modifying source drawings.

**Architecture:** `cad-export` owns report bytes; `cad-io-acadsharp` owns CAD mutation mapping and writer invocation. A save coordinator writes a temporary sibling, reopens it independently, verifies invariants, and only then finalizes the selected destination.

**Tech Stack:** TypeScript 5.8, Node 24, .NET 9, ACadSharp 3.6.35, Playwright 1.62.

## Global Constraints

- Never pass the source path as a writer destination.
- Output paths must remain within the user-selected destination directory.
- DWG versions use an explicit tested allowlist.
- A writer exit code is not verification.
- Failed output remains uncommitted and is safely removed or quarantined.
- Source fixture hashes must match the immutable manifest after every test.
- New module READMEs document public or process entrypoints, dependency
  direction, output safety rules, and focused test commands.

---

### Task 1: Add Report Export Module

**Files:**
- Create: `modules/cad-export/package.json`
- Create: `modules/cad-export/tsconfig.json`
- Create: `modules/cad-export/README.md`
- Create: `modules/cad-export/src/index.ts`
- Create: `modules/cad-export/src/jsonReport.ts`
- Create: `modules/cad-export/src/csvReport.ts`
- Create: `modules/cad-export/src/svgReport.ts`
- Create: `modules/cad-export/src/pdfReport.ts`
- Create: `modules/cad-export/tests/report-export.test.ts`
- Modify: `packages/contracts/src/export.ts`
- Modify: `packages/contracts/src/index.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Produces:

```ts
interface CadReportInput {
  document: CadDocumentSnapshot;
  findings: InspectionRun | null;
  changeSet: CadReportChangeSet | null;
  verification: CadOutputVerification | null;
}
interface CadReportChangeSet {
  documentId: string;
  revision: number;
  transactionIds: string[];
  changes: CadChange[];
}
interface CadOutputVerification {
  id: string;
  status: "passed" | "failed";
  format: "dxf" | "dwg";
  version: string;
  sourceSha256: string;
  outputSha256: string;
  intendedChangeCount: number;
  verifiedChangeCount: number;
  copiedHandleMap: Record<string, string>;
  warnings: string[];
}
interface ExportedReport {
  format: ReportFormat;
  mediaType: string;
  filename: string;
  bytes: Uint8Array;
  sha256: string;
}
function exportCadReport(input: CadReportInput, format: ReportFormat): Promise<ExportedReport>;
```

`ReportFormat`, `DrawingFormat`, and `CadOutputVerification` are public
serialized DTOs exported by `@dwg/contracts`. `CadReportInput` remains an
internal `cad-export` application type.

- [ ] **Step 1: Write deterministic export tests**

Assert stable JSON ordering, UTF-8 CSV, spreadsheet-formula escaping, valid PDF
header, valid SVG root, sanitized filenames, byte ceiling, and equal hashes
across repeated runs. Include a two-transaction cumulative change set and
prove both transaction IDs and every typed change appear in stable order.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-export/tests/report-export.test.ts`

Expected: FAIL because export module is absent.

- [ ] **Step 3: Implement report exporters**

CSV prefixes cells beginning with `=`, `+`, `-`, or `@` with a single quote.
PDF and SVG state unsupported geometry explicitly instead of fabricating it.
Implement the PDF as a deterministic, text-first PDF 1.7 serializer within
`pdfReport.ts`; do not add a native or browser-only PDF dependency.

- [ ] **Step 4: Run tests**

Run: `node --import tsx --test modules/cad-export/tests/report-export.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-export/package.json modules/cad-export/tsconfig.json modules/cad-export/README.md modules/cad-export/src/index.ts modules/cad-export/src/jsonReport.ts modules/cad-export/src/csvReport.ts modules/cad-export/src/svgReport.ts modules/cad-export/src/pdfReport.ts modules/cad-export/tests/report-export.test.ts packages/contracts/src/export.ts packages/contracts/src/index.ts package.json package-lock.json tsconfig.json
git commit -m "feat: export deterministic CAD reports"
```

### Task 2: Add the ACadSharp Writer Host and Process Client

**Files:**
- Create: `modules/cad-io-acadsharp/package.json`
- Create: `modules/cad-io-acadsharp/tsconfig.json`
- Modify: `modules/cad-io-acadsharp/README.md`
- Create: `modules/cad-io-acadsharp/src/index.ts`
- Create: `modules/cad-io-acadsharp/src/processClient.ts`
- Modify: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIntelligence.CadIo.csproj`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadIoRequest.cs`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadIoResponse.cs`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CommandMapper.cs`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadFileWriter.cs`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/Program.cs`
- Create: `modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj`
- Create: `modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/CommandMapperTests.cs`
- Create: `modules/cad-io-acadsharp/tests/process-client.test.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Process input:

```json
{
  "schemaVersion": "cad-io/v1",
  "operation": "write-copy",
  "sourcePath": "absolute-contained-path",
  "temporaryOutputPath": "absolute-contained-path",
  "format": "dxf",
  "version": "AC1032",
  "lineage": []
}
```

- Process output contains status, output version, entity counts, warnings, and
  no CAD bytes.

- Public TypeScript client:

```ts
interface CadIoWriteRequest {
  sourcePath: string;
  temporaryOutputPath: string;
  format: "dxf" | "dwg";
  version: string;
  lineage: readonly CadIoWriteTransaction[];
}
interface CadIoWriteTransaction {
  transactionId: string;
  beforeRevision: number;
  afterRevision: number;
  commands: readonly CadIoWriteCommand[];
}
type CadIoWriteCommand =
  | { kind: "layer.create"; layerId: string; name: string; color: number }
  | {
      kind: "layer.update";
      layerId: string;
      name?: string;
      color?: number;
      visible?: boolean;
      frozen?: boolean;
      locked?: boolean;
    }
  | { kind: "text.replace"; handle: string; value: string }
  | { kind: "entity.move"; handles: string[]; delta: CadPoint3 }
  | {
      kind: "entity.copy";
      sourceHandles: string[];
      temporaryIds: string[];
      delta: CadPoint3;
    }
  | { kind: "entity.delete"; handles: string[] };
interface CadIoWriteResult {
  format: "dxf" | "dwg";
  version: string;
  entityCount: number;
  copiedHandleMap: Record<string, string>;
  warnings: string[];
}
interface CadIoClient {
  writeCopy(request: CadIoWriteRequest, signal?: AbortSignal): Promise<CadIoWriteResult>;
}
interface CadProcessRunner {
  run(spec: {
    command: string;
    args: string[];
    cwd: string;
    stdin: string;
    maxOutputBytes: number;
  }, signal?: AbortSignal): Promise<{
    exitCode: number;
    stdout: string;
    stderr: string;
  }>;
}
function createAcadSharpCadIoClient(options: {
  projectPath: string;
  processRunner: CadProcessRunner;
  dwgVersionManifestPath?: string;
}): CadIoClient;
```

Without `dwgVersionManifestPath`, every DWG request fails with
`DWG_POLICY_NOT_CONFIGURED`; DXF writing remains available.

- [ ] **Step 1: Write mapper tests against generated temporary fixture copies**

Cover layer changes, text replacement, move/copy/delete, missing handle,
unsupported type, transaction rollback, invalid JSON, bounded stdout/stderr,
process cancellation, source hash unchanged, two sequential transactions, and
unique final CAD-handle mappings for every `copy:<transactionId>:<commandId>:*`
temporary ID.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
dotnet test modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj --nologo
node --import tsx --test modules/cad-io-acadsharp/tests/process-client.test.ts
```

Expected: both commands FAIL because the writer host and process client are
absent.

- [ ] **Step 3: Implement the writer host and client**

Keep all document mapping in the `DwgIntelligence.CadIo` class library created
by the foundation plan. The host reads exactly one JSON request from stdin,
writes exactly one JSON response to stdout, and writes only generic bounded
diagnostics to stderr. Use `DxfWriter` and `DwgWriter` only inside
`CadFileWriter`. The TypeScript client launches the host project, passes one
request, enforces the existing 1 MiB combined output limit, and validates the
response before returning.
Apply the contiguous lineage in order. After the writer assigns handles,
return a one-to-one `copiedHandleMap` from every temporary copy ID to its final
uppercase CAD handle; reject missing or duplicate mappings.
The TypeScript client maps `CadSaveState.lineage` to the strict discriminated
`CadIoWriteTransaction` wire shape and never sends before/after snapshots or
`unknown` fields. For copy, `sourceHandles.length` must equal
`temporaryIds.length`; the writer returns one final handle per temporary ID.
Both TypeScript and C# reject unknown properties, non-finite coordinates,
duplicate handles/temporary IDs, more than 10,000 commands, or JSON over 1 MiB.
Update root scripts:

```json
"test:dotnet:parser": "dotnet test modules/dwg-parser/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo",
"test:dotnet:cad-io": "dotnet test modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj --nologo",
"test:dotnet": "npm run test:dotnet:parser && npm run test:dotnet:cad-io"
```

This keeps the two .NET projects sequential on Windows and makes every later
`verify`, `verify:all`, and `verify:release` run both suites.

- [ ] **Step 4: Run .NET tests sequentially**

Run: `dotnet test modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj --nologo; if ($LASTEXITCODE -eq 0) { node --import tsx --test modules/cad-io-acadsharp/tests/process-client.test.ts }; if ($LASTEXITCODE -eq 0) { npm run test:dotnet }`

Expected: both suites PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-io-acadsharp/package.json modules/cad-io-acadsharp/tsconfig.json modules/cad-io-acadsharp/README.md modules/cad-io-acadsharp/src/index.ts modules/cad-io-acadsharp/src/processClient.ts modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIntelligence.CadIo.csproj modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadIoRequest.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadIoResponse.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CommandMapper.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadFileWriter.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/Program.cs modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/CommandMapperTests.cs modules/cad-io-acadsharp/tests/process-client.test.ts package.json package-lock.json tsconfig.json
git commit -m "feat: add private ACadSharp writer host"
```

### Task 3: Implement Save Coordinator and Independent Verification

**Files:**
- Create: `modules/cad-capabilities/src/saveCapabilities.ts`
- Create: `modules/cad-capabilities/src/saveCoordinator.ts`
- Create: `modules/cad-capabilities/src/outputVerification.ts`
- Create: `modules/cad-capabilities/src/destinationGrants.ts`
- Create: `modules/cad-capabilities/tests/save-coordinator.test.ts`
- Create: `tests/roundtrip/dxf-roundtrip.test.ts`
- Modify: `modules/cad-capabilities/package.json`
- Modify: `package-lock.json`
- Modify: `modules/cad-capabilities/src/index.ts`
- Modify: `modules/cad-capabilities/src/contracts.ts`

**Interfaces:**
- Adds:

```text
export.report
export.drawing
verification.get
```

`export.drawing` accepts a document ID, expected current revision, opaque
destination grant ID, base filename, format, and version. It does not accept a
transaction ID, directory, arbitrary complete output path, or caller-supplied
command lineage.

```ts
interface OutputDestinationGrant {
  id: string;
  canonicalDirectory: string;
  expiresAt: number;
  used: boolean;
}
interface DestinationGrantProvider {
  consume(id: string): Promise<OutputDestinationGrant>;
}
interface CadSourceDocument {
  documentId: string;
  canonicalPath: string;
  sourceSha256: string;
  drawingVersion: string | null;
  units: string | null;
}
interface CadSourceDocumentResolver {
  resolve(documentId: string, signal?: AbortSignal): Promise<CadSourceDocument>;
}
interface CadParsedDocumentEvidence {
  index: CadEntityIndex;
  sourceSha256: string;
  drawingVersion: string | null;
  units: string | null;
}
interface CadSaveDependencies {
  cadIo: CadIoClient;
  sources: CadSourceDocumentResolver;
  readDocument(
    path: string,
    signal?: AbortSignal,
  ): Promise<CadParsedDocumentEvidence>;
  transactions: CadCommittedTransactionStore;
  grants: DestinationGrantProvider;
}
interface CadSaveCoordinator {
  saveCopy(input: {
    documentId: string;
    expectedRevision: number;
    destinationGrantId: string;
    baseFilename: string;
    format: "dxf" | "dwg";
    version: string;
  }, signal?: AbortSignal): Promise<CadOutputVerification>;
  getVerification(id: string): CadOutputVerification | null;
}
function createSaveCoordinator(deps: CadSaveDependencies): CadSaveCoordinator;
function createSaveCapabilityModule(
  coordinator: CadSaveCoordinator,
  reportExporter: typeof exportCadReport,
): CadCapabilityModule;
```

Declare `@dwg/cad-io-acadsharp` and `@dwg/cad-export` in
`modules/cad-capabilities/package.json`, run `npm install --package-lock-only`,
and consume only their public entrypoints.

- [ ] **Step 1: Write save failure and success tests**

Test unknown, expired, and reused destination grants; source/output equality
rejection; traversal rejection; existing-file rejection; writer failure;
reopen failure; invariant failure; successful atomic finalize; cancellation;
source-hash preservation; two sequential committed transactions; an undone
branch; stale revision; incomplete lineage; and copied temporary-to-final
handle verification.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-capabilities/tests/save-coordinator.test.ts tests/roundtrip/dxf-roundtrip.test.ts`

Expected: FAIL because save capabilities are absent.

- [ ] **Step 3: Implement temporary sibling and verifier**

Temporary name:

```text
.<sanitized-base>.<saveRequestId>.click-around.tmp.<ext>
```

Generate a server-owned UUID `saveRequestId`. Resolve
`CadCommittedTransactionStore.getSaveState(documentId, expectedRevision)` and
reject stale, incomplete, over-limit, or non-contiguous lineage. Resolve its
source through `CadSourceDocumentResolver.resolve(saveState.documentId)`;
reject a source hash or drawing metadata mismatch against `saveState.source`.
Pass only that resolver-owned `canonicalPath` and the server-owned
`saveState.lineage` to
`CadIoClient.writeCopy`. Resolve the canonical destination only through
`DestinationGrantProvider`. Invoke `CadIoClient.writeCopy`, then reopen through
a new parser process after writer close using `readDocument`. Compare
`saveState.current` to the reopened output, translating copy temporary IDs
through `CadIoWriteResult.copiedHandleMap`; compare source/output units,
requested versus reopened output version, all cumulative intended changes,
entity-count delta, unaffected handle/type/layer/bbox, and warning delta.
Finalize with `rename`.

- [ ] **Step 4: Run DXF round trip and fixture guard**

Run: `node --import tsx --test tests/roundtrip/dxf-roundtrip.test.ts && npm run test:fixtures`

Expected: PASS and source SHA-256 values remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-capabilities/src/saveCapabilities.ts modules/cad-capabilities/src/saveCoordinator.ts modules/cad-capabilities/src/outputVerification.ts modules/cad-capabilities/src/destinationGrants.ts modules/cad-capabilities/tests/save-coordinator.test.ts tests/roundtrip/dxf-roundtrip.test.ts modules/cad-capabilities/package.json modules/cad-capabilities/src/index.ts modules/cad-capabilities/src/contracts.ts package-lock.json
git commit -m "feat: verify CAD copies before finalizing"
```

### Task 4: Establish the DWG Version Allowlist

**Files:**
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgVersionPolicy.cs`
- Create: `modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgRoundTripTests.cs`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgVersionProbe.cs`
- Modify: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/Program.cs`
- Modify: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadFileWriter.cs`
- Modify: `modules/cad-io-acadsharp/src/processClient.ts`
- Modify: `modules/cad-io-acadsharp/tests/process-client.test.ts`
- Create: `tests/fixtures/dwg/roundtrip-manifest.json`
- Create: `tests/roundtrip/dwg-roundtrip.test.ts`
- Modify: `tests/fixtures/manifest.json`

**Interfaces:**
- Produces an allowlist containing only versions that pass the checked-in
  fixture matrix.

- Manifest entries are:

```json
{
  "version": "AC1032",
  "probeFixtureSha256": "64 uppercase hex characters",
  "verified": true,
  "invariantSha256": "64 uppercase hex characters"
}
```

- [ ] **Step 1: Write failing policy and manifest tests**

Include AC1014, AC1015, AC1018, AC1024, AC1027, and AC1032 candidates. Each
starts with `verified: false`. Assert unverified versions are rejected,
verified entries require exact probe-fixture and invariant hashes, and the
release gate requires at least one verified version.

- [ ] **Step 2: Run policy tests and verify RED**

Run:

```powershell
dotnet test modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj --filter DwgRoundTrip --nologo
node --import tsx --test modules/cad-io-acadsharp/tests/process-client.test.ts tests/roundtrip/dwg-roundtrip.test.ts
```

Expected: both commands FAIL because policy, manifest loader, probe, and client
injection are absent.

- [ ] **Step 3: Implement the deny-by-default policy and probe**

`DwgVersionPolicy.Load(manifestPath)` validates the complete checked-in
manifest and returns an immutable policy.
`policy.IsAllowed(version)` returns true only for a verified manifest entry;
`probeFixtureSha256` and `invariantSha256` are release evidence, not hashes
that a user's source drawing must match. The probe writes each candidate to a
temporary directory, reopens it, indexes it, compares invariants, and prints
one bounded JSON result per version.
The TypeScript client passes its configured manifest path to the host as
`--dwg-policy-manifest <absolute-path>`. `Program.cs` loads it before reading a
DWG write request, and `CadFileWriter` calls `policy.IsAllowed(version)` before
creating the temporary output. DXF requests do not require the policy.

- [ ] **Step 4: Run the candidate probe**

Run:

```powershell
dotnet run --project modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj -- --probe-versions tests/fixtures/dwg/export_sample.dwg tests/visual/test-results/dwg-version-probe.json
```

Expected: exit 0 when probing completes, even when individual candidates are
unsupported. Every candidate record contains `verified`, bounded warnings,
source SHA-256, and invariant SHA-256.

- [ ] **Step 5: Promote only proven versions**

For each probe record with `verified: true`, copy its exact probe-fixture and
invariant hashes into `roundtrip-manifest.json`. Leave every failing candidate
at `verified: false`. If no candidate passes, stop this plan as blocked; do not
claim DWG Save As support.

- [ ] **Step 6: Run .NET and Node round-trip suites**

Run: `dotnet test modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj --nologo; if ($LASTEXITCODE -eq 0) { node --import tsx --test modules/cad-io-acadsharp/tests/process-client.test.ts tests/roundtrip/dwg-roundtrip.test.ts }`

Expected: PASS. Unsupported candidates return `DWG_VERSION_NOT_ALLOWLISTED`
before writer creation.

- [ ] **Step 7: Commit**

```powershell
git add modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgVersionPolicy.cs modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgRoundTripTests.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgVersionProbe.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/Program.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadFileWriter.cs modules/cad-io-acadsharp/src/processClient.ts modules/cad-io-acadsharp/tests/process-client.test.ts tests/fixtures/dwg/roundtrip-manifest.json tests/roundtrip/dwg-roundtrip.test.ts tests/fixtures/manifest.json
git commit -m "test: allowlist verified DWG output versions"
```

### Task 5: Connect Export UI, Skills, HTTP, and MCP

**Files:**
- Modify: `modules/cad-runtime/src/http/gateway.ts`
- Modify: `modules/cad-runtime/src/application/createCadApplication.ts`
- Modify: `modules/cad-runtime/src/http/drawingWorkspace.ts`
- Modify: `modules/cad-runtime/src/http/exportCapabilityGateway.ts`
- Modify: `modules/cad-runtime/src/mcp/toolDefinitions.ts`
- Modify: `modules/cad-runtime/src/mcp/createServer.ts`
- Modify: `modules/cad-runtime/src/mcp/stdio.ts`
- Modify: `modules/cad-runtime/harness/run-skill.ts`
- Modify: `modules/cad-runtime/tests/integration/mcp-server.test.ts`
- Modify: `modules/cad-runtime/src/platform/repositoryPaths.ts`
- Create: `modules/cad-runtime/src/http/destinationGrantGateway.ts`
- Create: `modules/cad-runtime/src/application/drawing-access/sourceDocumentResolver.ts`
- Create: `modules/cad-runtime/src/application/drawing-access/parsedDocumentEvidence.ts`
- Create: `modules/cad-runtime/tests/application/source-document-resolver.test.ts`
- Create: `modules/cad-runtime/tests/http/export-composition.test.ts`
- Modify: `modules/cad-runtime/tests/application/cad-application-composition.test.ts`
- Create: `skills/export-drawing/SKILL.md`
- Create: `skills/export-drawing/manifest.json`
- Create: `skills/export-drawing/workflows/default.json`
- Create: `skills/export-drawing/tests/cases.json`
- Create: `skills/export-drawing/examples/input.json`
- Create: `skills/export-drawing/examples/output.json`
- Modify: `apps/workspace/src/shared/api/exportClient.ts`
- Modify: `apps/workspace/src/features/export/ExportPanel.tsx`
- Create: `apps/workspace/tests/e2e/save-as.spec.ts`
- Modify: `apps/workspace/tests/docs/route-captures.spec.ts`
- Modify: `apps/workspace/playwright.config.ts`
- Modify: `apps/workspace/playwright.docs.config.ts`
- Modify: `apps/workspace/tests/support/repositoryOutputPaths.ts`
- Create: `apps/workspace/tests/support/exportRootGlobalSetup.ts`
- Modify: `apps/workspace/tests/unit/repository-output-paths.test.ts`
- Create: `tests/skills/export-skill.test.ts`
- Modify: `packages/contracts/src/export.ts`
- Modify: `packages/contracts/src/index.ts`
- Create: `docs/ui-captures/save-verified.png`
- Create: `docs/ui-captures/export-report.png`
- Modify: `package.json`
- Modify: `package-lock.json`

**Interfaces:**
- MCP write tools declare `readOnlyHint: false`,
  `destructiveHint: false`, and `idempotentHint: false`.
- `export-drawing` requires `write-copy` for CAD and `export` for reports.
- Browser development mode grants only the configured local export root.
  Desktop hosts may replace the grant gateway with a native folder picker
  without changing `export.drawing`.
- Public transport DTOs from `@dwg/contracts`:

```ts
interface DestinationGrantRequest {}
interface DestinationGrantResponse {
  grantId: string;
  displayDirectory: string;
  expiresAt: number;
}
interface CadReportExportRequest {
  documentId: string;
  revision: number;
  format: ReportFormat;
}
interface CadReportExportResponse {
  downloadId: string;
  filename: string;
  mediaType: string;
  sha256: string;
}
interface CadDrawingExportRequest {
  documentId: string;
  expectedRevision: number;
  destinationGrantId: string;
  baseFilename: string;
  format: DrawingFormat;
  version: string;
}
interface CadDrawingExportResponse {
  verificationId: string;
  status: "passed" | "failed";
}
interface CadVerificationResponse {
  verification: CadOutputVerification;
}
```

- Root-owned service interface in
  `modules/cad-runtime/src/application/createCadApplication.ts` only:

```ts
interface DestinationSelectionProvider {
  request(signal?: AbortSignal): Promise<{
    canonicalDirectory: string;
    displayDirectory: string;
  } | null>;
}
```

It is never exported from `@dwg/contracts` or serialized across a transport.

- Adds `POST /api/export/destination-grants`; the body must be an empty strict
  object and can never contain a path. MCP adds
  `cad_request_export_destination`, which uses server elicitation to confirm
  the host-configured display directory and returns the same public response.
  Call `server.server.elicitInput({ mode: "form", ... })` with a strict
  boolean-only `confirm` schema after checking the client's advertised
  `elicitation.form` capability. Unsupported clients return
  `MCP_ELICITATION_UNSUPPORTED`; decline/cancellation creates no grant. The
  form displays the host directory but does not accept a directory string.
- Adds:

```text
POST /api/export/reports
GET  /api/export/reports/:downloadId
POST /api/export/drawings
GET  /api/export/verifications/:verificationId
```

All JSON requests/responses use the strict public DTOs above. Report download
IDs are random, expire after 10 minutes, are single-use, and map only to
server-owned bounded bytes. IDs and filenames are validated; no route accepts
a filesystem path.

- [ ] **Step 1: Write end-to-end tests**

Test preview-to-approve-to-Save-As-to-verified status, rejected save, DXF download,
allowlisted DWG selection, report download, permission denial, and browser
cancellation. Test that source resolution accepts only the configured drawing's
`documentId`, returns its canonical contained path, recomputes its SHA-256 and
metadata on every save, and rejects a changed file before writer invocation.
Test HTTP and MCP destination-grant issue/cancel/reuse behavior and assert no
request accepts an arbitrary path. Test every report/drawing/verification DTO,
malformed IDs, one-use report download, body/output ceilings, and assembled
MCP registration for grant, report, drawing, and verification tools.
Apply two edits through one factory result's composed `capabilities`, then
prove Save As and report export receive its paired cumulative
`transactions.getSaveState`; the report flattens the lineage into
`CadReportChangeSet` and Save As replays that same lineage.
Test two Save As attempts with the same base filename: the second returns
`OUTPUT_ALREADY_EXISTS` without overwriting the first.
Run inspect, edit preview, report export, and drawing export through the real
CLI host and assert gateway, MCP stdio, and CLI factories expose the same full
capability-name set.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
node --import tsx --test modules/cad-runtime/tests/application/source-document-resolver.test.ts
node --import tsx --test modules/cad-runtime/tests/http/export-composition.test.ts
node --import tsx --test modules/cad-runtime/tests/application/cad-application-composition.test.ts
node --import tsx --test modules/cad-runtime/tests/integration/mcp-server.test.ts
node --import tsx --test apps/workspace/tests/unit/repository-output-paths.test.ts
npm run test:e2e -- save-as.spec.ts
node --import tsx --test tests/skills/export-skill.test.ts
```

Expected: all seven commands FAIL because the resolver, shared edit/export
composition, isolated export roots, transports, MCP tools, and export skill
are not connected.

- [ ] **Step 3: Implement bounded transport adapters**

Return verification IDs and summaries, not output bytes, from CAD Save As.
Report downloads may stream bounded generated bytes with correct media types.
Implement `createConfiguredSourceDocumentResolver(...)` in
`sourceDocumentResolver.ts`. It receives the already-contained configured path
from `drawingWorkspace.ts`, an injected SHA-256 reader, and
`createParsedDocumentEvidenceReader(...)`; it caches no path supplied by a
request. The evidence reader launches the existing parser through
`buildCadIndexForPath`, computes the file SHA-256 independently, and returns
index, file version, and units. Extend `DrawingWorkspace` with
`getSourceDocumentResolver()` and pass that concrete resolver plus the evidence
reader into `createSaveCoordinator` in `gateway.ts`. Neither HTTP nor MCP
accepts a source path or source resolver override.
Resolve `roundtrip-manifest.json` through `repositoryPaths.ts`, inject it into
`createAcadSharpCadIoClient`, and assert a verified version reaches the writer
while an unverified version is rejected before file creation. Mount the
destination-grant route in the assembled gateway. The MCP tool calls the same
grant provider only after elicitation confirmation.
Create exactly one `CadEditHistory` and
`createEditCapabilityComposition(history)` in `createCadApplication.ts`.
The factory accepts:

```ts
interface CadApplicationConfig {
  workspaceRoot: string;
  drawingPath: string;
  exportRoot: string;
  dwgVersionManifestPath: string;
  processRunner: CadProcessRunner;
  destinationSelector: DestinationSelectionProvider;
  clock: () => number;
}
```

It composes the read/query module, `editComposition.module`, and Save/report
module exactly once per process with `composeCadCapabilityModules`.
`gateway.ts`, `mcp/stdio.ts`, and the CLI harness each resolve their own
contained config and call the same factory; they do not share an in-memory
runtime across processes. Within each process, inject the returned runtime
into every local adapter and inject `editComposition.transactions` into both
Save and report orchestration. Add
`@dwg/cad-io-acadsharp` to the root package dependencies and run
`npm install --package-lock-only`.
Make `gateway.ts`, `mcp/stdio.ts`, and `cad-runtime/harness/run-skill.ts` thin
process adapters over this same factory. No entrypoint may call the legacy
`createCadToolRuntime` directly.
Add `e2eExportRoot` and `docsExportRoot` under
`tests/visual/test-results/export-roots/<mode>-<process-id>` in
`repositoryOutputPaths.ts`. Both Playwright configs set `DWG_EXPORT_ROOT` to
their own resolved root for the gateway and use `exportRootGlobalSetup.ts`.
Setup and teardown reject any root outside `tests/visual/test-results`,
operate on the exact resolved per-process child only, assert it is empty at
preflight, and remove that child after the run. No repository/default export
directory is used.

- [ ] **Step 4: Run export integration verification**

Add:

```json
"test:roundtrip": "node --import tsx --test \"tests/roundtrip/**/*.test.ts\""
```

Run:

```powershell
npm run test:roundtrip
npm run test:skills
node --import tsx --test modules/cad-runtime/tests/application/source-document-resolver.test.ts
node --import tsx --test modules/cad-runtime/tests/http/export-composition.test.ts
node --import tsx --test modules/cad-runtime/tests/application/cad-application-composition.test.ts
node --import tsx --test modules/cad-runtime/tests/integration/mcp-server.test.ts
node --import tsx --test apps/workspace/tests/unit/repository-output-paths.test.ts
npm run test:e2e -- save-as.spec.ts
```

Expected: resolver, export, round-trip, skill, and browser integration tests
all pass.

- [ ] **Step 5: Inspect PNGs and commit**

Inspect the save-verified and export captures. Convert any discovered issue
into a failing Playwright assertion before recapture.
`route-captures.spec.ts` must reach verified Save As and completed report
download through visible controls, assert the status and filename, and retain
`save-verified.png` and `export-report.png`.

```powershell
git add modules/cad-runtime/src/http/gateway.ts modules/cad-runtime/src/application/createCadApplication.ts modules/cad-runtime/src/http/drawingWorkspace.ts modules/cad-runtime/src/http/exportCapabilityGateway.ts modules/cad-runtime/src/http/destinationGrantGateway.ts modules/cad-runtime/src/mcp/toolDefinitions.ts modules/cad-runtime/src/mcp/createServer.ts modules/cad-runtime/src/mcp/stdio.ts modules/cad-runtime/harness/run-skill.ts modules/cad-runtime/src/platform/repositoryPaths.ts modules/cad-runtime/src/application/drawing-access/sourceDocumentResolver.ts modules/cad-runtime/src/application/drawing-access/parsedDocumentEvidence.ts modules/cad-runtime/tests/application/source-document-resolver.test.ts modules/cad-runtime/tests/http/export-composition.test.ts modules/cad-runtime/tests/application/cad-application-composition.test.ts modules/cad-runtime/tests/integration/mcp-server.test.ts skills/export-drawing/SKILL.md skills/export-drawing/manifest.json skills/export-drawing/workflows/default.json skills/export-drawing/tests/cases.json skills/export-drawing/examples/input.json skills/export-drawing/examples/output.json apps/workspace/src/shared/api/exportClient.ts apps/workspace/src/features/export/ExportPanel.tsx apps/workspace/playwright.config.ts apps/workspace/playwright.docs.config.ts apps/workspace/tests/support/repositoryOutputPaths.ts apps/workspace/tests/support/exportRootGlobalSetup.ts apps/workspace/tests/unit/repository-output-paths.test.ts apps/workspace/tests/e2e/save-as.spec.ts apps/workspace/tests/docs/route-captures.spec.ts tests/skills/export-skill.test.ts packages/contracts/src/export.ts packages/contracts/src/index.ts docs/ui-captures/save-verified.png docs/ui-captures/export-report.png package.json package-lock.json
git commit -m "feat: deliver verified CAD Save As and exports"
```

### Task 6: Add Preview-Only Editing Skills

**Files:**
- Create: `skills/edit-layers/SKILL.md`
- Create: `skills/edit-layers/manifest.json`
- Create: `skills/edit-layers/workflows/default.json`
- Create: `skills/edit-layers/tests/cases.json`
- Create: `skills/edit-layers/examples/input.json`
- Create: `skills/edit-layers/examples/output.json`
- Create: `skills/edit-text/SKILL.md`
- Create: `skills/edit-text/manifest.json`
- Create: `skills/edit-text/workflows/default.json`
- Create: `skills/edit-text/tests/cases.json`
- Create: `skills/edit-text/examples/input.json`
- Create: `skills/edit-text/examples/output.json`
- Create: `skills/transform-entities/SKILL.md`
- Create: `skills/transform-entities/manifest.json`
- Create: `skills/transform-entities/workflows/default.json`
- Create: `skills/transform-entities/tests/cases.json`
- Create: `skills/transform-entities/examples/input.json`
- Create: `skills/transform-entities/examples/output.json`
- Create: `tests/skills/editing-skills.test.ts`
- Modify: `apps/workspace/tests/docs/route-captures.spec.ts`
- Modify: `docs/ui-captures/change-preview.png`
- Modify: `package.json`

**Interfaces:**
- Editing workflows terminate at `edit.preview`.
- `edit.apply` remains a separate user-approved UI or host action.

- [ ] **Step 1: Write editing skill tests**

Assert each skill produces a valid `CadEditBatch`, returns a preview ID and
bounded diff, never calls `edit.apply` or `export.drawing`, fails without
`propose-edit`, and includes skill ID, version, and run ID in every command's
origin metadata.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test tests/skills/editing-skills.test.ts`

Expected: FAIL because editing skills are absent.

- [ ] **Step 3: Add manifests, examples, workflows, and instructions**

Every SKILL requires handle-based targets, preview review, unsupported-object
reporting, a human-readable purpose, explicit failure and limitation codes,
and explicit user approval outside the skill before apply.

- [ ] **Step 4: Run skill verification**

Run: `npm run test:skills && npm run verify:all && npm run capture:docs`

Expected: PASS and `change-preview.png` is recaptured from an editing-skill
preview with typed handle/layer/type/bbox evidence.

- [ ] **Step 5: Commit**

```powershell
git add skills/edit-layers/SKILL.md skills/edit-layers/manifest.json skills/edit-layers/workflows/default.json skills/edit-layers/tests/cases.json skills/edit-layers/examples/input.json skills/edit-layers/examples/output.json skills/edit-text/SKILL.md skills/edit-text/manifest.json skills/edit-text/workflows/default.json skills/edit-text/tests/cases.json skills/edit-text/examples/input.json skills/edit-text/examples/output.json skills/transform-entities/SKILL.md skills/transform-entities/manifest.json skills/transform-entities/workflows/default.json skills/transform-entities/tests/cases.json skills/transform-entities/examples/input.json skills/transform-entities/examples/output.json tests/skills/editing-skills.test.ts apps/workspace/tests/docs/route-captures.spec.ts docs/ui-captures/change-preview.png package.json
git commit -m "feat: add safe CAD editing skills"
```

### Task 7: Qualify Real-CAD Edge Cases and the Full Agent Workflow

**Files:**
- Create: `tests/fixtures/cad-edge/README.md`
- Create: `tests/fixtures/cad-edge/manifest.json`
- Create: `tests/fixtures/cad-edge/ACADSHARP-LICENSE.txt`
- Create: `tests/fixtures/cad-edge/corrupted-header.dwg`
- Create: `tests/fixtures/cad-edge/aec-custom-object.dwg`
- Create: `tests/fixtures/cad-edge/unresolved-xref.dxf`
- Create: `tests/fixtures/cad-edge/missing-font.dxf`
- Create: `tests/fixtures/cad-edge/cp949-text.dxf`
- Create: `scripts/fetch-cad-edge-fixtures.mjs`
- Create: `scripts/generate-cad-edge-fixtures.mjs`
- Create: `tests/integration/real-cad-edge-cases.test.ts`
- Create: `tests/integration/agent-command-security.test.ts`
- Create: `tests/integration/multi-skill-workflow.test.ts`
- Create: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadWarningCode.cs`
- Modify: `modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIndexBuilder.cs`
- Modify: `modules/cad-runtime/src/application/cad-tools/runtime.ts`
- Modify: `modules/skill-runtime/src/workflowRunner.ts`
- Modify: `tests/fixtures/manifest.json`
- Modify: `package.json`
- Modify: `docs/ui-captures/00-overview.png`
- Modify: `docs/ui-captures/skill-selected.png`
- Modify: `docs/ui-captures/change-preview.png`
- Modify: `docs/ui-captures/save-verified.png`
- Modify: `docs/ui-captures/export-report.png`
- Modify: `docs/ui-captures/sidebar-narrow.png`
- Modify: `docs/ui-captures/dark-theme.png`
- Modify: `README.md`
- Modify: `docs/architecture/ai-clone-handoff.md`
- Modify: `docs/architecture/module-boundaries.md`
- Modify: `docs/architecture/integration-contract.md`
- Create: `modules/cad-runtime/tests/architecture/documentation-contracts.test.ts`
- Create: `tests/integration/clone-handoff-contract.test.ts`

**Interfaces:**
- Edge-case fixtures are immutable, locally generated or redistribution-safe,
  provenance-documented CAD files with exact SHA-256 values and expected
  parser warning codes.
- The workflow test uses only public skill, capability, HTTP, and MCP
  entrypoints.
- Required diagnostic codes are:

```text
CAD_INPUT_CORRUPT
CAD_CUSTOM_OBJECT_UNSUPPORTED
CAD_XREF_UNRESOLVED
CAD_FONT_RESOURCE_MISSING
CAD_CODEPAGE_CONVERSION_APPLIED
```

- The only downloaded binary is pinned to ACadSharp commit
  `219e5fc4a6def2b2d22fbbc1c2597d8e588df6c8`:

```text
https://raw.githubusercontent.com/DomCR/ACadSharp/219e5fc4a6def2b2d22fbbc1c2597d8e588df6c8/samples/aec_objects/AecObjects.dwg
SHA-256 DC196E99B8944D169493C9F3205D45F8A579C0C96E81DBC7FC2F90CD971F7A7E

https://raw.githubusercontent.com/DomCR/ACadSharp/219e5fc4a6def2b2d22fbbc1c2597d8e588df6c8/LICENSE
SHA-256 3CA5F3195B1F3056543596F7BB413BB143484C53CA9DEF699AF8F7964F509190
```

- [ ] **Step 1: Write failing edge-case and workflow tests**

Require exact bounded diagnostic codes for corrupted input, custom/proxy
objects,
unresolved XREFs, missing fonts, and CP949/codepage handling. Reject model
output that contains unknown commands, invalid handles, stale revisions,
undeclared permissions, direct `edit.apply`, or direct `export.drawing`.
Exercise `inspect-drawing`, an editing skill preview, explicit host approval,
apply, independent verification, report export, and drawing Save As as one
multi-skill scenario.
Assert canonical documentation names every public package, dependency
direction, Skill manifest/runtime boundary, edit/export HTTP DTO and route,
MCP read/write tool, `DWG_EXPORT_ROOT`, immutable-source rule, verified Save As
flow, and extension/merge ownership. From a non-repository cwd, the clone
handoff test resolves only documented public entrypoints and runs the
read-only CLI preflight without deep imports.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
node --import tsx --test tests/integration/real-cad-edge-cases.test.ts
node --import tsx --test tests/integration/agent-command-security.test.ts tests/integration/multi-skill-workflow.test.ts
node --import tsx --test modules/cad-runtime/tests/architecture/documentation-contracts.test.ts tests/integration/clone-handoff-contract.test.ts
```

Expected: all three commands FAIL until the fixtures, warning normalization,
workflow harness, and canonical handoff documentation exist.

- [ ] **Step 3: Add provenance-checked fixtures and close only observed gaps**

Implement `fetch-cad-edge-fixtures.mjs` with the two pinned URLs and literal
hashes above. It downloads to a temporary sibling, verifies SHA-256, then
renames to `aec-custom-object.dwg` and `ACADSHARP-LICENSE.txt`; any redirect
outside `raw.githubusercontent.com/DomCR/ACadSharp` or hash mismatch fails.
Implement `generate-cad-edge-fixtures.mjs` to:

1. copy `tests/fixtures/dwg/export_sample.dwg` and corrupt only the copy's
   six-byte header;
2. emit minimal ASCII DXF with an unresolved relative XREF;
3. emit minimal ASCII DXF referencing `CLICK_AROUND_MISSING.shx`;
4. emit an ANSI_949 DXF from literal CP949 byte arrays.

Run both scripts twice and require byte-identical outputs. Write every resulting
literal SHA-256, format, provenance, purpose, and expected diagnostic code to
`cad-edge/manifest.json`, then add those hashes to the root fixture manifest.
Document the generated fixtures and ACadSharp's MIT license in `README.md`.
Normalize diagnostics through `CadWarningCode.cs`; make only the listed
parser/runtime changes required by the failing tests. Do not label the AEC
fixture as a native `PROXY_OBJECT`; it qualifies unsupported custom/proxy-class
handling through observed `AEC_*` entities.
Update the four canonical documents with exact package ownership, supported
entrypoints, transport contracts, environment configuration, tests, source
safety, Save As verification, and steps another AI follows to clone or merge
this module into a larger repository.

Run:

```powershell
node scripts/fetch-cad-edge-fixtures.mjs
node scripts/generate-cad-edge-fixtures.mjs
node scripts/fetch-cad-edge-fixtures.mjs --verify-only
node scripts/generate-cad-edge-fixtures.mjs --verify-only
npm run test:fixtures
```

Expected: PASS with exact manifest hashes and no source fixture mutation.

- [ ] **Step 4: Run the complete release verification loop**

Add:

```json
"verify:release": "npm run verify:all && npm run test:skills && npm run test:roundtrip && node --import tsx --test \"tests/integration/*.test.ts\" && npm run capture:docs && npm audit --audit-level=high"
```

Run sequentially:

```powershell
npm run verify:release
npm --workspace @click-around/workspace run test:live-oauth-browser
git diff --check
git status -sb
```

Expected: every suite passes; live OAuth is 2/2; retained OAuth output contains
only `.last-run.json` and two redacted PNGs.

- [ ] **Step 5: Inspect all retained PNGs**

Inspect `docs/ui-captures/00-overview.png`, skill-selected, change-preview,
save-verified, sidebar, narrow, and dark-theme captures. Convert every visual
defect into a failing Playwright assertion before recapture.

- [ ] **Step 6: Commit**

```powershell
git add tests/fixtures/cad-edge/README.md tests/fixtures/cad-edge/manifest.json tests/fixtures/cad-edge/ACADSHARP-LICENSE.txt tests/fixtures/cad-edge/corrupted-header.dwg tests/fixtures/cad-edge/aec-custom-object.dwg tests/fixtures/cad-edge/unresolved-xref.dxf tests/fixtures/cad-edge/missing-font.dxf tests/fixtures/cad-edge/cp949-text.dxf tests/fixtures/manifest.json tests/integration/real-cad-edge-cases.test.ts tests/integration/agent-command-security.test.ts tests/integration/multi-skill-workflow.test.ts tests/integration/clone-handoff-contract.test.ts modules/cad-runtime/tests/architecture/documentation-contracts.test.ts scripts/fetch-cad-edge-fixtures.mjs scripts/generate-cad-edge-fixtures.mjs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/CadWarningCode.cs modules/cad-io-acadsharp/src/DwgIntelligence.CadIo/DwgIndexBuilder.cs modules/cad-runtime/src/application/cad-tools/runtime.ts modules/skill-runtime/src/workflowRunner.ts package.json README.md docs/architecture/ai-clone-handoff.md docs/architecture/module-boundaries.md docs/architecture/integration-contract.md docs/ui-captures/00-overview.png docs/ui-captures/skill-selected.png docs/ui-captures/change-preview.png docs/ui-captures/save-verified.png docs/ui-captures/export-report.png docs/ui-captures/sidebar-narrow.png docs/ui-captures/dark-theme.png
git commit -m "test: qualify skill-first CAD release"
```

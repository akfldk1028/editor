# CAD Skill Runtime and Built-In Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CAD functionality discoverable and composable through versioned, permissioned, independently tested skills.

**Architecture:** `skill-runtime` loads root skill packages, validates manifests, and executes workflows only through `cad-capabilities`. Skills contain instructions and declarative workflow definitions, not engine imports.

**Tech Stack:** TypeScript 5.8, Node 24 test runner, Zod 3, JSON Schema, Markdown Skill files.

## Global Constraints

- Skill directories are data packages, not executable plugin code.
- A workflow step names a capability and supplies schema-validated bindings.
- Edit skills can propose edits but cannot apply or save without explicit permission.
- Skill output is bounded and contains no provider session identifiers.
- New module READMEs document public entrypoints, allowed dependencies,
  forbidden engine imports, and focused Node test commands.

---

### Task 1: Implement Skill Discovery and Compatibility

**Files:**
- Create: `modules/skill-runtime/package.json`
- Create: `modules/skill-runtime/tsconfig.json`
- Create: `modules/skill-runtime/README.md`
- Create: `modules/skill-runtime/src/index.ts`
- Create: `modules/skill-runtime/src/discovery.ts`
- Create: `modules/skill-runtime/src/compatibility.ts`
- Create: `modules/skill-runtime/tests/discovery.test.ts`
- Create: `tests/skills/fixtures/valid-skill/SKILL.md`
- Create: `tests/skills/fixtures/valid-skill/manifest.json`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Produces:

```ts
interface InstalledCadSkill {
  root: string;
  manifest: CadSkillManifest;
  instructions: string;
  compatible: boolean;
  incompatibility: string | null;
}
function discoverCadSkills(root: string, capabilityVersion: "cad-capabilities/v1"): Promise<InstalledCadSkill[]>;
```

- [ ] **Step 1: Write discovery tests**

Accept the valid fixture. Reject symlink escape, missing files, invalid
manifest, duplicate skill ID/version, instructions over 64 KiB, and a
capability-contract mismatch.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/skill-runtime/tests/discovery.test.ts`

Expected: FAIL because skill runtime is absent.

- [ ] **Step 3: Implement canonical path containment and compatibility**

Sort results by skill ID and semantic version. Incompatible skills remain
listed with a reason but cannot execute.

- [ ] **Step 4: Run tests**

Run: `node --import tsx --test modules/skill-runtime/tests/discovery.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/skill-runtime/package.json modules/skill-runtime/tsconfig.json modules/skill-runtime/README.md modules/skill-runtime/src/index.ts modules/skill-runtime/src/discovery.ts modules/skill-runtime/src/compatibility.ts modules/skill-runtime/tests/discovery.test.ts tests/skills/fixtures/valid-skill/SKILL.md tests/skills/fixtures/valid-skill/manifest.json package.json package-lock.json tsconfig.json
git commit -m "feat: discover versioned CAD skills"
```

### Task 2: Implement Declarative Workflow Execution

**Files:**
- Create: `packages/skill-contracts/src/workflow.ts`
- Modify: `packages/skill-contracts/src/index.ts`
- Create: `modules/skill-runtime/src/workflowRunner.ts`
- Create: `modules/skill-runtime/src/permissions.ts`
- Create: `modules/skill-runtime/tests/workflow-runner.test.ts`

**Interfaces:**
- Produces:

```ts
interface CadSkillWorkflow {
  schemaVersion: "cad-skill-workflow/v1";
  steps: Array<{
    id: string;
    capability: string;
    input: Record<string, unknown>;
  }>;
}
interface CadSkillRunResult {
  skillId: string;
  status: "passed" | "failed" | "cancelled";
  steps: Array<{
    id: string;
    status: "passed" | "failed" | "cancelled";
    output: unknown;
  }>;
  warnings: string[];
}
function runCadSkillWorkflow(options: {
  skill: InstalledCadSkill;
  workflow: CadSkillWorkflow;
  input: unknown;
  grantedPermissions: SkillPermission[];
  capabilities: CadCapabilityRuntime;
  signal?: AbortSignal;
}): Promise<CadSkillRunResult>;
```

- [ ] **Step 1: Write workflow and permission tests**

Test deterministic step order, input binding, missing capability, read denial,
propose-edit denial, output schema failure, 32-step limit, 1 MiB result limit,
and cancellation.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/skill-runtime/tests/workflow-runner.test.ts`

Expected: FAIL because workflow contracts and runner are absent.

- [ ] **Step 3: Implement bounded execution**

Permit bindings only from `$input` and prior `$steps.<id>.output`. Reject
prototype keys and circular values. Pass one `AbortSignal` to every capability.

- [ ] **Step 4: Run runtime tests**

Run: `node --import tsx --test \"modules/skill-runtime/**/*.test.ts\"`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/skill-contracts/src/workflow.ts packages/skill-contracts/src/index.ts modules/skill-runtime/src/workflowRunner.ts modules/skill-runtime/src/permissions.ts modules/skill-runtime/tests/workflow-runner.test.ts
git commit -m "feat: execute permissioned CAD skill workflows"
```

### Task 3: Add Schedule and Drawing Comparison Capabilities

**Files:**
- Create: `modules/cad-query/package.json`
- Create: `modules/cad-query/tsconfig.json`
- Create: `modules/cad-query/README.md`
- Create: `modules/cad-query/src/index.ts`
- Create: `modules/cad-query/src/schedule.ts`
- Create: `modules/cad-query/src/compare.ts`
- Create: `modules/cad-query/tests/schedule.test.ts`
- Create: `modules/cad-query/tests/compare.test.ts`
- Create: `packages/contracts/src/query.ts`
- Modify: `packages/contracts/src/index.ts`
- Modify: `modules/cad-capabilities/src/readCapabilities.ts`
- Modify: `modules/cad-capabilities/src/contracts.ts`
- Modify: `modules/cad-capabilities/package.json`
- Modify: `package-lock.json`

**Interfaces:**
- Adds `query.schedule` and `query.compare`.
- Produces serialized DTOs from `@dwg/contracts`:

```ts
interface CadScheduleRow {
  sourceHandles: string[];
  cells: string[];
  layer: string;
  bbox: CadPointBox | null;
}
interface CadDrawingComparison {
  added: CadEntityMatch[];
  removed: CadEntityMatch[];
  changed: Array<{
    before: CadEntityMatch;
    after: CadEntityMatch;
    fields: Array<"type" | "layer" | "bbox" | "text">;
  }>;
}
```

- [ ] **Step 1: Write deterministic query tests**

Test row ordering, handle evidence, empty schedules, duplicated text,
added/removed/changed entities, bbox tolerance of `1e-6`, and stable output
ordering.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test "modules/cad-query/tests/*.test.ts"`

Expected: FAIL because `cad-query` does not exist.

- [ ] **Step 3: Implement evidence-preserving queries**

Schedule extraction groups indexed TEXT/MTEXT by Y bands and sorts cells by X.
It reports source handles and never claims native table-cell semantics.
Comparison matches non-null handles first and stable IDs second.
Declare `@dwg/cad-query` in `modules/cad-capabilities/package.json`, run
`npm install --package-lock-only`, and consume only its public entrypoint.
Register `query.schedule` and `query.compare` on the existing read/query
`CadCapabilityModule`; do not create a second standalone runtime.

- [ ] **Step 4: Run query and capability tests**

Run: `node --import tsx --test "modules/cad-query/tests/*.test.ts" "modules/cad-capabilities/tests/*.test.ts"`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-query/package.json modules/cad-query/tsconfig.json modules/cad-query/README.md modules/cad-query/src/index.ts modules/cad-query/src/schedule.ts modules/cad-query/src/compare.ts modules/cad-query/tests/schedule.test.ts modules/cad-query/tests/compare.test.ts packages/contracts/src/query.ts packages/contracts/src/index.ts modules/cad-capabilities/src/readCapabilities.ts modules/cad-capabilities/src/contracts.ts modules/cad-capabilities/package.json package-lock.json
git commit -m "feat: add grounded CAD schedule and comparison"
```

### Task 4: Add Read-Only Built-In Skills

**Files:**
- Create: `skills/inspect-drawing/SKILL.md`
- Create: `skills/inspect-drawing/manifest.json`
- Create: `skills/inspect-drawing/workflows/default.json`
- Create: `skills/inspect-drawing/tests/cases.json`
- Create: `skills/inspect-drawing/examples/input.json`
- Create: `skills/inspect-drawing/examples/output.json`
- Create: `skills/extract-schedule/SKILL.md`
- Create: `skills/extract-schedule/manifest.json`
- Create: `skills/extract-schedule/workflows/default.json`
- Create: `skills/extract-schedule/tests/cases.json`
- Create: `skills/extract-schedule/examples/input.json`
- Create: `skills/extract-schedule/examples/output.json`
- Create: `skills/compare-drawings/SKILL.md`
- Create: `skills/compare-drawings/manifest.json`
- Create: `skills/compare-drawings/workflows/default.json`
- Create: `skills/compare-drawings/tests/cases.json`
- Create: `skills/compare-drawings/examples/input.json`
- Create: `skills/compare-drawings/examples/output.json`
- Create: `tests/skills/built-in-skills.test.ts`

**Interfaces:**
- `inspect-drawing` uses `document.open`, `document.describe`,
  `query.layers`, and `query.entities`.
- `extract-schedule` uses `query.text` and `query.schedule`.
- `compare-drawings` uses `query.compare`.

- [ ] **Step 1: Write conformance tests**

Discover exactly three read-only skills, validate their examples, run each
against official fixtures, and assert every entity result includes handle,
type, layer, and bbox when available.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test tests/skills/built-in-skills.test.ts`

Expected: FAIL because the root skills are absent.

- [ ] **Step 3: Add concise Skill instructions and workflows**

Every SKILL includes a human-readable purpose, explicit failure and limitation
codes, and states that model geometry inference is forbidden and unsupported
objects must be reported. Every skill keeps local `tests/cases.json` plus
sanitized `examples/input.json` and `examples/output.json`.

- [ ] **Step 4: Run skill conformance**

Run: `node --import tsx --test tests/skills/built-in-skills.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add skills/inspect-drawing/SKILL.md skills/inspect-drawing/manifest.json skills/inspect-drawing/workflows/default.json skills/inspect-drawing/tests/cases.json skills/inspect-drawing/examples/input.json skills/inspect-drawing/examples/output.json skills/extract-schedule/SKILL.md skills/extract-schedule/manifest.json skills/extract-schedule/workflows/default.json skills/extract-schedule/tests/cases.json skills/extract-schedule/examples/input.json skills/extract-schedule/examples/output.json skills/compare-drawings/SKILL.md skills/compare-drawings/manifest.json skills/compare-drawings/workflows/default.json skills/compare-drawings/tests/cases.json skills/compare-drawings/examples/input.json skills/compare-drawings/examples/output.json tests/skills/built-in-skills.test.ts
git commit -m "feat: add grounded CAD inspection skills"
```

### Task 5: Add Skill Listing and Read-Only Execution HTTP Endpoints

**Files:**
- Create: `modules/cad-runtime/harness/run-skill.ts`
- Create: `modules/cad-runtime/src/http/skillGateway.ts`
- Modify: `modules/cad-runtime/src/http/gateway.ts`
- Create: `modules/cad-runtime/tests/http/skill-gateway.test.ts`
- Create: `tests/skills/skill-cli.test.ts`
- Modify: `packages/contracts/src/skill.ts`
- Modify: `packages/contracts/src/index.ts`
- Modify: `package.json`

**Interfaces:**
- Adds:

```ts
type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
interface SkillListItem {
  id: string;
  version: string;
  compatible: boolean;
  permissions: SkillPermission[];
  recentStatus: "idle" | "running" | "passed" | "failed";
}
interface SkillRunRequest {
  skillId: string;
  version: string;
  documentId: string;
  input: JsonValue;
}
interface SkillRunResponse {
  runId: string;
  skillId: string;
  version: string;
  status: "passed" | "failed";
  previewId: string | null;
  changeCount: number;
  warningCodes: string[];
  result: JsonValue | null;
}
```

- Adds loopback routes:

```text
GET /api/skills
POST /api/skills/run
```

- CLI:

```text
npm run skill -- --skill inspect-drawing --input skills/inspect-drawing/examples/input.json
```

Correction: the standalone CLI consumes the skill input schema, not an MCP
harness scenario.

- [ ] **Step 1: Write HTTP and CLI tests**

Assert skill listing returns public `SkillListItem` DTOs, incompatible skills
remain visible, read-only execution is cancellable, malformed input fails, and
the CLI summary is bounded. Strictly validate `SkillRunRequest` and
`SkillRunResponse` from `@dwg/contracts`; reject unknown fields, invalid
semver, unbounded JSON depth/bytes, and response data that fails the selected
skill's output schema.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-runtime/tests/http/skill-gateway.test.ts tests/skills/skill-cli.test.ts`

Expected: FAIL because skill HTTP and CLI adapters are absent.

- [ ] **Step 3: Add typed HTTP and CLI adapters**

The CLI prints one safe JSON summary containing skill ID, status, change
count, warning count, and preview ID presence as a boolean. It never prints
raw provider text or complete document snapshots. The HTTP gateway forwards
one `AbortSignal` into the workflow runner. Export
`createSkillGatewayRoutes(...)` from `skillGateway.ts`, import it from the
existing `gateway.ts`, and mount it on the same loopback server before the
fallback 404 handler. The HTTP test must start the assembled `gateway.ts`
server, not invoke the route helper directly.
The workflow runner receives the same composed `CadCapabilityRuntime` used by
HTTP and MCP, so one skill can query and then propose an edit without a
transport-specific registry.
The CLI host lives in `cad-runtime/harness`, calls
`createCadApplication(...)`, and injects its composed capabilities into the
reusable `skill-runtime`; `skill-runtime` never imports parser, writer, path,
HTTP, MCP, or root composition code.

- [ ] **Step 4: Run skill and full verification**

Add:

```json
"skill": "tsx modules/cad-runtime/harness/run-skill.ts",
"test:skills": "node --import tsx --test \"modules/skill-runtime/**/*.test.ts\" \"tests/skills/**/*.test.ts\""
```

Run: `npm run test:skills && npm run verify:all`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add modules/cad-runtime/harness/run-skill.ts modules/cad-runtime/src/http/skillGateway.ts modules/cad-runtime/src/http/gateway.ts modules/cad-runtime/tests/http/skill-gateway.test.ts tests/skills/skill-cli.test.ts packages/contracts/src/skill.ts packages/contracts/src/index.ts package.json
git commit -m "feat: expose installed CAD skills"
```

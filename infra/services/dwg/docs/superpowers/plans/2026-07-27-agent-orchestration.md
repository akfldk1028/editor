# DWG Intelligence Agent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every DWG Intelligence specialist agent identifiable, permission-bounded, evidence-checked, and executable through a deterministic plan-execute-verify loop.

**Architecture:** A static registry declares seven typed agent manifests and their readiness. The orchestrator accepts structured inspection requests, constructs an ordered task graph, calls the existing CAD runtime, sends all findings through a deterministic evidence verifier, and returns an event trace that identifies which agent performed each step. LLM integration is outside this plan; no model is allowed to bypass the typed request or evidence gate.

**Tech Stack:** TypeScript 5.8, Node.js 24 test runner, existing CAD tool runtime and `cad-index/v0.1`.

## Global Constraints

- Search and geometry facts must come from existing `cad.*` tools.
- Every finding must contain `id`, `handle`, `type`, `layer`, and `bbox`.
- Missing evidence produces a rejected result, not a warning-only success.
- Only the orchestrator may delegate.
- Delegation depth is exactly one.
- Independent checks may run concurrently with a maximum of three.
- Agents with missing viewer, rule, or report dependencies are marked `planned`.
- Agent identity and readiness are inspectable without calling an LLM.

---

### Task 1: Typed Agent Registry And Identity Audit

**Files:**
- Create: `agent/src/orchestration/types.ts`
- Create: `agent/src/orchestration/agentRegistry.ts`
- Create: `agent/tests/orchestration/agentRegistry.test.ts`

**Interfaces:**
- Produces: `AgentId`
- Produces: `AgentManifest`
- Produces: `listAgentManifests(): readonly AgentManifest[]`
- Produces: `getAgentManifest(id: AgentId): AgentManifest`

- [ ] **Step 1: Write the failing registry test**

```ts
const agents = listAgentManifests();
assert.deepEqual(
  agents.map((agent) => agent.id),
  [
    "orchestrator",
    "drawing-index-agent",
    "search-agent",
    "rule-check-agent",
    "evidence-agent",
    "viewer-agent",
    "report-agent"
  ]
);
assert.equal(getAgentManifest("orchestrator").canDelegate, true);
assert.ok(
  agents.filter((agent) => agent.id !== "orchestrator")
    .every((agent) => agent.canDelegate === false)
);
assert.equal(getAgentManifest("viewer-agent").readiness, "planned");
assert.equal(getAgentManifest("evidence-agent").execution, "deterministic");
```

Also assert unique IDs, nonempty purpose/input/output declarations, exact
allowed CAD tools, `maxConcurrency` between 1 and 3, and evidence policy.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/orchestration/agentRegistry.test.ts
```

Expected: FAIL because `agentRegistry.ts` does not exist.

- [ ] **Step 3: Implement manifest types**

```ts
export type AgentId =
  | "orchestrator"
  | "drawing-index-agent"
  | "search-agent"
  | "rule-check-agent"
  | "evidence-agent"
  | "viewer-agent"
  | "report-agent";

export interface AgentManifest {
  id: AgentId;
  displayName: string;
  purpose: string;
  execution: "deterministic" | "tool-driven" | "hybrid";
  readiness: "active" | "planned";
  allowedTools: readonly string[];
  inputKinds: readonly string[];
  outputKinds: readonly string[];
  evidencePolicy: "required" | "pass-through" | "not-applicable";
  canDelegate: boolean;
  maxConcurrency: number;
}
```

- [ ] **Step 4: Implement the immutable registry**

Readiness:

```text
orchestrator          active
drawing-index-agent   active
search-agent          active
rule-check-agent      planned
evidence-agent        active
viewer-agent          planned
report-agent          planned
```

`drawing-index-agent` is limited to open/build/unsupported tools. `search-agent`
is limited to layer/type/text/entity tools. Planned agents list only tools that
already exist; future tool requirements are stated in their purpose and output
kinds instead of granting nonexistent permissions.

- [ ] **Step 5: Run focused and full tests**

Run:

```powershell
node --import tsx --test agent/tests/orchestration/agentRegistry.test.ts
npm test
npx tsc --noEmit
```

Expected: registry test and all existing tests pass.

- [ ] **Step 6: Commit**

```powershell
git add agent/src/orchestration/types.ts agent/src/orchestration/agentRegistry.ts agent/tests/orchestration/agentRegistry.test.ts
git commit -m "feat: define inspectable CAD agent registry"
```

### Task 2: Deterministic Evidence Gate

**Files:**
- Create: `agent/src/orchestration/evidenceVerifier.ts`
- Create: `agent/tests/orchestration/evidenceVerifier.test.ts`

**Interfaces:**
- Consumes: `CadToolMatch`
- Produces: `EvidenceFinding`
- Produces: `verifyMatches(matches: readonly CadToolMatch[]): EvidenceVerification`

- [ ] **Step 1: Write failing acceptance and rejection tests**

```ts
const accepted = verifyMatches([{
  id: "h:10",
  handle: "10",
  type: "LINE",
  layer: "A-WALL",
  bbox: { min: [0, 0, 0], max: [1000, 0, 0] },
  reason: "layer equals query",
  confidence: 1
}]);
assert.equal(accepted.status, "accepted");

const rejected = verifyMatches([{
  id: "h:10",
  handle: null,
  type: "LINE",
  layer: "A-WALL",
  bbox: null,
  reason: "layer equals query",
  confidence: 0.5
}]);
assert.equal(rejected.status, "rejected");
assert.deepEqual(rejected.issues, [
  { entityId: "h:10", missing: ["handle", "bbox"] }
]);
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/orchestration/evidenceVerifier.test.ts
```

Expected: FAIL because `evidenceVerifier.ts` does not exist.

- [ ] **Step 3: Implement the verifier**

The verifier checks `id`, non-null `handle`, `type`, `layer`, and non-null
`bbox`. It preserves accepted matches unchanged and returns every missing field
for rejected matches.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
node --import tsx --test agent/tests/orchestration/evidenceVerifier.test.ts
npm test
npx tsc --noEmit
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add agent/src/orchestration/evidenceVerifier.ts agent/tests/orchestration/evidenceVerifier.test.ts
git commit -m "feat: reject ungrounded CAD findings"
```

### Task 3: Executable Plan-Execute-Verify Loop

**Files:**
- Create: `agent/src/orchestration/orchestrator.ts`
- Create: `agent/tests/orchestration/orchestrator.test.ts`

**Interfaces:**
- Consumes: `CadToolRuntime`
- Consumes:

```ts
export interface InspectionRequest {
  path: string;
  checks: readonly (
    | { kind: "layer"; value: string }
    | { kind: "type"; value: string }
    | { kind: "text"; value: string; regex?: boolean }
  )[];
}
```

- Produces:

```ts
export interface InspectionRun {
  status: "completed" | "rejected";
  drawingId: string;
  events: AgentEvent[];
  findings: CadToolMatch[];
  issues: EvidenceIssue[];
  warnings: string[];
}
```

- Produces: `createInspectionOrchestrator(runtime?): { run(request): Promise<InspectionRun> }`

- [ ] **Step 1: Write a failing layer-loop test**

Use the real fixture and assert the event order:

```ts
assert.deepEqual(run.events.map((event) => event.agentId), [
  "orchestrator",
  "drawing-index-agent",
  "drawing-index-agent",
  "search-agent",
  "evidence-agent",
  "orchestrator"
]);
assert.equal(run.status, "completed");
assert.equal(run.findings.length, 2);
```

Every returned finding must include the five evidence fields.

- [ ] **Step 2: Write a failing multi-check concurrency test**

Inject a runtime that records active search calls. Submit layer, type, and text
checks. Assert `peakActiveSearchCalls === 3`, event results remain in request
order, and a fourth check never raises peak concurrency above three.

- [ ] **Step 3: Write a failing evidence rejection test**

Inject a runtime whose search result contains `handle: null` and `bbox: null`.
Assert `status === "rejected"`, findings are empty, issues name both missing
fields, and the final orchestrator event records rejection.

- [ ] **Step 4: Run and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/orchestration/orchestrator.test.ts
```

Expected: FAIL because `orchestrator.ts` does not exist.

- [ ] **Step 5: Implement the bounded execution loop**

Execution sequence:

```text
orchestrator: plan
drawing-index-agent: cad.open_drawing
drawing-index-agent: cad.build_index
search-agent: run checks with a worker pool of 3
evidence-agent: verify every match
orchestrator: complete or reject
```

Use an index-preserving worker pool rather than unbounded `Promise.all`.
Propagate `cad.open_drawing` warnings and `cad.list_unsupported` results into
`InspectionRun.warnings`.

- [ ] **Step 6: Run focused and full verification**

Run:

```powershell
node --import tsx --test agent/tests/orchestration/orchestrator.test.ts
npm test
npm run harness -- agent/harness/cases/find-layer-a-wall.json
npm run harness -- agent/harness/cases/find-text-room.json
npx tsc --noEmit
```

Expected: all orchestration, MCP, parser, and harness checks pass.

- [ ] **Step 7: Commit**

```powershell
git add agent/src/orchestration/orchestrator.ts agent/tests/orchestration/orchestrator.test.ts
git commit -m "feat: run verified CAD specialist loop"
```

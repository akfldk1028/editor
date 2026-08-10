# PLANM Always-On GitAgent Runtime Implementation Plan

> **For implementation:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and execute inline, task-by-task. Do not dispatch agent subprocesses. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every deployed PLANM stage through a generic-GitAgent-backed PLANM runtime host without requiring an LLM provider or changing the product API.

**Architecture:** Backend launches one Node host owned by `agents/planm`. The host uses public generic runtime discovery APIs to verify the checked-in workflow and skill, then executes that skill's Python script with the existing versioned engine command injected by Backend. Deterministic geometry remains Backend-owned; no user mode or silent bypass exists.

**Tech Stack:** Python 3.11+, Node.js 22, GitAgent TypeScript build output, FastAPI, pytest, Node test runner, Docker Compose.

## Global Constraints

- Frontend calls only the Backend HTTP API.
- Backend owns run state, project ownership, artifacts, approval, and optional post-approval DWG orchestration.
- `agents/planm` owns identity, contracts, skills, workflow, memory, and its deployment runtime host.
- `agents/runtimes/gitagent` remains generic and imports no PLANM, Backend, or DWG product code.
- PLANM Agent imports no Backend modules and contains no Backend filesystem path.
- DWG remains an independent submodule and process.
- No user-facing runtime mode or activation flag is introduced.
- No LLM provider credential is required for the deployed deterministic path.
- Every child process uses argument arrays with `shell=False` or Node `spawn(..., { shell: false })`.
- Existing `skill-result/v1`, `planm-stage-request/v1`, and HTTP contracts remain unchanged.

---

## File Structure

- Create `agents/planm/runtime/gitagent_host.mjs`: generic-runtime discovery, stage-to-skill resolution, contained script execution, bounded failure result.
- Create `agents/planm/tests/gitagent-host.test.mjs`: host resolver, containment, dispatch, forwarding, and failure tests with a fake public runtime module.
- Modify `backend/app/adapters/planm_agent.py`: build and launch only the Node PLANM host; inject Python and engine commands.
- Modify `backend/tests/test_agent_process_boundaries.py`: enforce Backend-to-host and host-to-runtime dependency direction.
- Modify `backend/tests/test_planm_agent_e2e.py`: run all five stages through the Backend adapter and real GitAgent build output.
- Modify `package.json`: build the generic runtime before Agent host tests and include `.test.mjs` files.
- Modify `deploy/backend.Dockerfile`: retain runtime build output and verify the host file is packaged.
- Modify `README.md` and `docs/architecture/module_map.md`: document the actual always-on runtime path.

---

### Task 1: Stage Resolution Through Generic Runtime Discovery

**Files:**
- Create: `agents/planm/runtime/gitagent_host.mjs`
- Create: `agents/planm/tests/gitagent-host.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: `discoverSkills(agentDir): Promise<SkillMetadata[]>` and `discoverWorkflows(agentDir): Promise<WorkflowMetadata[]>` from the generic runtime public export.
- Produces: `resolveStage({ agentDir, stage, runtime }): Promise<{ skillName: string; scriptPath: string }>`.

- [ ] **Step 1: Write failing stage-resolution tests**

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveStage } from "../runtime/gitagent_host.mjs";

const runtime = {
  discoverSkills: async () => [
    { name: "normalize-plan-request", directory: "C:/repo/agents/planm/skills/normalize-plan-request" },
  ],
  discoverWorkflows: async () => [{
    name: "planm-delivery",
    type: "flow",
    steps: [{ skill: "normalize-plan-request", prompt: "normalize" }],
  }],
};

test("maps normalize to the declared PLANM workflow skill", async () => {
  const result = await resolveStage({ agentDir: "C:/repo/agents/planm", stage: "normalize", runtime });
  assert.equal(result.skillName, "normalize-plan-request");
  assert.match(result.scriptPath.replaceAll("\\\\", "/"), /skills\/normalize-plan-request\/scripts\/run\.py$/);
});

test("rejects a stage absent from the declared workflow", async () => {
  await assert.rejects(
    resolveStage({ agentDir: "C:/repo/agents/planm", stage: "unknown", runtime }),
    /unsupported PLANM stage/,
  );
});
```

- [ ] **Step 2: Run tests and confirm the host module is missing**

Run: `node --test agents/planm/tests/gitagent-host.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `gitagent_host.mjs`.

- [ ] **Step 3: Implement the fixed stage map and discovery checks**

```javascript
import { join } from "node:path";

export const STAGE_SKILLS = Object.freeze({
  normalize: "normalize-plan-request",
  analyze: "analyze-building-mass",
  alternatives: "generate-plan-alternatives",
  review: "review-floorplan",
  deliver: "deliver-planm-package",
});

export async function resolveStage({ agentDir, stage, runtime }) {
  const skillName = STAGE_SKILLS[stage];
  if (!skillName) throw new Error(`unsupported PLANM stage: ${stage}`);
  const [skills, workflows] = await Promise.all([
    runtime.discoverSkills(agentDir),
    runtime.discoverWorkflows(agentDir),
  ]);
  const workflow = workflows.find((item) => item.name === "planm-delivery" && item.type === "flow");
  if (!workflow) throw new Error("PLANM delivery workflow is unavailable");
  const declared = workflow.steps?.filter((step) => step.skill === skillName) ?? [];
  if (declared.length !== 1) throw new Error(`PLANM workflow must declare ${skillName} exactly once`);
  const skill = skills.find((item) => item.name === skillName);
  if (!skill) throw new Error(`PLANM skill is unavailable: ${skillName}`);
  return { skillName, scriptPath: join(skill.directory, "scripts", "run.py") };
}
```

- [ ] **Step 4: Add exact workflow-order and duplicate-declaration tests**

Assert that the five workflow steps equal `Object.values(STAGE_SKILLS)` and that duplicate or missing declarations reject before process launch.

- [ ] **Step 5: Add the host tests to the root Agent test script**

```json
{
  "scripts": {
    "build:agent-runtime": "npm --prefix agents/runtimes/gitagent run build",
    "test:agent": "npm run build:agent-runtime && node --test agents/planm/tests/*.test.ts agents/planm/tests/*.test.mjs --experimental-strip-types"
  }
}
```

- [ ] **Step 6: Run Agent tests**

Run: `npm run test:agent`

Expected: all existing seven tests plus the new host resolver tests pass.

- [ ] **Step 7: Commit stage discovery**

```powershell
git add agents/planm/runtime/gitagent_host.mjs agents/planm/tests/gitagent-host.test.mjs package.json
git commit -m "feat(planm): resolve stages through GitAgent runtime"
```

---

### Task 2: Contained Skill Process Execution

**Files:**
- Modify: `agents/planm/runtime/gitagent_host.mjs`
- Modify: `agents/planm/tests/gitagent-host.test.mjs`

**Interfaces:**
- Consumes: `resolveStage(...)` from Task 1 and environment variable `PLANM_PYTHON_EXECUTABLE`.
- Produces: `runHost({ argv, env, runtime, spawnProcess }): Promise<number>` that forwards a strict `skill-result/v1` payload and child exit code.

- [ ] **Step 1: Write failing execution and containment tests**

Use temporary real directories for `agentDir/skills/<skill>/scripts/run.py`. Assert that a script resolving outside the canonical Agent root rejects, `spawnProcess` receives `shell: false`, and `--input`, `--state`, and `--output-dir` are forwarded unchanged.

```javascript
test("launches only the contained declared skill script", async () => {
  const calls = [];
  const code = await runHost({
    argv: ["normalize", "--input", "input.json", "--state", "state.json", "--output-dir", "out"],
    env: { PLANM_PYTHON_EXECUTABLE: "python-test" },
    runtime,
    agentDir,
    spawnProcess: (command, args, options) => {
      calls.push({ command, args, options });
      return fakeChild({ stdout: VALID_RESULT, code: 0 });
    },
  });
  assert.equal(code, 0);
  assert.equal(calls[0].command, "python-test");
  assert.equal(calls[0].options.shell, false);
});
```

- [ ] **Step 2: Run the new execution tests and confirm failure**

Run: `node --test agents/planm/tests/gitagent-host.test.mjs`

Expected: FAIL because `runHost` is not exported.

- [ ] **Step 3: Implement canonical containment and child forwarding**

Use `realpath()` for the Agent root, skill directory, and script. Require the script path to be beneath `${canonicalAgentDir}${sep}`. Use `spawn(command, args, { cwd: agentDir, env, shell: false, stdio: ["ignore", "pipe", "pipe"] })`. Pipe child stdout/stderr without parsing or rewriting successful output.

- [ ] **Step 4: Implement bounded infrastructure failures**

For discovery, containment, runtime import, or spawn failure, write one `skill-result/v1` blocked payload with violation code `agent_runtime_failed`, no absolute path, and exit code `4`. Limit the public message to 512 characters and replace path-bearing exception text with a stable category.

- [ ] **Step 5: Implement signal and timeout propagation**

Forward `SIGINT` and `SIGTERM` to the active child once. Read `PLANM_SKILL_TIMEOUT_SECONDS`, reject non-finite or non-positive values, and terminate the child after the bounded timeout with violation code `agent_skill_timeout`.

- [ ] **Step 6: Run host tests**

Run: `node --test agents/planm/tests/gitagent-host.test.mjs`

Expected: resolver, containment, forwarding, malformed runtime, and timeout tests pass.

- [ ] **Step 7: Commit process execution**

```powershell
git add agents/planm/runtime/gitagent_host.mjs agents/planm/tests/gitagent-host.test.mjs
git commit -m "feat(planm): execute discovered skills through runtime host"
```

---

### Task 3: Backend Always-On Host Adapter

**Files:**
- Modify: `backend/app/adapters/planm_agent.py`
- Modify: `backend/tests/test_agent_process_boundaries.py`

**Interfaces:**
- Consumes: `agents/planm/runtime/gitagent_host.mjs` CLI and existing stage/path arguments.
- Produces: `build_planm_host_command(repository_root: Path) -> list[str]` and unchanged `run_planm_stage(...) -> dict[str, Any]`.

- [ ] **Step 1: Write failing adapter command tests**

```python
def test_backend_planm_adapter_invokes_only_node_runtime_host() -> None:
    command = build_planm_host_command(PLAN_ROOT)
    assert command[0] in {"node", "node.exe"}
    assert command[1] == str(
        PLAN_ROOT / "agents" / "planm" / "runtime" / "gitagent_host.mjs"
    )
    assert "planm_bridge.py" not in " ".join(command)
```

Add a source-boundary assertion that `planm_agent.py` contains no direct bridge path and that `gitagent_host.mjs` contains no `backend`, `dwg-intelligence`, or `agents/dwg` product import.

- [ ] **Step 2: Run the adapter tests and confirm failure**

Run: `python -m pytest backend/tests/test_agent_process_boundaries.py -q`

Expected: FAIL because `build_planm_host_command` is absent and the adapter still launches Python bridge directly.

- [ ] **Step 3: Implement Backend command construction**

```python
def build_planm_host_command(repository_root: Path) -> list[str]:
    executable = "node.exe" if os.name == "nt" else "node"
    return [
        executable,
        str(repository_root / "agents" / "planm" / "runtime" / "gitagent_host.mjs"),
    ]
```

Have `run_planm_stage` append stage and the three owned paths. Inject:

```python
environment["PLANM_AGENT_DIR"] = str(repository_root / "agents" / "planm")
environment["PLANM_GITAGENT_RUNTIME_ENTRY"] = str(
    repository_root / "external" / "gitagent-runtime" / "dist" / "exports.js"
)
environment["PLANM_PYTHON_EXECUTABLE"] = sys.executable
environment["PLANM_ENGINE_COMMAND_JSON"] = json.dumps(
    [sys.executable, "-m", "backend.app.adapters.planm_engine"]
)
environment["PLANM_ENGINE_CWD"] = str(repository_root)
```

- [ ] **Step 4: Preserve both watchdog layers**

Set `PLANM_SKILL_TIMEOUT_SECONDS` to 90% of the Backend outer timeout. Preserve the existing Python bridge engine timeout at 90% of the skill timeout so termination order remains engine, host, Backend.

- [ ] **Step 5: Update timeout fixtures to create a fake Node host**

The outer-timeout test must create `agents/planm/runtime/gitagent_host.mjs` containing `setTimeout(() => {}, 5000)` and continue to assert `TimeoutError` from the Backend adapter.

- [ ] **Step 6: Run adapter and API tests**

Run: `python -m pytest backend/tests/test_agent_process_boundaries.py backend/tests/test_planm_run_api.py -q`

Expected: all tests pass and no product route contract changes.

- [ ] **Step 7: Commit the Backend adapter**

```powershell
git add backend/app/adapters/planm_agent.py backend/tests/test_agent_process_boundaries.py
git commit -m "refactor(backend): route PLANM through GitAgent host"
```

---

### Task 4: Real Runtime End-to-End Delivery

**Files:**
- Modify: `backend/tests/test_planm_agent_e2e.py`
- Modify: `agents/planm/tests/runtime-boundary.test.ts`

**Interfaces:**
- Consumes: real `agents/runtimes/gitagent/dist/exports.js`, the Backend adapter, and all five PLANM skill scripts.
- Produces: evidence that normalize through deliver traverses the generic runtime host without model credentials.

- [ ] **Step 1: Rewrite the PLANM E2E helper to call `run_planm_stage`**

```python
def _run(stage: str, state: Path, output_dir: Path) -> dict:
    return run_planm_stage(
        stage=stage,
        input_path=SAMPLE,
        state_path=state,
        output_dir=output_dir,
        repository_root=PLAN_ROOT,
        run_root=output_dir,
        timeout_seconds=120,
    )
```

Build the generic runtime once in test setup with `npm --prefix agents/runtimes/gitagent run build`; fail explicitly if `dist/exports.js` is absent.

- [ ] **Step 2: Prove the runtime boundary without changing the result contract**

Keep `skill-result/v1` byte-compatible at the schema boundary. In the host unit test, inject a temporary runtime facade whose `discoverWorkflows` and `discoverSkills` calls are recorded, then assert both calls occur before the skill process starts. In the real E2E test, launch through `gitagent_host.mjs` with the vendored `dist/exports.js` entry and assert the existing delivery result remains valid. Do not add runtime metadata to PLANM result JSON or generated product artifacts.

- [ ] **Step 3: Strengthen the generic runtime boundary test**

Assert that runtime source contains no `agents/planm`, `backend.app`, or `dwg-intelligence`, while the PLANM host imports only the generic runtime entry supplied by environment.

- [ ] **Step 4: Run real Agent tests and E2E**

Run: `npm run test:agent`

Run: `python -m pytest backend/tests/test_planm_agent_e2e.py backend/tests/test_planm_bridge.py backend/tests/test_planm_run_api.py -q`

Expected: all stages deliver at least two distinct reviewed alternatives without any model/API key.

- [ ] **Step 5: Commit E2E evidence**

```powershell
git add backend/tests/test_planm_agent_e2e.py agents/planm/tests/runtime-boundary.test.ts agents/planm/runtime/gitagent_host.mjs
git commit -m "test(planm): prove always-on GitAgent delivery path"
```

---

### Task 5: Deployment and Documentation

**Files:**
- Modify: `deploy/backend.Dockerfile`
- Modify: `README.md`
- Modify: `docs/architecture/module_map.md`
- Modify: `docs/integrations/deployment.md`

**Interfaces:**
- Consumes: committed host, runtime build output, Backend adapter, existing Compose services.
- Produces: one deployable image whose normal API path always traverses the GitAgent host.

- [ ] **Step 1: Add a Docker build assertion**

After the generic runtime build in `deploy/backend.Dockerfile`, add:

```dockerfile
RUN test -f agents/runtimes/gitagent/dist/exports.js \
    && test -f agents/planm/runtime/gitagent_host.mjs
```

- [ ] **Step 2: Update architecture documentation**

Document the exact path:

```text
Backend -> PLANM Node host -> generic GitAgent discovery -> PLANM skill
        -> Python bridge -> injected Backend execution service
```

State explicitly that this is always active, requires no user switch, and does not require an LLM credential.

- [ ] **Step 3: Run focused regression suites**

Run: `python -m pytest backend/tests/test_agent_process_boundaries.py backend/tests/test_planm_agent_e2e.py backend/tests/test_planm_run_api.py -q`

Run: `npm run test:agent`

Expected: all tests pass.

- [ ] **Step 4: Build and start the committed Compose stack**

Run: `docker compose build backend`

Run: `docker compose up -d --force-recreate backend frontend`

Expected: both services are `Up`; Backend logs show successful startup without provider credentials.

- [ ] **Step 5: Execute the deployed product flow**

Create a five-floor mixed-use run through `http://localhost:8080/api/v1/planm`, poll until delivered, require at least two accepted alternatives, approve one, create the DXF handoff, and run `F001_ROOMS` DWG inspection.

Expected evidence:

- run status `delivered`;
- accepted count at least `2`;
- approved alternative recorded;
- DXF entity count greater than `0`;
- DWG inspection status `passed`;
- grounded matches include string handles and bounding boxes;
- warning count `0`.

- [ ] **Step 6: Commit deployment integration**

```powershell
git add deploy/backend.Dockerfile README.md docs/architecture/module_map.md docs/integrations/deployment.md
git commit -m "docs(deploy): document always-on PLANM runtime"
```

- [ ] **Step 7: Final clean-state audit**

Run: `git status --short`

Run: `git submodule status`

Expected: root worktree clean; DWG pointer equals the committed DWG HEAD; no new nested Git repository exists.

# PLANM GitAgent Skill Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an executable PLANM product agent inside `agents/planm` that uses discoverable skills to produce validated alternatives, visual artifacts, and a delivery manifest from a PLAN mass input.

**Architecture:** Keep `external/gitagent-runtime/src` generic. PLANM identity, contracts, workflows, adapters, and skills live in one isolated agent directory. Thin Python adapters call public `backend.app.modules` APIs and exchange persisted JSON contracts; neither the backend nor GitAgent runtime imports PLANM product code.

**Tech Stack:** GitAgent 2.0 TypeScript runtime, Node.js 20+, Python 3.11, JSON Schema, YAML SkillFlows, pytest, Node test runner.

## Global Constraints

- The single source of truth for product skills is `agents/planm/skills`.
- `external/gitagent-runtime/src` must not import PLAN backend or PLANM product files.
- `backend.app.modules` must not import `agent` or GitAgent.
- Deterministic validation cannot be overridden by an LLM.
- Skill status is exactly `success`, `needs_input`, `retryable`, or `blocked`.
- Duplicate canonical candidate fingerprints are not re-evaluated.
- Regulatory `not_checked` remains explicit and is never described as approval.
- BIM delivery remains blocked until its current external verification policy passes.
- Do not run git commands or create commits unless the user explicitly requests them.

---

### Task 1: PLANM Agent Package and Cross-Skill Contracts

**Files:**
- Create: `agents/planm/agent.yaml`
- Create: `agents/planm/SOUL.md`
- Create: `agents/planm/RULES.md`
- Create: `agents/planm/memory/MEMORY.md`
- Create: `agents/planm/contracts/planm-state.schema.json`
- Create: `agents/planm/contracts/skill-result.schema.json`
- Create: `agents/planm/tests/planm-contracts.test.ts`

**Interfaces:**
- Produces: JSON Schema `planm-state/v1` and `skill-result/v1`.
- Produces: Agent directory loadable by `loadAgent(<repo>/agents/planm)`.

- [ ] **Step 1: Write failing contract discovery tests**

```ts
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

test("PLANM contracts expose stable status and artifact boundaries", async () => {
  const result = JSON.parse(await readFile(
    new URL("../agents/planm/contracts/skill-result.schema.json", import.meta.url),
    "utf8",
  ));
  assert.deepEqual(result.properties.status.enum, [
    "success", "needs_input", "retryable", "blocked",
  ]);
  assert.deepEqual(result.required, [
    "contract_version", "skill_name", "status", "outputs",
    "violations", "artifacts", "provenance",
  ]);
});
```

- [ ] **Step 2: Run the failing test**

Run: `npm test -- --test-name-pattern="PLANM contracts"`

Expected: FAIL because `agents/planm/contracts` does not exist.

- [ ] **Step 3: Add the PLANM identity and schemas**

Set `agent.yaml` to `name: planm`, tools `cli`, `read`, and `memory`, and a bounded `max_turns: 40`. Define both schemas with `additionalProperties: false` at the contract root. Require canonical artifact records with `path`, `media_type`, `sha256`, and `size_bytes`.

`RULES.md` must require skills-first execution, persisted state between stages, hard-gate preservation, bounded retries, and explicit unresolved facts. `SOUL.md` must identify PLANM as a building-planning agent rather than a coding assistant.

- [ ] **Step 4: Run contract and existing GitAgent tests**

Run: `npm test`

Expected: PASS, including `PLANM contracts expose stable status and artifact boundaries`.

---

### Task 2: Public Mass Input Parser and PLANM Python Adapter

**Files:**
- Create: `backend/app/schemas/mass_io.py`
- Modify: `backend/app/cli.py`
- Create: `agents/planm/adapters/planm_bridge.py`
- Create: `backend/tests/test_mass_io.py`
- Create: `backend/tests/test_planm_bridge.py`

**Interfaces:**
- Produces: `mass_input_from_payload(payload: dict) -> MassInput`.
- Produces: `python adapters/planm_bridge.py <stage> --input <json> --state <json> --output-dir <dir>`.
- Stages: `normalize`, `analyze`, `alternatives`, `review`, `deliver`.

- [ ] **Step 1: Write failing parser and adapter tests**

```python
def test_mass_input_parser_preserves_typed_floor_context():
    mass = mass_input_from_payload({
        "project_id": "planm-parser",
        "floors": 1,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [],
        "use_mix": {"office": 1.0},
        "building_code_context": {
            "jurisdiction": "KR",
            "effective_date": "2026-08-05",
            "floor_facts": [{"floor_index": 1, "above_grade": True}],
        },
    })
    assert mass.building_code_context is not None
    assert mass.building_code_context.floor_facts[0].floor_index == 1
```

```python
def test_bridge_normalize_writes_versioned_state(tmp_path):
    result = run_bridge("normalize", SAMPLE_INPUT, tmp_path)
    assert result["contract_version"] == "skill-result/v1"
    assert result["status"] == "success"
    state = json.loads((tmp_path / "planm-state.json").read_text())
    assert state["contract_version"] == "planm-state/v1"
    assert state["stage"] == "normalized"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_mass_io.py backend/tests/test_planm_bridge.py -q`

Expected: FAIL because the public parser and bridge do not exist.

- [ ] **Step 3: Extract the parser without changing CLI behavior**

Move the payload-to-`MassInput` conversion contract from `backend.app.cli` into `backend.app.schemas.mass_io`. Keep `backend.app.cli._mass_input_from_payload` as a compatibility alias imported from the public module so existing CLI tests and callers remain valid.

- [ ] **Step 4: Implement bridge stage dispatch and atomic state writes**

The bridge locates the PLAN root from `Path(__file__).parents[5]`, adds only that root to `sys.path`, reads UTF-8 JSON, and writes through a sibling temporary file followed by `Path.replace`. Every stdout response is one JSON object matching `skill-result/v1`; diagnostics go to stderr.

`normalize` validates the mass payload and records unresolved regulatory facts. `analyze` calls `analyze_mass`. Later stages call their existing public APIs. Exceptions map to `needs_input` for input errors, `retryable` for candidate validation failures with attempts remaining, and `blocked` for unsupported or exhausted paths.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest backend/tests/test_mass_io.py backend/tests/test_planm_bridge.py backend/tests/test_cli.py -q`

Expected: PASS.

---

### Task 3: Five Executable PLANM Skills

**Files:**
- Create: `agents/planm/skills/normalize-plan-request/SKILL.md`
- Create: `agents/planm/skills/analyze-building-mass/SKILL.md`
- Create: `agents/planm/skills/generate-plan-alternatives/SKILL.md`
- Create: `agents/planm/skills/review-floorplan/SKILL.md`
- Create: `agents/planm/skills/deliver-planm-package/SKILL.md`
- Create one `scripts/run.py` under each skill directory
- Create: `agents/planm/tests/planm-skills.test.ts`

**Interfaces:**
- Consumes: bridge stage CLI from Task 2.
- Produces: five GitAgent-discoverable skills with names matching their directories.

- [ ] **Step 1: Write failing GitAgent discovery tests**

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { discoverSkills } from "../src/skills.js";

test("PLANM exposes the executable vertical-slice skills", async () => {
  const skills = await discoverSkills(new URL("../agents/planm", import.meta.url).pathname);
  assert.deepEqual(skills.map((skill) => skill.name), [
    "analyze-building-mass",
    "deliver-planm-package",
    "generate-plan-alternatives",
    "normalize-plan-request",
    "review-floorplan",
  ]);
  assert.ok(skills.every((skill) => skill.description.includes("PLANM")));
});
```

- [ ] **Step 2: Run the discovery test and verify RED**

Run: `npm test -- --test-name-pattern="PLANM exposes"`

Expected: FAIL with an empty skill list.

- [ ] **Step 3: Implement concise SKILL.md contracts**

Each frontmatter contains only `name` and `description`. Each body requires reading the current state, invoking its local `scripts/run.py`, checking the returned status, and refusing to advance on `needs_input` or `blocked`. Do not duplicate backend geometry or validation rules in Markdown.

Each `run.py` resolves `agents/planm/adapters/planm_bridge.py` and invokes the fixed stage with `subprocess.run([...], shell=False, check=False)`. It forwards stdout and preserves the bridge exit code. No script constructs shell command strings.

- [ ] **Step 4: Run GitAgent discovery and bridge tests**

Run: `npm test -- --test-name-pattern="PLANM exposes"`

Run: `python -m pytest backend/tests/test_planm_bridge.py -q`

Expected: PASS.

---

### Task 4: PLANM SkillFlow and Bounded State Policy

**Files:**
- Create: `agents/planm/workflows/planm-delivery.yaml`
- Create: `agents/planm/config/default.yaml`
- Create: `agents/planm/tests/planm-workflow.test.ts`

**Interfaces:**
- Produces: GitAgent SkillFlow `@planm-delivery`.
- Consumes: exactly the five skill names from Task 3.

- [ ] **Step 1: Write the failing workflow test**

```ts
test("PLANM delivery flow uses the required skill order", async () => {
  const flows = await discoverWorkflows(planmDir);
  const flow = flows.find((item) => item.name === "planm-delivery");
  assert.deepEqual(flow?.steps?.map((step) => step.skill), [
    "normalize-plan-request",
    "analyze-building-mass",
    "generate-plan-alternatives",
    "review-floorplan",
    "deliver-planm-package",
  ]);
});
```

- [ ] **Step 2: Run the workflow test and verify RED**

Run: `npm test -- --test-name-pattern="PLANM delivery flow"`

Expected: FAIL because the flow is absent.

- [ ] **Step 3: Add the real GitAgent SkillFlow**

Use GitAgent's supported YAML fields only: `name`, `description`, and `steps` with `skill`, `prompt`, and optional `channel`. Every prompt names `planm-state.json` as the stage boundary and requires the previous stage status to be `success`. Set attempt limits in `config/default.yaml`; do not invent unsupported workflow keys.

- [ ] **Step 4: Run workflow and all GitAgent tests**

Run: `npm test`

Expected: PASS.

---

### Task 5: Shared Codex Installation Without a Second Source Tree

**Files:**
- Create: `agents/planm/install_codex_skills.py`
- Create: `backend/tests/test_planm_skill_install.py`

**Interfaces:**
- Produces: `python install_codex_skills.py --codex-home <path> --mode link|copy`.
- Produces: `<codex-home>/skills/planm-<skill-name>` entries and `planm-skills-install.json` hash manifest.

- [ ] **Step 1: Write failing isolated installation tests**

```python
def test_codex_link_install_keeps_planm_as_single_source(tmp_path):
    install(codex_home=tmp_path, mode="link")
    installed = tmp_path / "skills" / "planm-generate-plan-alternatives"
    assert installed.is_symlink()
    assert installed.resolve().name == "generate-plan-alternatives"

def test_install_refuses_to_replace_unmanaged_skill(tmp_path):
    target = tmp_path / "skills" / "planm-review-floorplan"
    target.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        install(codex_home=tmp_path, mode="copy")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_planm_skill_install.py -q`

Expected: FAIL because the installer does not exist.

- [ ] **Step 3: Implement safe link and copy modes**

Default to `link` in development and `copy` in packaging. Prefix installed names with `planm-` to avoid global collisions. Refuse to overwrite directories not listed in the prior install manifest. Hash `SKILL.md` and all regular bundled files in stable relative-path order.

- [ ] **Step 4: Run installer tests**

Run: `python -m pytest backend/tests/test_planm_skill_install.py -q`

Expected: PASS.

---

### Task 6: End-to-End PLANM Delivery

**Files:**
- Create: `backend/tests/test_planm_agent_e2e.py`
- Create runtime artifacts only under the pytest temporary directory

**Interfaces:**
- Consumes: representative input `datasets/manifests/sample_mass_office_commercial.json`.
- Produces: `planm-state.json`, `planm-manifest.json`, two accepted alternative review packages, and canonical artifact hashes.

- [ ] **Step 1: Write the failing end-to-end test**

```python
def test_planm_vertical_slice_delivers_two_reviewed_alternatives(tmp_path):
    state = run_all_stages(
        input_path=Path("datasets/manifests/sample_mass_office_commercial.json"),
        output_dir=tmp_path,
    )
    assert state["status"] == "success"
    assert len(state["accepted_alternative_ids"]) >= 2
    manifest = json.loads((tmp_path / "planm-manifest.json").read_text())
    assert manifest["internal_validation"] == "pass"
    assert manifest["render_validation"] == "pass"
    assert manifest["regulatory_screening"] == "not_checked"
    assert all(Path(item["path"]).is_file() for item in manifest["artifacts"])
    assert len({item["sha256"] for item in manifest["preview_pngs"]}) >= 2
```

- [ ] **Step 2: Run the end-to-end test and verify RED**

Run: `python -m pytest backend/tests/test_planm_agent_e2e.py -q`

Expected: FAIL until all bridge stages persist and consume the shared state correctly.

- [ ] **Step 3: Complete stage state transitions and delivery manifest**

Ensure each stage records its input hash, output hash, start/end timestamps, attempt number, skill name, and artifacts. `deliver` succeeds only when at least two semantically distinct alternatives have internal and render status `pass`. Preserve regulatory `not_checked` and unresolved facts in the manifest without blocking concept delivery.

- [ ] **Step 4: Run focused product verification**

Run: `python -m pytest backend/tests/test_mass_io.py backend/tests/test_planm_bridge.py backend/tests/test_planm_skill_install.py backend/tests/test_planm_agent_e2e.py -q`

Run: `npm test`

Expected: all tests PASS.

- [ ] **Step 5: Run the real representative workflow and retain artifacts**

Run from `C:\DK\PLAN`:

```powershell
python agents/planm/adapters/planm_bridge.py normalize `
  --input datasets/manifests/sample_mass_office_commercial.json `
  --state logs/runs/planm-agent/planm-state.json `
  --output-dir logs/runs/planm-agent
```

Then invoke the remaining four stages against the same state. Open the retained review index and inspect the alternative PNGs before reporting completion.

Expected: `planm-manifest.json` reports at least two accepted alternatives, internal/render pass, regulatory not checked, and distinct preview hashes.

# PLANM GitAgent Skill Runtime Design

## Objective

Build PLANM as a deployable product agent that selects and executes versioned
skills to turn a building mass request into validated floor-plan alternatives,
visual review artifacts, bounded repairs, and BIM handoff evidence.

The GitAgent framework remains a reusable runtime. PLANM-specific identity,
contracts, workflows, skills, adapters, and memory live under one isolated
agent package inside that runtime.

## Ownership Boundary

```text
agents/runtimes/gitagent/
  src/                         GitAgent runtime; no PLAN imports
  agents/
    planm/
      agent.yaml               runtime and model policy
      SOUL.md                  product identity
      RULES.md                 safety and validation policy
      contracts/               stable JSON boundaries
      memory/                  product continuity
      workflows/               bounded orchestration definitions
      adapters/                PLAN Python bridge
      skills/                  PLANM product skills
      tests/                   agent contract and workflow tests
```

The existing Python modules remain the deterministic domain engine:

```text
PLANM Agent -> PLANM Skill -> PLAN adapter -> backend.app.modules
backend.app.modules -X-> agent/gitagent
agents/runtimes/gitagent/src -X-> PLAN domain code
```

No PLAN-specific behavior belongs in `agents/runtimes/gitagent/src`. This keeps GitAgent
replaceable and prevents framework updates from owning product behavior.

## Skill Layout

Each skill is a kebab-case directory with a concise `SKILL.md` and deterministic
scripts when execution is required.

```text
agents/planm/skills/
  normalize-plan-request/
  analyze-building-mass/
  plan-space-program/
  generate-floorplan/
  generate-plan-alternatives/
  validate-floorplan/
  review-floorplan/
  repair-floorplan/
  export-bim-ifc/
  deliver-planm-package/
```

Skills do not import one another. Workflows compose skills through persisted
contract documents. This prevents hidden state and allows one skill to be
replaced without changing the others.

## Contracts

`contracts/planm-state.schema.json` defines the workflow state:

- request identity and normalized requirements
- source mass input and typed regulatory context
- current stage and bounded attempt counters
- generated candidate and alternative identifiers
- hard-gate violations and unresolved facts
- canonical artifact links and content hashes
- final completion status and delivery blockers

`contracts/skill-result.schema.json` defines every skill result:

- `skill_name` and `contract_version`
- `status`: `success`, `needs_input`, `retryable`, or `blocked`
- typed `outputs`
- structured `violations`
- canonical `artifacts`
- retry guidance and provenance

Skills must not report `success` from process exit status alone. Required files,
schema validity, domain validation, and render evidence must support success.

## Initial Executable Vertical Slice

The first slice implements five executable skills:

1. `normalize-plan-request`
2. `analyze-building-mass`
3. `generate-plan-alternatives`
4. `review-floorplan`
5. `deliver-planm-package`

The slice accepts an existing PLAN mass JSON file, produces at least two
geometrically distinct accepted alternatives where the supported mass permits
them, writes architectural SVG/PNG/HTML review artifacts, and emits a PLANM
manifest. Unsupported or unresolved requirements remain explicit blockers.

The remaining skills are added only when their deterministic backend contracts
are ready. `export-bim-ifc` must remain blocked until IFC validation and the
required external-open verification policy are satisfied.

## Workflow

```text
normalize request
  -> analyze mass
  -> generate alternatives
  -> validate each candidate
  -> render and inspect evidence
  -> repair from structured violations when retryable
  -> select accepted alternatives
  -> package PLANM result
```

The repair loop is bounded by workflow configuration. A repeated canonical
fingerprint is not re-evaluated. Hard-gate violations are passed unchanged to
the repair skill. An LLM may interpret requirements or choose among valid
strategies, but cannot override deterministic geometry, egress, render, or BIM
validation.

## Runtime Policy

The default runtime is deterministic-first:

- deterministic skills execute without an LLM decision when prerequisites are
  complete
- an LLM is optional for request interpretation, strategy selection, and user
  explanation
- every LLM proposal is converted to a typed contract before domain execution
- missing jurisdiction, effective date, or floor code facts produce
  `needs_input`, not fabricated assumptions
- retry and tool-call limits are configured in `agent.yaml` and workflow files

## Development and Deployment

`agents/planm/skills` is the single source of truth.

- GitAgent loads it directly when run with
  `--dir agents/planm`.
- A Windows installation script creates Codex skill directory links or performs
  an explicit synchronized install when links are unavailable.
- Deployment packages GitAgent, `agents/planm`, and the PLAN Python engine.
- Deployed runtime never depends on a developer's `C:\Users\...\.codex` path.
- Skill installation records source paths and hashes so stale copies are
  detectable.

## Error Handling

- Invalid input: `needs_input` with field-level errors.
- Unsupported geometry or program: `blocked` with domain violation evidence.
- Candidate hard-gate failure: `retryable` while attempts remain.
- Duplicate candidate fingerprint: skip and record duplicate provenance.
- Render mismatch or unresolved label collision: candidate remains rejected.
- Regulatory applicability unresolved: preserve `not_checked`; do not present
  regulatory approval.
- Missing BIM external verification: BIM delivery remains blocked while concept
  artifacts may still be delivered.

## Verification

The vertical slice requires:

- schema tests for valid and invalid skill results
- skill discovery tests through GitAgent
- adapter tests against deterministic PLAN fixtures
- workflow tests for success, retry, duplicate, needs-input, and blocked paths
- an end-to-end run on the representative office/commercial mass
- at least two accepted, semantically distinct alternatives for the supported
  representative fixture
- retained PNG comparison and direct visual inspection
- Codex installation link/copy verification

GitAgent framework tests and PLAN Python tests run separately. Product success
requires both suites plus the end-to-end workflow.

## Non-Goals

- Rewriting deterministic geometry algorithms in TypeScript
- Allowing an LLM to approve invalid plans
- Moving PLAN backend modules into the GitAgent framework source
- Claiming BIM/Revit completion without current external verification
- Generating every planned skill as a non-executable placeholder

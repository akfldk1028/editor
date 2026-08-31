# PLANM execution and recovery

## Authority

- Backend owns `run.json`, run status, attempts, resume position, approval, and
  CAD handoff state.
- PLANM owns its manifest, contracts, ordered workflow, skills, and
  `planm-state.json`.
- The generic GitAgent runtime loads and validates the PLANM manifest, discovers
  the declared workflow and skill, and does not import PLAN or DWG product code.
- PLAN deterministic Python services own geometry generation and validation.

## Persisted run fields

- `next_stage`: the first unfinished stage
- `stage_attempts`: bounded count per stage
- `execution_history`: completed attempt status, timestamp, and violations
- `violations`: the current terminal or recoverable failure

Every stage request, agent state, and skill result is validated against the
checked-in Draft 2020-12 schemas under `agents/planm/contracts`.

## Retry and resume

- `agent_process_failed`, `engine_timeout`, and `stage_execution_failed` are
  transient and retry automatically up to `maximum_stage_attempts`.
- Deterministic planning failures do not auto-repeat without a changed repair
  input. They remain at the same `next_stage` for explicit recovery.
- Attempt exhaustion becomes `blocked` with `stage_attempts_exhausted`.
- `POST /api/v1/planm/runs/{run_id}/execute` explicitly resumes a run.
- Before resuming, Backend reconciles `planm-state.json`; if the agent committed
  a stage immediately before a Backend crash, execution starts at the following
  stage.
- An OS-backed file lock prevents two processes from executing one run at the
  same time. Repeating execute after delivery performs no work.

## Optional LLM repair boundary

`agent.yaml` declares deterministic execution and an optional LLM proposal mode.
No model is called in the normal workflow. A future repair provider may propose
a typed bounded adjustment, but Backend must validate it and deterministic skills
must re-run every hard gate. It cannot alter approval or verified regulatory
status directly.

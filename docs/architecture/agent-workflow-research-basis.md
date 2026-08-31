# Agent workflow research basis

The workspace uses a deterministic workflow kernel with optional model-assisted
repair proposals. A model never owns PLAN run state and never bypasses geometry,
render, approval, or CAD handoff validation.

## Adopted findings

- ReAct interleaves reasoning and actions to update plans and handle exceptions.
  PLANM uses that pattern only at an optional repair boundary; deterministic
  skills remain the authority for geometry and validation.
  <https://arxiv.org/abs/2210.03629>
- Durable Functions persists workflow progress and reconstructs execution from
  durable state. PLANM therefore persists `next_stage`, per-stage attempts, and
  execution history, and reconciles Backend progress with agent state after a
  crash window. <https://arxiv.org/abs/2103.00033>
- Beldi demonstrates log-based fault-tolerant stateful function composition.
  PLANM retains append-only attempt evidence and uses an OS file lock so duplicate
  workers cannot execute the same run concurrently.
  <https://arxiv.org/abs/2010.06706>
- JSON Schema Draft 2020-12 defines structural validation assertions. PLANM
  validates stage requests, persisted agent state, and skill results at runtime
  instead of checking only a version string.
  <https://json-schema.org/draft/2020-12/json-schema-validation>
- MCP separates model-controlled tools from application-controlled resources.
  PLAN and DWG remain independent products connected by explicit public
  contracts; private runtime modules are not exposed as agent tools.
  <https://modelcontextprotocol.io/specification/2025-06-18/basic/index>

## Deliberate limits

- No provider or model credential is required for normal PLAN execution.
- An LLM repair proposal is optional and is not implemented as an authority.
- Non-transient geometry failures remain `retryable` for an explicit repair or
  resume; the system does not repeatedly run an identical deterministic stage
  automatically.
- Regulatory facts remain unresolved until supplied and are never inferred by a
  model as verified facts.

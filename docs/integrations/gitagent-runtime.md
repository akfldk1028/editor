# GitAgent Runtime Boundary

`agents/runtimes/gitagent` is a repository-owned vendored snapshot of the
generic GitAgent executor. Its upstream identity is recorded in
`agents/runtimes/gitagent/UPSTREAM.md`.

## Ownership

- Runtime source owns generic agent loading, skills, workflows, tools, MCP,
  scheduling, telemetry, and SDK behavior.
- `agents/planm` owns PLANM identity, contracts, skills, workflows, and memory.
- `external/dwg-intelligence` owns the independent DWG Agent and CAD runtime.
- Runtime source must not import PLAN Backend, PLANM, or DWG product code.

## Local verification

```powershell
npm --prefix agents/runtimes/gitagent ci
npm --prefix agents/runtimes/gitagent run build
npm --prefix agents/runtimes/gitagent test
npm run test:agent
```

The runtime receives an Agent directory as configuration. It never discovers a
product Agent through a hard-coded repository-relative path.

## PLANM execution

Backend always starts `agents/planm/runtime/gitagent_host.mjs`. The host loads
the configured runtime entry, discovers `planm-delivery` and the stage's named
skill, verifies the canonical five-skill order, and executes only that skill's
contained `scripts/run.py`. The Python bridge and deterministic Backend engine
remain separate process boundaries. This path has no activation mode and does
not require model credentials.

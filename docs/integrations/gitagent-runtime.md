# GitAgent Runtime Boundary

`external/gitagent-runtime` is a repository-owned vendored snapshot of the
generic GitAgent executor. Its upstream identity is recorded in
`external/gitagent-runtime/UPSTREAM.md`.

## Ownership

- Runtime source owns generic agent loading, skills, workflows, tools, MCP,
  scheduling, telemetry, and SDK behavior.
- `agents/planm` owns PLANM identity, contracts, skills, workflows, and memory.
- `external/dwg-intelligence` owns the independent DWG Agent and CAD runtime.
- Runtime source must not import PLAN Backend, PLANM, or DWG product code.

## Local verification

```powershell
npm --prefix external/gitagent-runtime ci
npm --prefix external/gitagent-runtime run build
npm --prefix external/gitagent-runtime test
npm run test:agent
```

The runtime receives an Agent directory as configuration. It never discovers a
product Agent through a hard-coded repository-relative path.

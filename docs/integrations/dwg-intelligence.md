# DWG Intelligence integration boundary

DWG Intelligence is pinned as an independent Git submodule at
`external/dwg-intelligence`. Its source, dependencies, tests, agent guidance,
and repository memory remain owned by that repository.

## Boundary

- Do not copy DWG source into `backend/`, `frontend/`, or `agent/gitagent/`.
- Do not deep-import DWG parser, runtime, workspace feature, or CAD capability
  internals.
- Prefer the DWG loopback `/api` or MCP stdio process boundary when PLAN needs
  CAD inspection or export capabilities.
- Contract-only consumers may use the public `@dwg/contracts` or
  `@dwg/skill-contracts` package entrypoints with their declared dependencies.
- Before changing the submodule, read
  `external/dwg-intelligence/AGENTS.md` and
  `external/dwg-intelligence/docs/handoff/repo-memory.md`.

PLANM and GitAgent remain PLAN-owned. They may call a supported DWG process
surface, but neither repository imports the other's internal implementation.

## Initialize and verify

```powershell
git submodule update --init --recursive
npm --prefix external/dwg-intelligence ci
npm --prefix external/dwg-intelligence run verify
```

Update the submodule only to a reviewed DWG commit, then commit the changed
submodule pointer in PLAN separately from DWG implementation work.

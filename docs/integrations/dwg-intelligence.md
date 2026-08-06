# DWG Intelligence integration boundary

DWG Intelligence is pinned as an independent Git submodule at
`external/dwg-intelligence`. Its source, dependencies, tests, agent guidance,
and repository memory remain owned by that repository.

## Boundary

- Do not copy DWG source into `backend/`, `frontend/`, `agents/planm/`, or
  `external/gitagent-runtime/`.
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

## Approved-plan CAD capability

The default PLANM generation loop never starts DWG. After approval only:

1. `backend/app/modules/cad_handoff` converts reviewed SVG geometry into a
   layered, meter-unit DXF owned by the PLAN run.
2. `backend/app/adapters/dwg_client.py` starts the public DWG `gateway` process
   with the run's `cad-handoff` directory as `DWG_WORKSPACE`.
3. Backend calls loopback `/api/drawing` and `/api/skills/run`; it never imports
   a DWG source module.
4. The `inspect-drawing` result is retained as
   `cad-handoff/inspection.json`, with only relative paths in PLAN records.

The current DXF handoff uses floor-prefixed layers such as `F001_ROOMS` and
places floors side by side. It is an inspection/export artifact, not a claim
that native DWG authoring or regulatory validation has completed.

During integration, the DWG DXF indexer was found to return numeric handles for
handle-less ASCII DXF even though the public contract requires `string | null`.
The fix and regression test belong to the DWG submodule and must be committed
and released there before updating PLAN's submodule pointer.

## Initialize and verify

```powershell
git submodule update --init --recursive
npm --prefix external/dwg-intelligence ci
npm --prefix external/dwg-intelligence run verify
```

Update the submodule only to a reviewed DWG commit, then commit the changed
submodule pointer in PLAN separately from DWG implementation work.

# DWG Intelligence integration boundary

DWG Intelligence is vendored as one complete independent product module at
`external/dwg-intelligence`. PLAN directly tracks its workspace, runtime,
parsers, contracts, skills, tests, agent guidance, and repository memory so a
normal PLAN checkout contains every DWG Frontend and Backend source file.

## Boundary

- Do not copy DWG source into `backend/`, `frontend/`, `agents/planm/`, or
  `external/gitagent-runtime/`.
- Do not deep-import DWG parser, runtime, workspace feature, or CAD capability
  internals.
- Prefer the DWG loopback `/api` or MCP stdio process boundary when PLAN needs
  CAD inspection or export capabilities.
- Contract-only consumers may use the public `@dwg/contracts` or
  `@dwg/skill-contracts` package entrypoints with their declared dependencies.
- Before changing the vendored module, read
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
The vendored module retains the string-handle normalization and its regression
test while preserving all other source from the reviewed DWG checkout.

## Initialize and verify

```powershell
npm --prefix external/dwg-intelligence ci
npm --prefix external/dwg-intelligence run verify:all
```

Upstream synchronization must compare tracked blobs, preserve PLAN-reviewed
fixes, exclude nested `.git`, local OAuth state, generated outputs, and source
drawings, then rerun the complete DWG verification before committing the
vendored update.

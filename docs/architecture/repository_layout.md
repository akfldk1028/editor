# PLAN Repository Layout

The repository tree is an ownership boundary, not a feature inventory. Product
code belongs to exactly one of the following top-level modules.

```text
PLAN/
|-- frontend/                 PLAN web UI; Backend HTTP only
|-- backend/
|   |-- app/
|   |   |-- api/              versioned HTTP routes
|   |   |-- schemas/          frontend-to-backend DTOs
|   |   |-- modules/          PLAN domain and orchestration services
|   |   `-- adapters/         thin PLANM and DWG process clients
|   |-- engine/               backend-owned geometry and validation primitives
|   `-- tests/                backend unit and contract tests
|-- agents/
|   |-- planm/
|   |   |-- agent.yaml        agent manifest
|   |   |-- SOUL.md           identity
|   |   |-- RULES.md          behavior boundary
|   |   |-- config/           agent-owned configuration
|   |   |-- contracts/        backend-to-agent JSON contracts
|   |   |-- runtime/          GitAgent host and process bridge
|   |   |-- skills/           executable PLANM capabilities
|   |   |-- workflows/        ordered skill flows
|   |   |-- memory/           PLANM product memory
|   |   `-- tests/            agent contract and runtime tests
|   |-- runtimes/
|   |   `-- gitagent/         generic runtime; no PLAN or DWG imports
|   `-- dwg/                  vendored independent DWG product module
|-- infra/
|   |-- docker/               container definitions and reverse proxy config
|   |-- dev/                  local product launcher and structure tests
|   `-- e2e/                  product UI and visual E2E, Playwright configs
|-- resources/
|   |-- datasets/             retained source and normalized fixtures
|   |-- experiments/          bounded experiment definitions and evidence
|   |-- research/             papers, notes, cards, and survey material
|   `-- scripts/              retained research and ingestion scripts
`-- docs/                     architecture, decisions, integrations, evidence
```

No `external/` directory exists. It was removed when each product took ownership
of its own module: the generic runtime became `agents/runtimes/gitagent/` and the
vendored DWG product became `agents/dwg/`.

## Dependency Rules

```text
Frontend -> Backend API
Backend -> PLANM adapter -> GitAgent host -> PLANM skill -> process bridge
Backend -> DWG adapter -> independent DWG process, after approval only
```

- Frontend never imports Backend, PLANM, GitAgent, or DWG source.
- Backend modules never import `agents/planm` or `agents/dwg` product internals.
- PLANM never imports Backend modules or DWG internals.
- The generic GitAgent runtime never imports PLANM, Backend, or DWG code.
- DWG never imports PLANM or Backend modules.
- Cross-module data uses versioned JSON or public HTTP/MCP contracts.

## Non-Product Directories

None of the following is a product module. No production import, workflow path,
installer, or deployment command may depend on one.

Ignored, and excluded from IDE indexing:

- `clone/`: large local research checkouts.
- `logs/`: generated runs, migration backups, and retained execution evidence.
- `test-results/`, `playwright-report/`: browser verification artifacts.
- `node_modules/`, `dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`:
  generated dependencies, builds, and caches.
- `.worktrees/`: local isolated Git worktrees.
- `.idea/`: local IDE configuration.

Tracked, because they carry decision history a later session needs:

- `.superpowers/sdd/`: per-task briefs and reports for completed work.
- `.remember/`: session handoff state.

`docs/` holds both documentation and retained evidence. `architecture/`,
`decisions/`, `integrations/`, `schemas/`, `datasets/`, `research_plan/`, and
`superpowers/` are documentation. The remaining dated directories are the
evidence a plan or spec produced; their names are referenced from those records
and are not renamed after the fact.

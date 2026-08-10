# PLAN Repository Layout

The repository tree is an ownership boundary, not a feature inventory. Product
code belongs to exactly one of the following top-level modules.

```text
PLAN/
|-- frontend/                 PLAN web UI; Backend HTTP only
|-- backend/
|   `-- app/
|       |-- api/              versioned HTTP routes
|       |-- schemas/          frontend-to-backend DTOs
|       |-- modules/          PLAN domain and orchestration services
|       `-- adapters/         thin PLANM and DWG process clients
|-- agents/
|   `-- planm/
|       |-- agent.yaml        agent manifest
|       |-- SOUL.md           identity
|       |-- RULES.md          behavior boundary
|       |-- config/           agent-owned configuration
|       |-- contracts/        backend-to-agent JSON contracts
|       |-- runtime/          GitAgent host and process bridge
|       |-- skills/           executable PLANM capabilities
|       |-- workflows/        ordered skill flows
|       |-- memory/           PLANM product memory
|       `-- tests/            agent contract and runtime tests
|-- external/
|   |-- gitagent-runtime/     generic runtime; no PLAN or DWG imports
|   `-- dwg-intelligence/     vendored independent DWG product module
|-- backend/
|   |-- engine/              backend-owned geometry and validation primitives
|-- infra/docker/                   container definitions and reverse proxy config
|-- tests/browser/            product UI and visual E2E tests
|-- datasets/                 retained source and normalized fixtures
|-- experiments/              bounded experiment definitions and evidence
|-- research/                 papers, notes, cards, and survey material
`-- docs/                     architecture, decisions, integrations, evidence
```

## Dependency Rules

```text
Frontend -> Backend API
Backend -> PLANM adapter -> GitAgent host -> PLANM skill -> process bridge
Backend -> DWG adapter -> independent DWG process, after approval only
```

- Frontend never imports Backend, PLANM, GitAgent, or DWG source.
- Backend modules never import `agents/planm` or `external` product internals.
- PLANM never imports Backend modules or DWG internals.
- The generic GitAgent runtime never imports PLANM, Backend, or DWG code.
- DWG never imports PLANM or Backend modules.
- Cross-module data uses versioned JSON or public HTTP/MCP contracts.

## Non-Product Directories

The following paths may exist in a developer checkout but are not product
modules and must remain ignored and excluded from IDE indexing:

- `clone/`: large local research checkouts.
- `logs/`: generated runs, migration backups, and retained execution evidence.
- `test-results/`, `playwright-report/`: browser verification artifacts.
- `node_modules/`, `dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`:
  generated dependencies, builds, and caches.
- `.worktrees/`: local isolated Git worktrees.
- `.superpowers/`, `.remember/`: development-tool records, not runtime code.

No production import, workflow path, installer, or deployment command may depend
on a non-product directory.

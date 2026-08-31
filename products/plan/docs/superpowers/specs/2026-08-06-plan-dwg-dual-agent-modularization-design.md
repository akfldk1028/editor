# PLAN/DWG Dual-Agent Modularization Design

## Goal

Make `C:\DK\PLAN` the PLANM product integration repository while keeping the
PLAN Agent and DWG Agent as independent product agents and processes.

## Ownership

```text
frontend/                       PLAN UI only
backend/app/schemas/            versioned frontend HTTP DTOs
backend/app/adapters/           PLAN Agent and DWG process clients
backend/app/modules/            PLAN domain implementation
agents/planm/                   PLAN Agent identity, contracts, skills, workflows, memory
agents/runtimes/gitagent/      generic GitAgent runtime
agents/dwg/      independent DWG repository, including its own Agent
docs/integrations/              process and contract integration documentation
```

## Allowed Dependencies

```text
Frontend -> PLAN Backend HTTP API
PLAN Backend -> PLANM adapter -> PLAN Agent -> GitAgent runtime
PLAN Backend -> DWG adapter -> DWG loopback API or MCP
```

PLAN Agent and DWG Agent never import each other. Frontend never invokes an
Agent or DWG directly. GitAgent runtime never imports PLAN domain code. DWG is
not part of default generation; it is an optional post-approval CAD capability.

## Migration

1. Extract PLANM product files from the untracked nested GitAgent checkout into
   `agents/planm`, preserving current behavior and relocating product tests.
2. Register a clean generic runtime under `agents/runtimes/gitagent`; upstream
   runtime changes must be committed in a reviewed fork or replaced by a
   released package, never left as a dirty nested repository.
3. Replace PLAN Agent direct Python imports with a versioned JSON process/API
   boundary owned by `backend/app/adapters`.
4. Add Backend run/project/status/artifact orchestration and then a Frontend UI
   that calls only those HTTP endpoints.
5. Add optional DWG inspection/export through its published API/MCP contracts.

Every step preserves existing uncommitted work and is reviewed before the next
step. Repository-root-relative paths replace personal absolute paths.

## Acceptance

- Folder ownership is unambiguous and enforced by dependency tests.
- PLAN and DWG Agents have separate identity, skills, workflow, memory, state,
  contracts, and process lifecycle.
- Existing PLANM accepted-alternative and visual artifact gates remain intact.
- Python, Agent contract, PLANM E2E, Frontend, and Playwright checks pass after
  their owning migration stages.

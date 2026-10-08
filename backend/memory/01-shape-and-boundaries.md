# Shape and boundaries (2026-10-06)

## What this backend is
FastAPI app `backend.app.main:create_app` (port 18449, declared once in
`infra/config/services.json` → `infra/dev/runtime.mjs BACKEND_PORT`). It is the **domain owner**
of the 25_ACE platform: land/parcel analysis, law reference, the design/massing runtime, the
MasterPlan planning engine, the AutoGen workspace (absorbed from AutoGen Studio "AG"), and the
doors agents call. ARR (old Django backend) and AG are **absorbed**: nothing runs or calls
them any more (verified 2026-10-06: no ARR/AG process, no listener on 18000/18320/8081). Their
folders remain only as read-only reference; `infra/dev/inventory-original-ui.mjs` and the
`*source-manifest.json` files cite them.

## Layers (where code goes)
Enforced by import-linter (`[tool.importlinter]` in pyproject, `lint-imports`, test_import_layers.py):
`route_inventory` > `main | cli` > `api` > `modules` > `adapters` > `core | schemas | contracts`. A new
violation fails the test; never add to `ignore_imports` without a reason line.
- `app/modules/<domain>/routers/*.py` (law: `modules/law/router.py`) — thin FastAPI routers
  (parse, check origin/token, call a module); each domain owns its routers. `app/api/` keeps
  only the agent doors (`routes_agent_providers.py`, `routes_design_runtime.py`).
- `app/api/design_runtime/` — a **Django** URLConf + views reached through the FastAPI
  catch-all `routes_design_runtime.py` (`/api/v1/design/{path}`). Legacy ARR design views live
  here; FastAPI owns `modules/design/routers/workspace.py` paths (no duplicates).
- `app/api/agent_providers/{law,land,design}.py` — agent-only ops behind
  `routes_agent_providers.py` (`POST /api/v1/{domain}/agent/{op}`).
- `app/modules/<domain>/` — logic (land, law, design, massing, workspace, planm_runs, ...).
- `app/adapters/` — external systems (autogen, Neo4j storage, planm agent client,
  Orchestrator client, CLI model client). A client that serves one domain lives in it
  (Vworld: `modules/land/vworld/`; LLM extraction: `modules/regulations/extraction.py`).
- `app/core/` — single owners of cross-cutting names: `agent_network.py` (A2A_TOKEN),
  `model_auth.py` (EDITOR_MODEL_AUTH), `graph_config.py` (Neo4j), `mcp_params.py`,
  (route inventory tool lives at `app/route_inventory.py`, beside `main.py`).
- Files under ~500 lines; one env name has one owner module.
- Splitting a module: make it a package (`foo/__init__.py` keeps every public/underscore name,
  parts in `foo/<concern>.py`), as `regulations/calculator/`, `maas/delivered/`. No `foo_<part>.py` siblings.

## Service registry (2026-10-08)
`infra/config/services.json` (schema `services.schema.json`) is the one owner of every port and
base URL: editor services, the Orchestrator editor API, the 15 A2A agents of a2a.ps1 and Neo4j.
`infra/host/registry.mjs` reads and validates it (`byId`, `baseUrl` = host_env override else
127.0.0.1:port, `healthUrl`, `cardUrl`, `startCommand`); `infra/dev/runtime.mjs` takes its ports from
there and may hold no literal. **Derive, never restate**: `bun run host:check` compares the registry
with `OrchestratorAgent/scripts/services/a2a.ps1`, `config/*_agent.json`, each owner's serve script
and `editor_api.py` read-only. A mismatch is a finding for the Orchestrator session, not an edit in agents/.

## The planning engine
`app/modules/design/generation/maas/masterplan/` (planner, rows, ramps, validation, ...) is the
engine the MasterPlan **agent** used to import; it is now owned here and reached by agents only
through `POST /api/v1/design/masterplan/operations/` (`masterplan_operations.py`, envelope
`arr.masterplan.operations.v1`, request/result hashes). See `04-planning-engine.md`.

## Not this backend
- The floor-plan engine (17 packages + `backend/engine` + `cli.py`, see 07-decisions 2026-10-07) is planm's
  source copy: do not move/split it; it goes away when the editor is re-pointed to planm.
- Agents (`D:\Data\25_ACE\agents\...`) — separate repos, separate servers, A2A/HTTP only.
- `planm` floor-plan engine — agent `agents/planm` (port 8309); this backend calls it
  (`adapters/planm_agent.py`). The learned generator (planm-learn v13) is separate and private.
- Frontend — `frontend/` (Next), its own session and memory.

# PLAN

PLAN is the product integration repository for PLANM floorplan generation,
review, approval, artifact delivery, and optional post-approval DWG inspection.

## Ownership

| Path | Owner |
| --- | --- |
| `frontend/` | PLANM web UI; Backend HTTP only |
| `backend/app/api/` | Versioned product HTTP routes |
| `backend/app/modules/` | PLAN domain logic, run state, artifacts, execution |
| `backend/app/adapters/` | Thin PLANM process and DWG loopback adapters |
| `agents/planm/` | PLANM identity, contracts, skills, workflows, memory, runtime bridge |
| `external/gitagent-runtime/` | Generic GitAgent host for PLANM skill/workflow discovery |
| `external/dwg-intelligence/` | Vendored independent DWG product: workspace, runtime, parsers, skills, and tests |
| `engine/` | Shared geometry, graph, constraints, metrics, and image primitives |
| `datasets/`, `experiments/`, `research/` | Retained research inputs and evidence |

## Dependency Direction

```text
Frontend
   -> Backend API and orchestration
      -> PLANM GitAgent host -> discovered workflow/skill -> process bridge -> injected Backend execution service
      -> optional DWG loopback process after approval

PLANM Agent package
   -> generic GitAgent runtime for agentic skill/workflow hosting
```

The product API does not require an LLM provider. Every PLANM stage always runs
through the generic GitAgent host, which discovers the PLANM workflow and skill
before executing the deterministic process bridge. The
Frontend never reads Agent or DWG paths. PLANM and DWG never import each other.
The deterministic PLANM bridge receives a Backend-owned engine command at
runtime and contains no Backend filesystem path.

## Run

```powershell
docker compose up --build
```

Open `http://localhost:8080`.

See `docs/architecture/repository_layout.md`, `docs/architecture/module_map.md`,
and `docs/integrations/` for ownership, contracts, and deployment details.

# PLAN Workspace

This workspace composes the independent PLAN and DWG products without merging
their private source trees. It is designed to be added to a larger monorepo
without overlaying another repository's `frontend`, `backend`, or `agents`.

## Ownership

| Path | Owner |
| --- | --- |
| `products/plan/` | PLAN frontend, backend, PLANM agent, research, and product docs |
| `products/dwg/` | Independent DWG workspace, CAD runtime, parsers, skills, and tests |
| `platform/agent-runtimes/gitagent/` | Generic GitAgent runtime; no product imports |
| `shared/contracts/plan-dwg/` | Versioned PLAN-DWG data contracts only |
| `infra/` | Cross-product development, Compose, proxy, and E2E orchestration |
| `docs/` | Workspace-wide architecture and migration decisions only |

## Dependency Direction

```text
PLAN Frontend
   -> Backend API and orchestration
      -> PLANM GitAgent host -> discovered workflow/skill -> process bridge -> injected Backend execution service
      -> optional DWG loopback process after approval

PLANM Agent package
   -> generic GitAgent runtime for agentic skill/workflow hosting
```

The product API does not require an LLM provider. Every PLANM stage always runs
through the generic GitAgent host, which discovers the PLANM workflow and skill
before executing the deterministic process bridge. The
PLANM and DWG never import each other. PLAN consumes DWG through supported public
package and HTTP surfaces only.
The deterministic PLANM bridge receives a Backend-owned engine command at
runtime and contains no Backend filesystem path.

## Run

```powershell
docker compose up --build
```

Open `http://localhost:8080`.

Run `npm run test:architecture` before changing product locations. PLAN product
documentation lives under `products/plan/docs`; DWG documentation lives under
`products/dwg/docs`.

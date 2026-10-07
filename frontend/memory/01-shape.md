# Shape (2026-10-06)

Next app: `frontend/app/editor` (package name `editor`). Upstream Pascal parts:
`frontend/components/{viewer,editor}`, `resources/lib/core` (layer rules: root `AGENTS.md`).

## Pages (`app/**/page.tsx`)
- Workspace — absorbed from AutoGen Studio (AG-frontend), under `app/(workspace)/`:
  agents, build, deploy, dialogue, flow, gallery, history, land, mcp, settings. Plus
  `/playground`, `/playground/flow`.
- Domain screens — absorbed from ARR's frontend: `/law` (incl. "AI 심화 분석" deep analysis,
  SSE), `/map`, `/design`, `/design/language`, `/dwg`, `/planm`.
- Platform: `/projects`, `/projects/[id]`, `/runs/[id]` (Orchestrator runs via the backend),
  `/scene/[id]`, `/scenes`.
- `/privacy`, `/terms`.

## Features (`features/*`)
AG-origin: agents, agent-dialogue, agent-flow, assistants, context-usage, deployment, gallery,
history, mcp, model-registry, playground, schedule, sessions, settings, streaming,
team-builder, team-templates, tool-approval, workspace. Domain: design, export, land,
land-map, law. AG's dashboard/auth/font-scale/shortcuts have no folder of their own (merged
into other screens; their AG unit tests were not ported).

## Libraries (`lib/*`)
`backend-request.ts` (the one server-side fetch to the backend), `workspace-request.ts`,
`design-operation-path.ts` (which design paths the proxy forwards), `platform-design-operation.ts`,
`scene-*` (scene store/security), `api-surface.test.ts` (guard, see 02).

## Where split pieces go (2026-10-06)
A feature folder keeps its page/entry file at the root; pieces go to its own `components/`
(subcomponents), `hooks/` (React hooks), `lib/` (pure helpers, loaders, types). Flat folders that
already group one kind of file (`lib/cesium`, `lib/envelopes`, `book-language-flow`, `agentflow`)
take siblings there. Upstream Pascal (`frontend/components`, `frontend/elements`) is not split.

## The shell (2026-10-07)
`/dwg` = the product shell (`features/shell`): sidebar | conversation | artifact panel. Every feature is an
artifact module in `features/artifacts/<id>/` registered in `features/shell/registry.ts` (default `site-map`,
then `cad`). See 05-decisions 2026-10-07.

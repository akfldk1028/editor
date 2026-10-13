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
`ledger/` (2026-10-13): the 협업 장부 client - first read + live tail, one shared tail per scope per page, rows → messages, who the chat waits on and what each agent was asked; the flow (collaboration artifact) and the conversation both read it here, never each other.

## Where split pieces go (2026-10-06)
A feature folder keeps its page/entry file at the root; pieces go to its own `components/`
(subcomponents), `hooks/` (React hooks), `lib/` (pure helpers, loaders, types). Flat folders that
already group one kind of file (`lib/cesium`, `lib/envelopes`, `book-language-flow`, `agentflow`)
take siblings there. Upstream Pascal (`frontend/components`, `frontend/elements`) is not split.

## The shell (2026-10-07)
`/dwg` = the product shell (`features/shell`): sidebar | conversation | artifact panel. Every feature is an
artifact module in `features/artifacts/<id>/` registered in `features/shell/registry.ts` (default `site-map`,
then `cad`). See 05-decisions 2026-10-07.
The centre column (2026-10-08) is the **agent conversation** (`features/shell/conversation/AgentConversation.tsx`,
multi-agent chat: user bubbles, receipts, one turn per speaking agent, the Orchestrator moderates and asks) built from
`lib/orchestrator-runs/feed` via `lib/orchestrator-runs/thread.ts`. A manifest with `conversation: 'page'` (cad) shows
the page's own conversation instead, with the `AgentFeed` strip above it.

As of 2026-10-09, ordinary composer messages use `lib/design-conversation/` and the project-scoped
`GET/POST /platform/projects/{project_id}/conversation` door. The shell merges persisted owner messages
with the existing Law/run feed by time; `useAsk` still handles clause commands. The shared project selection
also follows the site-map project picker. Conversation IDs are retained per project in localStorage;
new conversation selects a new ID without deleting history. The controller restores/polls snapshots,
keeps pending POSTs across project switches, and retries uncertain messages with the original message ID.
`design-conversation/context.ts` scopes selected site/date and Law evidence by project, parcel and date. Restored
site cards publish their context too; restored Law reviews publish only results whose run ID and request
parcel match. The composer includes that confirmed `law_run_id`, never another project's or parcel's run.
Server `awaiting_confirmation` artifacts of kind `intent_reconfirmation` expose an explicit review action.
It sends `{artifact_id, context_hash}` with a fresh message ID; the controller checks the current artifact
version and disables confirmation during work/delivery. Ordinary agent proposals have no approval action.
Composer messages queue locally while the owner is working; idle polls send the next message in order.
Only one POST is in flight per conversation. A transport failure pauses that queue until explicit retry
with the same message ID. Queued messages survive project switches in the mounted shell, not a full reload.
Second review (2026-10-09): transient feed also captures conversation identity at dispatch. Shared project
binding and scoped state prevent old run polls and mounted parcel context from moving into another project.
Only terminal usable Law evidence becomes a chat reference; changing the selected date drops the old reference.
`설계 시작하기` focuses a real editable composer draft, without sending; optional review actions remain catalog-driven.
Site/clause detail buttons are removed from the initial prompt. `검토 결과` opens saved orchestrator results without
starting direct Law analysis. Idle cards refresh every 15 seconds and on focus; a failed queued message can be
explicitly discarded. Browser hook regressions cover first selection, project switching and first Law completion.

## Artifact slice layout (2026-10-08, FSD)
`features/artifacts/<id>/` = `manifest.ts` + `ui/` (components + css) + `model/` (hooks, state) + `api/` (backend
calls; URL literals only here; register in lib/api-surface.test.ts) + `lib/` (pure; `engine/`, `layers/` allowed).
Slices never import each other — only `features/shell/artifact-types.ts` and shared `lib/`. Examples: site-map, system.

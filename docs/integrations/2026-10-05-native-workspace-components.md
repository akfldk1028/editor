# Native workspace components and persisted configuration

The original AG-frontend settings, gallery and team builder now run as native Editor routes `/settings`, `/gallery` and `/build`. This is an incremental delivery, not full ARR/AG integration or proof of agent execution.

## Structure

- `elements/workspace`: theme-preserving Button, Card, Badge, Input and Toggle primitives.
- `components/workspace`: composed shell, navigation, query/language providers and scoped theme.
- `features/settings/{components,hooks,api,model}`: original settings sections and persistence.
- `features/gallery/{components,hooks}`: original six-category gallery, cards, detail and import/sync dialogs.
- `features/team-templates/{components,hooks,model}`: template list, cards, dialogs and persistent editing.
- `features/team-builder/{components,hooks,agentflow}`: original agent configuration, patterns, termination, JSON and graph editors.
- `lib/workspace-request.ts`: shared HTTP transport; feature clients do not depend on another feature's transport.
- Backend `api/routes_workspace*`, `schemas/workspace.py`, `modules/workspace`: HTTP boundary, settings schemas and SQLite repositories respectively. There is no ARR/AG server dependency in these routes.

Workspace state uses `editor/runtime/editor/workspace`. SQLite online backups preserved the previous external runtime database before switching configuration. Existing source repositories and artifacts were not moved or deleted. Optimistic versions reject stale settings/template saves. Gallery input rejects malformed component collections before rendering. Browser-facing same-origin mutation validation now uses the request Host, since Next can reconstruct an internal hostname in request.url; the backend separately checks its configured public origin.

## Verification on 2026-10-05

- Native frontend 127.0.0.1:3003 and backend 127.0.0.1:18449; hidden processes.
- TypeScript noEmit passed.
- Workspace settings/catalog and design workspace tests: 11 passed.
- Final native Playwright migration run: all 16 cases passed, including live VWorld 3D navigation, original design/archive views, settings save/reload/theme isolation, gallery import, team JSON modification/save and unsaved-navigation confirmation.
- The PowerShell wrapper returned exit 1 while the final Playwright log reported 16 passed, after treating Node's FORCE_COLOR warning on stderr as NativeCommandError. This is retained as a runner limitation, not silently described as a clean wrapper exit.
- Tests using intercepted responses establish rendering contracts only. The new workspace CRUD cases call the real native backend and clean up their fixtures; they do not execute an LLM or A2A conversation.

## Still open

History, Playground and its execution/streaming/approval/context/attachment controls, the AG standalone flow popup, MCP, deployment, and ARR subroute accounting remain. Original design generation/cancellation/floor-plan/parking/interactive workflows and the actual project remediation loop remain open. Systems, DomainExpert and InteriorDesign are unfinished.

Within this increment: gallery component live testing has no native runtime implementation; external URL sync has not been verified against a live remote gallery; Team Run still targets the unported Playground; JSON validation verifies structure only. Stored environment settings are not yet consumed by an execution process. Original disabled New Gallery/API-key-generation controls remain disabled.

The lockfile now declares the builder dependencies. Local recovery copied missing dagre/graphlib/lodash packages from the preserved AG-frontend installation. Installed lodash is 4.17.23 while the generated lock resolves 4.18.1, and pre-existing dependency junctions remain. A clean locked installation is therefore not verified. No cache deletion was performed after an automatic approval review rejected a compound command containing recursive cache deletion; a normal hidden restart resolved the module load issue.

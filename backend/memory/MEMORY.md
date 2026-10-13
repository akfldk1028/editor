# Editor backend — memory index (read this first)

- [2026-10-13 five-path review](2026-10-13-five-review.md): required targets, diverse candidates, declared-door routing, source-bound measurements; actual before/after evidence and remaining owner gaps.

- [2026-10-13 siting law](2026-10-13-siting-law.md): source-owned small surface parking criteria, LawAgent frontage criteria, actual count/structure checks; legal road certification remains unverified.

- [2026-10-13 retained planning alternatives](2026-10-13-planning-portfolio.md): individually revisable solved geometries reach MasterPlan comparison and AI.

- [2026-10-13 default siting search](2026-10-13-default-siting-search.md): real seven-site paired verification, shared-axis search and ground-area preservation.

This folder is the working memory for any AI session that works on the editor **backend**
(`D:\Data\25_ACE\editor\backend`). Read this index, then open the file for your task. Each
file is short and factual; facts carry a date. When you learn something durable, update the
matching file (or add one and list it here). Do not duplicate what the code or git log says.

Who owns what (2026-10-06):
- Since 2026-10-06 **one editor session owns both backend and frontend** (the two roles below are
  held by the same session; it is modularizing both — see `07-decisions.md`).
- **Editor backend session** (you): `backend/` — domain API, planning engine, workspace/AG,
  agent-facing doors. Port **18449**.
- **Editor frontend session**: `frontend/` — see `../../frontend/memory/MEMORY.md`.
- **Orchestrator session**: `D:\Data\25_ACE\agents\*` (all agents incl. OrchestratorAgent).
  Agents call this backend only over HTTP; changing an agent-facing door is a contract change
  — see `02-agent-doors.md` and tell the Orchestrator session (write it in `07-decisions.md`).

| File | Read when |
|---|---|
| [01-shape-and-boundaries.md](01-shape-and-boundaries.md) | before any change: layers, where code goes, what was absorbed from ARR/AG |
| [02-agent-doors.md](02-agent-doors.md) | touching any route an agent calls, tokens, hrefs, bundles |
| [03-workspace-and-models.md](03-workspace-and-models.md) | AutoGen workspace, model keys vs local OAuth, /law deep analysis |
| [04-planning-engine.md](04-planning-engine.md) | MasterPlan engine (`maas/masterplan`), parking rows, ramps, tests |
| [2026-10-12-placement-parent.md](2026-10-12-placement-parent.md) | generated-parent revision handles, piloti choices, reference parking count contract |
| [05-run-and-test.md](05-run-and-test.md) | starting the server, venv, which tests, guards |
| [06-pitfalls.md](06-pitfalls.md) | before debugging something odd — known traps |
| [07-decisions.md](07-decisions.md) | dated log of decisions and contract changes |
| [08-design-conversation.md](08-design-conversation.md) | persistent Requirement/DesignIntent/Program chat, owner contracts and explicit reconfirmation |
| [../frontend/memory/2026-10-09-national-ordinance-followup.md](../frontend/memory/2026-10-09-national-ordinance-followup.md) | Claude handoff: nationwide ordinance completeness, current MCP limits, and next end-to-end implementation |

Agent-network rules live outside this repo: `D:\Data\25_ACE\agents\docs\AGENT_MODULE_CONVENTIONS.md` §5.

## Quick pointers (2026-10-08)
- Ports/URLs: `infra/config/services.json` only (schema `services.schema.json`; `bun run host:check`).
- Start/keep servers: `bun run host:start|stop|status` (`infra/host`, detached daemon; see 05-run-and-test).
- Status: `GET /api/v1/platform/status` (`modules/platform/status/`), shell artifact `system`.
- Runs: site run door `schemas/site_run.py` (`{goal:'limits', pnu}`), tracing `core/tracing.py`, `GET /platform/runs/{id}/trace`.
- Site selection: `modules/land/selections.py`, `selection_facts.py`, routes `/land/selections[/preview|/outlines|/latest]`.
- Decisions log: 07-decisions.md (newest first).

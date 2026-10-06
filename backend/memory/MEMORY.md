# Editor backend — memory index (read this first)

This folder is the working memory for any AI session that works on the editor **backend**
(`D:\Data\25_ACE\editor\backend`). Read this index, then open the file for your task. Each
file is short and factual; facts carry a date. When you learn something durable, update the
matching file (or add one and list it here). Do not duplicate what the code or git log says.

Who owns what (2026-10-06):
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
| [05-run-and-test.md](05-run-and-test.md) | starting the server, venv, which tests, guards |
| [06-pitfalls.md](06-pitfalls.md) | before debugging something odd — known traps |
| [07-decisions.md](07-decisions.md) | dated log of decisions and contract changes |

Agent-network rules live outside this repo: `D:\Data\25_ACE\agents\docs\AGENT_MODULE_CONVENTIONS.md` §5.

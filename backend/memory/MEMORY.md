## 2026-10-17 - Mass numerical impose fitting

[Algorithm, REA source and limits](2026-10-17-mass-numeric-impose.md): bounded
rank-aware fitting plus translation-domain refinement, actual occupied-band gates.
Independent archived replay6/6 accepted, retained GFA +0.34–13.84%;101 combined
Mass regression tests pass. More computation; no global or aesthetic guarantee.

## 2026-10-17 - Mass multi-operation grammar search

[Implementation, limits and validation](2026-10-17-mass-grammar-search.md): bounded
append/prepend beam derivations with full baseline parameter lattice, actual delivery
feedback and honest operation lineage.67 related tests pass; matched exploration
delivery3→4, originals preserved, all10 final records freshly accepted. Production
rerun pending. KMass owns residential types/core/corridor/unit composition.

## 2026-10-17 - Mass delivery-guided parameter search

[Implementation and evidence](2026-10-17-mass-delivery-search.md): actual parameter
regeneration, shared UCB1 selection, final-import probe, bounded extra retries and
explicit partial supply. 65 tests pass; matched delivery1→3 with original hashes
preserved. Full rerun and exact development comparison completed; see limits in record.

## 2026-10-14 - Module axis and solve budget review

Explicit underground module axes now use site frame; row solve reservation is conditional and enforced per actual generic/fallback/stacked invocation.73 focused tests pass. Actual cross-axis replay31/39 and budget replay34/39 remain failed; do not claim quality gains. Full engine sweep incomplete. [Details](2026-10-14-module-axis-budget-review.md).

## Latest: comparison workbook and auto routing

See 2026-10-14-auto-routing.md for measured comparison, policies and limits.

## 2026-10-14 - Outdoor component precision

Actual rotated-site numerical islands falsely increased fragmentation. Owner and MasterPlan observer fixed; matched HTTP remeasurement on isolated18479. Shared18449 restarted and actual layouts revalidated. Exact building/basement configuration signatures added;19 affected tests pass. [Details](2026-10-14-outdoor-component-precision.md).

Latest: [Router speed and accuracy; corrected task ownership](2026-10-14-routing-performance.md).

Latest: [MAS implementation and quota diagnosis](2026-10-14-mas-implementation.md).

# Editor backend — memory index (read this first)

- [2026-10-14 mass geometry](2026-10-14-mass-geometry.md): centroid, concave loft, component/height-band preservation, curved shell thickness and actual external LLM/VLM verification; final cycle status in linked MassAgent report.

- [2026-10-14 MAS evaluation](2026-10-14-mas-evaluation.md): routing scores, model fallback, canonical plan and thesis evidence; design diversity still unmeasured.

- [2026-10-13 road aisle](2026-10-13-road-aisle.md): Law-bound external road geometry, candidate generation and independent per-stall validation; actual CLI comparison and unsupported scope.

- 2026-10-13 Program scoped Law completion: see [contract decision](07-decisions.md). Positive bounded comparisons are separated from broad legal clearance; default full scope remains fail-closed.

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

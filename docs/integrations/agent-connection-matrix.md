# Agent connection matrix — CURRENT / TARGET

Initial read-only architecture inventory checked 2026-10-04; subsequent isolated runtime evidence is listed separately below. Existing preservation work remains in progress; this is not Task 4 implementation, a folder migration, or proof that all agents are connected to Editor.

## Evidence and counting

Source root abbreviations: `A = D:/Data/25_ACE/agents`, `E = D:/Data/25_ACE/editor`, `G = D:/Data/25_ACE/AG`. Relative links below resolve from this document.

- Central source: [registry.py](../../../agents/OrchestratorAgent/orchestrator/registry.py), its `config/` JSON declarations, phase activation/policy used by `profiles()`. Read-only `python -B` evaluation of `profiles()` found **25 profile IDs**, including **14 endpoint declarations: 12 A2A and 2 HTTP provider entries**. The two HTTP entries share ARR port 18320. These are catalog counts, not live service counts or unique server counts.
- The remaining 11 profiles have null endpoint: Orchestrator is local, Mass intentionally uses a local adapter, and 9 roles lack endpoint declarations. A null endpoint does not alone prove an owner has no code.
- Owner root `agent.yaml` files were inspected. Several still say generic `gitagent`; that template name is not a canonical architectural identity or evidence that an owner service is absent. Elevation has its own package/service rather than a root `agent.yaml`.
- No owner service calls, health probes, task executions, environment-secret inspection, or owner-directory writes were performed. Runtime availability is **unverified** for catalog endpoints. A Windows listener lookup found no 8081 listener at the instant of inspection; this does not prove no Studio instance exists in another environment.
- Existing Editor surfaces are `/dwg`, `/planm`, `/editor` in [PLANM App.tsx](../../frontend/app/planm/src/app/App.tsx). No `/agents` or `/agentlab` product surface was found in the inspected shell. Editor connection below means the proposed unified agent surface, not whether a sibling service previously ran successfully.

## Central domain catalog

All rows target **`/agents`** for discovery/status and explicit domain execution through the existing Orchestrator. CURRENT `not yet` means no unified Editor connection was found; it does not negate existing central adapters. Endpoint ports below are declarations on `127.0.0.1`, not live observations. Capabilities describe owner scope/source implementation, not unconditional acceptance or completion.

| Agent ID | Owner/source path | Capability / CURRENT evidence | Transport declaration | Editor CURRENT | TARGET route / remaining boundary |
|---|---|---|---|---|---|
| orchestrator | `A/OrchestratorAgent/orchestrator` | Durable routing, state/issue ownership, execution/phase coordination; director is an alias | Local coordinator, no remote profile endpoint | not yet | `/agents`; adapt existing coordinator, no second engine |
| law | `A/Lawagent/agent.yaml`; central `config/law_agent.json` | Statutory evidence and bounded legal review; project verdict requires evidence | A2A :8301 | not yet | `/agents`; runtime/tools must be observed |
| masterplan | `A/MasterPlanagent/agent.yaml`; `config/masterplan_agent.json` | Parcel layout, site planning alternatives and review | A2A :18312 | not yet | `/agents`; runtime unverified |
| program | `A/ProgramAgent/agent.yaml`; `config/program_agent.json` | Program spaces/areas/adjacency and revision-bound specialist review | A2A :18421 | not yet | `/agents`; gross reservations are not accepted rooms |
| revision | `A/RevisionAgent/agent.yaml`; `config/revision_agent.json` | Evidence-bounded owner rerun selection/order, no owner design repairs | A2A :18303 | not yet | `/agents`; preserve rerun/authoring distinction |
| site_context | `A/SiteContextAgent`; `config/site_context_agent.json` | Site boundaries/access/terrain/context scope; generic root manifest | A2A :8304 | not yet | `/agents`; verify current owner card/tools |
| requirement | `A/RequirementAgent`; `config/requirement_agent.json` | Structured brief, priorities, assumptions/unknowns scope | A2A :8305 | not yet | `/agents`; verify current owner card/tools |
| design_intent | `A/DesignIntentAgent`; `config/design_intent_agent.json` | Parti, ordering, material/interior intent and rationale scope | A2A :8306 | not yet | `/agents`; verify current owner card/tools |
| elevation | `A/ElevationAgent/package.json`; `config/elevation_agent.json` | Geometry-locked facade design/appearance artifacts | A2A :18327 | not yet | `/agents`; surface stage/selection/evidence separately |
| kmass | `A/KMassAgent/agent.yaml`; `config/kmass_agent.json` | Explicit mass provider; siting/envelope/core/parking generation scope | A2A :18319 | not yet | `/agents`; provider is not a second mass owner |
| mass | `A/MassAgent/agent.yaml`; central local adapter | Parti, mass pipeline and selection-board authoring | Local adapter, intentionally no A2A catalog endpoint | not yet | `/agents`; retain existing local execution |
| mass_export | `A/OrchestratorAgent/config/mass_export_provider.json`; `D:/Data/25_ACE/ARR` | Export receipted delivered mass; `provider_of=mass`, tool `mass_export` | HTTP :18320 | not yet | `/agents`; export provider, not design author |
| plan | `A/OrchestratorAgent/config/plan_provider.json`; `D:/Data/25_ACE/ARR` | ARR existing floor-plan provider, tool `plan_generate` | HTTP :18320; no standalone Plan A2A declaration | not yet | `/agents`; distinguish ARR provider from PLANM below |
| systems | `A/SystemsAgent/a2a_service/tools.py`; `config/systems_agent.json` | Source tools: review, IFC review, analyze, clearance, requirements, health | A2A :18328 | not yet | `/agents`; presence does not certify MEP completeness |
| domain_expert | `A/DomainExpertAgent/a2a_service/tools.py`; `config/domain_expert_agent.json` | `domain_review`, `domain_profile_catalog`; undeclared project domain may block review | A2A :18329 | not yet | `/agents`; require explicit domain/source evidence |
| interior | `A/InteriorDesignAgent/a2a_service/tools.py`; `config/interior_agent.json` | Review, source-bound concept prepare/apply; supplied-image proxy/diagnostic artifacts | A2A :18330 | not yet | `/agents`; staged partial, no accepted room/live image-generation claim |
| existing_conditions | `A/ExistingConditionsAgent/agent.yaml`; central phases/policy | AS-IS ownership roster; generic scaffold inspected, domain service not demonstrated | No central endpoint declaration | not yet | `/agents`; display not-declared/implementation unverified, no fabricated executor |
| intervention | `A/RemodelingAgent/agent.yaml` candidate owner; central phases/policy | Retain/remove/new/intervention roster; folder-to-role binding is provisional | No central endpoint declaration | not yet | `/agents`; confirm owner identity and callable contract |
| detail | `A/OrchestratorAgent/orchestrator/phases.py`, `policy.py` | Detail geometry role only; implementation not established | No central endpoint declaration | not yet | `/agents`; unavailable execution until implemented/registered |
| documentation | Same central phases/policy | Drawings/schedules/sheets/revisions role only | No central endpoint declaration | not yet | `/agents`; no inferred link to drawingbook scaffold |
| specification | Same central phases/policy | Material specification role only | No central endpoint declaration | not yet | `/agents`; implementation unverified |
| evaluation | Same central phases/policy | General evaluation/simulation role only | No central endpoint declaration | not yet | `/agents`; do not conflate existing owner-specific review with this executor |
| cost | Same central phases/policy | Quantities/BOQ/estimate/VE role only | No central endpoint declaration | not yet | `/agents`; implementation unverified |
| procurement | Same central phases/policy | Packages/vendors/submittals/long-lead role only | No central endpoint declaration | not yet | `/agents`; implementation unverified |
| construction | Same central phases/policy | Constructability/preparation/logistics/hold-point role only | No central endpoint declaration | not yet | `/agents`; implementation unverified |

## Additional owned components outside the 25-profile catalog

These rows are deliberately not counted as additional live central agents. Scaffold names require a canonical identity/contract before domain routing.

| ID / component | Source path | Capability / transport evidence | Editor CURRENT | TARGET |
|---|---|---|---|---|
| planm | `A/planm/agent.yaml`, `runtime/gitagent_host.mjs`; `E/backend/app/adapters/planm_agent.py` | Existing versioned PLANM planning stages via Node subprocess host, with Python engine adapter | **Existing separate `/planm` backend bridge**; central registry does not include PLANM | `/agents` catalog plus retain `/planm`; central integration is not implemented by this inventory |
| DiagramAgent (folder identity) | `A/pascalAgents/DiagramAgent/agent.yaml` | Owner scaffold present; domain transport/callability unverified | not yet | `/agents` after canonical identity/tool verification |
| drawingbookAgent (folder identity) | `A/pascalAgents/drawingbookAgent/agent.yaml` | Owner scaffold present; domain transport/callability unverified | not yet | `/agents` after canonical identity/tool verification |
| pptagent (manifest ID; folder pptAgent) | `A/pascalAgents/pptAgent/agent.yaml` | Manifest declares deterministic architecture PPTX deck generation, engine-owned state; domain transport/callability unverified | not yet | `/agents` after callable-tool verification |
| AutoGen Studio / AG | `G/autogen_a2a_kit/autogen_source/python/packages/autogen-studio/autogenstudio/web/app.py` | Actual Studio API mounts teams, sessions, runs, WebSocket, A2A import/registry and other routes; declared startup port 8081 | not yet; standalone source/runtime, no unified Editor surface observed | `/agentlab` for team/workflow experiments; `/agents` links/discovery for verified domain adapters only |

PLANM source details: [backend adapter](../../backend/app/adapters/planm_agent.py), [owner resolver](../../backend/app/core/planm_location.py), [run API](../../backend/app/api/routes_planm_runs.py). Resolver defaults to sibling `agents/planm` and now accepts an explicit absolute server-configured `PLANM_AGENT_DIR`; no owner folder was moved. `/api/v1/planm/runs` is already a separate backend contract. Treating it as central `plan` would silently replace ARR's current provider contract.

AG source details: `G/start_with_key.ps1` names the actual autogen-studio source root; only matching startup-path lines were inspected, not secret assignments. Studio [web app](../../../AG/autogen_a2a_kit/autogen_source/python/packages/autogen-studio/autogenstudio/web/app.py) and [A2A routes](../../../AG/autogen_a2a_kit/autogen_source/python/packages/autogen-studio/autogenstudio/web/routes/a2a.py) were read directly. `G/autogen_a2a_kit/AG-cli/mcp/autogen_studio_server.py` also references the Studio URL. The sibling `D:/Data/25_ACE/AG-frontend` is a separate checkout, not evidence of integration. Studio team execution/A2A import is not the central source-revision/effects/issue-closure execution contract.

Shared `a2a_common`, protocol libraries, JSON_MODULES, Gitagent runtimes, skills, vendor/reference clones and dynamic experiment teams are infrastructure, not additional canonical domain agents. They are intentionally excluded from the profile count. This bounded inventory inspected owner-level manifests and selected actual adapters; it does not claim to have enumerated every vendored example or plugin.

## Subsequent isolated runtime observations

These observations establish existing component baselines, not the new unified `/agents` surface. Source/receipt details are in the [migration record](../migrations/2026-10-04-source-map.md). Original project databases were not used.

| Component | Observed flow | Evidence / limitation |
|---|---|---|
| PLANM → Editor | Actual deterministic API generation, fixture alternative selection, MCP publish, scene API reopen and browser 2D/3D | Run `858fab437a334726904a2116bde47539`, scene `868e0a5e9231`, version2,321nodes. Existing bridge only; unresolved regulatory inputs remain. Editor `5e36616f`, tested PLANM wrapper changes subsequently committed `151c59d`. |
| Studio / AG | Isolated source+venv on8081: health, session create/read, CREATED run, WebSocket ping/pong | No start/model execution. Additional run detail GET500 due raw SQL timestamp string handling. AutoGen0.7.5 + MCP1.25.0 in isolated environment; original venv/source unchanged. |
| AG-frontend | Restored source unit96tests and TypeScript/Vite build | Not yet integrated into Editor navigation/API; standalone browser-to-Studio execution not claimed. |

The 25 central catalog rows above remain unverified for the new Editor connection. Component startup or one provider's successful baseline must not promote all rows to verified.

## TARGET connection rules and acceptance boundary

1. Add `/agents` to existing Editor navigation while preserving `/editor`, `/planm`, `/dwg`; expose the central catalog as declared/local/not-declared first. Observe live owner cards separately and timestamp results. Missing card skills remain unknown, not synthesized from folder names.
2. Connect explicit selected tools through existing central execution adapters with source revisions, exact request bindings, bounded artifact receipts, and partial/blocked/failed states. Read-only inspection must not silently execute paid models or mutate shared design state.
3. Add AG functionality through an explicit `/agentlab` surface/API integration for team/session/run management. Do not replace the domain coordinator with an AutoGen experiment engine or duplicate its registry as an authoritative domain catalog.
4. Keep PLANM's working Editor bridge intact; design a declared central adapter separately before claiming unified execution. Keep unimplemented roles visible with precise blockers, rather than offering fake success buttons.
5. Completion evidence must include route reload/navigation, declared-vs-observed statuses, explicit execution/error handling, streamed run results, artifact hash/source-revision checks, and proof that blocked roles/owner failures do not become successful design acceptance. No such new Editor integration has been implemented or tested by this document-only task.

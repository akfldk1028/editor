# Remaining integration execution

Authority: user requests completion of all previously open integration work, with
original views/elements retained, Editor as the product and shared agents external.
Start: cc33882a. Preserve all existing source, runtime data and unrelated edits.

Parallel ownership:
- Scene: geometry-aware initial framing; versioned binding refresh, preserving source.
- Providers: move remaining law/site/plan/export contracts to native domain modules;
  repoint external owners only after verification, without deleting original sources.
- Specialists: execute owner tools against actual current inputs; never invent missing
  use/load/room evidence or convert a blocked review into acceptance.
- Product shell: original Playground, live flow popup and MCP workbench, paired with
  Editor-owned execution/session/tool contracts and native route entries.

Execution boundary: saved team snapshots own a playground run. Browser transport
must support messages, streaming, human input, stop and persisted history, while
rejecting cross-origin writes, duplicate starts and stale/foreign session responses.
Use installed AutoGen libraries through a domain adapter; do not run old AG server.
MCP sessions belong to the native backend and close on disconnect/expiration.

Completion requires actual service/browser tests, original-view accounting, source
preservation, no old product runtime dependency, updated memory and scoped commits.
Domain input gaps must be named with owner evidence; passing UI tests is not domain
acceptance. Record verified closures and concrete blockers here as execution proceeds.

User clarification: domain requirements are developed through agent dialogue, not
an upfront checklist the user must finalize alone. The product must preserve the
original request, explain owner findings, let the user refine a proposal, submit
the refined request and show its next review. A missing engineering basis may
prevent acceptance of a calculation, but must not prevent starting that dialogue.
Keep proposed assumptions distinct from reviewed evidence throughout the loop.

## Verified native workflow

- `/playground` preserves the original task, attachment, messages, streaming,
  history, helper panels and agent graph. `/playground/flow` has a tab-scoped
  popup channel. The native backend owns the frozen team snapshot, durable run
  events, human-input wait, stop, terminal history and restart reconciliation.
- `/mcp` preserves the original server/tool/resource workbench. Connections are
  owned by the backend and expire or close on disconnect. Actual stdio invocation
  returned `add(17,25)=42`, read the fixture resource, then disconnected.
- `/dialogue` retrieves the full original submitted request rather than an 8 KB
  transcript summary. Human-readable Domain proposals, Interior briefs and
  Systems applicability questions prepare a source-bound next review. Editing
  a prepared draft invalidates the old preview; stale or foreign project sources
  remain rejected. Uncertain submissions retry the identical captured request.
- Actual browser Systems follow-up run `e3e8c37f582d48f9a5c9f594de30aa0f`
  returned 30 owner items, including 6 applicability questions. The existing
  provisional `government_office` choice survives the next follow-up. Its result
  is partial and the coordinator remains blocked; no design acceptance was made.
- Actual Domain re-review used 32 existing Program-authored proposals and moved
  from blocked to partial. Assumptions remain proposals and dirty source flags
  are retained. These conditions are developed with agents, not demanded as an
  upfront complete design from the user.
- The retained r39 GLB is visible on a fresh browser load without clicking a saved
  camera. Its source hash remains
  `67fb4ba51ddc01916cf6125234fd848e605506bb6a68cf1079e788de544876d1`.
  Scene-binding refresh explicitly advances the existing binding by revision;
  it does not substitute an unrelated scene or rewrite the source model.

## Runtime and structure

Routes compose domain features; original cards and controls live under their
feature folders, with shared primitives under `elements/workspace`. Native
execution/MCP services live under `backend/app/modules/workspace`, domain code
under `modules/law`, `modules/land`, `modules/design` and `modules/massing`;
adapters and HTTP boundaries remain separate. External agents remain outside Editor.

The native backend now uses `Editor/.venv`, with its declared AutoGen/MCP/model
dependencies and the Graph2Plan inference extra. `pip check` reports no broken
requirements. OpenAI/Azure, Anthropic and Ollama classes import successfully;
this is dependency readiness, not a claim of a configured paid model call.
The native launcher prefers this environment unless `EDITOR_PYTHON` is explicit.
The common header/sidebar contains 20 destinations, including CAD and PLANM.

Shared Python was found to contain OpenAI 0.27.2, which could not load the modern
client. Its protobuf version was restored after dependency resolution changed it;
the product was isolated rather than upgrading unrelated shared applications.
Graph2Plan initially failed in the fresh environment because torch was absent;
installing the declared inference extra restored actual model inference.

## Verification evidence

- Production webpack builds passed, including the final Systems input restoration.
- Full migration browser suite: **61 passed**, live VWorld and design enabled;
  separate product navigation suite: **7 passed**.
- After the final two-line input restoration, specialist/scene browser suite:
  **10 passed**, including prepared-draft invalidation and the restored submission.
- Bun feature/model tests: **18 passed, 48 assertions**; native launcher tests:
  **10 passed**.
- Fresh isolated Python regression: **56 passed**, then the one missing-dependency
  Graph2Plan case passed after the inference extra was installed. Additional
  platform/audit/archive checks: **22 passed**. Counts overlap and are not summed.
- Owner follow-up/request tests: **27 passed**. Provider and historical artifact
  cutover checks are recorded separately; the broad legacy backend suite was not
  completed and is not claimed as passing.

Local browser/build receipts are in `.superpowers/sdd/actual-project`,
`.superpowers/sdd/completion-migration`, `.superpowers/sdd/followup-final-green`
and the `actual-r39-*` / `actual-systems-followup-*` evidence files.
Owner detail is in the `editor-followup-dialogue-20261005.md` and
`editor-specialist-analysis-20261005.md` checkpoints.

## Domain provider and archive cutover

Law and SiteContext Docker owners now call the Editor domain provider through
`http://host.docker.internal:18449/api/v1`; their own agent service ownership is
unchanged. Native law/facility/parking/site modules retain source manifests and
reference snapshots. The import rewrite now checks actual module paths so the
official `law.go.kr` host cannot be mistaken for a Python package name. The
unchanged parking golden cases passed after this regression was corrected.

Mass workspace tools and command entrypoints now live under `modules/massing`,
`backend.domain_cli` and `backend.mass_workspace_tool`. Existing receipted exports
are copied into `runtime/editor/design/mass-archive` with hash checks. Immutable
receipt/evidence bytes remain unchanged; only returned artifact locations map to
Editor-owned copies. The actual retained export returned the same shape identity
`ee3ba45e667096c71f9e` and certificate `c091b67043b049ea55aa`, with 41 artifact
hashes verified. A test also resolves an archive after deleting its original test
source files and rejects tampered copies.

Actual native five-floor Plan replay returned `needs_evidence`, with 30 artifact
hashes verified and `permit_ready=false`. Native audit returned exit 0 while
retaining unresolved law/source gates. Neither operation promotes a historical
measurement into design acceptance. `EDITOR_MASS_OUTPUT_ROOT` is configured as
`D:/Data/25_ACE/runtime/editor/massing/candidates` for the current runtime.

Old ARR listeners on 18000 and 18320 were stopped after read-only verification:
the 16 stored running rows date from March-June, preceding the October 2 server
starts; the original implementation has no startup recovery and refuses to start
already-running rows. The original database, four pending rows and artifacts
were preserved. After both old servers stopped, **2 live browser checks passed**
for native design/floor-plan execution and VWorld 3D. No legacy server was needed.
Local cutover receipts are the `runtime/editor/native-*.json`,
`provider-cutover-a2a.json` and `legacy-*.json` files.

## Scope still distinct from verification

- Systems, DomainExpert and InteriorDesign responses are partial/blocked design
  reviews, not completed professional design or approval. Further requirements
  should be explored in the dialogue that is now connected.
- The catalog reports 12 available agents, 2 declared HTTP providers, 1 local
  adapter and 10 undeclared roles. Do not describe all 25 roles as implemented.
- Playground's current execution manifest supports the listed chat/team/model
  components. Code-executor, browser-agent and MCP-in-team components are shown
  as unsupported; the working standalone MCP workbench does not close that gap.
- Browser schedules run while an eligible tab is open. UI environment drafts do
  not configure server credentials, and no unattended scheduler/cloud deployment
  or multi-user authorization is asserted.
- The original visual inventory is retained. The tested routes and interactions
  do not establish exhaustive parity of all 5,415 conditional JSX occurrences.

## Scoped commits and handoff

Product implementation: `34d6a0af` (native workbenches), `28fc6e1a`
(specialist dialogue and scene refresh), `ebf41e30` (native domain providers and
preserved archives). Owner: `89fc474` (follow-up contract), `68ef3d7` (provider
routes), `3a3f9dd` (verified handoff). External owners: Law `3285710`, Site
`13603e9`, Mass `3fda967`/`d05a66c`; operating compose `57f667da`.

Orchestrator memory points first to
`memory/checkpoints/editor-native-dialogue-cutover-20261005.md`. Previous memory
bytes and unstaged changes were preserved while staging only the new pointer
prefixes. Law, Site and Mass each have their own provider-cutover checkpoint.
Two previously untracked Mass user files retain local integration changes with
separate saved patches; they were not committed wholesale. See the provider
closure report for their exact paths and recovery copies.

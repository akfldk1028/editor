# Agent communication display in Editor

## Source and scope

ARR already has `frontend/src/design/components/DefaultAgentFlowPanel.tsx`,
`MASDialoguePanel.tsx`, `DirectAgentChatPanel.tsx`, and `ag-light-flow/`.
The inspected DefaultAgentFlowPanel offers dialogue, topology and direct-command
tabs. Its `lib/mas-dialogue.ts` fetches localhost8302/dialogue/transcript, then
returns a fixed benchmark transcript on failure. Those fallback approvals and
timestamps must not be presented as current project evidence in Editor.

This first slice adds stored communication display to the existing `/runs/:id`
route. It does not claim full migration of the three ARR tabs. Ownership:

- Shared Orchestrator `editor_dialogue.py`: read-only projection of saved calls.
- Existing owner run detail: project/branch check before projecting records.
- Editor `schemas/communications.py` and orchestrator adapter: strict contract,
  bounded text/list and duplicate identity checks.
- Existing RunService: product project binding, owner run identity and request
  prefix checks remain in force.
- Frontend `api/communications.ts`: response validation;
  `runs/RunCommunications.tsx` and scoped CSS: request/reply display.

## Behavior

The latest100 calls are shown in database insertion order, not claimed wall-clock
order. Each has tool/task identity, saved outcome, transport evidence and
expandable request/reply text. Requests use persisted args; responses use persisted
raw text. No conversation sentence, timestamp or peer identity is fabricated.
Current historical traces usually lack an agent identity; the UI says so while
retaining the tool name. Transport completion does not promote partial domain
outcomes to success.

Each body is limited to8000 Unicode code points. Structured credential/header
containers are omitted in the owner projection; any omission is indicated.
Plain text is displayed as React text, never executed HTML. This is a bounded
display, not a complete audit export or universal plain-text secret detector.
List/submission responses stay lightweight. Older gateways that do not expose
these fields show unavailable; malformed partial contracts fail explicitly.
Active run polling refreshes saved records, not token streaming.

## Verification

- Owner13 tests passed, including DB byte equality before/after reads,
  project/branch refusal, latest100 bounds, partial outcome and no transcript
  expansion in list/submission responses.
- Editor33 platform/communication tests passed; frontend build and2 boundary
  tests passed.
- Chrome12 passed,6 unrelated opt-in cases skipped. Includes saved A2A receipts
  through actual owner8794 → Editor18437 → browser5186, reload, text escaping,
  unsupported gateway, and Unicode length regression. Review independently found
  the JS/Python character-count mismatch; regression reproduced RED then GREEN.
- Historical run21685e9df3834a52be72c14dfc3bfa0c contains three actual A2A health
  receipts. SQLite online backups of its owner/product databases were used;
  no new remote execution or original database mutation occurred.
- Disposable HTTP process tree was stopped. Existing services were not restarted.
  Evidence: `.superpowers/sdd/2026-10-04-run-communications/browser.json`;
  screenshot `test-results/editor-saved-a2a-communications.png` inspected.

## Follow-up: explicit invocation identity and collaboration flow

New owner calls now persist locally authored `invocation_trace` after result
validation and before receipt storage. It binds run/task/tool and records
`from_agent=orchestrator`, `to_agent=<dispatched owner>`. Wire metadata carries the
same explicit fields. A remote response cannot substitute its own routing claim.
Historical receipt replay is left untouched; missing identities stay missing.

The existing communication API needs no new endpoint. Frontend responsibilities:

| Path within `features/agent-workspace/` | Responsibility |
|---|---|
| `api/communications.ts` | Validate the communication contract |
| `runs/communication-flow.ts` | Group recorded target identities and counts |
| `runs/RunCommunicationFlow.tsx` | Accessible target selection and edge display |
| `runs/RunCommunications.tsx` | Selection state and filtered request/reply cards |
| `runs/communications.css` | Scoped flow/card layout, including narrow screens |

There is no parallel frontend root, graph-library dependency, global bus state or
inferred sequence. All calls to a recorded target are grouped, including failed
attempts; an edge is an invocation relationship, not successful transport or
design approval. Missing-target calls remain visible in the unfiltered list.

Fresh verification run `5903c8c9257f495297453b6b7417ab1a` used isolated state and
actual Law8301, MasterPlan18312 and Elevation18327 A2A health calls. All three
returned succeeded and TASK_STATE evidence; new local target identities were
law/masterplan/elevation. Owner8794 and Editor18437 then served this run to
Chrome5186. The product binding was seeded only in the isolated test database;
this verifies read/display, not project creation or scene validation.

Checks: expanded owner graph/execution/wire/editor suite119 passed; identity suite
with two additional edge cases10 passed. Frontend build/boundary2 passed.
Chrome14 passed,7 unrelated opt-in cases skipped; includes grouping, unknown
identities, actual new A2A targets, reload/filter and390px layout. Two new UI tests
failed before controls existed, then passed. Independent owner-side reviewer found
no UI blocker. Evidence is `.superpowers/sdd/2026-10-04-communication-flow/`;
`test-results/editor-live-communication-flow.png` inspected. Disposable HTTP
servers were stopped and existing shared services were not restarted.

MasterPlan's downstream Law client copies the upper trace, updates caller/hop and
adds parent_task_id. Its inherited from_agent/to_agent **must not** be interpreted
as a new peer edge. This slice renders only the locally bound top-level invocation.

## Next gates

1. Extend explicit identity and correlation to downstream agent-to-agent hops;
   preserve missing evidence for historical records.
2. Extend the top-level collaboration flow to verified downstream edges. Port direct
   commands only through durable project-bound execution, with approval/resume
   semantics; do not adopt the unscoped global bus as a product write boundary.
3. Load the verified changes in the operational gateway and
   implement interrupted/resumed dialogue. Existing gateways need the updated
   code loaded before the new display is available.
4. Continue parcel provider/address linkage and remaining ARR/AG feature slices.
   Systems/DomainExpert/Interior completion remains unestablished.

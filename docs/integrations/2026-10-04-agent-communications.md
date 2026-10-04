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

## Remaining work

1. Record explicit sender/recipient and correlation on future calls and downstream
   agent-to-agent hops; preserve missing evidence for historical records.
2. Connect the ARR collaboration topology to those actual edges. Port direct
   commands only through durable project-bound execution, with approval/resume
   semantics; do not adopt the unscoped global bus as a product write boundary.
3. Verify newly executed A2A exchanges in the upgraded operational gateway and
   implement interrupted/resumed dialogue. Existing gateways need the updated
   code loaded before the new display is available.
4. Continue parcel provider/address linkage and remaining ARR/AG feature slices.
   Systems/DomainExpert/Interior completion remains unestablished.

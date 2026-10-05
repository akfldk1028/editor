# Remaining integration: deployment, historical identity and specialist submission

Baseline: `8fb38500`. This increment continues the original route ledger; it does
not close the full ARR/AG migration or specialist design acceptance.

## Native deployment surface

`/deploy` now composes `features/deployment/DeploymentPage.tsx`, four feature
components and existing workspace elements. The original useful sections remain:
guide cards, launch configuration, environment draft, API table and status.
Native backend/frontend commands replace Studio commands. Port validation,
copy/reset, navigation/back/reload and health errors are covered in Chrome.
The environment draft is temporary, masked and excluded from copied templates;
it does not change server configuration. Connection status describes the actual
configured workspace API, independently of command-preview ports.

Ruling: the existing PLANM Docker subset remains documented, but it is not a
container deployment of the unified native Editor. Full native Docker/cloud
deployment is explicitly unavailable. The old Studio Docker generator is not
presented as a working Editor deployment. No deployment is initiated by this UI.

## Preserved historical result access

Detail/evidence GET routes accept `design_uid`; aesthetic POST accepts the same
selector in its body or query, with conflicting selectors rejected. Selection
requires an exact stored UID within the job and numeric design ID. Wrong UID is
404, never a fallback to an arbitrary row. Missing selectors on duplicate numbers
remain 409. Conflicting stored identities also remain 409. Evidence bundle IDs
include the selected UID. Frontend review/image calls supply the selected UID;
polling recovers UID from stored result metadata when geometry lacks it.

The HTTP regressions compare complete database rows before/after. No historical
data was renumbered or deleted. Duplicates without stored UID remain unresolved.
The aesthetic regression uses the explicit placeholder provider, not paid AI.

## Bounded specialist submission

The existing product POST `/api/v1/platform/projects/{project_id}/runs` now accepts
the owner's `specialist_review` request alongside health. No new execution engine
or alternate scene writer is introduced. It validates exact item shape, read-only
tool ownership, one-to-six unique tools, finite arguments and positive source
revisions matching the submitted context. Bound project/branch, scene revision,
origin and idempotency protections remain. Authoring/concept requests are refused.

The owner counterpart lives in `agents/OrchestratorAgent/orchestrator/editor_runs.py`.
It queues through the existing durable worker, validates current context under
the existing lock for new requests and keeps accepted exact retries stable.
The worker still marks stale sources superseded and rejects side effects.
Caller-declared context is not proof that owner calculations consumed those nodes.

Actual owner HTTP -> queue -> A2A evidence is in the Orchestrator's
`runtime/diagnostics/editor-specialist-http-20261005-182724/`:

| Owner | Result | Evidence boundary and missing input |
|---|---|---|
| Systems | blocked | Frozen actual Program r2; 224 missing inputs, including use/function classification and engineering criteria/supply/network data. |
| DomainExpert | blocked | Historical actual Program; explicit specialist domain and source-backed operational requirements missing. |
| InteriorDesign | partial | Historical retained mass1; actual rooms/surfaces/doors/ceilings and camera/conditioning contracts missing. |

The coordinator context was isolated and synthetic around the historical inputs.
All isolated snapshots were unchanged; receipts retained exact request hashes.
This proves actual owner HTTP/A2A, not current shared-project adoption, frontend
specialist submission, image generation, corrective authoring or issue closure.
Each specialist's own named MD and memory were updated with these distinctions.

## Verification and runtime

- Product backend: 55 tests passed in 18.00s (platform binding/submission,
  workspace persistence, historical identity, runtime adapter and metadata).
- Orchestrator: 38 tests passed in 9.53s (Editor HTTP/submission, specialist flow,
  requirements routing and stale/no-mutation guards).
- Frontend identity/recovery: 7 tests, 20 assertions passed.
- Targeted deployment Chrome: 4 passed; UID review Chrome: 8 passed;
  UID aesthetic caller Chrome: 1 passed.
- Aggregate browser run: 46 passed, one gallery navigation `load` timeout in
  4.2 minutes. Its captured snapshot already showed the gallery and fixture card.
  Waiting for DOM content and the visible gallery heading replaced the unrelated
  full-page load wait; both gallery/import/builder cases then passed in 18.6s.
  All 47 unique scenarios have passing evidence; this was not a single 47/47 run.
- Fresh review-hook browser run: 8 passed in 2.90s.
- Final Next production webpack build and TypeScript checks passed, including
  `/deploy`. Visual screenshot reviewed: `.superpowers/sdd/deploy-final.png`.
- Final frontend/backend workspace health probes and sheet8790 root returned200.

Product code commits: `73315f57` specialist submission, `0722f171` historical UID,
`b92f9202` deployment view. Owner contract: `2e031f9`. Specialist memory-only
commits: Systems `25b71ed`, DomainExpert `ea61173`, InteriorDesign `cd203bf`.
The named owner MD updates remain alongside their pre-existing untracked content;
unrelated owner code/results were not swept into these memory commits.

Backend 18449 was reloaded hidden after executable/command identity checks and
read-only confirmation of zero running design jobs. New observed PID53484;
frontend3003/PID62016 remains. Logs: `.superpowers/sdd/integration-followup.*.log`.
The existing backend points at owner8791, whose catalog responds but whose older
live gateway lacks `/editor/v1/health`. Owner8793 is a separate prior isolated
gateway and must not be silently substituted for the shared state. Neither was
restarted or switched in this increment; the new owner contract was exercised
in an ephemeral isolated server, then that server was shut down.

## Next acceptance work

1. Verify the shared owner gateway's intended state root, worker and project/scene
   binding, then apply the new gateway version without redirecting to diagnostic
   state. Wire the original Playground UI to explicit supported owner contracts.
2. Finish original popup/channel/session, MCP workbench and remaining settings/auth
   interactions against the source element ledger, preserving original views.
3. Obtain missing owner-authored domain/engineering/room inputs. Run against current
   source revisions, then verify correction -> independent review -> scene/sheet
   publication with actual project evidence. Do not promote blocked/partial to done.

Existing original ARR/AG roots and all prior results remain preserved.

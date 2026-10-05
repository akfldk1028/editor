# Backend and frontend follow-up review

Review baseline: `a8755470`. The review covered native design HTTP contracts,
execution/results, cancellation and browser request ownership. Existing runtime
data was preserved. Fixes below are backed by reproduced failures, including
real React hooks in Chrome with deliberately reordered responses.

## Confirmed findings and fixes

| Severity | Trigger and original failure | Correction |
|---|---|---|
| P1 | All-algorithm runs reused algorithm-local result numbers. Detail, evidence and aesthetic lookup could raise `MultipleObjectsReturned`/500. | New all-mode runs map stable candidate UIDs to job-wide IDs consistently across SSE, geometry and persistence. Original local ID/algorithm/UID are retained in result provenance. Existing rows are unchanged; ambiguous historical numeric lookups return explicit409. |
| P1 | One or all algorithm evaluators threw, but the parallel runner logged exceptions and emitted complete, sometimes with zero results. | Per-algorithm failures propagate to failed job/event state. Cancellation wins over late evaluator errors. Legitimately infeasible empty runs retain their distinct complete state. |
| P1 | New parcel lookup retained old runnable geometry/legal state; delayed boundary, constraints or creation responses could reconnect an old job under a new parcel. | Clear old context at lookup start, abort superseded requests and check request ownership before returning or writing state. Resolved PNU and same-tick state are checked before creation. |
| P1 | Delayed floor plans or interactive operations/textures arrived after selection changes, reset or unmount. | Request ownership covers result, error and loading writes. Job/UID/parcel context changes invalidate pending mutations; a newer operation supersedes the old one. Floor debounce is cancelled when auto mode is disabled and old floor results clear when another design is selected. |
| P1 | Delayed evidence for the previous selection could initiate derived handoffs and repopulate reviews under a new job. | Guard identity and request ownership before every handoff and state update, including late errors, direct-message refresh and unmount. Browser regressions mock transport; they are not new live A2A proof. |
| P2 | Valid design number0 failed a truthiness check before aesthetic generation. | Accept finite numeric zero explicitly. No paid image provider was invoked by verification. |
| P2 | Boundary lookup captured an earlier building type while the user selected another type during the request. | Load legal context using the current selected type. Actual page regression reproduced office selection being sent as housing before the fix. |
| P2 | Persisted-result recovery omitted objective labels/budget; old polling errors could fail the next job and clear its timer. | Include objective metadata in job responses, restore it when polling and clear old labels on connection; ignore obsolete run failures. |
| P2 | A JSON integer beyond float range raised overflow/500 during validation. | Reject non-representable numeric input as400 before persisting a job. |

## Verification

- Backend:40 passed in77.76s across runner fault injection, result identity,
  metadata, lifecycle, HTTP adapter, real geometry and floor coordinates.
- Frontend data/BFF/canvas:9 passed,243 assertions.
- Parcel/job and evidence-review hooks:19 real-Chrome tests passed in6.91s.
  Command: `node --experimental-strip-types --test frontend/app/editor/features/design/hooks/use-design-job.test.ts frontend/app/editor/features/design/hooks/use-interactive-agent-review.test.ts`.
  Windows local tooling uses `PLAYWRIGHT_BROWSER_CHANNEL=chrome` and
  `BUN_EXECUTABLE=C:/Users/SOGANG1/AppData/Roaming/npm/node_modules/bun/bin/bun.exe`.
- Floor and interactive hooks have16 additional Chrome regressions in the main
  migration browser suite. Polling/SSE state has2, and actual page context has1.
  Delayed-response fixtures intentionally ignore cancellation to prove ownership
  checks, not only successful transport aborts.
- Full migration browser suite: 43 passed in 4.0 minutes, including live VWorld
  navigation, original ten-algorithm execution, floor display and cancellation.
- Next production webpack build and TypeScript checks passed after all changes.
- Final live probes: frontend `/design`, backend
  `/api/v1/design/collaboration/health` and `/api/v1/platform/agents` returned 200.
  Bare backend `/health` is not a registered route and returned 404; it is not
  used as evidence that the service is unavailable.

Initial page-race checks timed out before the lazy design view loaded; after
waiting for its visible heading, the test reproduced the actual stale building
type, then passed after correction. This setup timeout is distinct from the
reproduced application bug. No successful test claim is based on those timeouts.

## Runtime and limits

Editor backend18449 was reloaded hidden after process identity verification;
observed PID84152. Frontend remains3003/PID62016. Never reuse these PIDs without
checking current executable/command identity. Shared owner services were untouched.

Historical ambiguous result numbers were not renumbered or deleted. Their lists
and geometry remain preserved; detail actions receive an explicit conflict rather
than selecting an arbitrary old row. This review does not close unported original
surfaces or specialist domain acceptance in the original route ledger.

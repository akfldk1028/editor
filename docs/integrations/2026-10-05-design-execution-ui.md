# Project execution controls and actual browser verification

Existing ProjectPage → NativeDesignJobs now includes a separate DesignExecutionPanel. It consumes the native attempt API and standalone worker. No second application or ARR frontend directory was introduced.

The panel requires explicit unverified-search acknowledgement and a numeric seed. Additive jobs support queue, progress, cancellation and a new attempt after a terminal state. Other algorithms remain specification-only. Failed POST retries retain request identity; successful explicit reruns create a new identity. History read failures disable launch rather than masquerade as an empty list. History is paginated, event replay uses a cursor, requests abort on unmount, and terminal results stop polling after retrieval. The API validates project/job identities and result shape before rendering.

Results display saved 2D footprint geometry, candidate selection and metric labels with units. A cancelled attempt can expose partial results. Interrupted work is described as restart from the beginning. No legal approval or 3D scene publication is implied. The original immutable job's execution_supported=false field remains its creation-era record; actual attempts are separate runtime records and are displayed separately.

## Evidence

- Real hidden backend on 18446, standalone worker and Vite frontend on 5186 were launched directly. Browser verification uses Chrome and real HTTP/SQLite/computation, with synthetic project/scene identities and a synthetic parcel.
- Actual browser flow: save additive specification → acknowledge/start → default 1050 evaluations → saved footprint displayed → page reload/reopen with identical result → new attempt cancelled → explicit new attempt computed. Three distinct attempts have computed/cancelled/computed states. No page runtime errors were observed.
- Final focused browser run: two passes (one retry/error mock and one actual HTTP/worker case). Broader mock regression: 40 passed, 20 separately gated tests skipped. This includes existing land-analysis and agent communication/flow UI cases; it is not live VWorld-provider or new actual A2A evidence.
- Frontend build and two module-boundary checks passed. Screenshot `test-results/design-execution-actual.png` was inspected. Evidence/logs are under `.superpowers/sdd/2026-10-05-design-execution-ui`.

The user requested that the frontend be started and tested. The isolated verification services remain running for inspection at `http://127.0.0.1:5186/projects/bcdb670334314266a896c8353517fa8d`. The process receipt identifies Vite PID48084, backend launcher88400/server980 and worker launcher45440/process17116. These are session receipts, not fixed operational process IDs. Launches used CREATE_NO_WINDOW. Original/canonical data and unrelated operating services were preserved.

## Remaining scope

This is a real calculation UI test against isolated bindings, not the full operational stack. Next reconcile service startup/health and real project bindings, then verify the actual VWorld provider/map workflow and actual shared-agent request/response/flow paths. The VWorld land adapters and RunCommunications/RunCommunicationFlow remain part of the Editor integration target. Do not drop them or infer current live connectivity from mock tests. Full generated-mass→PLANM/DWG/3D publication/reopen, other algorithms and MAAS/parking/agent-specific workflows remain open. Overall ARR/AG integration is incomplete.

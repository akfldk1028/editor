# Durable additive attempts and worker API

This backend unit wraps the existing additive computation in persisted attempts, events and results. It does not yet expose execution controls in the frontend or start an operational worker automatically.

## Ownership

`execution_store.py` owns a separate versioned `executions.sqlite`. `execution.py` validates a saved project-bound job and pins resolved engine options at queue time. `worker.py` executes queued work using the existing compute function. Original native jobs and historical archives remain unchanged.

Request identity is unique per actor/project. Identical retry returns the same attempt; changed execution inputs conflict. A partial unique index permits only one queued/running attempt per actor/project/job. A different request after a terminal state creates a new attempt; it restarts from the explicit seed rather than claiming optimizer-state continuation.

One OS file lock owns execution per storage directory. A second worker cannot claim or recover while that lock is held. On process death the OS releases the lock; the next worker marks former running attempts interrupted before claiming queued work. Per-attempt tokens fence progress/terminal writes. This deliberately uses process-held ownership rather than an expiring time lease, avoiding false expiry during a long generation. It supports one active worker per storage directory, not distributed execution.

Result JSON, its SHA256, terminal status and final event commit in one SQLite transaction. Compute's terminal callback is not published early. A terminal write failure rolls back success and is recorded as failed if storage remains available. If storage itself is unavailable, the running attempt remains recoverable as interrupted. Queued cancellation is immediate; running cancellation is checked at generation boundaries and can retain partial results. Event reads use a sequence cursor and never execute work.

## API and command

Existing project native-job routes now include:

- POST `/{job_id}/attempts`: request_id, scene_revision, unsigned 64-bit seed and explicit unverified_search=true.
- GET `/{job_id}/attempts`: limit/offset pagination.
- GET `/{job_id}/attempts/{attempt_id}`: persisted state.
- GET `.../events?after=N`: up to 200 persisted events in sequence order.
- GET `.../result`: checksummed computed/partial result, or null when unavailable.
- POST `.../cancel`: scene_revision, existing origin/live project binding guards.

All paths are below `/api/v1/platform/projects/{project_id}/design/native-jobs`. Attempt access is scoped to both project and job. Mutation reuses DesignAccess. HTTP requests only queue/cancel; no HTTP handler starts a daemon thread or generates results.

```powershell
python -m backend.app.modules.design.worker --storage-directory ABSOLUTE_DIRECTORY
```

`--once` performs one recovery/claim cycle and exits. Launch persistent workers with hidden windows under the existing service management conventions; this unit has not installed or started an operational worker. Idle workers poll every 0.5 seconds.

## Verification and remaining work

347 backend tests passed, including 10 new lifecycle/API cases and 337 prior regressions. New tests cover concurrent duplicate submission/claim, actor isolation, HTTP queue/result/event replay, origin/live scene checks, queued/running cancellation, stale ownership, terminal persistence rollback and a real hidden subprocess killed during an attempt. While the subprocess held the OS lock, a competing worker left the running state untouched; after process death, recovery recorded interrupted and an explicit new attempt completed. Original native-job DB bytes remained unchanged. Final suite evidence is `.superpowers/sdd/2026-10-05-design-worker/backend.xml`.

Next: existing project UI execution controls, paginated attempt history, progress/event replay, cancel and explicit restart; actual browser against HTTP server plus standalone hidden worker; service startup/health integration. Keep UI capability wording accurate until that path is verified. No new 3D scene publication, legal validation, MAAS portfolio or non-additive execution is claimed. Overall ARR/AG integration remains incomplete.

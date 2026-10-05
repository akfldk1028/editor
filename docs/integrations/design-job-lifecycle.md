# Design job execution and event replay

Editor design jobs are stored in the isolated `EDITOR_DESIGN_DATABASE` SQLite database. Migration `0003_job_execution_events` adds an execution token, heartbeat, and durable event journal without changing existing job/result records.

Both `POST /api/design/jobs/{id}/run/` and `GET /api/design/jobs/{id}/stream` use the same conditional pending-to-running database claim. The winning process starts one background producer using the existing single/multiple algorithm runners and geometry enrichment. Connecting another stream or repeating run cannot start a second producer. Closing an SSE connection does not cancel computation.

SSE entries include `id`, `event`, and JSON `data`. Clients can reconnect with `Last-Event-ID` or an `after` query parameter. Replay reads persisted entries; results, terminal state, and the terminal event commit in one transaction before delivery. Existing terminal states cannot be overwritten by late generation or completion events. Cancelling an unknown job returns 404; cancelling a completed job preserves its state.

Workers refresh their lease every five seconds. A running job with a heartbeat older than thirty seconds becomes failed when status, run, stream, or results is requested. Its persisted error event has `recovery_required: true`; create a new job to retry. It is never automatically rerun. Cancellation signals the local engine immediately; another process's engine notices the persisted terminal state at its next queue poll/generation. An already executing generation may finish, but cannot publish late results.

Result writes now propagate exceptions. A failed transaction rolls back both results and its completion event, and the worker records an error event. If the database itself is unavailable, no success is emitted; lease recovery records the interruption once storage is available again. A Pareto result without generated mass geometry fails rather than producing a success containing unusable output. A run with no feasible Pareto candidates can complete with an empty result set.

Job creation rejects unsupported algorithms, malformed specifications, non-finite JSON, and invalid budgets before persistence. Limits are 1–500 generations, 1–32 islands, 2–500 designs per island, and at most 2,000,000 estimated evaluations (including the multiplier for all-algorithm modes).

Verification uses temporary SQLite files and the real Django bootstrap. `python -m pytest backend/tests/test_design_job_lifecycle.py -q` covers concurrent threads/processes, terminal replay, disconnects, rollback, cancellation, interrupted leases, invalid requests, and a real original-engine run that persists generated geometry without an SSE client.

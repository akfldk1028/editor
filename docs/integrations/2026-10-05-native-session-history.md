# Original history and native session storage

`/history` now retains the original AG-frontend list cards, detail panels, two-session comparison, expandable runs, message types and two-step deletion control. Screens are split into `features/history/HistoryPage.tsx` and `components/{SessionCard,SessionDetailPanel,RunCard,MessageBubble}`. Shared session queries and transport are under `features/sessions`, ready for Playground reuse. Query errors are shown explicitly instead of empty history.

The native backend owns `modules/workspace/sessions.py`, `api/routes_workspace_sessions.py` and the strict session-create schema. A session captures its selected team configuration when created; subsequent template deletion cannot erase that snapshot. The delete operation archives the visible session while retaining run evidence. No public endpoint accepts fabricated run results. Stored sessions with no runs are explicitly `not_started`.

Actual session creation/list/reload/archive and original comparison controls passed a real-backend browser test. A separate intercepted-response test passed for historical text, handoff, tool-call/result, recorded error and retrieval failure rendering; it is not live execution evidence. Backend tests verify snapshot retention, archive preservation, unknown-team and cross-origin rejection. TypeScript passed.

The source scripts refer to `C:/Users/SOGANG1/.autogenstudio/autogen04203.db`; that file is absent. The existing folder contains a model log and a private environment file. A scoped filename search of `D:/Data/25_ACE` and `C:/Users/SOGANG1/AppData/Local/CodexMigrationBackups` found no `*autogen*.db*`. Do not infer that old session records were imported. Old scripts, logs and credentials were not modified.

Still open: original AG session database recovery/import, actual Playground run creation/execution/streaming/input/cancellation, project/owner binding for this session engine, and ARR-specific history routes. Current History storage is local workspace configuration, not a substitute for project-bound A2A evidence already shown on `/dialogue`.

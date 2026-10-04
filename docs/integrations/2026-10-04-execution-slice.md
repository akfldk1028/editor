# Editor execution integration — bounded verification

2026-10-04. AG absorption remains partial. Feature coverage is tracked in `../migrations/ag-function-coverage.md`; the existing lightweight frontend/backend inventories remain source references.

## Implemented and verified

- Project page submits the explicit health template through Editor API; owner creates a durable run and the existing worker executes it. HTTP handlers never advance execution.
- Run list/detail, status polling, call-record display and reload work. These are newly implemented Editor contracts, not a wholesale copy of Playground/History.
- Pending request identity and source context survive reload in sessionStorage. Network failure retains the same identity. Accepted retries bypass current scene validation but still pass immutable owner payload validation; fresh requests validate the live binding.
- Owner accepted retries do not acquire the worker lock. Wrong project replies and malformed JSON are rejected; missing runs map to404. Unsupported templates and invalid versions are rejected at the product boundary.
- Dev service definition explicitly enables submissions and rejects a read-only gateway as incompatible. Full normal product launcher was not exercised; its existing worker prerequisite remains.

## Live evidence

Isolated owner8793 + worker, Editor backend18433, Next scene3002 and Playwright Vite5186. Runtime data resides outside Git under `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/editor/platform-live/`.

Project binding `07e1f9cb80884e39b2f4a910096f38b1`, scene `platform-run-20261004` version1, owner project `editor-run-probe-20261004/main`.

Browser submission produced run `21685e9df3834a52be72c14dfc3bfa0c`, status `succeeded`; reload retained the run URL and three call records. Actual stored A2A replies all had `TASK_STATE_COMPLETED`:

| Call | Remote task ID |
|---|---|
| law_health | 54d5b4c8-48e0-459e-8a1c-54e8be5663f5 |
| masterplan_health | 7ce522f8-e419-402b-bb24-d1165c4ef99d |
| elevation_health | 2385a222-6d0f-42d5-bc93-7cb7ad15deed |

The UI currently shows local call identifiers, not these remote task IDs or detailed artifacts. No generation or geometry mutation was requested. Systems/DomainExpert/Interior completion is not established by this run.

## Checks and limits

- Platform backend27 tests, owner gateway6 tests, dev12 tests, route2 and boundary2 tests passed.
- Chrome: live execution1 passed; mocked retry/reload and existing route regressions3 passed. Frontend TypeScript/Vite build passed in the isolated restored dependency environment.
- Full `pytest backend/tests` was attempted, then interrupted after a failure and slow remaining tests. A fail-fast repeat reproduced `test_backend_planm_adapter_runs_versioned_normalize_stage`: missing `infra/runtimes/gitagent/dist/exports.js` in the original D: checkout. Do not report the whole backend suite green. Existing checkout dependencies/build outputs need restoration before the full regression gate.
- Existing Starlette/httpx deprecation and Node color-environment warnings remain.
- Task4 remains incomplete: general task input, attachments, messages, interruption/resume, artifacts, comparison/export. Task5 full launcher and existing DWG/PLANM/scene regression remains incomplete. ARR land analysis is the next independent product module to map into Editor; do not substitute agent health for it.

# Native Editor frontend/backend wiring

Latest runtime update: [native-runtime-recovered](2026-10-05-native-runtime-recovered.md). The native frontend is now actually running on3003 against existing backend18447, and native browser cases were exercised. Earlier "startup blocked / browser pending" statements below are historical; new configured-backend startup is still not completed.

The native Next app previously exposed only catalog/project/run GETs although the Editor backend already implemented project binding and health-run submission. The old product launcher also made PLANM the public shell and never supplied the native frontend's backend URL. A page could be ported while its write operations remained unreachable.

## Changed

- Native `/api/v1/platform` now permits project POST, project context GET and project run POST. It still restricts paths and preserves original Origin, idempotency key, body and backend response status. Arbitrary agent registry writes remain rejected.
- `/dialogue` and `/flow` now provide a project connection form and a health-run action. The server validates actual owner/branch/scene/revision bindings. The browser reads source versions before submission and opens the accepted run in the selected view. Unknown submission outcomes retain the same key/body in project-scoped sessionStorage before POST, surviving same-tab navigation and reload. Acceptance clears the pending identity. Closing the tab is outside this persistence guarantee; corrupted/unavailable storage is surfaced instead of silently submitting a new identity.
- Only the backend's supported `health` request is exposed. This is not free-form Playground or design generation. Existing transcript/graph styling is preserved.
- Added `bun run editor:dev`: native Editor at `http://127.0.0.1:3002`, backend at `http://127.0.0.1:8000`, matching public Origin and scene URL, explicit platform/land/design storage and external orchestrator wiring. The profile does not launch AG, ARR, PLANM or DWG. MCP remains an Editor-owned service; shared agents remain externally managed. The original `plan:dev` command remains for existing users and artifacts.
- Native backend readiness now checks `/api/v1/platform/health` configuration before reuse, and startup verifies the actual Next-to-backend projects GET before reporting the project API connected. Readiness distinguishes configuration from provider/owner execution. No credentials or storage paths are returned by health.
- The launcher retains hidden Windows child processes and ownership-aware cleanup. `EDITOR_PYTHON` can select the backend virtualenv executable. `EDITOR_PLATFORM_DATA_DIR`, `EDITOR_LAND_DATA_DIR` and `EDITOR_DESIGN_DATA_DIR` preserve existing configured storage; do not point production at temporary test directories.

## Verification

- Native route regression first reproduced context404 and missing POST, then passed3 tests for forwarding and write guards. Combined targeted Bun suite:10 passed.
- Backend platform health/projects/runs/catalog:28 pytest tests passed (one existing Starlette TestClient deprecation warning).
- Native and existing runtime definition/probe tests:9 passed. Product launcher syntax and full native-app TypeScript check passed.
- Headless Chrome rendered the actual ProjectConnection/HealthExecution components with intercepted responses: form submitted correct binding; first submission503 remained uncertain; retry preserved exact key/body without rereading source versions; accepted callback returned run ID. No browser page errors. This is component/network-contract evidence, not real owner execution.
- Corrected incomplete flow-route fixtures and updated the dialogue regression for newly supported write routing. Added a native dialogue submission/retry test; native Next browser suite remains unexecuted because the prior approved hidden Next startup was rejected before process creation (`blocked by policy`). This launcher was authored and statically tested, not executed as a workaround.
- Live read-only check of existing backend18447: land zones200, platform projects503, agents503. That process has not adopted this startup profile. Do not claim deployed integration, real A2A or all-provider readiness.

## Still required

Follow-up review: native profile explicitly sets PORT3002 so inherited shell settings cannot redirect Next away from its configured Origin. Two pending-request storage tests, three BFF tests, nine runtime tests and native TypeScript passed. Offline Chrome repeated the actual form/action after a full page reload, retained exact identity/body, read context once and cleared pending storage after acceptance. Native Next route verification remains pending.

Permission investigation: the delivered session is unrestricted with approval policy `never`; no exposed tool can change the execution review policy. Selected local config fields did not reveal an actionable restriction. Official configuration documentation distinguishes settings from enforced requirements (https://learn.chatgpt.com/docs/config-file/config-basic), but the generic `blocked by policy` response does not identify which layer rejected this launch. No managed policy was changed, and no alternative execution path was used to evade the rejection.

Run the native profile when the execution tool permits startup; verify fresh Next route load/reload, live project/scene binding and actual owner run through the native UI. Then finish original DesignPage/parking/drawing/floor-plan/3D and Playground input/stream/stop routes, plus the remaining entries in `native-editor-route-ledger.md`. This change does not port every original screen or complete Systems, DomainExpert or InteriorDesign.

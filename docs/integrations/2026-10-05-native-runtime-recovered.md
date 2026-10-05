# Native frontend runtime recovered

Current browser URL: http://127.0.0.1:3003 . Actual D: app is `frontend/app/editor`; its ignored `.env.local` points to existing Editor backend http://127.0.0.1:18447 . No agent implementation was changed in this increment.

## Actual startup evidence

A literal, hidden PowerShell `Start-Process` of Next succeeded after earlier compound launch commands were rejected. Therefore "all server startup is blocked" was an overstatement. No policy was disabled or bypassed; the same execution tool admitted the smaller command. The precise policy reason for the earlier rejection remains unknown. A subsequent compound environment-setting + new backend18448 launch was again rejected before execution; that new backend was not started. Existing backend18447 remains running and is used by the frontend.

Initial Next PID52812 was stopped after inspecting its identity/child processes. Its cross-drive Next dependency resolved to the C: recovery tree and generated an invalid `./C:/.../next-dev.js` entry. Copied the same Next16.3.0 package to `frontend/app/editor/node_modules/next`, preserving the original. Moved the stopped D: `.next` to ignored `.superpowers/sdd/next-before-local-package` after verifying absolute paths; no cache deletion. Current launcher PID38680, worker PID77168 (recheck before managing). Logs: `.superpowers/sdd/frontend-local.stdout.log` and `.stderr.log`.

## Source fixes

- Disabled development diagnostics now compile out of the shared browser bundle. Merely passing `enableDevDiagnostics=false` did not prevent Webpack from compiling react-scan, whose named JSON import caused500. Diagnostics remain opt-in with PASCAL_DEV_DIAGNOSTICS=1; that opt-in dependency incompatibility is not claimed fixed.
- Client Webpack ignores only `node:module` from the manifold-3d package context. Its universal WASM loader uses this import only in the Node branch; browser workers use fetch. Server configuration and other Node imports are unchanged. This fixes root Editor compilation; printing/export output is not yet revalidated.
- Two native browser-test issues fixed: Next route announcer also has role=alert, so error assertion must select the actual message; flow test now waits for destination URL before reloading.

## Verified

- Native /land and root / return200. The fresh root compile took57 seconds; subsequent page navigation worked.
- Actual native Next → existing FastAPI `/api/v1/land/zones` returns200 with records. Browser suite also verified real backend GET, rejected cross-origin writes and unknown operations.
- Nine native Chrome cases are now verified across the final suite run (8 passed, one cold-load timeout) and targeted rerun (remaining case passed). Includes land search/cards, existing 3D canvas/tools, same-document land→Editor return with loader gone, map search/error/analysis UI, catalog, dialogue/binding/retry and flow navigation/reload/controls. Domain/provider responses in UI cases are intercepted fixtures; only explicit proxy checks use the real backend.
- Screenshots inspected: `test-results/native-editor-return.png` shows original tools/grid/canvas; `test-results/native-vworld-map.png` shows the original map/search/right analysis layout but NO imagery. Missing provider is visibly reported, not counted as successful VWorld display.
- Two wrapper bundle tests passed (including red→green diagnostics exclusion); native TypeScript passed.

## Remaining

Existing backend18447 still lacks platform/owner configuration (previous live projects/agents503); new configured backend startup did not execute. Provider credentials/readiness, real cadastral imagery, design/parking/drawing workflows, save/reopen, printing/export and other original routes remain unverified or unmigrated. Shared agents remain external and unfinished. Some workspace package links still resolve to C: preserved sources, so this is not a clean-install reproducibility signoff. Do not conflate main Editor navigation recovery with full original feature migration.

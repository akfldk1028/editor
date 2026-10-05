# Native Editor routing correction

## Latest increment: map, dialogue and catalog (not full migration)

The user's latest "전부다 이전" instruction requires tracking the remaining original screens and interactions, not treating the first land form as completion. The native route ledger is [native-editor-route-ledger.md](native-editor-route-ledger.md). Older candidate/exclusion recommendations do not establish that remaining screens have been migrated.

- Added native `/map` with the original ARR OpenLayers map, address/PNU search, parcel highlight, setback layers and 420px analysis panel. Native backend tile/WMS routes validate coordinates/layers, keep the VWorld key server-side, restrict provider URLs and image size, and report provider failures. Failed/null elevations display as unknown, not 0m. Selection requests are cancelled/replaced to avoid stale analysis overwriting a newer parcel.
- Added native `/dialogue` using ARR's original MAS participant cards, timeline, agent filter and expandable record metadata. Project/run selections survive reload in the URL. Native owner records supply requests/responses; the source's fallback transcript, invented timestamps/ports and hardcoded parking/BCR/height values are not copied. Missing/failed/truncated records and partial/blocked execution remain explicit. This is stored-record polling, not a new free-form execution or verified live A2A session.
- Added native `/agents` preserving AG-frontend card grid, search, keyboard selection, details and JSON display, bound to the existing owner catalog. Connection and implementation status remain separate. Registry writes and live health probes are not implemented in this slice; do not report full agent-management parity.
- Route handlers call only the Editor backend. Heavy map imports are client-only. Workspace colors remain scoped and navigation now marks the current route. Original roots, agent storage and design artifacts are preserved.

Verification: 16 backend map/land tests passed, including native route mounting, provider failure/redaction and input validation. Latest native-app TypeScript check passed after adding the catalog and request cancellation. Six Chrome cases passed **before** the last catalog/cancellation changes: original land rendering, same-document Editor return, native GET/guards, original map rendering and two dialogue/binding/error cases. Dialogue screenshot inspected. The map screenshot caught the entrance animation; a stronger animation-completion assertion was added but its rerun is pending. New catalog browser test is also pending. Do not turn that earlier six-test result into a claim that every current route passed.

Runtime blocker: C: free space reached **0 bytes**, producing `ENOSPC` during runtime source copying and test startup. The preserved Next3002 process subsequently exited; the latest read-only checks found no listener or process. D: Webpack3003 remains listening but `/agents` returns500 from the existing `manifold-3d`/`node:module` bootstrap error. Source types and in-process backend tests still run from D:.

Recovery attempts: NTFS compression of generated cache/dependencies did not free sufficient space. A cross-volume move of the inactive `.next` cache failed partway; partial generated files exist under `.superpowers/sdd/2026-10-05-native-editor-routes/runtime-next-cache`, and the remaining C: `.next` must not be treated as intact. No junction was created. A scoped recursive deletion of the inactive Turbopack cache was rejected by automatic review (`blocked by policy`, no further reason). No alternate deletion was attempted. This is an actual disk/tool limitation, not proof that the user's visible access setting is wrong. Runtime copied agent files may also be incomplete; D: source is authoritative.

Next: recover a reproducible native runtime with sufficient build/temp storage and aligned backend origin; rerun all native browser cases, then continue the ledger through original flow/chat, design/3D/floorplan/parking and history. No whole-AG/ARR or specialist-agent completion claim is justified.

The user's October 5 correction supersedes earlier frontend placement decisions: the main editing experience is `frontend/app/editor`, using its Next App Router. Work in `frontend/app/planm` is preserved, but its tests do not establish migration into the native Editor or preservation of AG-frontend/ARR screens. Do not present port 5186 as the original Editor UI.

## Implemented first route

- `app/(workspace)/land/page.tsx` mounts the ported AG-frontend LandPage.
- `features/land` retains the original search form, cards, regulations, expandable law articles, restrictions and statistics components. Imports and native API response contracts are adapted: zone names are strings, law articles are flat, PNU may be null. Provider/query errors remain visible.
- `features/workspace` contains the selected original Card/Button/Input components and scoped original theme/typography. The native route-group layout retains the original 240px sidebar, 56px header and content spacing. Its navigation includes only implemented destinations, and does not fabricate AG authentication.
- The existing Editor root page is preserved, with one additional `/land` link. No iframe or cross-application redirect implements this route.
- `app/api/v1/land/[operation]/route.ts` permits only the four selected land operations and forwards to `EDITOR_BACKEND_URL`, never ARR/AG. It rejects cross-origin writes, forwards the original Origin, and surfaces missing/unreachable backend configuration. Backend `EDITOR_PUBLIC_URL` must equal the browser origin; this guard was not weakened for testing.
- Shared agents remain outside Editor. No core/viewer or specialist implementation changed.

## Verification and limits

The regression first failed because the land screen was absent. Three Chrome browser cases subsequently passed: native land direct-load/reload and result expansion with intercepted analysis responses; same-document native Editor/land navigation, scoped theme, canvas and loader disappearance; actual Next-to-Editor backend zoning GET plus rejected cross-origin/unknown/method requests. The last navigation check was rerun with explicit loader disappearance and its screenshot inspected. Full native-app TypeScript check passed; production build was not run.

Browser verification used the already-running preserved Next runtime on `http://127.0.0.1:3002`, with these changed files copied from the authoritative D: checkout. Its source snapshot is under `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/editor/restored-files-v2`. This is runtime-copy verification, not proof of a fresh checkout deployment. Original AG-frontend source is unchanged. Selected dependency versions are pinned and bun.lock updated.

A direct D: checkout Next/Webpack trial on 3003 failed on existing external dependency font resolution, then `manifold-3d`'s `node:module` import through the existing Editor bootstrap. Do not claim that server works. The Editor backend on 18447 runs authoritative D: source, with isolated land storage and allowed origin 3003. GET zoning works through 3002; browser analysis POST from 3002 is not verified successful because origins differ. Restart/cache-move and a separate hidden-backend startup command were rejected by automatic approval review (`blocked by policy`, no more specific reason). No approval bypass or broader Origin acceptance was introduced.

Evidence: `.superpowers/sdd/2026-10-05-native-editor-routes/`, `test-results/native-land-results.png`, `test-results/native-editor-return.png`. The screenshot now shows the existing Editor toolbars/grid after returning; an earlier screenshot captured the loader and was not accepted as full render evidence. These screenshots are local ignored artifacts. The browser mock establishes rendering contracts, not live VWorld or law availability.

## Next implementation sequence

1. Finish reproducible native runtime configuration with aligned public origin and verify real PNU/address submission, explicit provider errors and storage. Keep actual dependency errors distinct from permission/tool rejection.
2. Port selected **original** AG-frontend `PlaygroundPage`, `LiveAgentFlow`, `FlowPage` and their dependency closure into native `/playground` and `/flow` routes. Preserve session/chat/agent-detail/graph interactions; bind Editor-owned run and shared-owner contracts. Do not substitute the simplified PLANM run list. Preserve waiting/unavailable states and do not replay fake agent exchanges as live evidence.
3. Port the original ARR VWorld map and agent-dialogue UI, including selection/layer/parcel behavior, via native feature routes. The current land form is not the VWorld map and is not map parity.
4. Move already-implemented project/job/execution/history interactions from the PLANM surface into appropriate native routes, preserving IDs, scene bindings, immutable results and existing API ownership. Keep drawing/parking/3D original behavior and test project save/reopen end to end.
5. Reconcile launcher/router ownership only after these routes work; preserve original sources and all existing results. Test with original AG/ARR roots unavailable before declaring absorption complete.

Neither whole ARR/AG integration nor Systems/DomainExpert/InteriorDesign completion is established by this change. Final independent agent review remains unavailable from the earlier agent usage limit; primary review and verification are recorded above.

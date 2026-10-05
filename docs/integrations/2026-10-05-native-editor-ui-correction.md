# Native Editor routing correction

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

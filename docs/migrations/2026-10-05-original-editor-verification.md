# Original Editor route and CAD verification

Date: 2026-10-05. Runtime: http://127.0.0.1:3003. Verification used the running browser and real scene API, without mocked scene responses.

## Routes and observed behavior

- `/` is the original editor, with 3D, 2D and Split modes. There is no separate `/cad` page route in the current native app.
- `/scenes` lists stored scenes; `/scene/[id]` opens a stored editable scene. `/terms` and `/privacy` are also original page routes.
- Root mode buttons were clicked in the browser. 2D, Split and 3D became selected; the Split screenshot shows both viewports.
- HTTP smoke checks returned 200 for all 17 checked routes: `/`, `/scenes`, the verification `/scene/[id]`, `/terms`, `/privacy`, `/land`, `/map`, `/law`, `/design`, `/design/language`, `/agents`, `/dialogue`, `/flow`, `/build`, `/gallery`, `/history`, `/settings`. HTTP 200 alone does not establish full feature behavior on these pages.
- A separate verification scene was created through the Create new scene UI. Two canvas clicks in 2D created a wall; this was not an API-injected geometry fixture.
- The real API subsequently contained four nodes: site, building, level and wall. Autosave advanced the scene to version 2.
- The fixture was renamed through PATCH to `Editor verification 2026-10-05` (version 3), then the page was reloaded. The graph hash remained `ad801dea3665a11d46543e7b553583137669f5204ec4542c1d39669532f26051`.
- The 3D screenshot was visually inspected and shows the saved wall. Split was also opened with the saved geometry. All scenes -> the fixture card -> the scene editor returned to the same ID with a canvas and unchanged stored graph.
- Retained fixture: `/scene/1bf925e33e03`. Its name identifies it as verification data. No existing scene was overwritten or deleted.

Screenshots are local ignored artifacts under `test-results/`: `original-editor-2d.png`, `original-editor-split.png`, `original-editor-3d.png`, `original-editor-saved-wall-3d.png`, `original-editor-saved-wall-split.png`.

## Findings that prevent an integration-complete claim

1. **Scene storage differs from the earlier isolated baseline.** The current default Windows store is `C:/Users/SOGANG1/AppData/Roaming/Pascal/data/pascal.db`. It initially listed no scenes and now contains the verification fixture. Read-only SQLite inspection of `C:/Users/SOGANG1/AppData/Local/CodexMigrationBackups/editor-platform-20261004/editor/runtime-baseline/pascal.db` found six scenes, including `868e0a5e9231` with 321 nodes. These are separate databases; an empty current list is not evidence that the old scenes were deleted. Neither database was replaced or merged.
2. **Runtime packages still resolve outside D:/Data/25_ACE/editor.** The core, editor, viewer and mcp entries under node_modules/@pascal-app point to the restored-files-v2 backup tree. Browser webpack traces independently confirm this. These browser passes verify the current mixed runtime, not a self-contained build of all D: sources.
3. **Warnings remain.** The final scene navigation reported zero console errors but warnings include unsupported direct import.meta access, THREE.Clock deprecation, Windows powerPreference, zero-count draw calls and a skipped BVH for incompatible mesh geometry. Selection/raycast behavior under the BVH fallback was not established.
4. Follow-up verified the scene URL contract: the API advertises `/editor/<id>` and `next.config.ts` redirects it to `/scene/<id>`. A real request returned 307 with the correct Location; following it returned 200. This is not a missing route. See `docs/integrations/2026-10-05-route-boundary-review.md` for the additional audit.

## Scope limits and next work

- This verifies a real wall edit, autosave, reload and 3D rendering. It does not verify every CAD tool, dimensions, stairs, openings, imported assets, export, undo/redo, or a full project.
- Preserve both scene databases. Establish an explicit shared Editor/MCP data location and a conflict-aware, backed-up migration before expecting earlier scenes in the current list.
- Rebuild and relink workspace packages to the actual Editor tree, then repeat this browser check and the integration suite. Do not edit backup package sources as a substitute for integration.
- Test selection and editing around the BVH warning, then extend coverage to the remaining CAD tools and the real 321-node baseline via an isolated copy.
- Systems, DomainExpert and InteriorDesign implementation and end-to-end agent delivery remain separate incomplete work.

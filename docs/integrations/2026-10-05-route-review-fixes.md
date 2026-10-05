# Route review fixes - 2026-10-05

This increment fixes confirmed route-review defects without replacing the original views or claiming completion of the full ARR/AG integration.

## Code changes

- `/scenes` now distinguishes unavailable storage, malformed responses and a genuinely empty list. Failures render an alert with a full-page Retry link. The extracted `lib/scene-list.ts` validates displayed metadata, uses the configured base path and bounds upstream waiting to 15 seconds. Existing successful list layouts remain intact.
- `features/design/lib/design-selection.ts` owns the existing parcel/geometry and candidate-selection functions formerly embedded in DesignPage. Function bodies and DOM behavior are preserved. DesignPage decreased from 971 to 769 lines; other large design components still need decomposition.
- Native product startup calls `infra/dev/workspace-links.mjs` before starting services. It rejects an external node_modules root, missing/misdirected workspace package links and nested dependency aliases resolving outside the checkout. The checker is also directly runnable with Node.
- Removed Next's `typescript.ignoreBuildErrors: true`. Production builds once again retain the default type-check gate; a full production Next build was not performed in this increment.

## Local runtime repair

The previous root node_modules junction was preserved at `.superpowers/sdd/node_modules-backup-link-20261005`. Installed third-party dependencies were copied into an independent Editor-owned node_modules directory (49,996 files, about 996 MiB; zero copy failures). This reused the installed versions; it was not a fresh lockfile installation.

All 15 declared workspace package links now point to the actual D:/Data/25_ACE/editor source packages. Four additional app-level React/Three aliases were also relinked locally; their old links remain in `.superpowers/sdd/app-aliases-before-local`. The previous Next caches were moved into `.superpowers/sdd/next-before-local-20261005` and `next-before-local-aliases-20261005`, without deleting them or the original backup tree.

The final link scan found zero dependency links into CodexMigrationBackups. The native startup checker passes. Next was restarted hidden on 127.0.0.1:3003; the backend at 18449 was left running. Package/cache changes are local runtime state and are not included in Git; the new startup checker and these recovery instructions are committed.

## Validation

- Source builds of capture-protocol, core, viewer, MCP, nodes and capture-viewer: TypeScript project build exit 0.
- Explicit application TypeScript check after local alias repair: exit 0.
- Development/runtime tests: 25 passed, including wrong-checkout and nested-alias regression cases.
- Scene-list and design-selection unit tests: 7 passed. Tests cover error vs empty, malformed/interrupted responses, mounted API URL construction, polygon selection, site containment and cross-algorithm candidate identity.
- Browser fault injection exercised a real `/scenes` page against a local test upstream: 503 -> malformed payload -> empty response via Retry, without modifying any scene database.
- Initial full browser run after workspace relinking: 21 passed. Final run after the four nested dependency aliases were corrected and the type-check bypass removed: **21 passed in 2.1 minutes**, with live VWorld enabled.
- Saved verification scene `1bf925e33e03` reopened using the locally built packages, with four nodes and unchanged hash `ad801dea3665a11d46543e7b553583137669f5204ec4542c1d39669532f26051`. The wall was visually confirmed in 3D; no page errors were recorded. Screenshot: `test-results/local-workspace-scene-3d.png` (ignored local artifact).
- After the final alias repair, a new scene `d0ce3a407e51` was created through UI, a wall drawn in 2D, autosaved (four nodes), reloaded and displayed in 3D/Split. The stored hash remained `d16fd905482f87586a88cec1f209678c44331d3de48ca50347ee235b49f5ffd4` across reload. Only this new temporary scene was deleted through the API afterward (204); the earlier fixture and historical scenes were preserved. Screenshots: `test-results/local-workspace-new-wall-3d.png` and `local-workspace-new-wall-split.png`. Split renders both views; optimal camera framing after resizing was not established.

## Still open

- Original design job/run/cancel/SSE/floor-plan/interactive contracts are not implemented by these changes. The original Django API and the limited native additive execution service differ in algorithms, identity, payload and result contracts. Mapping the latter onto all original UI actions would misrepresent feature parity. Port the original contracts and algorithms into Editor-owned modules and verify real outputs.
- The default Windows scene store and the historical isolated baseline store remain separate and unchanged. No six-scene baseline import, merge, overwrite or deletion was performed. A preservation-aware scene migration is still needed if those historical scenes are to appear in the active store.
- A clean frozen-lockfile install and production Next build remain unverified. The copied dependency set retains previously observed version discrepancies; this fix removes backup-path authority, not that separate dependency audit.
- Mounted URL construction is unit-tested; a full second mounted deployment was not launched. Existing import.meta/BVH warnings and remaining CAD tools still require follow-up.
- Systems, DomainExpert, InteriorDesign and the route ledger's unported Playground/MCP/deployment surfaces remain incomplete.

# Original design workspace migration

The native Next application now mounts the original ARR DesignPage at `/design` and BookLanguagePage at `/design/language`. Their original controls, map, inspector, Pareto, floor-plan viewer, AI collaboration tabs, language network and evidence panels live in `frontend/app/editor/features/design`. Shared map infrastructure remains in `features/land-map`; route entries and explicit API forwarding remain under `app/`.

Editor backend owns the parcel-boundary contract, language catalog snapshot and saved MASS evidence APIs. Parcel lookup uses the native VWorld adapter. Constraint lookup uses native land analysis. The language catalog is imported source material, not proof of execution. Saved images and passports are read from Editor's existing immutable artifact archive, checked against captured byte hashes and paired geometry identity. Eighteen run groups are available locally. Missing evaluation metrics are not invented, and imported records carry `execution_verified: false`.

The collaboration panels use project/run-bound owner records. Removed the fallback transcript and fixed benchmark metrics. A configured topology or empty prompt template is not actual A2A execution. Removed the test-only map replacement. Design-owned map entities and delayed building visibility changes are cleaned up on route exit so the shared VWorld viewer can return to other screens.

## Verification

- TypeScript check passed with the native application configuration.
- Five backend tests passed: boundary/address contract, origin protection, catalog graph references, archive identity and byte corruption rejection.
- Real backend boundary lookup for PNU `1168010100106770000` returned an Editor-owned Polygon and projected area about 497.19 square metres.
- Real archive response returned 18 run groups; native browser loaded archived MASS PNGs without original ARR serving requests.
- Final full browser regression passed 14 cases in 2.4 minutes: original design controls, language tabs, archived MASS images and reload, live VWorld route return, existing law/map/land/agent/dialogue/flow controls and binding isolation.

Runtime: native frontend `127.0.0.1:3003`, Editor backend `127.0.0.1:18449`. Existing dependency recovery includes junctions to a local backup; clean installation reproducibility is not verified. Playwright uses `--tsconfig frontend/app/editor/tests/tsconfig.json` because its resolver cannot resolve the application workspace config through that recovered dependency layout. This does not change application type checking.

## Open work, not completed by moving the screen

1. Original optimization/MAAS creation, streaming, cancellation, floor-plan generation, interactive modifications, constraint visualization fallback and direct agent commands need Editor-owned execution contracts. Preserved buttons do not prove these endpoints work.
2. Creative portfolio, single-execution archives, evaluation ledger, exact AST replay and VLM generation need their original backend behavior migrated. The current archive serves paired saved MASS previews/passports only, with incomplete original metadata.
3. Verify populated regulation overlays, municipal evidence gating, real drawing/parking/3D results and project save/reopen identity. Native additive design execution does not establish original algorithm parity.
4. Continue the full route ledger: Playground, history/comparison, team builder, MCP workbench, gallery, settings and remaining original subroutes. Preserve original nested views and interactions.
5. Shared agents remain under `D:/Data/25_ACE/agents`. Systems, DomainExpert and InteriorDesign remain incomplete; real A2A remediation through final sheet/project evidence remains unverified.

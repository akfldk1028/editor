# Final review of the current Editor integration increment

Scope: the native navigation/specialist/scene increment in `6b70e1fa`, its module
boundaries, and the existing migrated screen regression suite. This review is not
an assertion that every ARR provider has been retired or every specialist is complete.

## Correction

Header and workspace sidebar maintained separate route lists. The sidebar omitted
`/scenes`. A browser regression reproduced the missing destination before the fix.
`components/workspace/product-routes.ts` now owns the 18 destinations and active
route matching. Both views consume it; sidebar translations, labels and icons are
preserved. Scene/project/run detail activation follows the same rule in both views.

Existing navigation tests assumed one matching link in the whole document. The
restored global header makes that assumption invalid. Tests now select the intended
navigation region, preserving their same-document navigation assertions. Builder
unsaved-edit protection is exercised through both header and sidebar.

## Module boundaries

| Location | Responsibility |
| --- | --- |
| `frontend/app/editor/app` | Thin native pages and bounded API forwarding |
| `components/workspace` | Shared shell, navigation metadata, providers and scoped theme |
| `elements/workspace` | Reusable controls without domain execution |
| `features/agent-dialogue` | Project/run clients, review parsing and frozen retry, preview, execution UI |
| `frontend/app/planm` | Reused original PLANM/project/run screens; native route wrappers mount them |
| `infra/services/dwg` | Editor-owned CAD gateway and original workspace composition; CSS is scoped |
| `backend/app/api` | Request/origin/response boundaries, bounded scene-asset delivery |
| `backend/app/modules` | Domain services and persistence |
| `backend/app/adapters` | External owner/provider communication |
| `frontend/elements/nodes/src/site` | Site rendering, including children without a parcel boundary |
| `D:/Data/25_ACE/agents` | Shared domain owners, execution state and memory, outside Editor |

Navigation stays in the application shell. No domain calculations, stores, viewer
dispatch or plugin dependencies were added to core/viewer. The specialist UI remains
split between preview, execution and request/retry logic. There is no new generic
abstraction layer. The original PLANM and CAD compositions remain reused in their
current Editor-owned folders; this is not a claim that all folder consolidation is done.

## Verification

- Product backend: 41 tests passed (scene assets, projects, specialist runs, runs,
  native design API and execution API).
- Owner: 30 specialist/dialogue/Systems-flow tests passed.
- Routing/prefix unit checks: 3 passed, 28 assertions.
- Navigation browser suite: 7 passed on the rebuilt production server, including
  the previously failing sidebar parity check, CAD/PLANM and retained scene GLB.
- `next build --webpack`: exit 0, including TypeScript. Build/service receipt:
  `.superpowers/sdd/actual-project/final-module-production-build-service.json`.
- Initial migration suite: 47 passed, 3 selector failures, 3 opt-in live checks
  skipped. Corrected catalog/deploy/land tests: 9 passed. Live design execution
  passed; two live VWorld checks exposed equivalent selector ambiguity and were
  corrected. Final combined run with `EDITOR_VERIFY_LIVE_VWORLD=1` and
  `EDITOR_VERIFY_LIVE_DESIGN=1`: **53 passed, no skips (1.0m)**. Evidence output:
  `.superpowers/sdd/final-module-all-live`. Together with navigation: 60 browser tests.

CAD and live metric floor-plan screenshots were visually inspected. The law VWorld
return screenshot captured a transient connection warning; a separate browser check
waited for `/api/v1/law/health` 200 and confirmed the warning cleared. Its evidence is
`.superpowers/sdd/final-module-law-ready.png`. Health readiness is not legal acceptance.

Reproduce the browser suites from the repository root with `EDITOR_TEST_URL` set
to `http://127.0.0.1:3003` and the two opt-in variables above set to `1`:

```powershell
node node_modules/@playwright/test/cli.js test --config frontend/app/editor/playwright.product.config.cjs --tsconfig frontend/app/editor/tests/tsconfig.json --reporter=line
node node_modules/@playwright/test/cli.js test --config frontend/app/editor/playwright.migration.config.cjs --tsconfig frontend/app/editor/tests/tsconfig.json --reporter=line
```

The design test creates new bounded verification jobs and cancels its second job;
these are test-parcel algorithm checks, not acceptance of the retained r39 project.

Health probes returned 200 for backend18449 `/api/v1/platform/health`, owner8791
`/editor/v1/health`, CAD4317 `/api/health`, sheet8790 `/`, and the product catalog.
Catalog: 12 available, 2 HTTP-provider-declared, 1 local, 10 not-declared.
Frontend3003 was rebuilt/restarted hidden after command/cwd verification of PID60880;
new production PID33476. Other services were not restarted during this review.

The existing actual run `0c8fd0d96bdc429ca34294e349a77050` was retrieved through
Editor again: blocked, three named communication records (systems/domain_expert/interior).
This is retrieval of the prior actual A2A run, not a new specialist dispatch.

## Open work and ownership

1. Systems: current Program input and use/load/clearance evidence; prior actual
   requirements review consumed frozen Programr2, not current Programr3.
2. DomainExpert: explicit use criteria and domain evidence; no acceptance yet.
3. Interior: real surface/camera/UV/material contracts and source-conditioned image
   generation/application verification; retained mass is not an accepted room.
4. Editor scene owner: automatic framing for offset GLBs and explicit scene-revision
   binding refresh. Saved-camera display is verified; automatic initial framing is open.
5. Coordinator: actual correction -> re-review -> scene/sheet publication -> closure
   against current source guards. No new design publication occurred in this review.
6. Integration owners: remaining old ARR provider dependencies and executable-role
   gaps. Do not remove ARR/AG roots or their retained artifacts on this evidence.

See [actual activation and preserved-source evidence](2026-10-05-native-navigation-and-owner-activation.md).

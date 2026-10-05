# Native workspace structure and remaining route execution

Authority: the user's complete ARR/AG frontend and backend integration request and `native-editor-route-ledger.md`. Preserve all original reachable view elements. Editor is the application; agents remain shared outside it. Work proceeds on the existing authorized branch, preserving prior artifacts.

## Ownership

- `frontend/app/editor/app`: thin Next route composition and explicit HTTP forwarding.
- `frontend/app/editor/elements/workspace`: reusable primitive controls carrying the original lightweight theme. No data fetching, domain imports or routing.
- `frontend/app/editor/components/workspace`: shared composed navigation/layout/providers. No feature-specific execution logic.
- `frontend/app/editor/features/<domain>/{components,hooks,api,model}`: original screens, feature components, state and domain API calls. Split large screens along existing original sections; do not introduce empty abstraction folders.
- `backend/app/api`: request validation, origin boundaries, response mapping.
- `backend/app/modules/<domain>`: domain services and repositories. HTTP-independent persistence and execution.
- `backend/app/adapters`: external provider communication. Original AG/ARR applications are not final runtime dependencies.

## Execution sequence

1. Extract existing workspace primitives and composed shell, updating every consumer. Preserve existing route/theme isolation tests.
2. Port original settings sections, separate environment rows/UI preferences/appearance components, and implement Editor-owned versioned persistence. Verify save/reload, stale-write rejection, language/theme/font behavior and isolation from the main scene UI.
3. Port remaining original team builder, gallery, history, Playground and MCP/deployment surfaces with their nested components. Connect each to explicit Editor-owned contracts; maintain route-level incomplete behavior accounting until actual executions are verified.
4. Migrate original design generation/floor-plan/parking/interactive services with preserved contracts, project identity, cancellation and result artifacts. Do not substitute the limited native additive solver for original algorithms.
5. Exercise original workflows in the browser and through real backend calls, review boundaries, update owner checkpoints and commit validated increments.

Shared interfaces: shell owns theme/language/query providers; settings consumes these providers and must not change document-wide styles. API clients use Next BFF routes; backend owns persistent identity. Saved templates are configuration, not runnable or validated agents until owner execution actually succeeds.

Verification is incremental. Passing view tests does not close an execution row; original disabled controls remain identified as originally disabled. This plan does not narrow the outstanding full integration scope.

# Final Modular Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give DWG Intelligence one public contract source, reload-safe provider sessions, functional layer visibility, a small composition-only `App`, and feature-owned styles without changing the verified UI or OAuth behavior.

**Architecture:** A local `@dwg/contracts` package owns public CAD and provider DTOs while agent-only process contracts remain local. React composition delegates workspace interactions to one hook and provider session state to an injected storage adapter. Feature components import their own CSS; only tokens and cross-feature layout remain in the app stylesheet.

**Tech Stack:** TypeScript 5.8, Node test runner with `tsx`, React 19, Vite 8, Playwright 1.62, npm local file packages.

## Global Constraints

- Preserve the uncommitted attachment work in `ChatComposer.tsx`, `styles.css`, and `workspace.spec.ts`.
- Preserve existing gateway JSON shapes, CAD evidence rules, and OAuth-only authentication.
- Do not edit or commit `.idea/*`.
- Keep the white desktop CAD layout pixel-identical at 1280×800, 1440×900, and 1920×1080.
- Use tests before behavior changes and commit each independently testable task.

---

### Task 1: Shared public contracts package

**Files:**
- Create: `packages/contracts/package.json`
- Create: `packages/contracts/src/cad.ts`
- Create: `packages/contracts/src/provider.ts`
- Create: `packages/contracts/src/index.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `agent/src/domain/cad-index/types.ts`
- Modify: `agent/src/providers/contracts.ts`
- Modify: `agent/src/http/providerGateway.ts`
- Modify: `frontend/src/shared/types.ts`
- Modify: `frontend/src/shared/api/providerGatewayClient.ts`
- Test: `agent/tests/contracts/public-contracts.test.ts`

**Interfaces:**
- Produces: `CadEntityIndex`, `CadEntityIndexItem`, `ProviderId`, `ProviderStatus`, `ProviderChatPayload`, `ProviderChatResult`, `isProviderChatPayload`, and `isProviderSessionId` from `@dwg/contracts`.
- Consumes: no application modules; only standard TypeScript/JavaScript.

- [ ] **Step 1: Write the failing public-contract validator test**

```ts
import assert from "node:assert/strict";
import test from "node:test";

import {
  isProviderChatPayload,
  isProviderSessionId
} from "@dwg/contracts";

test("public provider contract accepts only bounded UUID sessions", () => {
  assert.equal(isProviderSessionId("019fa2d0-2534-7691-b50e-875340b7e3a5"), true);
  assert.equal(isProviderSessionId("--last"), false);
  assert.equal(isProviderChatPayload({
    provider: "codex",
    drawingPath: "drawing.dwg",
    message: "도면 설명",
    sessionId: "019fa2d0-2534-7691-b50e-875340b7e3a5"
  }), true);
  assert.equal(isProviderChatPayload({
    provider: "other",
    drawingPath: "drawing.dwg",
    message: "도면 설명"
  }), false);
});
```

- [ ] **Step 2: Run the test and verify the package is missing**

Run: `node --import tsx --test agent/tests/contracts/public-contracts.test.ts`

Expected: FAIL because `@dwg/contracts` is not installed.

- [ ] **Step 3: Create the local package and install it in both consumers**

`packages/contracts/package.json`:

```json
{
  "name": "@dwg/contracts",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts"
  }
}
```

Add `"@dwg/contracts": "file:packages/contracts"` to the root dependencies and
`"@dwg/contracts": "file:../packages/contracts"` to frontend dependencies.
Run `npm install` at the repository root and in `frontend`.

- [ ] **Step 4: Implement public DTOs and runtime guards**

`packages/contracts/src/provider.ts` must export:

```ts
export type ProviderId = "codex" | "claude";

export interface ProviderChatPayload {
  provider: ProviderId;
  drawingPath: string;
  message: string;
  sessionId?: string | null;
}

export function isProviderSessionId(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
```

`isProviderChatPayload` must enforce the two provider IDs, non-empty drawing
path/message, and absent/null/UUID session ID. Move complete CAD index DTOs from
`agent/src/domain/cad-index/types.ts` into `cad.ts`. Re-export them through the
existing agent domain file so internal imports remain stable, while frontend
imports public CAD/provider types directly from `@dwg/contracts`.

- [ ] **Step 5: Replace gateway-local validation with the shared guard**

Use `isProviderChatPayload(body)` in `providerGateway.ts`. Keep the existing
`GroundedChatRequest` alias compatible with `ProviderChatPayload`; keep
`AbortSignal`, `ChatProvider`, and process runner interfaces in the agent.

- [ ] **Step 6: Run contract, agent, and frontend compilation**

Run:

```powershell
node --import tsx --test agent/tests/contracts/public-contracts.test.ts
npm test
Set-Location frontend
npm run typecheck
npm run build
```

Expected: all commands PASS and no duplicate `ProviderStatus` or public
`CadEntityIndex` interface remains in either consumer.

- [ ] **Step 7: Commit**

```powershell
git add packages package.json package-lock.json frontend/package.json frontend/package-lock.json agent/src agent/tests/contracts frontend/src/shared
git commit -m "refactor: centralize public DWG contracts"
```

---

### Task 2: Provider session storage boundary

**Files:**
- Create: `frontend/src/features/agent-chat/providerSessionStore.ts`
- Create: `frontend/tests/unit/provider-session-store.test.ts`
- Modify: `package.json`
- Modify: `frontend/src/features/agent-chat/useProviderChat.ts`
- Modify: `frontend/tests/e2e/workspace.spec.ts`

**Interfaces:**
- Consumes: `ProviderId` and `isProviderSessionId` from `@dwg/contracts`.
- Produces: `ProviderSessionStore`, `createProviderSessionStore(storage)`, and `browserProviderSessionStore`.

- [ ] **Step 1: Write failing pure storage tests**

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { createProviderSessionStore } from "../../src/features/agent-chat/providerSessionStore.js";

class MemoryStorage {
  value: string | null = null;
  getItem() { return this.value; }
  setItem(_key: string, value: string) { this.value = value; }
  removeItem() { this.value = null; }
}

test("session store persists and isolates provider sessions", () => {
  const storage = new MemoryStorage();
  const store = createProviderSessionStore(storage);
  store.set("codex", "019fa2d0-2534-7691-b50e-875340b7e3a5");
  assert.equal(store.get("codex"), "019fa2d0-2534-7691-b50e-875340b7e3a5");
  assert.equal(store.get("claude"), null);
});

test("session store ignores malformed data and clears all providers", () => {
  const storage = new MemoryStorage();
  storage.value = '{"codex":"--last"}';
  const store = createProviderSessionStore(storage);
  assert.equal(store.get("codex"), null);
  store.set("claude", "98d84d53-7861-4c73-a789-d6c8f5490966");
  store.clear();
  assert.equal(store.get("claude"), null);
});
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `node --import tsx --test frontend/tests/unit/provider-session-store.test.ts`

Expected: FAIL because `providerSessionStore.ts` does not exist.

- [ ] **Step 3: Implement the storage adapter**

Use one key, `dwg-intelligence.provider-sessions.v1`. Catch `getItem`,
`setItem`, JSON parse, and `removeItem` errors. Read and validate every value
through `isProviderSessionId`; never throw storage failures into React.
Update the root test script so the default suite includes both trees:

```json
"test": "node --import tsx --test \"agent/**/*.test.ts\" \"frontend/tests/unit/**/*.test.ts\""
```

- [ ] **Step 4: Inject storage into `useProviderChat`**

Change the signature to:

```ts
export function useProviderChat(
  sessionStore: ProviderSessionStore = browserProviderSessionStore
)
```

Replace the in-memory `sessionIds` record with `get`, `set`, and `clear`.
Preserve cancellation generation checks and the existing `reset` behavior.

- [ ] **Step 5: Add a failing Playwright reload continuation assertion**

In the OAuth provider test, return a valid Claude UUID, reload after the first
response, select Claude again, submit the follow-up, and assert the second
payload contains the first UUID. This must fail before the storage adapter is
wired and pass afterward.

- [ ] **Step 6: Run unit and browser tests**

Run:

```powershell
node --import tsx --test frontend/tests/unit/provider-session-store.test.ts
Set-Location frontend
npm run test:e2e -- --grep "OAuth provider|cancels"
```

Expected: storage tests and both Playwright cases PASS.

- [ ] **Step 7: Commit**

```powershell
git add package.json frontend/src/features/agent-chat/providerSessionStore.ts frontend/src/features/agent-chat/useProviderChat.ts frontend/tests
git commit -m "feat: persist provider sessions per browser tab"
```

---

### Task 3: Functional layer visibility

**Files:**
- Create: `frontend/src/features/drawing-explorer/useLayerVisibility.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/features/drawing-explorer/DrawingExplorer.tsx`
- Modify: `frontend/src/features/cad-viewer/CadViewer.tsx`
- Modify: `frontend/src/app/styles.css`
- Modify: `frontend/tests/e2e/workspace.spec.ts`

**Interfaces:**
- Consumes: layer names from `CadEntityIndex`.
- Produces: `hiddenLayers: ReadonlySet<string>` and `toggleLayer(name: string): void`.

- [ ] **Step 1: Write the failing layer-eye browser test**

Extend the workspace-controls Playwright test:

```ts
const zeroLayerEye = page.getByRole("button", { name: "0 레이어 숨기기" });
await expect(page.locator(".cad-entity")).toHaveCount(22);
await zeroLayerEye.click();
await expect(page.locator(".cad-entity")).toHaveCount(0);
await expect(page.getByRole("button", { name: "0 레이어 표시" }))
  .toHaveAttribute("aria-pressed", "false");
await page.getByRole("button", { name: "0 레이어 표시" }).click();
await expect(page.locator(".cad-entity")).toHaveCount(22);
```

- [ ] **Step 2: Run the test and verify the eye is inert**

Run:

```powershell
Set-Location frontend
npm run test:e2e -- --grep "workspace controls"
```

Expected: FAIL because there is no accessible layer visibility button and the
viewer still renders 22 entities.

- [ ] **Step 3: Implement the visibility hook**

`useLayerVisibility(layerNames)` keeps a `Set<string>` of hidden names, removes
stale names when the drawing changes, and returns a stable toggle callback.
The hook never mutates the CAD index.

- [ ] **Step 4: Wire explorer and viewer**

Render each eye as:

```tsx
<button
  aria-label={`${displayName} 레이어 ${hidden ? "표시" : "숨기기"}`}
  aria-pressed={!hidden}
  onClick={() => onToggleLayer(layer.name)}
>
  {hidden ? <EyeOff size={13} /> : <Eye size={13} />}
</button>
```

Pass `hiddenLayers` into `CadViewer` and filter before mapping:

```tsx
{index.entities
  .filter((entity) => !hiddenLayers.has(entity.layer))
  .map((entity) => <EntityShape key={entity.id} entity={entity} highlighted={...} />)}
```

Keep the viewer status total as the indexed count; layer visibility is a view
filter and must not rewrite index summary data.

- [ ] **Step 5: Run focused and full visual tests**

Run:

```powershell
Set-Location frontend
npm run typecheck
npm run test:e2e -- --grep "workspace controls"
npm run test:e2e
```

Expected: the layer toggle test and every exact screenshot PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/app/App.tsx frontend/src/features/drawing-explorer frontend/src/features/cad-viewer frontend/src/app/styles.css frontend/tests/e2e/workspace.spec.ts
git commit -m "feat: connect layer visibility to CAD rendering"
```

---

### Task 4: Workspace-control state extraction

**Files:**
- Create: `frontend/src/app/useWorkspaceControls.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/tests/e2e/workspace.spec.ts`

**Interfaces:**
- Produces: `useWorkspaceControls()` with state, setters, `searchRef`, and `topActionsRef`.
- Consumes: browser keyboard and pointer events only.

- [ ] **Step 1: Extend the existing controls characterization test**

Add assertions that `Control+K` focuses “전체 도면 검색”, Escape closes the
settings dialog, and clicking outside closes notifications. Run the test before
refactoring and confirm these behaviors pass against the current implementation.

- [ ] **Step 2: Extract the hook without changing returned behavior**

Move `agentPanelOpen`, `activePopover`, `gridVisible`, `searchQuery`, both refs,
and both effects into `useWorkspaceControls.ts`. Return named values:

```ts
return {
  agentPanelOpen,
  activePopover,
  gridVisible,
  searchQuery,
  searchRef,
  topActionsRef,
  setActivePopover,
  setAgentPanelOpen,
  setGridVisible,
  setSearchQuery
};
```

Use `const controls = useWorkspaceControls()` in `App.tsx`; retain scenario,
selected handle, drawing loading, and chat composition in `App`.

- [ ] **Step 3: Verify composition size and behavior**

Run:

```powershell
Set-Location frontend
npm run typecheck
npm run test:e2e -- --grep "workspace controls"
```

Expected: PASS, and `App.tsx` contains no `addEventListener`, `useEffect`,
`useRef`, `KeyboardEvent`, or `PointerEvent`.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/app/App.tsx frontend/src/app/useWorkspaceControls.ts frontend/tests/e2e/workspace.spec.ts
git commit -m "refactor: isolate workspace control state"
```

---

### Task 5: Feature-owned styles

**Files:**
- Create: `frontend/src/features/drawing-explorer/styles.css`
- Create: `frontend/src/features/cad-viewer/styles.css`
- Create: `frontend/src/features/agent-chat/styles.css`
- Create: `frontend/src/features/inspection-results/styles.css`
- Modify: `frontend/src/app/styles.css`
- Modify: `frontend/src/features/drawing-explorer/DrawingExplorer.tsx`
- Modify: `frontend/src/features/cad-viewer/CadViewer.tsx`
- Modify: `frontend/src/features/agent-chat/AgentWorkspace.tsx`
- Modify: `frontend/src/features/inspection-results/InspectionDock.tsx`

**Interfaces:**
- Consumes: global CSS variables declared in `app/styles.css`.
- Produces: feature-local selector ownership with unchanged class names.

- [ ] **Step 1: Establish the exact visual baseline**

Run:

```powershell
Set-Location frontend
npm run test:e2e
```

Expected: all tests and exact screenshots PASS before moving declarations.

- [ ] **Step 2: Move drawing, viewer, agent, and dock selectors**

Move declarations byte-for-byte by selector responsibility. Import each file
from its feature entry component:

```ts
import "./styles.css";
```

Keep `.workspace-grid`, `.agent-panel-hidden`, `.panel`, grid placement rules,
tokens, reset, topbar, scenario bar, load states, animation keyframes, and media
grid overrides in the app stylesheet. Preserve the current uncommitted
attachment selectors and hidden-file-input implementation.

- [ ] **Step 3: Verify styles and exact screenshots**

Run:

```powershell
Set-Location frontend
npm run typecheck
npm run build
npm run test:e2e
```

Expected: all tests PASS with `maxDiffPixelRatio: 0`; no snapshot update is
allowed for this task.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/app/styles.css frontend/src/features
git commit -m "refactor: colocate feature styles"
```

---

### Task 6: Architecture documentation and final verification

**Files:**
- Modify: `docs/architecture/module-boundaries.md`
- Modify: `docs/architecture/oauth-cli-providers.md`
- Modify: `tests/visual/artifacts/oauth-codex-persistent-browser-e2e.png` only if a new live run intentionally replaces it

**Interfaces:**
- Consumes: completed package, hook, storage, and CSS boundaries.
- Produces: final module tree and verified runtime evidence.

- [ ] **Step 1: Update architecture documentation**

Document `packages/contracts`, storage lifetime, dependency directions, feature
CSS ownership, and the rule that transport/process types never enter the public
contract package.

- [ ] **Step 2: Run the full automated suite**

Run:

```powershell
npm test
dotnet test backend/tests/DwgIntelligence.DwgParser.Tests/DwgIntelligence.DwgParser.Tests.csproj --nologo
Set-Location frontend
npm run typecheck
npm run build
npm run test:e2e
```

Expected: every Node, .NET, type, build, browser, layout, and exact PNG check
passes.

- [ ] **Step 3: Run both real OAuth two-turn smoke tests**

Run from the repository root:

```powershell
npm run providers:smoke -- codex
npm run providers:smoke -- claude
```

Expected: each provider is authenticated through its existing subscription,
returns handle evidence, and keeps one session ID across both turns.

- [ ] **Step 4: Restart and inspect the local runtime**

Restart the loopback gateway and Vite server from the committed source. Verify
`/api/health`, provider status, a meaningful browser snapshot, zero console
errors, no error overlay, and the 1440×900 persistent-session PNG.

- [ ] **Step 5: Commit**

```powershell
git add docs tests/visual/artifacts
git commit -m "docs: finalize modular runtime boundaries"
```

- [ ] **Step 6: Confirm the final worktree**

Run:

```powershell
git status --short
git log -6 --oneline
```

Expected: only the user's `.idea/*` files remain untracked and no product file
is modified.

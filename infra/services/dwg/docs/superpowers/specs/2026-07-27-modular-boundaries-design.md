# DWG Intelligence Modular Boundaries Design

## Goal

Make the current DWG workspace independently understandable and replaceable at
four boundaries without changing its UI, OAuth behavior, CAD evidence rules, or
existing gateway payloads.

## Scope

This pass covers:

1. one shared TypeScript source for public CAD and provider DTOs;
2. workspace-control state extraction from `App.tsx`;
3. provider-session persistence behind an injected storage boundary;
4. functional per-layer visibility shared by the explorer and viewer;
5. feature-owned CSS without pixel changes.

The current attachment behavior in `ChatComposer.tsx` is preserved. Streaming,
server-side conversation storage, Codex app-server adoption, and new CAD
features are outside this pass.

## Architecture

### Shared contracts

Create `packages/contracts/src/` as the single source for types that cross a
runtime boundary:

- `cad.ts`: `PointBox`, `CadEntity`, `CadIndex`, and related DTOs;
- `provider.ts`: `ProviderId`, `ProviderStatus`, public chat request, and chat
  result;
- `index.ts`: public exports only.

Agent-only contracts such as `ChatProvider`, `ProcessRunner`, `AbortSignal`,
system prompts, and subprocess specifications stay under `agent/src/providers`.
Frontend-only scenario and view-state types stay under `frontend/src`.

Both applications consume the shared source through a local
`@dwg/contracts` package dependency. The package contains no React, Node, CLI,
HTTP, parser, or provider implementation.

### Workspace controls

Move global UI coordination from `App.tsx` into
`frontend/src/app/useWorkspaceControls.ts`. The hook owns:

- agent-panel visibility;
- notification/settings popover state;
- grid visibility;
- global drawing search;
- keyboard focus and Escape handling;
- the refs required by those interactions.

`App.tsx` remains the composition root: it loads the drawing and chat features,
selects the current entity, and wires feature outputs to layout components.

### Layer visibility

Create `frontend/src/features/drawing-explorer/useLayerVisibility.ts` as the
owner of visible/hidden layer state for the loaded index. `DrawingExplorer`
receives the visibility state and toggle callback; it does not own a second
copy. `CadViewer` receives hidden layer names and excludes matching entities
from SVG rendering.

Each layer eye is a real button with `aria-pressed` and a state-specific Korean
label. Clicking it hides every entity on that layer without changing the CAD
index, finding evidence, or stable handles. Clicking it again restores the
same entities. Loading a different drawing removes hidden names that do not
exist in the new index.

### Provider session storage

Create `frontend/src/features/agent-chat/providerSessionStore.ts` with a small
interface:

```ts
interface ProviderSessionStore {
  get(provider: ProviderId): string | null;
  set(provider: ProviderId, sessionId: string): void;
  clear(): void;
}
```

The browser implementation uses `sessionStorage`, one namespaced JSON record,
strictly accepts known providers and UUID session IDs, and treats malformed or
unavailable storage as empty. `useProviderChat` receives the store through an
optional dependency so storage behavior can be tested without React or a real
browser.

First responses save their provider session. Follow-up requests reuse only the
selected provider's session. “새 대화” clears both providers. Reloading the page
within the same browser tab restores sessions; closing the tab naturally
removes them.

### Feature-owned styles

Keep tokens, resets, top-level shell, top bar, scenario bar, loading states, and
responsive grid rules in `app/styles.css`.

Move feature selectors without changing declaration values:

- drawing explorer selectors to `features/drawing-explorer/styles.css`;
- CAD viewer selectors to `features/cad-viewer/styles.css`;
- agent workspace and composer selectors to
  `features/agent-chat/styles.css`;
- inspection dock selectors to `features/inspection-results/styles.css`.

Each feature entry component imports its own stylesheet. Selectors that affect
multiple grid children stay in the app stylesheet.

## Data flow

```text
App
  -> useWorkspaceControls
  -> useLayerVisibility
  -> drawing/chat feature hooks
  -> feature components

frontend shared API
  -> @dwg/contracts
  -> loopback gateway
  -> application chat service
  -> provider adapter

useProviderChat
  <-> ProviderSessionStore
  -> shared API
```

Imports may point from composition to features and from features to shared
contracts. The contracts package never imports an application module.

## Error handling

- Invalid persisted JSON, unknown provider keys, non-UUID values, and storage
  access failures return an empty session state.
- A failed provider request never overwrites a stored session.
- Cancellation keeps the currently stored valid session but ignores the
  cancelled response.
- Layer visibility changes only rendering state; the immutable CAD index and
  evidence results remain available.
- Shared public request validation remains in the loopback gateway.
- CSS movement must not introduce missing assets, console errors, overflow, or
  screenshot differences.

## Verification

- Unit tests prove session save, provider isolation, invalid-data recovery, and
  clear behavior.
- Contract compilation proves frontend and agent consumers use the shared
  package without duplicate public DTO declarations.
- Playwright proves a layer eye hides and restores exactly the entities owned
  by that layer.
- Existing provider, gateway, orchestration, MCP, and real DWG tests remain
  green.
- Playwright adds a reload-continuation scenario and retains cancellation,
  workspace controls, 1280/1440/1920 fit checks, and exact screenshots.
- Frontend typecheck and production build must pass.
- Real Codex and Claude OAuth smoke tests remain explicit final checks rather
  than default unit tests.

## Completion criteria

- `App.tsx` contains no keyboard or popover event-listener implementation.
- Frontend and agent public CAD/provider DTOs come from `@dwg/contracts`.
- Provider sessions survive a same-tab reload and remain isolated by provider.
- Every layer eye controls the visibility of its indexed entities in the CAD
  viewer and exposes its current state accessibly.
- Every feature owns its CSS, with cross-feature grid rules remaining in app.
- All automated tests, exact PNG comparisons, and both real OAuth two-turn
  smoke tests pass.

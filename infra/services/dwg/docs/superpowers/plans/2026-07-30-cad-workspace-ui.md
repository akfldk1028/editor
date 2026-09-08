# CAD Workspace Navigation and Change Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three-panel workspace readable at project scale and expose Skill and change-review workflows without coupling React to CAD internals.

**Architecture:** The left panel becomes a resizable tabbed navigator; the right artifact panel gains Changes and Export feature components. All network access remains in `shared/api`.

**Tech Stack:** React 19, TypeScript 5.8, Vite 8, Playwright 1.62, existing CSS and preference store.

## Global Constraints

- Preserve a minimum 500 px conversation width.
- Sidebar width is 280-420 px and persists locally.
- Artifact width remains independently resizable.
- Components call typed API clients rather than `fetch`.
- Light and dark themes remain supported.
- Every visual state receives a Playwright assertion before PNG capture.

---

### Task 1: Add Sidebar Tab and Width Preferences

**Files:**
- Modify: `apps/workspace/src/app/workspacePreferences.ts`
- Modify: `apps/workspace/src/app/useWorkspacePreferences.ts`
- Modify: `apps/workspace/src/app/useWorkspaceControls.ts`
- Modify: `apps/workspace/tests/unit/workspace-preferences.test.ts`
- Modify: `apps/workspace/tests/e2e/workspace-refinement.spec.ts`

**Interfaces:**
- Produces:

```ts
type SidebarTab = "project" | "sessions" | "skills";
interface WorkspacePreferences {
  theme: ThemePreference;
  artifactWidth: number;
  sidebarWidth: number;
  sidebarTab: SidebarTab;
  sidebarSections: {
    project: boolean;
    drawing: boolean;
    sessions: boolean;
  };
}
```

- [ ] **Step 1: Write migration and clamp tests**

Assert legacy v1 storage loads with `sidebarWidth: 320` and
`sidebarTab: "project"`. Clamp persisted width to 280-420 and reject unknown
tabs.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test apps/workspace/tests/unit/workspace-preferences.test.ts`

Expected: FAIL because sidebar preferences are absent.

- [ ] **Step 3: Implement preference migration and controls**

Add `setSidebarWidth`, `setSidebarTab`, keyboard resize by 16 px, and pointer
resize. Persist under a new `dwg.workspace-preferences.v2` key while reading
v1 once for migration.

- [ ] **Step 4: Run unit and focused browser tests**

Run: `node --import tsx --test apps/workspace/tests/unit/workspace-preferences.test.ts && npm run test:e2e -- workspace-refinement.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/workspace/src/app/workspacePreferences.ts apps/workspace/src/app/useWorkspacePreferences.ts apps/workspace/src/app/useWorkspaceControls.ts apps/workspace/tests/unit/workspace-preferences.test.ts apps/workspace/tests/e2e/workspace-refinement.spec.ts
git commit -m "feat: persist readable sidebar layout"
```

### Task 2: Split Project, Sessions, and Skills Navigation

**Files:**
- Modify: `apps/workspace/src/app/WorkspaceSidebar.tsx`
- Create: `apps/workspace/src/features/project-navigation/ProjectNavigator.tsx`
- Create: `apps/workspace/src/features/project-navigation/styles.css`
- Create: `apps/workspace/src/features/session-navigation/SessionNavigator.tsx`
- Create: `apps/workspace/src/features/session-navigation/styles.css`
- Create: `apps/workspace/src/features/skill-navigation/SkillNavigator.tsx`
- Create: `apps/workspace/src/features/skill-navigation/styles.css`
- Create: `apps/workspace/src/shared/api/skillClient.ts`
- Modify: `apps/workspace/src/app/App.tsx`
- Modify: `apps/workspace/src/app/styles.css`
- Create: `apps/workspace/tests/e2e/sidebar-navigation.spec.ts`

**Interfaces:**
- `SkillNavigator` imports `SkillListItem` and `SkillPermission` from the only
  browser/runtime shared TypeScript package, `@dwg/contracts`, and consumes:

```ts
interface SkillListItem {
  id: string;
  version: string;
  compatible: boolean;
  permissions: SkillPermission[];
  recentStatus: "idle" | "running" | "passed" | "failed";
}
```

Do not add a browser dependency on `@dwg/skill-contracts` and do not redeclare
these DTOs in app source.

- [ ] **Step 1: Write the sidebar hierarchy browser test**

Assert tab keyboard navigation, sticky search, drawing-to-layout-to-layer hierarchy,
aligned eye/lock/color/count fields, long-name tooltip, session grouping, skill
compatibility, and independent scrolling.

- [ ] **Step 2: Run test and verify RED**

Run: `npm run test:e2e -- sidebar-navigation.spec.ts`

Expected: FAIL because tabbed navigation is absent.

- [ ] **Step 3: Implement focused feature components**

`WorkspaceSidebar` owns only tab selection and composition. Project,
session, and skill state stays within their owning feature and typed props.

- [ ] **Step 4: Run focused browser and boundary tests**

Run: `npm run test:e2e -- sidebar-navigation.spec.ts && node --import tsx --test modules/cad-runtime/tests/architecture/module-boundaries.test.ts`

Expected: PASS with zero cross-feature imports.

- [ ] **Step 5: Commit**

```powershell
git add apps/workspace/src/app/WorkspaceSidebar.tsx apps/workspace/src/app/App.tsx apps/workspace/src/app/styles.css apps/workspace/src/features/project-navigation/ProjectNavigator.tsx apps/workspace/src/features/project-navigation/styles.css apps/workspace/src/features/session-navigation/SessionNavigator.tsx apps/workspace/src/features/session-navigation/styles.css apps/workspace/src/features/skill-navigation/SkillNavigator.tsx apps/workspace/src/features/skill-navigation/styles.css apps/workspace/src/shared/api/skillClient.ts apps/workspace/tests/e2e/sidebar-navigation.spec.ts
git commit -m "feat: add project session and skill navigation"
```

### Task 3: Add Typed Change Review Feature

**Files:**
- Create: `apps/workspace/src/features/change-review/ChangeReview.tsx`
- Create: `apps/workspace/src/features/change-review/useChangeReview.ts`
- Create: `apps/workspace/src/features/change-review/styles.css`
- Create: `apps/workspace/src/shared/api/editClient.ts`
- Modify: `apps/workspace/src/app/CadArtifactPanel.tsx`
- Modify: `apps/workspace/src/app/App.tsx`
- Create: `apps/workspace/tests/e2e/change-review.spec.ts`

**Interfaces:**
- Imports `CadEditBatch`, `CadEditPreviewResponse`, and
  `CadEditApplyResponse` from `@dwg/contracts`; `editClient` produces UI
  actions:

```ts
preview(batch: CadEditBatch): Promise<CadEditPreviewResponse>;
apply(previewId: string, expectedRevision: number): Promise<CadEditApplyResponse>;
undo(expectedRevision: number): Promise<CadEditApplyResponse>;
redo(expectedRevision: number): Promise<CadEditApplyResponse>;
```

- [ ] **Step 1: Write preview and approval tests**

Assert Changes tab shows grouped before/after evidence, warnings, revision,
approve, reject, undo, and redo. Assert reject causes no apply call and stale
revision renders a re-preview action.

- [ ] **Step 2: Run test and verify RED**

Run: `npm run test:e2e -- change-review.spec.ts`

Expected: FAIL because Changes UI is absent.

- [ ] **Step 3: Implement API client, hook, and view**

Render bounded values only. Use handle/type/layer/bbox labels and never render
raw provider responses as change evidence.

- [ ] **Step 4: Run focused tests**

Run: `npm run test:e2e -- change-review.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/workspace/src/features/change-review/ChangeReview.tsx apps/workspace/src/features/change-review/useChangeReview.ts apps/workspace/src/features/change-review/styles.css apps/workspace/src/shared/api/editClient.ts apps/workspace/src/app/CadArtifactPanel.tsx apps/workspace/src/app/App.tsx apps/workspace/tests/e2e/change-review.spec.ts
git commit -m "feat: review and approve CAD changes"
```

### Task 4: Add Export Surface and Responsive Layout

**Files:**
- Create: `apps/workspace/src/features/export/ExportPanel.tsx`
- Create: `apps/workspace/src/features/export/useExport.ts`
- Create: `apps/workspace/src/features/export/styles.css`
- Create: `apps/workspace/src/shared/api/exportClient.ts`
- Create: `packages/contracts/src/export.ts`
- Modify: `packages/contracts/src/index.ts`
- Create: `modules/cad-runtime/src/http/exportCapabilityGateway.ts`
- Modify: `modules/cad-runtime/src/http/gateway.ts`
- Create: `modules/cad-runtime/tests/http/export-capability-gateway.test.ts`
- Modify: `apps/workspace/src/app/CadArtifactPanel.tsx`
- Modify: `apps/workspace/src/app/styles.css`
- Modify: `apps/workspace/tests/e2e/three-panel-workspace.spec.ts`
- Create: `apps/workspace/tests/e2e/export-panel.spec.ts`
- Modify: `apps/workspace/tests/docs/route-captures.spec.ts`
- Modify: `docs/ui-captures/00-overview.png`
- Create: `docs/ui-captures/skill-selected.png`
- Create: `docs/ui-captures/change-preview.png`
- Create: `docs/ui-captures/sidebar-narrow.png`
- Create: `docs/ui-captures/dark-theme.png`

**Interfaces:**
- Export panel distinguishes:

```ts
type ReportFormat = "json" | "csv" | "pdf" | "svg";
type DrawingFormat = "dxf" | "dwg";
interface ExportCapabilityItem {
  format: ReportFormat | DrawingFormat;
  kind: "report" | "drawing";
  available: boolean;
  reason: string | null;
}
```

The real loopback endpoint `GET /api/export/capabilities` returns every format
as unavailable with reason `EXPORT_MODULE_NOT_INSTALLED` in this UI-shell
phase. The Save and Export plan replaces availability from registered
capabilities; UI tests do not mock this endpoint.

- [ ] **Step 1: Write export-label and responsive tests**

Assert report download is never labeled drawing download, Save As requires a
destination and validation status, 1280x800 keeps 500 px conversation, narrow
screens use sidebar and artifact overlays, and both resizers support keyboard.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --import tsx --test modules/cad-runtime/tests/http/export-capability-gateway.test.ts && npm run test:e2e -- export-panel.spec.ts three-panel-workspace.spec.ts`

Expected: FAIL because Export UI and new sidebar width are absent.

- [ ] **Step 3: Implement export UI and layout constraints**

Disabled report and drawing formats show the real endpoint's explicit
capability reason. The UI does not simulate a successful file write. Export
`createExportCapabilityRoutes(...)` from `exportCapabilityGateway.ts`, import
it from the existing `gateway.ts`, and mount it on the same loopback server
before the fallback 404 handler. The HTTP and Playwright tests must use that
assembled server.

- [ ] **Step 4: Run the full visual loop**

Run: `npm run verify:all && npm run capture:docs`

Expected: PASS. Inspect `docs/ui-captures/00-overview.png` for Project,
Sessions, Skills, Changes, Export, sidebar widths, hierarchy, overlap, and
theme contrast.
The capture spec must also retain `skill-selected.png`,
`change-preview.png`, `sidebar-narrow.png`, and `dark-theme.png`; each state is
reached through visible controls and asserted before capture.

- [ ] **Step 5: Commit**

```powershell
git add apps/workspace/src/features/export/ExportPanel.tsx apps/workspace/src/features/export/useExport.ts apps/workspace/src/features/export/styles.css apps/workspace/src/shared/api/exportClient.ts apps/workspace/src/app/CadArtifactPanel.tsx apps/workspace/src/app/styles.css apps/workspace/tests/e2e/three-panel-workspace.spec.ts apps/workspace/tests/e2e/export-panel.spec.ts apps/workspace/tests/docs/route-captures.spec.ts packages/contracts/src/export.ts packages/contracts/src/index.ts modules/cad-runtime/src/http/exportCapabilityGateway.ts modules/cad-runtime/src/http/gateway.ts modules/cad-runtime/tests/http/export-capability-gateway.test.ts docs/ui-captures/00-overview.png docs/ui-captures/skill-selected.png docs/ui-captures/change-preview.png docs/ui-captures/sidebar-narrow.png docs/ui-captures/dark-theme.png
git commit -m "feat: complete skill-first workspace layout"
```

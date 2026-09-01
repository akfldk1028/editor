# DWG Intelligence Frontend Workspace Plan

**Goal:** Build and visually verify the desktop CAD intelligence workspace against real DWG-derived fixture data.

**Architecture:** A React/Vite app uses feature folders for drawing navigation, an SVG CAD viewport, agent activity, findings, and evidence. The frontend reads a committed `cad-index/v0.1` fixture derived from the unchanged real DWG sample. Playwright drives deterministic UI states against the real dev server and stores PNG evidence at three desktop sizes.

**Tech Stack:** React 19, TypeScript, Vite 8, Lucide React, Playwright 1.62.

## Task 1: Scaffold and fixture contract

- Create `frontend/` package, Vite config, TypeScript config, app entry, and feature folders.
- Generate `frontend/public/data/export_sample.index.json` from the local ACadSharp CLI.
- Add a fixture-integrity test asserting DWG source kind, schema version, and 22 indexed entities.
- Keep frontend dependencies isolated under `frontend/node_modules`.

## Task 2: Desktop workspace and CAD viewport

- Build the compact top command bar, left drawing explorer, central SVG viewer, right agent workspace, and bottom result/evidence dock.
- Render actual entity bounds from the DWG index with type-aware SVG primitives and a nonblank-canvas assertion target.
- Use only a white/light neutral palette, restrained cyan selection color, compact controls, and Lucide icons.
- Preserve center-viewer priority at 1280x800 through 1920x1080.

## Task 3: Deterministic interaction loop

- Implement agent tabs and explicit identities for all seven configured specialists.
- Add scenario controls for layer inspection, finding selection, tool activity, unsupported warnings, and reset.
- Selecting a finding highlights its stable handle in the viewer and exposes handle/layer/type/bbox evidence.
- Add component tests for scenario transitions and selected evidence.

## Task 4: Playwright semantic and PNG verification

- Configure Playwright with a managed Vite dev server, disabled animations, and stable screenshots.
- Verify empty, loaded, tool-running, highlighted, evidence-selected, and warning states.
- Capture full-page PNGs at 1280x800, 1440x900, and 1920x1080 plus focused viewer and agent-panel PNGs.
- Inspect every produced PNG directly; fix clipping, overlap, blank drawing, weak selection, or poor space allocation and repeat.
- Run frontend typecheck/build/test/e2e plus root Node/.NET regressions before merging.

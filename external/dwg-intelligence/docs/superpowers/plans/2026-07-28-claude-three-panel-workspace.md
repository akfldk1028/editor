# Claude-style Three-panel Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Deliver the approved Claude Artifact-style DWG workspace with real
local sessions, persistent theme preferences, and a resizable CAD panel.

**Architecture:** Keep backend contracts intact. Add focused frontend stores
and hooks, then compose existing drawing, inspection, and provider features
through a new three-panel app shell.

**Tech stack:** React 19, TypeScript, CSS Grid, browser storage, Playwright.

## Global constraints

- TDD for behavior changes.
- Preserve existing CAD and OAuth boundaries.
- No new runtime dependency.
- Retain 1280, 1440, and 1920 visual verification.

### Task 1: Theme, preferences, and sessions

- Add failing unit tests for theme resolution, corrupt storage, session
  creation, provider UUID persistence, 20-session retention, and 20-message
  retention.
- Implement isolated preference and workspace-session stores with in-memory
  fallback.
- Verify focused tests, then the complete Node suite.

### Task 2: Three-panel composition

- Add failing Playwright assertions for sidebar, conversation, artifact panel,
  panel order, and removal of the bottom dock.
- Introduce the workspace sidebar and conversation panel while preserving all
  existing user actions.
- Move inspection controls into the artifact surface.

### Task 3: Resize, maximize, themes, and responsive behavior

- Add failing unit tests for artifact-width clamping.
- Add failing browser tests for pointer/keyboard resize, reload persistence,
  maximize/Escape restoration, theme switching, and the sub-1280 drawer.
- Implement the layout controller and semantic light/dark tokens.

### Task 4: Session workflow

- Add failing browser tests for new session, transcript persistence, session
  switching, provider isolation, and resumed provider UUID.
- Refactor provider chat into session-aware transcript state without changing
  the gateway request shape.
- Verify the existing live OAuth browser suite for Codex and Claude.

### Task 5: Visual and final verification

- Replace visual snapshots and docs capture gallery with the approved light,
  dark, expanded CAD, inspection, and 1280 states.
- Run Node, .NET, both TypeScript checks, Vite build, standard Playwright,
  live OAuth Playwright, audit, and `git diff --check`.
- Inspect the combined PNG overview before completing the branch.

# Claude-style three-panel DWG workspace

## Goal

Reframe the existing single-page DWG workspace as a Claude-inspired desktop
surface without changing CAD, inspection, or OAuth gateway contracts.

## Approved layout

The desktop shell is exactly three columns:

1. A 238px workspace sidebar containing collapsible Project, Drawing tree, and
   Recent sessions sections.
2. A conversation panel with provider selection, transcript, tool progress,
   specialist details, and a sticky composer.
3. A resizable CAD artifact panel with Preview, Findings, Evidence, and
   Warnings tabs.

The CAD panel defaults to 55% of the viewport, never becomes narrower than
520px, and leaves at least 360px for the conversation. A vertical separator
supports pointer and keyboard resizing. Maximize hides the sidebar and
conversation; Escape restores the prior layout. Below 1280px the sidebar is an
overlay drawer.

## Theme

Theme preference is `light`, `dark`, or `system`; `system` is the default and
tracks `prefers-color-scheme`. The palette uses warm Claude-like neutral
surfaces and terracotta `#D97757` as the interactive accent. Semantic success
and warning colors remain independent.

## Sessions

`Sample review` remains the only project. Recent sessions are real local
workspace sessions, not placeholders. Each session records provider,
provider-session UUID, drawing path, title, updated time, and the last 20 user
or assistant messages. At most 20 sessions are retained. Existing provider
session storage is used as a compatibility fallback for the first migrated
session.

## Boundaries

- Browser layout, preference, and session stores stay under frontend features.
- `@dwg/contracts`, gateway routes, deterministic CAD evidence, and CLI
  adapters remain unchanged.
- Existing layer visibility, search, inspection, selection, cancellation, and
  live Codex/Claude resume behavior must remain observable.

## Acceptance

Unit tests cover theme resolution, preference persistence, session retention,
and width clamping. Playwright covers three-panel desktop layout, narrow
sidebar drawer, resizing, maximize/restore, themes, real local session
switching, existing CAD controls, and visual snapshots. Both live OAuth CLI
browser tests pass after the redesign.

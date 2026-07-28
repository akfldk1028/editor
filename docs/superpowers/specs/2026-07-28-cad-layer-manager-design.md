# CAD Layer Manager Design

## Goal

Replace the visual review page's loose layer buttons with a compact CAD-style
layer manager that controls the existing SVG `data-layer` groups.

## Scope

- Keep the generated SVG and PNG geometry unchanged.
- Keep the review page background white.
- Put the drawing and layer manager side by side on desktop.
- Move the layer manager below the drawing on narrow screens.
- Show one row per layer with a visibility checkbox, color swatch, Korean name,
  and modeled object count.
- Provide `전체 켜기`, `전체 끄기`, `선택만 보기`, and `초기화` commands.
- Keep disabled layers visible in the list but unavailable when the floor has no
  basic-design data.
- Synchronize layer state after the SVG iframe loads.
- Preserve keyboard operation and expose checked state to assistive technology.

## Layer Model

The manager uses the existing `LAYER_ORDER` values as stable layer IDs. Display
metadata is defined once in the visual-review module:

- `grid`: 그리드
- `rooms`: 공간
- `circulation`: 복도·동선
- `core`: 코어
- `structure`: 구조
- `envelope`: 외벽·창호
- `door-openings`: 문
- `furniture`: 가구
- `fixtures`: 설비
- `egress`: 피난
- `dimensions`: 치수·대지
- `text-labels`: 문자

Each row carries `data-layer`, a checkbox, a decorative color swatch, the Korean
label, and the modeled count from `report["layer_completeness"]`.

## Interaction

- Changing a checkbox immediately updates every matching SVG group.
- `전체 켜기` checks every enabled row.
- `전체 끄기` unchecks every enabled row.
- Clicking the row's native layer-selection button makes it the active layer
  without changing the sibling visibility checkbox.
- `선택만 보기` keeps the active enabled layer visible and hides every other
  enabled layer. It is disabled until an active layer exists.
- `초기화` restores the initial all-visible state.
- Reloading the iframe reapplies the current manager state.

## Validation

HTML contract tests verify Korean layer metadata, checkboxes, counts, commands,
responsive layout, and synchronization script. Playwright verifies checkbox and
bulk-command behavior against actual SVG node `style.display` values at desktop
and mobile widths. Final artifacts are regenerated under
`docs/plan-alternatives-architectural`.

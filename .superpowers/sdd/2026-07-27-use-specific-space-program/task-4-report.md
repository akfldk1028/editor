# Task 4 Report

## RED

```powershell
python -m pytest backend/tests/test_visual_review.py -q -k room_form
```

Result: `1 failed, 26 deselected`; the report had no `checks.room_form`.

## GREEN

- Serialized `ValidationReport.room_shapes` into review JSON without
  recalculating room validator policy.
- Added a `room_form` hard check driven only by `room_min_width` and
  `room_aspect_ratio`, plus overall minimum width, maximum aspect ratio, and
  failed room IDs.
- Added distinct SVG/PNG colors for all office and commercial roles, compact
  room form tables, responsive plan sizing, building use/room-count index
  entries, and working SVG layer controls.
- Updated legacy visual/CLI expectations to the truthful role-driven connected
  circulation and the known 20x10 commercial `search_exhausted` result.
- Updated the research card with the precise OpenAI/deterministic ownership
  boundary.

Focused result:

```powershell
python -m pytest backend/tests/test_visual_review.py backend/tests/test_cli.py -q
```

`36 passed`.

## Actual Generation

```powershell
python -m backend.app.cli building-review --input resources/datasets/manifests/sample_mass_office_commercial.json --output-dir logs/runs/sample_building_review_llm --planner openai
```

`OPENAI_API_KEY` was available. The actual five-floor OpenAI run was accepted;
F1 commercial has 7 rooms, F2-F5 office have 8 rooms, and every floor reported
`room_form: pass`.

## Browser And Visual Verification

- Reused `http://127.0.0.1:8765` for the generated review output.
- Playwright screenshots covered building index at 1440x900, commercial at
 1440x900, and office at 390x844.
- A Playwright interaction test clicked rooms, circulation, doors, and labels
  off/on, checked `aria-pressed`, verified the room-form table, and recorded
  zero console/page errors: `1 passed`.
- Inspected commercial and office PNGs. Commercial uses the large pink sales
  room and seven-role palette; office uses the large blue open-work room and
  eight-role palette. The responsive SVG change keeps the entire plan visible
  at the mobile viewport.

## Final Verification

```powershell
python -m pytest -q
ruff check .
python -m compileall backend engine
git diff --check
```

Result: `164 passed`; Ruff passed; compileall passed; diff check passed.

## Self-Review

- Room form review values originate only in `ValidationReport.room_shapes` and
  violation codes; the visual layer does not duplicate width/aspect policy.
- Layer toggles address SVG groups and preserve the plan frame dimensions.
- Existing corridor measurements remain intact; only room form metrics rely on
  validator output.

## Concerns

- The 20x10 commercial review-loop fixture remains a truthful rejected sample
  because its constrained role program is infeasible; tests now state this
  rather than asserting legacy acceptance.

## Commit

`feat(review): expose room form evidence`

## Review Fix Round

### RED

```powershell
python -m pytest backend/tests/test_visual_review.py -q -k "room_form_table or resynchronizes"
```

Result: `2 failed`; the compact table did not contain validated actual area and
the page had no iframe-load synchronization function.

### GREEN

- Review JSON now serializes `ValidationReport.room_areas`; the table joins its
  `actual_area` values to `room_shapes` by `room_id`, without geometry work in
  the visual layer.
- Layer visibility derives from `aria-pressed` in `synchronizeLayers()`, which
  runs after every click and iframe `load`, preserving an early-click state.
- Added tracked Playwright configuration and
  `tests/browser/visual_review.spec.js`. It delays the SVG response, clicks
  Rooms before iframe load, verifies the post-load SVG group is hidden, then
  toggles all four layers off/on with no console or page errors.

```powershell
npm run test:browser
```

Result: `1 passed`.

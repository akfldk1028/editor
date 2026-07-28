# CAD Layer Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CAD-style, Korean layer manager for generated floor-plan review HTML.

**Architecture:** Reuse the existing SVG `data-layer` contract and replace only the HTML controls, styles, and synchronization script produced by `_render_html`. Layer display metadata stays centralized in the visual-review service and modeled counts come from the existing completeness report.

**Tech Stack:** Python 3, static HTML/CSS/JavaScript, SVG iframe, pytest, Playwright.

## Global Constraints

- Background remains white.
- No external frontend library or network dependency.
- PNG remains a flattened artifact; interactive visibility is HTML/SVG only.
- Existing layer IDs and renderer geometry remain backward compatible.
- All commands must be keyboard accessible and mobile responsive.

---

### Task 1: CAD Layer Manager Contract

**Files:**
- Modify: `backend/tests/test_visual_review.py`
- Modify: `backend/app/modules/visual_review/service.py`

**Interfaces:**
- Consumes: `LAYER_ORDER`, `_BASIC_DESIGN_LAYERS`, and `report["layer_completeness"]`.
- Produces: `#cad-layer-manager`, checkbox inputs with `data-layer`, and bulk command buttons with `data-command`.

- [ ] **Step 1: Write failing HTML contract tests**

Add assertions that generated HTML contains `id="cad-layer-manager"`, Korean
layer names, color swatches, modeled counts, checkbox inputs, four bulk commands,
and responsive CSS. Assert the synchronization code reads checkbox `checked`
state instead of `aria-pressed`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
pytest -q backend/tests/test_visual_review.py -k "layer_control or cad_layer"
```

Expected: failures because the current output only contains loose buttons.

- [ ] **Step 3: Implement the manager**

Add centralized layer labels and colors, render semantic rows and commands, and
replace the current button event code with checkbox and bulk-command handlers.
Each row has sibling native controls: a visibility checkbox and a layer-selection
button. The selection button makes its layer active, and `선택만 보기` leaves
only that active enabled layer checked. Keep iframe-load synchronization and
disabled basic-design layers.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
pytest -q backend/tests/test_visual_review.py
ruff check backend/app/modules/visual_review/service.py backend/tests/test_visual_review.py
```

Expected: all tests and lint pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/modules/visual_review/service.py backend/tests/test_visual_review.py
git commit -m "feat(review): add CAD layer manager"
```

### Task 2: Artifact and Browser Verification

**Files:**
- Regenerate: `docs/plan-alternatives-architectural/**`

**Interfaces:**
- Consumes: `python -m backend.app.cli alternatives-review`.
- Produces: review HTML whose manager controls the embedded SVG.

- [ ] **Step 1: Regenerate all three mass reviews**

Run the alternatives-review CLI for `alternatives_20x12.json`,
`alternatives_30x12.json`, and `alternatives_30x20.json` with architectural
rendering into their existing docs directories.

- [ ] **Step 2: Verify browser behavior**

Serve `docs/plan-alternatives-architectural`, open a commercial floor with
Playwright, and assert:

```javascript
checkbox.checked === false
svgNodes.every(node => node.style.display === "none")
```

after toggling a layer. Verify 전체 켜기, 전체 끄기, 선택만 보기, 초기화,
iframe reload synchronization, and the mobile stacked layout.

- [ ] **Step 3: Run full verification**

```powershell
pytest -q
ruff check backend engine
python -m compileall -q backend engine
git diff --check
```

- [ ] **Step 4: Commit regenerated artifacts**

```powershell
git add docs/plan-alternatives-architectural
git commit -m "docs(review): refresh CAD layer artifacts"
```

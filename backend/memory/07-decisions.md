# Decisions and contract changes (newest first)

Write one dated line per decision; link the commit. Contract changes to agent doors must also
be told to the Orchestrator session.

- 2026-10-06 `2fc0c8c4` regulations/land split modules are packages like `cli/`:
  `regulations/{calculator,setbacks}/`, `services/{regulation_calculator,setback_geometry}/`
  (533 hashes identical, 421 pass after rebasing onto `d4ee05b9`; ORDINANCE_DIR re-pointed;
  import_design_runtime.py maps package destinations to `__init__.py`).
- 2026-10-06 PENDING: branch `pkg/masterplan` `2d0e82e0` (`masterplan/{planner,rows,validation}/`,
  plan_site hashes identical, 205 pass). Held: another session has uncommitted edits to
  planner.py/planner_rank.py/joint.py (+ new siting_terms.py). Cherry-pick after they commit;
  their planner_rank edits land in `planner/rank.py`.
- Folder rule (user, 10-06): a split module becomes a package (`foo/__init__.py` + parts), never
  prefix siblings (`foo_rules.py`). Existing flat conventions (`design_runtime/*_views.py`) stay.
- 2026-10-06 Modularization round 1 (platform core, pure moves, originals stay the public import path):
  `65045d70` cli.py -> `cli/` package; `94b08e71` design_runtime views.py -> 7 modules; `f14f7806`
  masterplan planner/rows/validation -> siblings (plan_site hashes identical; planner.py still 835 —
  `_plan_site_fixed` is one closure-heavy function, splitting it is a refactor); `4999585d`
  regulations + land/reference calculator/setbacks split (385 output hashes identical; the two
  diverged copies were NOT merged). Monkeypatched names and their callers stayed in the original
  module. `backend/scripts/import_design_runtime.py` + `source-manifest.json` still hash the
  pre-split files — do not re-run the importer over them (it would overwrite or flag the splits).
  Agent doors unchanged. Not done: research code under `design/generation` (book_language, massv2).
- 2026-10-06 `1ec08619` Delivered mass export by content: `/bundle` door, `files/` and
  `package.zip` routes, hrefs on results. Mass ships its cycle; nothing reads Mass's disk.
- 2026-10-06 `5ddd2b35` A2A_TOKEN on agent doors; planm stages travel as bundles
  (planm-stage-bundle/v1).
- 2026-10-06 `792b4644` Local OAuth for workspace models (EDITOR_MODEL_AUTH); API keys only in
  deployment.
- 2026-10-06 `f82d804a` Planning engine: 209/209 (bounded large-site search, single-loaded rows,
  direct two-bay aisles, exact curved ramps, design target without Law count follows dad68f5).
- 2026-10-06 `009a5b1e` 차량출입불허구간 enforced for ramps/connectors/surface entrances;
  validation placement_stage scope fix.
- 2026-10-06 `ef2eb0e6` `ramp_overhead` planning op; `law/agent/parking-count` provider op.
- 2026-10-05~06 ARR + AG absorbed into the editor (workspace keys/tool policy/validate-test/
  seeds/Replay/deep-analysis SSE; route inventory + api-surface guards; 18449 declared in
  services.json). ARR/AG are no longer run or called.
- 2026-10-06 Datum DEM is a VRT. `NGII_DEM_LOCAL_PATH` (sdd env) now names
  `D:/Data/NGII_DEM/ngii_dem.vrt`, which SiteContext rewrites when it adds a WFS contour tile
  for a parcel outside the installed mosaic (`tiles/wfs_<x>_<y>.tif`, mosaic listed last, so it
  wins). `elevation_api._get_ngii_dem_src` reopens when the file's mtime changes. Changed by the
  Orchestrator session; Site owns the tiles (agents/SiteContextAgent `dem.ensure_cover`).
- 2026-10-06 Ordinance caps for all 163 jurisdictions (`d4ee05b9`), generator in
  `law/reference/scripts/ordinance_batch/`. Calculator looks up the 시 of an 일반구
  (`ordinance_codes`). Known: the original `fetch_ordinance_caps.parse_caps` misread "1,500" as
  500 and spaced zone names; the rebuild parser replaced its values. Re-run the three scripts
  rather than `fetch_ordinance_caps.py` alone. Changed by the Orchestrator session.

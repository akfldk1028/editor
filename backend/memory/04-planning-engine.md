# Planning engine — `app/modules/design/generation/maas/masterplan/` (2026-10-06)

Owned here; the MasterPlan **agent** reaches it only through the planning operations door.
Tests: `backend/tests/masterplan_engine/` — **209 passed** (2026-10-06, editor `f82d804a`).

## Rules that are decisions, not bugs
- **Parking counts are Lawagent's.** The engine never invents a count; without a Law count a
  design target still draws an *unapproved* surface proposal (ARR `dad68f5`, 2026-09-30;
  `test_design_target.py`), and the missing count stays a blocking line.
- **No placement without an authored building-zone target** (`planner._placement_target_refusal`);
  a BCR ceiling is never promoted to a target (`test_bcr_ceiling_is_not_promoted_to_authored_target`).
- **차량출입불허구간** (district-plan vehicle-prohibited intervals, request key
  `vehicle_prohibited`, line geometry): no ground ramp body, ramp connector or surface entrance may
  come within 0.05 m (`planner._off_prohibited`, `rows.row_candidates(prohibited=)`). Basement
  drives run under the line and are not checked.
- **Digging less wins** among valid schemes (rank: validity → counts → surface target →
  excavation cost units → efficiency → loops → score).

## Row search (`rows.py`)
- Practice-scale parcels (ground < 10,000 m²) keep the full 0.5 m offset sweep, so results do
  not move. Large envelopes use a bounded, usable-offset sample (`BOUNDED_OFFSETS` 32/angle,
  `SEARCH_BUDGET` 384), and every candidate reports `search_count`.
- Adjacent-stall pairs via STRtree; stall checks on prepared geometry. 240×120 m: 160 s → 9.7 s.
- Shallow parcel → one loaded row; a direct-to-road aisle shorter than two aisle widths keeps
  bays at its entrance end and needs only two bays; a direct entrance must meet the road over
  the full aisle width; entrance corridors reach the site's own edge (no fixed 200 m).
- Curved ramps share `_curved_ramp`: chord length sets the tail so the centreline is exactly the
  statutory run; grade stations are vertices; `lead_fraction`, `turn_deg` supported.

## Validation
`validation.py`: `placement_stage` is computed once before the level loop (it crashed on ground
levels before 2026-10-06).

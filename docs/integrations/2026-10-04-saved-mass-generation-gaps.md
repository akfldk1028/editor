# Saved mass: generation limits verified on 2026-10-04

The saved candidate reaches the real Editor PLANM normalize and analyze stages. It does **not** produce an accepted floor-plan alternative. The immediate cause is that the current polygonal generator cannot place any of its supported core geometries inside this small footprint. This is an implementation capability limit, not a finding that the archived building is legally impossible.

## Evidence and scope

Run: `.superpowers/sdd/2026-10-04-design-archive/browser-data/runs/0fa13c38842848d58272e1a8602b6831/`.

- `run.json`: normalize and analyze succeeded; alternatives stopped with `insufficient_accepted_alternatives`; no approval.
- `artifacts/alternatives.json`: `accepted_count: 0`, no alternatives, and **empty `rejected_families`**.
- `input/mass.json`: two explicit floor footprints; 3.5 m floor height; explicit office planning scenario; no supplied street/access edges. Archived source building type remains separate from this chosen scenario.
- `artifacts/mass-analysis.json`: each floor is a nine-vertex, non-rectangular polygon of 21.263416997821526 m²; total floor area 42.52683399564305 m². Bounding width/depth are approximately 6.4351 m / 7.9084 m.
- Raw source geometry was converted from EPSG:4326 to EPSG:32652 and translated about its projected centroid. The bridge does not enlarge, rotate, replace, or simplify the selected footprint. Provenance and original archive remain available.

This investigation read existing artifacts and invoked pure geometry/program functions. It did not rerun an agent, modify a stored candidate, approve a result, or write a new design run. Diagnostic command output was captured in exec chunk `4c383f`; only aggregate geometry measurements are reproduced here.

## Immediate failure mechanism

`backend/app/modules/generation_loop/service.py::run_building_alternatives` routes non-axis-aligned rectangles and other polygons into `_composed_building_alternatives`. The latter delegates to `alternative_composer/service.py::compose_structural_alternatives`.

The composer obtains an office profile core target of approximately 2.9769 m² for this small floor, then requests rectangular cores with fixed minimum width 7.6 m and depth 5.2 m. These minimum dimensions require at least **39.52 m²**, already exceeding the entire 21.2634 m² floor. Its widened search changes enumeration, not the minimum geometry. Its last fallback requests a 6.8 m square core, or **46.24 m²**.

Read-only calls using the exact saved floor boundaries produced:

| Search | Candidates |
|---|---:|
| Initial 7.6 × 5.2 m core family | 0 |
| Widened 7.6 × 5.2 m family | 0 |
| Widened 6.8 × 6.8 m fallback | 0 |

The existing stair enclosure helper reports 2.8 × 4.92 m at the supplied floor height, but this is not proof that a complete alternate core, entrance, circulation system, or legal egress arrangement fits. Do not substitute that rectangle for the current core contract merely to make the run pass.

No core reaches `_evaluate_core`, so its per-family rejection collector remains empty. `_composed_building_alternatives` only propagates rejection records when that collector is nonempty. The final caller therefore knows that fewer than two accepted alternatives exist but loses the concrete reason that no core candidates existed at all.

## Missing inputs are separate from this geometry failure

The saved run explicitly reports unresolved jurisdiction, effective date, floor code context, and travel-limit classification. The input has no asserted occupancy counts, floor-specific legal occupancy classification, qualifying sprinkler protection, construction qualification, or verified access geometry.

These facts must come from project evidence and the responsible domain/program/legal agents. They must not be inferred from the historical `is_feasible` flag, a broad archived building-type label, or the fact that the bridge could parse the polygon. The observed failure occurs before those missing facts could establish legal adequacy.

The current PLANM program keys are `office` and `neighborhood_commercial`. The explicit office scenario in this run is not a claim that the original neighborhood-facility label legally equals an office. Commercial planning additionally needs genuine street-edge evidence. An empty access list must not be silently replaced by edge zero or a manufactured south frontage.

## Next implementation sequence

1. **Preserve rejection evidence for an empty search.** Add a structured generator rejection when all core searches return zero candidates. Include a stable code such as `no_core_candidates`, common-floor area/bounds, requested core target, attempted minimum dimensions, and candidate counts. Propagate it through `alternatives.json` and the existing halt display. Keep the two-distinct-accepted-alternatives requirement unchanged. A focused regression should prove that this saved shape reports the cause and still produces zero accepted alternatives.
2. **Expose generator compatibility before a long run.** Reuse the same pure feasibility checks to show that this candidate does not support the current core families. Label it a generation limitation, separate from regulatory screening. Allow the user to inspect another archived candidate without modifying the rejected original. A larger candidate is suitable for a separate integration test only after measurements establish that it supports the existing geometry contract; it must not replace this failure evidence.
3. **Define an evidence-backed small-building typology contract.** If planning this footprint is required, first establish the intended spaces, actual entry/frontage, vertical circulation requirements, legal egress facts, and supported floor-to-floor geometry. The responsible external agents should supply those requirements. Implement and validate an additional core/program family only if it can satisfy them; do not shrink the existing minimums or assume one stair is legally sufficient.
4. **Treat orientation support as a separate enhancement.** The current core search is axis-aligned. Rotated otherwise-capable footprints may need an explicit reversible local planning frame, including transformed access edges and a stored inverse transform. Rotation cannot solve this run's area deficit, so it is not the immediate fix. Geometry containment, area, north/frontage semantics, and export round trips need verification before introducing it.

## Remaining completion boundary

The archive-to-Editor selection and geometry handoff are exercised. This particular candidate has not completed alternatives, review, delivery, approval, or 3D publication. No result from this run supports a claim of end-to-end design completion. Source agents remain external to Editor and retain responsibility for the missing project and domain facts.

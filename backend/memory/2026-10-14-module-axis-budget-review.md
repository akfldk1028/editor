# Module-axis and basement solve-budget review

MasterPlan user requested generation/Jev/benchmark/paper re-review. Independent inspection found explicit cross_axis was applied relative to the selected surface row angle in one planner branch. solve_level now binds module families to the canonical site angle; legacy non-module branch remains row-relative. Reproduced before fixing direct/rows × along/cross tests.

Existing row solve reservation could discard a call when no viable row existed, and generic ring fallback/stacked solves could consume the reserved call. Row candidates are generated before reserving; reserve only for viable ramp/slab with remaining demand. BasementSearchBudget.run enforces internal reserved capacity at each actual generic invocation. Reproduced absent/missing-slab/usable rows, budgets1/2/3, auto/ring/stacked paths.

73 focused tests passed covering budget, module integration, parking modules, diagnostics, compact slabs and siting. Cross-review33 scheduling/module tests also pass (overlapping, do not sum). Full engine folder sweep was interrupted after29 progress dots in slow unbounded legacy geometry tests; do not claim full-engine pass.

Actual Uijeongbu seed2: site150.215deg, old wrong cross330.22deg; fixed240.215deg and31stalls versus supplied39 -> failed. Old45-stall geometry is retained, not a successful cross-axis result. Seed4 used2->3 calls but still34/39 -> failed. Root inspected drawings and retained HTTP receipts under MasterPlanagent/runs/review-20261014. Shared backend restarted after final changes and both saved layouts independently revalidated.

Remaining structural scope: basement_layout/planner_rank retain one internal winner; joint's mass portfolio does not expose all fixed-mass basement alternatives. Placement uses full-host slab then compaction. Paper WFC2023 demonstrates alternate internal adjacency, but its fixed8.4m grid, parking-maximizing objective and unavailable recipe/data are not a ready general owner replacement. No new law values hardcoded.

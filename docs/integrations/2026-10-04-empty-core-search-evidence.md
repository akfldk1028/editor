# Empty core searches retain their cause

The archived candidate PK18183 previously passed normalization and mass analysis, then stopped with zero accepted alternatives and an empty rejected-family list. Editor now retains a typed `no_core_candidates` diagnostic through the composer, generation result, `alternatives.json` and existing PLANM halt display.

The evidence contains the actual shared floor intersection area/bounds, requested core target and every attempted minimum width/depth, widening flag and candidate count. It is emitted only when every attempted search produced zero candidates. Existing core enumeration, fallback dimensions, layout evaluation and the two-accepted-alternatives gate are unchanged. Finite values, positive dimensions, immutable evidence and zero-count consistency are validated.

For this saved shape, the shared floor area is 21.2634 m². The generator attempted 7.6 × 5.2 m twice and 6.8 × 6.8 m once, each returning zero candidates. The UI identifies this as a limitation of the current generator, not a legal impossibility finding. Unresolved regulatory facts remain separate. Original geometry and the explicitly selected office planning scenario remain unchanged.

## Verification

The full-stage regression was observed failing because rejected families were empty, then passed after propagation was added. It verifies normalize/analyze success, alternatives blocked, zero accepted alternatives, exact saved-shape area and search evidence, unchanged input bytes and unresolved jurisdiction. Additional focused regressions cover disjoint floor intersection and invalid diagnostic values. Existing PLANM API/recovery/contracts plus the full-stage regression: 14 passed.

Eight mocked saved-design browser cases passed, with two separately gated live cases skipped. The new actual HTTP/Chrome case passed separately: run `8f26aa2044164b2691170dda7bc6a659` normalized and analyzed, then stopped at alternatives with the diagnostic, zero accepted designs and no approval. The complete outgoing mass matched the selected archived mass except for the explicitly chosen office use mix. Jurisdiction, effective date, floor code context and travel-limit classification stayed unresolved.

Production frontend build and two boundary checks passed. The halt renderer was extracted into `HaltEvidence.tsx`; its diagnostic table has scoped spacing and a narrow-screen scroll container. Screenshots and machine-readable results are under `.superpowers/sdd/2026-10-04-no-core-candidates/` and `test-results/no-core-candidates-actual.png`. The isolated server used copied project/design records; source services and archives were untouched.

## Next integration work

This change explains failure; it does not add a small-building core typology or port ARR mass optimization. The source-backed [native execution plan](2026-10-04-native-design-execution-plan.md) distinguishes fixed-footprint PLANM generation from site/genome mass optimization. Next implement project-bound immutable native job specifications, then the complete additive SSIEA evaluator/repair/renderer and durable worker lifecycle. Additional algorithms, full MAAS, parking, agent/VLM evidence and DWG/scene publication remain required before overall integration completion.

Final existing composer/building-alternative regression: 94 passed in 511.63 seconds, including the initial diagnostic/full-stage cases. Seven latest focused diagnostic/full-stage cases also passed separately, including four added validation cases. Independent backend/UI review found no material issue. Disposable 18443/5186 were confirmed closed.

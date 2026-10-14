# Outdoor component precision

Real Uijeongbu fixed-building alternative had one 767.897668496m2 outdoor region plus ~1e-15m2 polygon islands after rotated Boolean operations. `siting_relations._parts` counted four components, incorrectly changing the fragmentation benchmark. Filter polygon area <= TOL² (existing TOL=1e-6m); retain real small pockets. Regression reproduced then fixed; siting relations/terms tests: 13 passed.

MasterPlan observer duplicated the problem (five islands) and was corrected with the same numerical tolerance. Baseline and alternatives were revalidated together via isolated editor HTTP18479. Baseline667.898m2/one component vs alternative767.898m2/one component; upper and ground1073.8m2 unchanged. Component correction is measurement repair, not design improvement. Shared18449 subsequently restarted and actual baseline/C plus4 new building/basement alternatives revalidated. See MasterPlan docs/evidence/real-context-quality-benchmark-20261014.md. No legal threshold or space usability assumption added.

Added configuration_signature: exact building/enclosed-ground and basement aisle/ramp/stall-axis identity, excluding count/labels. Not perceptual diversity or design quality. Review reproduced false uniqueness from redundant collinear vertices and malformed basement features crashing measurement; both fixed with regressions.19 affected tests passed.

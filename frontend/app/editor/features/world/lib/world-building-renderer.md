# Building renderer selection

`prepareWorldBuildingRenderer(readRelease)` resolves one publication before importing a renderer. Its returned `create({viewer, C, changed, firstFrame})` can be used once. The caller must check disposal after awaiting preparation. Use `WorldBuildingRenderer` for the existing hook ref; its public methods match both implementations.

- Absent publication and `ace-map-release-v1` retain `BuildingTiles`, including existing prebuilt/vector coverage.
- `ace-map-release-v2` consumes the actual publisher fields `sourceFamily: 'NGII-B021'`, `nationalBuildings`, `coverage`, and `runtimeValidationRequired: true`. It creates `NationalBuildings` only and never imports/prepares the vector branch.
- Unknown, partial, inconsistent, or sample publications reject before either renderer loads. National loading errors do not select a different source.

`nationalBuildings` is the existing `NationalBuildingSource` descriptor, bound to release terrain and the coverage catalog revision. `coverage` has schema `ngii-national-coverage-v1`; source plan, region counts, component/building counts, ground support totals, and all 17 province codes must agree. `verifyNationalBuildingCoverage` additionally verifies its canonical SHA256 against the descriptor before importing either renderer. Its encoding matches Python `release_store.encoded` for the publisher schema. A Python-generated digest is covered by tests.

The completed database and exact nationwide region/component set are audited by `prepare_ngii_national_release.py`. The client cannot independently prove geographic completeness from counts or SHA strings; a finished sample cannot be relabeled as national. `runtimeValidated: false` is retained honestly for isolated preview and does not mean runtime acceptance has passed. Activation remains a separate validation gate.

The hook and `/dwg` preload now select the renderer through the pinned release factory; the release parser verifies v2 and legacy vector/catalog readers reject v2 before fetching. Missing original province attributes are retained and explicitly counted as `unclassifiedProvinceBuildings`; all 17 known province codes remain required. Keep terrain/catalog/asset-base consumers on the same pinned release. Do not remove v1 fallback until a validated v2 exists.

At active a91, 26,248 source Z14 addresses comprise 25,569 prepared, 679 absent and 113 partial prepared regions. The historical missing-ground cohort has 167,669 remaining keys: 139,250 in 672 absent regions and 28,419 in 113 partial regions. Seven absent addresses are outside the former publication bounds and outside that cohort. These are source-tile counts, not physical-building deduplication or geographic province proof. Evidence: `C:/Data/25_ACE/management/continuous-ground-audit/active-a91-single-renderer-coverage.json`. Existing v1 cannot safely switch to prebuilt-only today.

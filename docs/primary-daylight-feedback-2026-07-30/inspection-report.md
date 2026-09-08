# Final Daylight Feedback Evidence

## Provenance

- Source commit: `06953d6447979039c78122f171d1c3888af6d905` (`fix: retain validation retry provenance`).
- Initial dirty-state check: clean.
- Fixture: `resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json`, SHA-256 `6b59bfea90ed15aea10a9e2814fc14a8561cba1fd90e5cc2c7acee945a1c143c`.
- CLI command: `python -m backend.app.cli irregular-alternatives-review --input resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json --output-dir logs/runs/primary_daylight_feedback_final_06953d6 --limit 3`.
- CLI result: exit `0` in `235.2s`.
- Retained output: 36 source/retained file pairs with equal SHA-256 and byte count. See `sha256-manifest.json`.
- Before aggregate remains immutable at `docs/building-quality-baseline-2026-07-30/source-run/alternatives.review.json`, SHA-256 `1a1b0390d7ed01e6293b31af786d60207ec2e6028fb2bd3c09c1e574ca5bff69`.

## Aggregate Evidence

- Schema `1`; policy `building-quality/v1`; accepted `2`; rejected `0`.
- Distinct structural/core/circulation/candidate-PNG/PNG counts: `2/2/2/2/2`.
- `alternative-01`, `notch_adjacent`: validation score `2.6152`; building-quality score `0.7935`; floor daylight ratios `0.9423614866510824`, `0.911026869081252`, `0.9146022582464355`.
- `alternative-02`, `long_edge_adjacent`: validation score `2.6220999999999997`; building-quality score `0.7874`; floor daylight ratios `0.9766151723543345`, `0.9756863096715561`, `0.8459560292236058`.
- Repair operator `primary_daylight_exterior_allocation/v1`; floor `3`; requested/served room IDs exactly `["meeting"]`; before `0.6625309657157782`; threshold `0.7`; after/re-evaluated `0.8459560292236058`.
- `accepted_pairwise_diversity` contains one accepted pair and records `quality_distinct=true`.
- Pair metrics: core `0.6709791024774004`; circulation `0.5`; topology `0.0`; area distribution `0.19612151615637516`; total `0.3655180339744951`; nonzero components `3`.
- Source commit `06953d6` requires validation-rejected retries to retain matching lossless `generator_repairs` provenance and covers that contract in the current test suite. This accepted fixture has no rejected alternatives, so it does not manufacture a validation-retry rejection example.

## Usable Frontage Proof

The retained `alternative-02` floor-3 SVG was mapped back to the explicit floor footprint and checked with the current usable-daylight geometry rules.

- Meeting window length: `1.4999283885363788m`, above the required `1.2m`.
- Meeting exterior contact: `7.662288317167921m`.
- One complete inward daylight zone is contained by the meeting polygon: required dimensions `1.2m x 2.4m`, measured area `2.8800000000000052m2`.
- `polygon_has_usable_daylight_frontage(meeting)=true`.
- Focus was not requested or served by the repair.
- `polygon_has_usable_daylight_frontage(focus)=false`.
- Focus exterior contact: `0.0m`; minimum rendered distance to the exterior: `0.999952259024251m`.
- Retained window IDs are exactly `meeting-window` and `open_work-window`; `focus-window` is absent.
- The prior focus tendril/window geometry is absent from the refreshed floor-3 SVG, HTML, PNG, and manifest.

## Visual Inspection

All six unique top-level PNGs were inspected at original `1920x1080` resolution.

- Explicit irregular boundaries are visible and all rooms, circulation, stairs, and cores remain inside.
- Labels are readable without incoherent overlap.
- `open_work` remains the largest non-core room.
- The alternatives remain visibly planning-distinct.
- Repaired long-edge floor 3 visibly shows meeting on the upper exterior with a window line and substantial inward room depth.
- Focus is an interior room with no exterior tendril and no window line.
- Long-edge core/circulation family geometry remains intact.

Every retained PNG SHA-256:

| Retained path | SHA-256 |
| --- | --- |
| `alternative-01/floor_001/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f1.png` | `cb14068aa65b5871d113501da9ad470d1b84b96aeffff3ec0324008283657ec9` |
| `alternative-01/floor_002/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f2.png` | `77c4f118e0ff5d5ddb3188e1e9fe4678fd95401b34cc74338277c45d44a04003` |
| `alternative-01/floor_003/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f3.png` | `1763b4747d7c1b29a40c1160b4198913af497468fe5da762dcae99a2f43b9337` |
| `alternative-01-floor-001.png` | `cb14068aa65b5871d113501da9ad470d1b84b96aeffff3ec0324008283657ec9` |
| `alternative-01-floor-002.png` | `77c4f118e0ff5d5ddb3188e1e9fe4678fd95401b34cc74338277c45d44a04003` |
| `alternative-01-floor-003.png` | `1763b4747d7c1b29a40c1160b4198913af497468fe5da762dcae99a2f43b9337` |
| `alternative-02/floor_001/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f1.png` | `d127a2af17ce06f91e5226b44d3e2deac464b5b0a61a49c8eaecfb4c4dbc2cf7` |
| `alternative-02/floor_002/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f2.png` | `d5fc45679abb152613a73f04ec83cafd1388e39928c7f10502c655d3b3ca9f34` |
| `alternative-02/floor_003/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f3.png` | `78eb43e9d873ed391b0a6a742b4ff28fc5e569dd0413a9ae10d89de80e5a3df3` |
| `alternative-02-floor-001.png` | `d127a2af17ce06f91e5226b44d3e2deac464b5b0a61a49c8eaecfb4c4dbc2cf7` |
| `alternative-02-floor-002.png` | `d5fc45679abb152613a73f04ec83cafd1388e39928c7f10502c655d3b3ca9f34` |
| `alternative-02-floor-003.png` | `78eb43e9d873ed391b0a6a742b4ff28fc5e569dd0413a9ae10d89de80e5a3df3` |

## HTML Interaction

The retained tree was served at `http://127.0.0.1:8772/index.html` and tested with an isolated Playwright Chromium process.

- Two accepted alternative sections rendered.
- All six top-level images loaded with natural dimensions `1920x1080`.
- The long-edge repair table displayed operator, `meeting`, exact before, threshold, and after values.
- Both accepted floor-3 pages passed `all-off -> rooms/core/envelope -> isolate core -> all-on`.
- Each page exposed 12 unique modeled layers across 13 top-level SVG nodes because the `rooms` layer has separate room and boundary groups; all layer states changed and restored.
- Long-edge floor-3 DOM contained one `meeting-window` and zero `focus-window` elements.
- Console errors: `0`; page errors: `0`.
- The owned HTTP server and listener were stopped after verification.

## Repository Verification

- `python -m pytest -q`: exit `0`; `873 passed, 2 skipped` in `1778.50s`.
- The environment emitted the pre-existing `RequestsDependencyWarning`.
- `python -m ruff check backend`: exit `0`; all checks passed.
- `git diff --check`: exit `0`.
- Generator ownership: no `modules.building_quality` imports in `generation_loop` or `layout_generator`.
- Frozen contracts/policy/service/daylight evaluator, fixture, and baseline docs emit no diff from `480640d`.
- Task 6 changed no production or test files.

## Remaining Issues

- Regulatory facts remain unresolved: `effective_date`, `floor_code_context`, `jurisdiction`, `measured_travel_distance`, `travel_limit_classification`; `non_axis_aligned_polygon` remains unresolved in floor/building quality evidence.
- Both alternatives retain the soft issue `wet_service_stack_ratio=0.0` below `0.7`.
- The pre-existing dependency warning remains.

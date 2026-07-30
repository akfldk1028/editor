# Primary Daylight Feedback Inspection Report

## Provenance

- Source commit: `a175364cc3f9869459ef1026979491190c9ad4ca`.
- Dirty-state check before Task 6: clean (`git status --short` emitted nothing).
- Fixture: `datasets/manifests/sample_mass_irregular_12v_setback_office.json` (`6b59bfea90ed15aea10a9e2814fc14a8561cba1fd90e5cc2c7acee945a1c143c`).
- CLI command (exit 0, 236.2s): `python -m backend.app.cli irregular-alternatives-review --input datasets/manifests/sample_mass_irregular_12v_setback_office.json --output-dir logs/runs/primary_daylight_feedback_after --limit 3`.
- Retained output: `source-run/`; 36 source/retained file pairs have equal SHA-256 and byte count. See `sha256-manifest.json`.
- Before aggregate: `docs/building-quality-baseline-2026-07-30/source-run/alternatives.review.json` (`1a1b0390d7ed01e6293b31af786d60207ec2e6028fb2bd3c09c1e574ca5bff69`).

## Focused Verification

All completed focused suite invocations exited 0. The environment emitted the pre-existing `RequestsDependencyWarning` about `urllib3` / `chardet` / `charset_normalizer` on each invocation.

| Command | Exit | Result |
| --- | ---: | --- |
| `python -m pytest -q backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_service.py backend/tests/test_building_quality_diversity.py backend/tests/test_building_quality_hardening.py` | 0 | 57 passed, 25.05s |
| `python -m pytest -q backend/tests/test_orthogonal_layout_generator.py` | 0 | 33 passed, 1.50s |
| `python -m pytest -q backend/tests/test_generation_loop.py` | 0 | 14 passed, 200.80s |
| `python -m pytest -q backend/tests/test_alternative_composer.py` | 0 | 42 passed, 745.44s |
| `python -m pytest -q backend/tests/test_cli.py` | 0 | 22 passed, 271.92s |
| `python -m pytest -q backend/tests/test_visual_review.py` | 0 | 59 passed, 39.90s |

`test_cli.py` first reached the 270s harness timeout before reporting a result (exit 124, 272.4s) and left PID 44888; the owned PID was terminated, confirmed absent, then the unchanged command was rerun with a 600s limit and passed as recorded above.

## Repository Verification

- `python -m pytest -q`: exit 0; `840 passed, 2 skipped` in `1710.78s` (28m30s). The pre-existing `RequestsDependencyWarning` remained.
- `python -m ruff check backend`: exit 0; all checks passed.
- Final staged `git diff --check`: exit 0 after adding a scoped `.gitattributes` exemption for the two byte-preserved generated alternative index files. Their source whitespace is unavoidable without changing retained bytes.
- Generator ownership check: `rg -n "modules\\.building_quality" backend/app/modules/generation_loop backend/app/modules/layout_generator` returned no matches (expected exit 1).
- Immutable-input check: `git diff 480640d --` over the frozen building-quality contracts, policy, service, daylight evaluator, fixture, and baseline documentation emitted nothing.

## Aggregate And Repair Evidence

- Aggregate schema: `1`; policy: `building-quality/v1`.
- `DEFAULT_QUALITY_POLICY` thresholds are retained in the manifest: floor coverage `0.6`, primary daylight ratio `0.7`, room-form pass ratio `0.9`, core stack `0.95`, shaft stack `0.9`, service stack `0.7`, pairwise diversity `0.25`; weights are also preserved there.
- Accepted count: `2`; distinct structural/core/circulation/candidate-PNG/PNG counts: `2/2/2/2/2`.
- `alternative-01`, `long_edge_adjacent`: validation score `2.6147`, building-quality score `0.8002`; primary daylight floors 1-3: `0.9766151723543345`, `0.9756863096715561`, `1.0`.
- `alternative-02`, `notch_adjacent`: validation score `2.6152`, building-quality score `0.7935`; primary daylight floors 1-3: `0.9423614866510824`, `0.911026869081252`, `0.9146022582464355`.
- Repair: operator `primary_daylight_exterior_allocation/v1`; issue `primary_daylight_ratio`; floor `3`; subject `floor-3`; rooms `focus`, `meeting`; before `0.6625309657157782`; threshold `0.7`; after/re-evaluated floor value `1.0`.
- Pairwise diversity: core `0.6709791024774004`, circulation `0.5`, topology `0.0`, area distribution `0.1957872279553549`, total `0.3654511763342911`, nonzero components `3`, `quality_distinct=true`.

The brief's direct PowerShell numeric literal comparison evaluated false because `ConvertFrom-Json` yielded `System.Decimal` while the literal comparison followed a distinct coercion path, despite both round-tripping as `0.66253096571577819`. The same assertion using `[decimal]'0.6625309657157782'` exited 0; raw JSON retains the required token exactly. No production or test code was changed.

## PNG Inspection

All six unique top-level retained PNGs were inspected at original resolution (`1920x1080`), together with the three requested baseline `alternative-01` PNGs. The explicit irregular floor boundary is visible on every retained image; room labels are readable at original resolution without incoherent overlap; no room, circulation, stair, or core visibly escapes its boundary. `open_work` is visibly the largest non-core room on each floor. The two accepted alternatives are planning-distinct: `long_edge_adjacent` has its core/circulation assembly along the lower edge, while `notch_adjacent` places it across the upper notch/left sequence.

For repaired `long_edge_adjacent` floor 3, both `focus` and `meeting` visibly meet exterior edges and have double-line window marks. The core/circulation geometry remains in the long-edge family. The requested baseline images correspond to the accepted-set comparison only: the retained baseline has no rejected pre-repair `long_edge_adjacent` PNG. Therefore numeric before/after proof is same-strategy, while visual before/after proof is accepted-set comparison plus the repaired after geometry.

Every retained PNG SHA-256:

| Retained path | SHA-256 |
| --- | --- |
| `alternative-01/floor_001/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f1.png` | `d127a2af17ce06f91e5226b44d3e2deac464b5b0a61a49c8eaecfb4c4dbc2cf7` |
| `alternative-01/floor_002/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f2.png` | `d5fc45679abb152613a73f04ec83cafd1388e39928c7f10502c655d3b3ca9f34` |
| `alternative-01/floor_003/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f3.png` | `33c0254829f4466de220c03a31b8a731b80c2409ecc2bce88ee5fa48fd01b498` |
| `alternative-01-floor-001.png` | `d127a2af17ce06f91e5226b44d3e2deac464b5b0a61a49c8eaecfb4c4dbc2cf7` |
| `alternative-01-floor-002.png` | `d5fc45679abb152613a73f04ec83cafd1388e39928c7f10502c655d3b3ca9f34` |
| `alternative-01-floor-003.png` | `33c0254829f4466de220c03a31b8a731b80c2409ecc2bce88ee5fa48fd01b498` |
| `alternative-02/floor_001/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f1.png` | `cb14068aa65b5871d113501da9ad470d1b84b96aeffff3ec0324008283657ec9` |
| `alternative-02/floor_002/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f2.png` | `77c4f118e0ff5d5ddb3188e1e9fe4678fd95401b34cc74338277c45d44a04003` |
| `alternative-02/floor_003/sample-irregular-12v-setback-office-b3b39de2f3bc6d23-f3.png` | `1763b4747d7c1b29a40c1160b4198913af497468fe5da762dcae99a2f43b9337` |
| `alternative-02-floor-001.png` | `cb14068aa65b5871d113501da9ad470d1b84b96aeffff3ec0324008283657ec9` |
| `alternative-02-floor-002.png` | `77c4f118e0ff5d5ddb3188e1e9fe4678fd95401b34cc74338277c45d44a04003` |
| `alternative-02-floor-003.png` | `1763b4747d7c1b29a40c1160b4198913af497468fe5da762dcae99a2f43b9337` |

## HTML Interaction

Playwright served the retained output from `http://127.0.0.1:8766/index.html`: the required `127.0.0.1:8765` was already occupied by unrelated IPv4/IPv6 `http.server` processes and returned another run, so those processes were not disturbed. The retained `index.html` rendered two accepted sections; `long_edge_adjacent` displayed its operator, room IDs, exact before value, threshold, and after value; all six top-level images completed with non-zero natural dimensions (`1920x1080`).

For `alternative-01` floor 3 and `alternative-02` floor 3, the interactive flow `all-off -> enable rooms/core/envelope -> isolate core -> all-on` was run through the rendered controls. Each of 12 modeled layers changed visibility at every expected step and restored on `all-on`. Console errors: `0`; page errors: `0`.

## Remaining Facts And Soft Issues

- Unresolved regulatory facts: `effective_date`, `floor_code_context`, `jurisdiction`, `measured_travel_distance`, `travel_limit_classification`; `non_axis_aligned_polygon` remains additionally unresolved in `long_edge_adjacent` building-quality output. These remain unresolved, not approved regulatory findings.
- Residual soft issue for both alternatives: `wet_service_stack_ratio=0.0`, below threshold `0.7`.
- Environment limits: the pre-existing `RequestsDependencyWarning`, the initial CLI-test timeout described above, direct-literal decimal coercion in the brief assertion, and port 8765 occupancy. None required source changes.

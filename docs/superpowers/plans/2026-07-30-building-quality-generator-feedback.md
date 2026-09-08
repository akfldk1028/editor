# Building Quality Generator Feedback Plan

## Trigger And Target

Baseline evidence from `sample_mass_irregular_12v_setback_office` produced one
accepted alternative, not the required two. The first measured quality rejection
is `long_edge_adjacent: primary_daylight_ratio 0.662530965716 < 0.7`. Preserve
the policy threshold `0.7`; the goal is to produce at least two hard-pass,
quality-distinct alternatives on this fixture.

At commit `d095f4a`, the rejection already retains a structured quality report:
hard issue `primary_daylight_ratio`, floor `3`, subject `floor-3`, measured value
`0.6625309657157782`, threshold `0.7`, and candidate score `0.77`. The next work
consumes this report; it must not add a parallel rejection schema.

The feedback loop must consume structured evaluator failures, alter the next
candidate deterministically, and re-run the same evaluator. It must not infer
geometry from prose or turn hard failures into warnings.

## Implementation Order

1. Primary daylight feedback
   - Consume the retained `quality_report` and map `floor-3` to the affected
     primary-space allocation before candidate acceptance.
   - Reserve a valid window-bearing exterior edge for the primary space and
     deterministically grow, move, or split adjacent secondary allocation until
     the primary space visibly contacts that edge.
   - Re-evaluate the candidate and require ratio `>= 0.7`; append deterministic
     repair provenance and the measured before/after ratio to the existing
     rejection/report contract.
   - Cover the measured `long_edge_adjacent` failure in a regression test using
     the unchanged irregular fixture.

2. Room-form feedback
   - Convert a room-form failure into deterministic minimum-width and maximum-
     aspect repair operations while preserving the daylight reservation from
     step 1.
   - Re-run room-form checks after every repair and retain the original and
     repaired room identifiers and measurements.
   - Do not introduce a fixture-specific ratio exception. The current baseline
     has no room-form failure, so add a focused failing shape fixture as well.

3. Core, shaft, and service-stack feedback
   - Carry a stable vertical core/shaft anchor through floor composition and
     reserve wet-service positions relative to that anchor.
   - Treat the observed `wet_service_stack_ratio=0.0` and the rejected
     insufficient-core feasibility case as deterministic placement/size inputs,
     not threshold changes.
   - Require explicit before/after stack ratios and preserve the existing
     separated-stair and lobby feasibility constraints.

4. Checked egress feedback
   - Keep unresolved regulatory facts distinct from checked egress failures.
   - Once jurisdiction, effective date, floor-code context, travel measurement,
     and travel-limit classification are supplied, use the measured egress
     result to drive deterministic circulation/exit repairs.
   - Preserve the central strategy's `protected_exit_separation`,
     `remote_exit_unfit`, and governing-separation evidence. Do not claim an
     egress pass from the current unresolved screen.

5. Pairwise diversity feedback
   - Only after two candidates hard-pass, compare structural, core,
     circulation, and candidate PNG fingerprints pairwise.
   - When a pair duplicates, deterministically vary a meaningful planning
     decision while re-running steps 1-4. Do not count rendering-only variation
     as diversity.

## Acceptance Tests

- The irregular CLI exits `0` only with at least two hard-pass,
  quality-distinct alternatives.
- The existing structured rejection report remains backward-compatible and the
  repaired retry adds deterministic provenance plus before/after measurements.
- The existing quality policy version and thresholds remain unchanged.
- Focused quality, composer, CLI, visual-review, and full repository suites
  pass after implementation.
- Defer BIM/IFC property mapping until `BuildingQualityReport` is stable; do
  not couple IFC field names to this feedback iteration.

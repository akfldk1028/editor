# Building Quality Evaluation Design

## Goal

Improve generated irregular-mass floor plans from valid concept layouts into
measurably better basic-design candidates without coupling quality policy to
geometry generation.

The first release adds a deterministic building-quality evaluation boundary,
uses it to reject and rank alternatives, and exposes its evidence in retained
JSON, HTML, and PNG review artifacts. A later generation pass consumes the same
report as feedback. A BIM adapter then exports the accepted building through
IFC4 for Revit linking and opening. No quality claim may depend on an LLM
response.

## Current State

The repository already has strong floor-level evidence:

- `validator` checks boundary containment, overlap, program area, room shape,
  frontage, openings, circulation, basic-design elements, and regulatory
  evidence.
- `egress_graph` measures traversable routes when required context is present.
- `alternative_composer` produces distinct core and circulation families.
- `visual_review` renders architectural SVG, PNG, and interactive layered HTML.

The missing boundary is building-level quality. Multi-floor stacking, useful
daylight access, pairwise design diversity, and policy aggregation are either
represented by booleans or checked only in the review CLI. Adding more rules to
the 3,696-line validator would mix floor validity with building selection.

## Scope

### Included

- Area-weighted exterior-window access proxy for primary occupied spaces.
- Room-form aggregation using existing minimum-width and aspect-ratio evidence.
- Adjacent-floor core, shaft, restroom, and utility-stack overlap evidence.
- Building-level aggregation of internal egress and regulatory screening.
- Pairwise alternative diversity from core, circulation, adjacency, and room
  area-distribution evidence.
- Versioned hard gates and weighted quality scores.
- Alternative filtering and ordering through a public quality report.
- JSON, HTML, and PNG review evidence with exact measured values.
- Deterministic improvement feedback for the generator after the evaluator is
  proven independently.
- A neutral BIM snapshot and IFC4 export for every retained building.
- Stable IFC GUIDs and PLAN quality property sets for repeatable Revit linking.
- Automated IFC schema, hierarchy, geometry, and property validation.

### Excluded

- Solar exposure, glare, energy, or climate simulation.
- Structural member sizing and MEP engineering.
- Automatic jurisdiction selection or inferred legal facts.
- Construction-document or permit-compliance claims.
- LLM-generated geometry or LLM authority over hard quality gates.
- Native `.rvt` authoring without an installed and licensed Revit environment.
- Lossless IFC-to-native-Revit round trips.

## Architecture

Create one package with no import from `generation_loop`,
`alternative_composer`, `visual_review`, or CLI code:

```text
backend/app/modules/building_quality/
  __init__.py
  contracts.py
  daylight.py
  room_form.py
  vertical_stack.py
  egress.py
  diversity.py
  policy.py
  service.py
```

The package consumes immutable schema records and public validation evidence.
It may use shared geometry primitives, but it must not call a generator or
mutate a layout.

```text
BuildingGenerationResult + QualityPolicy
                         |
                         v
             evaluate_building_quality()
                         |
                         v
              BuildingQualityReport
                 /       |       \
                v        v        v
      alternative   review CLI   generation
       composer      artifacts    feedback
```

### Ownership

- `contracts.py`: immutable report types and input validation only.
- `daylight.py`: exterior contact and valid-window access measurements.
- `room_form.py`: aggregation of existing room-shape and usable-layout facts.
- `vertical_stack.py`: adjacent-floor overlap and displacement measurements.
- `egress.py`: aggregation of floor egress and regulatory evidence.
- `diversity.py`: pairwise comparison of accepted candidate geometry.
- `policy.py`: policy version, thresholds, weights, and score normalization.
- `service.py`: orchestration only; it contains no geometry algorithm.

## Public Contracts

```python
@dataclass(frozen=True)
class QualityPolicy:
    version: str
    minimum_floor_coverage: float
    minimum_primary_daylight_ratio: float
    minimum_room_form_pass_ratio: float
    minimum_core_stack_ratio: float
    minimum_service_stack_ratio: float
    minimum_pairwise_diversity: float
    weights: Mapping[str, float]


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: Literal["hard", "soft", "unresolved"]
    floor_index: int | None
    subject_id: str | None
    measured_value: float | None
    threshold: float | None
    message: str


@dataclass(frozen=True)
class FloorQualityMetrics:
    floor_index: int
    coverage: float
    primary_daylight_ratio: float
    room_form_pass_ratio: float
    egress_status: Literal["pass", "fail", "not_checked"]


@dataclass(frozen=True)
class VerticalQualityMetrics:
    core_stack_ratio: float
    shaft_stack_ratio: float
    wet_service_stack_ratio: float
    maximum_service_centroid_shift_m: float | None


@dataclass(frozen=True)
class BuildingQualityReport:
    policy_version: str
    hard_pass: bool
    score: float
    component_scores: Mapping[str, float]
    floors: tuple[FloorQualityMetrics, ...]
    vertical: VerticalQualityMetrics
    issues: tuple[QualityIssue, ...]
    unresolved_facts: tuple[str, ...]
```

Primary entry points:

```python
def evaluate_building_quality(
    building: BuildingGenerationResult,
    *,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> BuildingQualityReport: ...


def compare_building_diversity(
    first: BuildingGenerationResult,
    second: BuildingGenerationResult,
) -> AlternativeDiversityReport: ...
```

All maps exposed by frozen contracts are converted to read-only mappings during
construction. Every numeric field rejects booleans, NaN, infinity, and values
outside its documented range.

## Measurements

### Daylight Proxy

This is explicitly an exterior-window access proxy, not a daylight simulation.

Primary space types:

- Office: `open_work`, `meeting`, `focus`.
- Neighborhood commercial: `sales`.

For every primary room polygon:

1. Measure room area inside the floor boundary.
2. Confirm at least one valid window line is hosted by that room.
3. Confirm the window lies on a real room/floor exterior segment using the same
   geometric tolerance as the floor validator.
4. Count the room area as served only when both checks pass.

`primary_daylight_ratio = served_primary_area / total_primary_area`.

Missing primary area is a hard input error. A missing valid exterior window is
a measured quality failure, not an unresolved legal fact.

### Room Form

Reuse `ValidationReport.room_shapes`; do not recompute width or aspect ratio.

`room_form_pass_ratio` is the area-weighted share of non-core program rooms
whose `minimum_width_passed` and `aspect_ratio_passed` fields are both true.
Rooms without applicable limits remain in the denominator and pass only when
their geometry is measurable. Invalid or degenerate geometry is a hard issue.

The report also records the worst measured aspect ratio and the narrowest
measured room width for review output.

### Vertical Stack

Measure pairs of adjacent floors in world coordinates.

- Core stack: intersection over the smaller core area.
- Shaft stack: intersection over the smaller shaft footprint area.
- Wet-service stack: maximum matching overlap for `restroom`, `utility`, and
  `pantry` rooms, matched by stable space type and then minimum centroid shift.
- Service shift: maximum centroid distance among matched wet-service pairs.

When a floor omits a required shaft or core, its pair score is zero. A service
type absent from both floors is excluded. A service type present on only one
floor is a soft issue and scores zero for that pair.

The building metric is the minimum adjacent-floor ratio so one bad transition
cannot be hidden by averaging.

### Egress

Reuse each floor's `egress_graph` and `regulatory_screening`.

- Any checked regulatory failure is a hard issue.
- Missing internally required protected exits, disconnected routes, or failed
  internal separation evidence is a hard issue.
- Jurisdiction, effective date, sprinkler classification, and travel-limit
  classification remain unresolved unless explicitly supplied.
- A `not_checked` legal rule never becomes `pass` through scoring.

The concept-quality report may hard-pass with unresolved legal facts, but its
regulatory status remains `not_checked` and artifacts must display that state.

### Alternative Diversity

Pairwise diversity has four normalized components:

- Core: normalized centroid distance plus footprint symmetric difference.
- Circulation: graph-edge Jaccard distance plus orientation difference.
- Program topology: room-adjacency Jaccard distance.
- Area distribution: normalized distance between per-space-type area shares.

The total is the weighted mean of the four components. Two alternatives are
quality-distinct only when:

- total diversity meets the policy threshold; and
- at least two components are non-zero above geometric tolerance.

PNG hashes and serialized coordinate order are evidence, not diversity
criteria.

## Default Policy

The first policy is `building-quality/v1`:

| Metric | Threshold | Gate |
| --- | ---: | --- |
| Floor coverage | `>= 0.60` on every floor | hard |
| Primary daylight proxy | `>= 0.70` on every floor | hard |
| Room-form pass ratio | `>= 0.90` on every floor | hard |
| Core stack ratio | `>= 0.95` | hard |
| Shaft stack ratio | `>= 0.90` | hard |
| Wet-service stack ratio | `>= 0.70` | soft in v1 |
| Checked egress rule | must not fail | hard |
| Pairwise diversity | `>= 0.25` and two components | selection |

Score weights:

- daylight: `0.25`
- room form: `0.20`
- vertical stacking: `0.20`
- egress: `0.20`
- coverage and efficiency: `0.15`

Weights sum to `1.0`. Hard failure cannot be offset by a high weighted score.
Policy construction rejects duplicate components, missing components, negative
weights, or a sum different from `1.0` within `1e-9`.

## Integration

### Alternative Composer

`alternative_composer` evaluates a completed building through the public entry
point. It retains only `hard_pass` candidates, records exact rejection issues,
then performs pairwise diversity selection. Ranking is deterministic:

1. Hard-pass status.
2. Building-quality score descending.
3. Minimum pairwise diversity descending.
4. Existing structural fingerprint as the stable tie-breaker.

The composer does not import quality submodules directly.

### Review CLI

The irregular-alternatives aggregate JSON adds:

- `quality_policy_version`
- `building_quality`
- `pairwise_diversity`
- exact hard, soft, and unresolved issues

The comparison page shows the five component scores and vertical stack ratios.
Each floor caption shows daylight proxy and room-form ratio beside coverage.
PNG drawing geometry is unchanged by reporting.

### Generation Feedback

Only after the evaluator and integration tests are green, add deterministic
feedback operators:

- Move primary-space allocation toward available exterior cells when daylight
  proxy is low.
- Reserve vertically overlapping service bands before residual subdivision.
- Reject sliver cells that cannot satisfy the program node's form limits.
- Generate additional core/circulation families only when diversity selection
  leaves fewer than two candidates.

Operators receive issue codes and measurements, not the complete quality
service, so generation remains independent of policy implementation.

## Failure Handling

- Invalid report inputs raise typed contract errors.
- A measurable quality miss returns a report with issues; it does not raise.
- Geometry computation failure returns a hard `geometry_unmeasurable` issue
  with the subject and floor.
- Missing legal context returns unresolved facts and never invents defaults for
  a compliance claim.
- Alternative composition records quality rejection separately from generation
  failure.
- Review artifact generation exits non-zero when fewer than two hard-pass,
  quality-distinct candidates remain.

## Testing

Each module gets focused unit fixtures:

- Primary rooms with valid, missing, interior, and invalid windows.
- Wide, narrow, compact, elongated, and degenerate rooms.
- Fully aligned, partially aligned, shifted, missing, and setback floor stacks.
- Passed, failed, and unresolved egress evidence.
- Coordinate-order-equivalent plans and semantically different alternatives.
- Invalid policy thresholds and weights.

Integration fixtures:

1. Existing 12-vertex, three-floor setback office mass.
2. A rotated/notched orthogonal mass with reduced exterior frontage.
3. A floor stack whose restroom shifts while its core remains aligned.
4. Two coordinate-different but semantically equivalent alternatives.
5. Two genuinely different core/circulation/program alternatives.

Required verification:

- Focused RED/GREEN tests per module.
- Existing validator, generation, composer, CLI, and visual-review suites.
- Full `pytest -q`.
- Ruff and `git diff --check`.
- Retained before/after JSON and six 1920 x 1080 PNGs.
- Direct image inspection of every final floor and the comparison board.
- Playwright verification of retained HTML layers with zero console errors.

## BIM and IFC Boundary

IFC logic must not be copied into every planning or quality module. The domain
modules remain independent and expose their existing immutable schemas. Two
downstream packages own BIM conversion:

```text
backend/app/modules/bim_model/
  __init__.py
  contracts.py       vendor-neutral BIM snapshot types
  geometry.py        2D-to-3D extrusion and shared-edge derivation
  mapper.py          BuildingGenerationResult to BimProjectSnapshot
  properties.py      PLAN identity and quality property dictionaries
  service.py         public build_bim_snapshot() entry point

backend/app/modules/bim_ifc/
  __init__.py
  contracts.py       IFC export options and manifest types
  hierarchy.py       project/site/building/storey/space entities
  architecture.py    slab, wall, door, window, and opening entities
  structure.py       column and structural-grid entities
  circulation.py     stair, elevator, lobby, and route entities
  systems.py         shaft, restroom, and conceptual service-system entities
  properties.py      IFC property-set assignment
  writer.py          IfcOpenShell-backed IFC serialization
  validation.py      schema and Revit-profile validation
  service.py         public export_building_ifc() entry point
```

The dependency direction is:

```text
planning modules --------> schemas <-------- building_quality
                               ^
                               |
CLI --> bim_ifc --> bim_model -+
                      |
                      +---------------------> building_quality contracts
```

`bim_model` may consume `BuildingQualityReport` as optional evidence, but no
planner, generator, validator, or quality module may import `bim_model` or
`bim_ifc`.

### BIM Snapshot

`bim_model.contracts` defines immutable, vendor-neutral records:

```python
@dataclass(frozen=True)
class BimProjectSnapshot:
    project_id: str
    source_fingerprint: str
    length_unit: Literal["METRE"]
    storeys: tuple[BimStorey, ...]
    elements: tuple[BimElement, ...]
    property_sets: tuple[BimPropertySet, ...]


@dataclass(frozen=True)
class BimStorey:
    source_id: str
    name: str
    elevation_m: float
    height_m: float
    footprint: tuple[Point, ...]


@dataclass(frozen=True)
class BimElement:
    source_id: str
    storey_id: str
    element_type: Literal[
        "space",
        "slab",
        "wall",
        "door",
        "window",
        "stair",
        "elevator",
        "column",
        "shaft",
        "furniture",
        "fixture",
    ]
    geometry: BimGeometry
    host_id: str | None
    properties: Mapping[str, BimScalar]
```

Stable `source_id` values come from existing floor, room, opening, line, and
element IDs. Geometry changes alter `source_fingerprint` but do not arbitrarily
rename unchanged elements.

### IFC Mapping

The primary exchange schema is IFC4 Add2 TC1. IfcOpenShell identifies this as
the ISO-approved IFC4 version and recommends IFC4 for new projects. IFC2X3 may
be added later as an explicit compatibility profile; it is not the default.

The current workstation has IfcOpenShell `0.8.4.post1`, so IFC authoring and
schema validation can run locally. Revit 2024, 2025, and 2026 are not installed;
therefore this workstation cannot claim `revit_open_verified`.

Spatial hierarchy:

```text
IfcProject
  IfcSite
    IfcBuilding
      IfcBuildingStorey
        IfcSpace
        physical elements
```

Entity mapping:

| PLAN element | IFC entity |
| --- | --- |
| Floor footprint | `IfcSlab` |
| Derived partition/exterior wall | `IfcWall` |
| Room/program polygon | `IfcSpace` |
| Door opening and leaf | `IfcOpeningElement` + `IfcDoor` |
| Exterior window | `IfcOpeningElement` + `IfcWindow` |
| Stair | `IfcStair` with flights and landings where available |
| Elevator | `IfcTransportElement` |
| Column | `IfcColumn` |
| Shaft | `IfcSpace` with `ObjectType="SHAFT"` |
| Furniture | `IfcFurniture` |
| Fixture | closest standard distribution or furnishing class |
| Conceptual plumbing stack | `IfcDistributionSystem` relationships |

`IfcBuildingElementProxy` is allowed only when no standard IFC class applies.
Every fallback records the original PLAN kind and fallback reason.

Geometry uses metre units, storey-local placements, and extruded solids for
spaces, slabs, walls, columns, and simple equipment. Doors and windows are
hosted through opening relationships. Elements are contained by exactly one
`IfcBuildingStorey`; spaces are decomposed under their storey.

### Revit Compatibility Profile

The supported workflow is Revit `Link IFC` or `Open IFC`. Revit creates an
intermediate IFC-based RVT for linked models; linked IFC content remains
reference-oriented rather than fully native editable Revit geometry.

The `revit-2026-link` export profile requires:

- IFC4 schema.
- Project, site, building, storey, and space hierarchy.
- Standard IFC classes instead of generic proxies wherever possible.
- Stable deterministic IFC GUIDs derived from project and source element IDs.
- Origin-to-origin coordinates with an explicit project origin.
- Storey-local placements and consistent floor elevations.
- Body representations for visible 3D elements.
- Standard `Name`, `Tag`, and `ObjectType` values.
- `Pset_PLAN_Identity` with source ID, source fingerprint, floor index, and
  generator version.
- `Pset_PLAN_Quality` with quality policy, hard-pass state, measured scores,
  and unresolved-fact count.
- A sidecar manifest recording IFC schema, export profile, element counts,
  fallback proxies, warnings, and SHA-256.

Native RVT creation is a separate future `revit_bridge` adapter that requires
Revit API execution on Windows. It must consume `BimProjectSnapshot`, not PLAN
generator internals.

### IFC Validation

`bim_ifc.validation` performs deterministic checks before reporting success:

1. Run IfcOpenShell schema validation.
2. Re-open the written file and verify the expected schema.
3. Verify one project, site, and building.
4. Verify storey count, order, elevations, and containment.
5. Verify every PLAN room became one `IfcSpace`.
6. Verify required slabs, walls, doors, windows, stairs, and columns by stable
   source IDs.
7. Verify all rooted products have unique, stable IFC GUIDs.
8. Verify no element is outside its storey footprint or elevation range.
9. Verify PLAN identity and quality property sets round-trip.
10. Reject missing geometry, orphan openings, invalid hosts, and duplicate
    containment.

When Revit is available locally, a separate smoke test links the generated IFC
through the Revit API and records the import log, category counts, and a 3D-view
capture. Without Revit, the exporter may claim `ifc_validated` but not
`revit_open_verified`.

### Authoritative References

- buildingSMART IFC 4.3 spatial decomposition:
  `https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/concepts/Object_Composition/Aggregation/Spatial_Decomposition/content.html`
- buildingSMART `IfcBuildingStorey`:
  `https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcBuildingStorey.htm`
- Autodesk Revit 2026 Link IFC:
  `https://help.autodesk.com/cloudhelp/2026/ENU/Revit-Model/files/GUID-DE8B322A-A507-4E03-93EC-AA21F354E43B.htm`
- Autodesk Revit IFC linking behavior:
  `https://help.autodesk.com/cloudhelp/2026/ENU/Revit-Model/files/GUID-BAA2ED9C-5107-4F21-ABE1-1ACF609AEEE3.htm`
- IfcOpenShell high-level authoring API:
  `https://docs.ifcopenshell.org/autoapi/ifcopenshell/api/index.html`
- IfcOpenShell project creation and supported schemas:
  `https://docs.ifcopenshell.org/autoapi/ifcopenshell/api/project/index.html`

## Delivery Sequence

1. Contracts, policy, and evaluator measurements.
2. Alternative composer filtering, ranking, and diversity.
3. Review JSON/HTML evidence.
4. Deterministic generation feedback operators.
5. Neutral BIM snapshot and IFC4 exporter.
6. IFC validation and optional installed-Revit link smoke test.
7. Irregular-mass real run, PNG/IFC comparison, independent review, and full
   suite.

Each sequence item is a separate commit and may be reverted without changing
the public schemas of preceding items.

## Acceptance Criteria

- At least two hard-pass, pairwise quality-distinct alternatives are retained
  for the existing three-floor irregular office fixture.
- Every retained floor has coverage at least `0.60`, daylight proxy at least
  `0.70`, and room-form pass ratio at least `0.90`.
- Core and shaft stack thresholds pass; wet-service stack evidence is reported.
- Checked egress failures reject candidates; unresolved law remains visible.
- All quality values in HTML match aggregate JSON exactly.
- Each retained alternative includes one IFC4 file and export manifest.
- IFC validation passes with no schema, hierarchy, GUID, containment, or
  required-property errors.
- Re-exporting unchanged input preserves every element GUID and file semantics.
- Revit compatibility is reported as `revit_open_verified` only after an
  installed-Revit smoke test; otherwise it remains `ifc_validated`.
- The post-change comparison preserves explicit F1-F3 boundaries and visibly
  improves any pre-change failing quality component.
- Existing module ownership remains acyclic and no generator imports
  `building_quality`, `bim_model`, or `bim_ifc`.

# BIM IFC Revit Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a deterministic, vendor-neutral PLAN building snapshot as validated IFC4 that Revit 2026 can Link/Open, while making no native RVT or installed-Revit verification claim.

**Architecture:** `bim_model` maps immutable PLAN schemas and optional `BuildingQualityReport` evidence into a frozen snapshot without importing IfcOpenShell. `bim_ifc` is the only IfcOpenShell owner: it writes IFC4 hierarchy, bodies, hosted openings, standard entities, property sets, manifests, and validation evidence. The CLI composes these public entry points; no planner, generator, validator, or quality module imports either downstream package.

**Tech Stack:** Python 3.11+, frozen dataclasses, Shapely 2.1+ only through existing geometry helpers, IfcOpenShell `0.8.4.post1`, NumPy 2.x, pytest, Ruff, IFC4 Add2 TC1, Revit 2026 Link/Open compatibility profile.

## Global Constraints

- Start from `07c8ea8cbe18f2b0ec60840fe7bdc35f58f4a7ec`.
- Preserve `planning modules -> schemas <- building_quality`, `CLI -> bim_ifc -> bim_model -> schemas`, and optional `bim_model -> building_quality contracts`.
- `bim_model` must import and run without IfcOpenShell installed.
- No planner, generator, validator, alternative composer, or quality module may import `bim_model` or `bim_ifc`.
- Do not modify current PLAN generator schemas to carry IFC-specific names or objects.
- Use IFC4 Add2 TC1 through `ifcopenshell.api.project.create_file(version="IFC4")`.
- Support only `revit-2026-link` in v1. It means Revit Link IFC/Open IFC compatibility, not native RVT authoring.
- This workstation has no Revit 2024, 2025, or 2026. Every local export must report `ifc_validated`; it must report `revit_open_verified=false`.
- A future installed-Revit adapter belongs in `revit_bridge` and consumes `BimProjectSnapshot`; it is not part of this plan.
- Use metre units, origin `(0.0, 0.0, 0.0)`, storey-local placements, explicit storey elevations, and visible Body representations.
- Preserve every existing floor-specific footprint from `GenerationResult.floor_boundary`, falling back to `MassAnalysis.boundary_for_floor()` only for legacy inputs.
- Preserve existing room, opening, line, and element identities inside storey-qualified `source_id` values. Geometry changes may change `source_fingerprint` but must not rename unchanged source-backed elements; a derived wall ID changes only when its atomic source segment changes.
- Derive all IFC product GUIDs deterministically from project ID plus source ID. Never call `ifcopenshell.guid.new()` for a product.
- Map to standard IFC classes. `IfcBuildingElementProxy` is allowed only for an unsupported PLAN kind and must carry `OriginalPLANKind` and `FallbackReason`.
- Export rooms, the core zone, circulation/lobby spaces, slabs, walls, doors, windows, stairs with flights/landings when available, elevators, shafts, columns, furniture, fixtures, and a conceptual wet-service system.
- Keep `Pset_PLAN_Identity/v1` and `Pset_PLAN_Quality/building-quality-v1` field names stable once Task 4 is committed.
- Validate the written file with IfcOpenShell, reopen it from disk, inspect the reopened model, and fail export on schema, hierarchy, GUID, geometry, host, property, or containment errors.
- Do not claim Revit compatibility from schema validation alone.
- Use TDD for every behavior change. Each task ends with focused tests and one reviewable commit.
- Leave unrelated worktree changes and generated files untouched.

## Verified Local IfcOpenShell Surface

The plan was authored after safe import/introspection against the current
interpreter:

```text
ifcopenshell.__version__ = 0.8.4.post1
ifcopenshell.api.project.create_file(version: "IFC2X3" | "IFC4" | "IFC4X3")
ifcopenshell.api.root.create_entity(file, ifc_class, predefined_type, name)
ifcopenshell.api.aggregate.assign_object(file, products, relating_object)
ifcopenshell.api.spatial.assign_container(file, products, relating_structure)
ifcopenshell.api.context.add_context(file, ...)
ifcopenshell.api.profile.add_arbitrary_profile(file, profile, name)
ifcopenshell.api.geometry.add_profile_representation(file, context, profile, depth, ...)
ifcopenshell.api.geometry.assign_representation(file, product, representation)
ifcopenshell.api.geometry.edit_object_placement(file, product, matrix, is_si=True)
ifcopenshell.api.feature.add_feature(file, feature, element)
ifcopenshell.api.feature.add_filling(file, opening, element)
ifcopenshell.api.pset.add_pset(file, product, name)
ifcopenshell.api.pset.edit_pset(file, pset, properties)
ifcopenshell.api.system.add_system(file, ifc_class="IfcDistributionSystem")
ifcopenshell.api.system.assign_system(file, products, system)
ifcopenshell.validate.validate(file_or_path, json_logger, express_rules=False)
ifcopenshell.geom.create_shape(settings, entity)
ifcopenshell.util.shape.get_vertices(geometry)
```

An in-memory IFC4 project/site/building/storey/slab with a Body representation,
metre units, containment, deterministic GUID, and `Pset_PLAN_Identity` produced
zero `express_rules=True` validation statements. Do not substitute unverified
API spellings during implementation.

## File Ownership Map

```text
backend/app/modules/bim_model/
  __init__.py       public neutral API only
  contracts.py      frozen vendor-neutral records and validation
  geometry.py       canonical rings, wall strips, extrusion records, source IDs
  mapper.py         PLAN result to neutral storeys/elements
  properties.py     exact PLAN identity and building-quality v1 dictionaries
  service.py        build_bim_snapshot()

backend/app/modules/bim_ifc/
  __init__.py       public export API; no eager IfcOpenShell import
  contracts.py      options, manifest, inventory, validation records/errors
  hierarchy.py      project/site/building/storey/space creation
  architecture.py   slabs, walls, doors/windows, openings, furniture/fixtures
  structure.py      columns and column-derived IfcGrid
  circulation.py    IfcStair, flights, landings, elevator
  systems.py        shafts and conceptual wet-service system relationships
  properties.py     IFC pset creation and reopened-file property extraction
  writer.py         lazy dependency load, write context, bodies, placements, GUIDs
  validation.py     schema/reopen/profile/geometry/round-trip validation
  service.py        export_building_ifc()

backend/tests/
  bim_fixtures.py
  test_bim_model_contracts.py
  test_bim_model_geometry.py
  test_bim_model_mapper.py
  test_bim_model_properties.py
  test_bim_ifc_dependency.py
  test_bim_ifc_hierarchy.py
  test_bim_ifc_architecture.py
  test_bim_ifc_circulation_systems.py
  test_bim_ifc_properties.py
  test_bim_ifc_validation.py
  test_bim_ifc_service.py
  test_bim_ifc_cli.py
  test_module_boundaries.py
```

---

### Task 1: Neutral BIM Contracts and Shared Test Fixture

**Files:**
- Create: `backend/app/modules/bim_model/__init__.py`
- Create: `backend/app/modules/bim_model/contracts.py`
- Create: `backend/tests/bim_fixtures.py`
- Create: `backend/tests/test_bim_model_contracts.py`

**Interfaces:**
- Produces: `BimScalar`, `BimExtrusion`, `BimStairPart`, `BimStairAssembly`, `BimGeometry`, `BimStorey`, `BimElement`, `BimPropertySet`, `BimProjectSnapshot`.
- Produces: `make_bim_building()` and `make_bim_quality_report()` test factories.
- Consumes: `Point` from `backend.app.schemas.mass`; no IFC type or import.

- [ ] **Step 1: Write failing immutable-contract tests**

```python
def test_snapshot_contract_is_frozen_vendor_neutral_and_ordered():
    snapshot = make_snapshot()

    assert snapshot.length_unit == "METRE"
    assert tuple(storey.floor_index for storey in snapshot.storeys) == (1, 2)
    assert snapshot.project_origin == (0.0, 0.0, 0.0)
    assert "ifcopenshell" not in sys.modules
    with pytest.raises(FrozenInstanceError):
        snapshot.project_id = "changed"


@pytest.mark.parametrize("value", [True, math.nan, math.inf, -0.1])
def test_extrusion_rejects_invalid_depth(value):
    with pytest.raises((TypeError, ValueError)):
        BimExtrusion(
            footprint=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
            base_offset_m=0.0,
            depth_m=value,
        )


def test_element_rejects_unknown_type_duplicate_source_or_cross_storey_host():
    with pytest.raises(ValueError, match="element_type"):
        replace(element(), element_type="grid")
    with pytest.raises(ValueError, match="unique source_id"):
        replace(make_snapshot(), elements=(element(), element()))
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_model_contracts.py
```

Expected: collection fails because `backend.app.modules.bim_model` does not
exist.

- [ ] **Step 3: Implement the exact neutral records**

```python
BimScalar = str | int | float | bool
ElementType = Literal[
    "space", "slab", "wall", "door", "window", "stair", "elevator",
    "column", "shaft", "furniture", "fixture",
]


@dataclass(frozen=True)
class BimExtrusion:
    footprint: tuple[Point, ...]
    base_offset_m: float
    depth_m: float


@dataclass(frozen=True)
class BimStairPart:
    source_id: str
    part_type: Literal["flight", "landing"]
    footprint: tuple[Point, ...]
    base_offset_m: float
    top_offset_m: float
    riser_count: int | None = None
    tread_count: int | None = None
    tread_depth_m: float | None = None


@dataclass(frozen=True)
class BimStairAssembly:
    enclosure: BimExtrusion
    parts: tuple[BimStairPart, ...]


BimGeometry = BimExtrusion | BimStairAssembly


@dataclass(frozen=True)
class BimStorey:
    source_id: str
    floor_index: int
    name: str
    elevation_m: float
    height_m: float
    footprint: tuple[Point, ...]


@dataclass(frozen=True)
class BimElement:
    source_id: str
    storey_id: str
    element_type: ElementType
    geometry: BimGeometry
    host_id: str | None
    name: str
    properties: Mapping[str, BimScalar]


@dataclass(frozen=True)
class BimPropertySet:
    name: Literal["Pset_PLAN_Identity", "Pset_PLAN_Quality"]
    schema_version: str
    target_source_ids: tuple[str, ...]
    properties: Mapping[str, BimScalar]


@dataclass(frozen=True)
class BimProjectSnapshot:
    project_id: str
    source_fingerprint: str
    length_unit: Literal["METRE"]
    project_origin: tuple[float, float, float]
    storeys: tuple[BimStorey, ...]
    elements: tuple[BimElement, ...]
    property_sets: tuple[BimPropertySet, ...]
```

Validate non-empty strings, finite non-boolean numerics, positive areas/depths,
strict storey order, unique storey and element IDs, valid host references, host
and hosted element storey equality, target existence, immutable copied property
maps, and stair-part elevation/count consistency. Property targets may use the
reserved spatial IDs `project` and `building` in addition to storey/element
source IDs. Allow a `shaft` or `space` to overlap the source core zone because
the existing concept model records both a core zone and nested functional
spaces.

- [ ] **Step 4: Add realistic but fast fixture factories**

`make_bim_building()` must produce two floors with different polygon
footprints, `RoomPolygon` rooms/circulation, validated doors, window and entrance
lines, two stairs with `StairGeometry`, elevator, shaft, lobby, columns,
furniture, fixtures, and a `BuildingGenerationResult`. Reuse public schema
constructors; do not invoke the real generator in unit tests.

`make_bim_quality_report()` must expose every current
`BuildingQualityReport` field with policy `building-quality/v1` and ordered
floor metrics.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_model_contracts.py
python -m ruff check backend/app/modules/bim_model backend/tests/bim_fixtures.py backend/tests/test_bim_model_contracts.py
git diff --check
git add backend/app/modules/bim_model backend/tests/bim_fixtures.py backend/tests/test_bim_model_contracts.py
git commit -m "feat: define neutral BIM snapshot contracts"
```

---

### Task 2: Canonical Geometry, Wall Derivation, and Stable Source Identity

**Files:**
- Create: `backend/app/modules/bim_model/geometry.py`
- Create: `backend/tests/test_bim_model_geometry.py`

**Interfaces:**
- Consumes: neutral contract types from Task 1.
- Produces: `canonical_ring(points: Iterable[Point]) -> tuple[Point, ...]`.
- Produces: `storey_source_id(floor_index: int) -> str`, `element_source_id(floor_index: int, element_type: str, existing_id: str) -> str`, and `segment_source_id(floor_index: int, segment: tuple[Point, Point]) -> str`.
- Produces: `derive_wall_extrusions(*, storey_id: str, floor_index: int, floor_boundary: tuple[Point, ...], spaces: Mapping[str, tuple[Point, ...]], wall_thickness_m: float, wall_height_m: float) -> tuple[BimElement, ...]`.
- Produces: `point_in_polygon_or_boundary(point: Point, polygon: tuple[Point, ...], tolerance: float = 1e-7) -> bool`.
- Produces: `geometry_fingerprint(storeys: tuple[BimStorey, ...], elements: tuple[BimElement, ...]) -> str`.

- [ ] **Step 1: Write failing geometry and identity tests**

```python
def test_canonical_ring_ignores_closing_vertex_rotation_and_winding():
    assert canonical_ring(((0, 0), (4, 0), (4, 3), (0, 3))) == canonical_ring(
        ((4, 3), (4, 0), (0, 0), (0, 3), (4, 3))
    )


def test_wall_derivation_splits_partial_shared_edges_and_deduplicates():
    result = derive_wall_extrusions(
        storey_id="storey:f001",
        floor_index=1,
        floor_boundary=((0, 0), (8, 0), (8, 4), (0, 4)),
        spaces={
            "room-a": ((0, 0), (4, 0), (4, 4), (0, 4)),
            "room-b": ((4, 0), (8, 0), (8, 2), (4, 2)),
            "path": ((4, 2), (8, 2), (8, 4), (4, 4)),
        },
        wall_thickness_m=0.20,
        wall_height_m=3.40,
    )

    assert len({wall.source_id for wall in result}) == len(result)
    assert sum(wall.properties["WallRole"] == "INTERIOR" for wall in result) > 0
    assert all(
        point_in_polygon_or_boundary(point, ((0, 0), (8, 0), (8, 4), (0, 4)))
        for wall in result
        for point in wall.geometry.footprint
    )


def test_geometry_fingerprint_changes_geometry_not_source_ids():
    first = mapped_elements(room_width=4.0)
    second = mapped_elements(room_width=4.5)

    assert tuple(item.source_id for item in first if item.element_type != "wall") == tuple(
        item.source_id for item in second if item.element_type != "wall"
    )
    assert geometry_fingerprint(fixture_storeys(), first) != geometry_fingerprint(
        fixture_storeys(), second
    )
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_model_geometry.py
```

Expected: import failure for `bim_model.geometry`.

- [ ] **Step 3: Implement canonical identity and pure-data geometry**

Use exact source ID forms:

```text
storey:f001
f001:space:<existing room/path/element id>
f001:slab:floor
f001:wall:<sha256 of canonical atomic segment, first 16 hex>
f001:door:<existing opening or line id>
f001:window:<existing line id>
f001:<element_type>:<existing PlanElement.element_id>
```

Normalize rings by removing one repeated closing vertex, converting to
counter-clockwise orientation, choosing the lexicographically smallest rotation,
and rounding coordinates to 9 decimal places only for identity serialization.
Keep full finite float values in geometry.

For walls:

1. Collect edges from every room, circulation polygon, and lobby polygon.
2. Put every collinear endpoint on the same scalar axis and split into atomic
   non-zero segments.
3. Deduplicate canonical endpoint pairs.
4. Classify an atomic segment as `EXTERIOR` when its midpoint and endpoints lie
   on the floor boundary, otherwise as `INTERIOR`.
5. Build exterior strips toward the floor interior and interior strips centered
   on the segment.
6. Reject a strip if any vertex falls outside the floor boundary within `1e-7`.
7. Sort by `(wall role, start x, start y, end x, end y)`.

`geometry_fingerprint()` is SHA-256 of canonical JSON containing storeys,
element source IDs/types/hosts, full geometry, and semantic properties. Exclude
quality property values and output paths.

- [ ] **Step 4: Verify diagonal and concave fixture behavior**

Add a 12-vertex floor test using floor 1 from
`sample_mass_irregular_12v_setback_office.json`. Assert exterior strips stay in
the polygon, every wall has positive area, repeated runs are equal, and reversed
input winding changes neither IDs nor geometry fingerprint.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_model_geometry.py
python -m ruff check backend/app/modules/bim_model/geometry.py backend/tests/test_bim_model_geometry.py
git diff --check
git add backend/app/modules/bim_model/geometry.py backend/tests/test_bim_model_geometry.py
git commit -m "feat: derive deterministic BIM geometry"
```

---

### Task 3: Complete PLAN-to-BIM Mapper

**Files:**
- Create: `backend/app/modules/bim_model/mapper.py`
- Create: `backend/tests/test_bim_model_mapper.py`

**Interfaces:**
- Consumes: `BuildingGenerationResult`, current `LayoutCandidate`,
  `BasicDesignFeatures`, and Task 2 geometry helpers.
- Produces: `map_building_to_bim(building, *, default_storey_height_m=3.6) -> tuple[tuple[BimStorey, ...], tuple[BimElement, ...]]`.

- [ ] **Step 1: Write a failing complete-inventory mapper test**

```python
def test_mapper_preserves_varying_storeys_and_complete_plan_inventory():
    storeys, elements = map_building_to_bim(make_bim_building())

    assert [item.footprint for item in storeys] == [
        ((0.0, 0.0), (20.0, 0.0), (20.0, 12.0), (0.0, 12.0)),
        ((2.0, 1.0), (18.0, 1.0), (18.0, 11.0), (2.0, 11.0)),
    ]
    assert [item.elevation_m for item in storeys] == [0.0, 3.6]
    assert {
        "space", "slab", "wall", "door", "window", "stair", "elevator",
        "column", "shaft", "furniture", "fixture",
    } <= {item.element_type for item in elements}
    assert sum(item.element_type == "space" for item in elements) == (
        sum(len(floor.layout.rooms) + len(floor.layout.circulation)
            for floor in make_bim_building().floor_results)
        + 2  # one core lobby per storey
    )
```

Add focused tests for:

- every `layout.openings` door and `entrance`, `stair_door`, and
  `protected_exit` line becoming a hosted door;
- every `window` line becoming a hosted window;
- stairs preserving flights, landings, risers, treads, and local elevations;
- `elevator`, `shaft`, `column`, `furniture`, and `fixture` PlanElement mapping;
- `wc`, `lavatory`, and `sink` retaining `PLANKind`;
- missing `BasicDesignFeatures`, unresolved door/window host, invalid
  floor-boundary source, or an unsupported required element raising
  `BimMappingError` with floor and source ID.

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_model_mapper.py
```

Expected: import failure for `map_building_to_bim`.

- [ ] **Step 3: Implement exact mapping rules**

Use these elevations and depths:

```python
height = (
    building.mass.building_code_context.floor_to_floor_height_m
    if building.mass.building_code_context
    and building.mass.building_code_context.floor_to_floor_height_m is not None
    else first_stair_height_on_floor
    if first_stair_height_on_floor is not None
    else default_storey_height_m
)
elevation = sum(previous_storey_heights)
slab_depth = 0.20
wall_height = max(height - slab_depth, 0.10)
space_height = wall_height
column_height = wall_height
door_height = 2.10
window_sill = 0.90
window_height = min(1.50, wall_height - window_sill)
```

Map rooms first, including the existing `core` room, then circulation polygons,
then the core-lobby PlanElement as `space`. Map the shaft as `shaft`, not as a
generic fixture. Map room objects by their existing category:

```text
category=furniture -> furniture
category=fixture   -> fixture
kind=column        -> column
kind=stair         -> stair
kind=elevator      -> elevator
kind=shaft         -> shaft
kind=lobby         -> space
```

Use a 0.05 m thick segment footprint for door/window bodies. Store
`OpeningWidth`, `OpeningHeight`, `SillHeight`, `PLANKind`, `PLANCategory`,
`OriginalHostId`, `FloorIndex`, and `HeightSource` in neutral properties.
Resolve a door/window host to exactly one derived wall using segment containment;
raise instead of silently emitting an orphan opening.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_model_mapper.py
python -m pytest -q backend/tests/test_basic_design.py backend/tests/test_basic_design_validation.py
python -m ruff check backend/app/modules/bim_model/mapper.py backend/tests/test_bim_model_mapper.py
git diff --check
git add backend/app/modules/bim_model/mapper.py backend/tests/test_bim_model_mapper.py
git commit -m "feat: map PLAN buildings to neutral BIM"
```

---

### Task 4: Stable Identity and Building-Quality v1 Property Dictionaries

**Files:**
- Create: `backend/app/modules/bim_model/properties.py`
- Create: `backend/app/modules/bim_model/service.py`
- Modify: `backend/app/modules/bim_model/__init__.py`
- Create: `backend/tests/test_bim_model_properties.py`

**Interfaces:**
- Consumes: `BuildingGenerationResult`, optional `BuildingQualityReport`, Task 3 mapper.
- Produces: `identity_property_sets(*, project_id: str, source_fingerprint: str, generator_version: str, storeys: tuple[BimStorey, ...], elements: tuple[BimElement, ...]) -> tuple[BimPropertySet, ...]`.
- Produces: `quality_property_sets(quality: BuildingQualityReport, storeys: tuple[BimStorey, ...]) -> tuple[BimPropertySet, ...]`.
- Produces: `build_bim_snapshot(building, *, quality=None, generator_version="plan/0.1.0", default_storey_height_m=3.6) -> BimProjectSnapshot`.

- [ ] **Step 1: Write failing stable-wire tests**

```python
def test_building_quality_v1_property_wire_is_exact_and_frozen():
    snapshot = build_bim_snapshot(
        make_bim_building(),
        quality=make_bim_quality_report(),
        generator_version="plan/0.1.0",
    )
    building = pset(snapshot, "Pset_PLAN_Quality", "building")

    assert building.schema_version == "Pset_PLAN_Quality/building-quality-v1"
    assert building.properties == {
        "PropertySchemaVersion": "Pset_PLAN_Quality/building-quality-v1",
        "QualityScope": "BUILDING",
        "QualityPolicyVersion": "building-quality/v1",
        "HardPass": True,
        "Score": 0.8,
        "DaylightScore": 0.8,
        "RoomFormScore": 0.9,
        "VerticalStackingScore": 0.85,
        "EgressScore": 0.75,
        "CoverageEfficiencyScore": 0.7,
        "CoreStackRatio": 1.0,
        "ShaftStackRatio": 1.0,
        "WetServiceStackRatio": 0.8,
        "UnresolvedFactCount": 0,
    }


def test_identity_wire_targets_every_storey_and_element():
    snapshot = build_bim_snapshot(make_bim_building())
    identity = [p for p in snapshot.property_sets if p.name == "Pset_PLAN_Identity"]

    assert {target for p in identity for target in p.target_source_ids} == {
        *(storey.source_id for storey in snapshot.storeys),
        *(element.source_id for element in snapshot.elements),
        "project",
        "building",
    }
    assert all(p.properties["SourceFingerprint"] == snapshot.source_fingerprint
               for p in identity)
```

Also assert one storey-scoped quality set per `FloorQualityMetrics` with the
exact keys:

```text
PropertySchemaVersion, QualityScope, QualityPolicyVersion, FloorIndex, FloorCoverage,
PrimaryDaylightRatio, RoomFormPassRatio, WorstAspectRatio,
NarrowestRoomWidth, EgressStatus
```

When `quality=None`, emit identity sets only. Reject a quality floor index not
present in the building rather than dropping it. Serialize an optional measured
numeric field as the exact string `NOT_MEASURED` when its report value is
`None`; do not omit stable v1 keys or invent a numeric value.

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_model_properties.py
```

Expected: import failure for `build_bim_snapshot`.

- [ ] **Step 3: Implement the snapshot service**

Build storeys/elements, compute a geometry-only fingerprint, then create
property sets using that final fingerprint. Set identity fields exactly:

```text
IdentitySchemaVersion = Pset_PLAN_Identity/v1
SourceId
SourceFingerprint
FloorIndex
GeneratorVersion
PLANKind
```

Use `FloorIndex=0` and `PLANKind=PROJECT` for the project target and
`PLANKind=BUILDING` for the building target. For a storey use
`PLANKind=STOREY`; for an element use its original kind when available and
otherwise its neutral element type. The building-quality property set targets
the reserved `building` ID.

- [ ] **Step 4: Verify neutral optional-dependency behavior**

Run this in a fresh interpreter before IfcOpenShell work starts:

```powershell
python -c "from backend.app.modules.bim_model import build_bim_snapshot; import sys; assert 'ifcopenshell' not in sys.modules"
```

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_model_contracts.py backend/tests/test_bim_model_geometry.py backend/tests/test_bim_model_mapper.py backend/tests/test_bim_model_properties.py
python -m ruff check backend/app/modules/bim_model backend/tests/test_bim_model_contracts.py backend/tests/test_bim_model_geometry.py backend/tests/test_bim_model_mapper.py backend/tests/test_bim_model_properties.py
git diff --check
git add backend/app/modules/bim_model backend/tests/test_bim_model_properties.py
git commit -m "feat: version BIM identity and quality properties"
```

---

### Task 5: Optional IFC Dependency, Export Contracts, Writer Foundation, and Hierarchy

**Files:**
- Modify: `pyproject.toml`
- Create: `backend/app/modules/bim_ifc/__init__.py`
- Create: `backend/app/modules/bim_ifc/contracts.py`
- Create: `backend/app/modules/bim_ifc/writer.py`
- Create: `backend/app/modules/bim_ifc/hierarchy.py`
- Modify: `backend/tests/bim_fixtures.py`
- Create: `backend/tests/test_bim_ifc_dependency.py`
- Create: `backend/tests/test_bim_ifc_hierarchy.py`

**Interfaces:**
- Produces: `IfcDependencyError`, `IfcExportError`, `IfcExportOptions`,
  `IfcEntityInventory`, `IfcValidationIssue`, `IfcValidationReport`,
  `IfcExportManifest`, `IfcExportArtifacts`.
- Produces: `require_ifcopenshell()`, `deterministic_ifc_guid()`,
  `create_write_context()`, `create_spatial_hierarchy()`.
- `IfcWriteContext` is internal and owns the IFC file, model/body contexts,
  project/site/building/storey entities, and `source_entities`. The map includes
  reserved keys `project` and `building`.
- Test helper: `build_fixture_snapshot(*, quality: bool = True) -> BimProjectSnapshot`.

- [ ] **Step 1: Write failing dependency and contract tests**

```python
def test_bim_ifc_import_is_lazy():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import backend.app.modules.bim_ifc; "
                "assert 'ifcopenshell' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_missing_optional_dependency_has_install_instruction(monkeypatch):
    monkeypatch.setattr(
        writer,
        "import_module",
        Mock(side_effect=ModuleNotFoundError("ifcopenshell")),
    )
    with pytest.raises(IfcDependencyError, match=r"pip install -e .\[ifc\]"):
        writer.require_ifcopenshell()


def test_deterministic_guid_is_ifc_compressed_and_source_stable():
    first = deterministic_ifc_guid("project-a", "f001:space:open-work")
    assert first == deterministic_ifc_guid("project-a", "f001:space:open-work")
    assert len(first) == 22
    assert first != deterministic_ifc_guid("project-a", "f002:space:open-work")
```

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py
```

Expected: import failure because `bim_ifc` does not exist.

- [ ] **Step 3: Add the optional dependency group**

```toml
[project.optional-dependencies]
ifc = [
    "ifcopenshell==0.8.4.post1",
    "numpy>=2,<3",
]
```

Do not add either package to base dependencies. Import IfcOpenShell and NumPy
through `import_module()` inside export calls, never at module import time.
Also register this marker in the existing `[tool.pytest.ini_options]` table:

```toml
markers = [
    "ifc_integration: runs real IfcOpenShell disk export and reopen",
]
```

- [ ] **Step 4: Define exact export records**

```python
@dataclass(frozen=True)
class IfcExportOptions:
    schema: Literal["IFC4"] = "IFC4"
    profile: Literal["revit-2026-link"] = "revit-2026-link"
    validate: bool = True
    geometry_tolerance_m: float = 1e-6


@dataclass(frozen=True)
class IfcEntityInventory:
    counts: Mapping[str, int]
    source_to_ifc_class: Mapping[str, str]


@dataclass(frozen=True)
class IfcValidationIssue:
    code: str
    severity: Literal["error", "warning"]
    source_id: str | None
    message: str


@dataclass(frozen=True)
class IfcValidationReport:
    schema: str
    profile: str
    ifc_validated: bool
    revit_open_verified: bool
    issues: tuple[IfcValidationIssue, ...]
    inventory: IfcEntityInventory


@dataclass(frozen=True)
class IfcExportManifest:
    manifest_schema_version: Literal["plan-ifc-manifest/v1"]
    project_id: str
    source_fingerprint: str
    ifc_schema: str
    export_profile: str
    ifcopenshell_version: str
    ifc_sha256: str
    inventory: IfcEntityInventory
    fallback_proxies: tuple[str, ...]
    warnings: tuple[str, ...]
    ifc_validated: bool
    revit_open_verified: bool


@dataclass(frozen=True)
class IfcExportArtifacts:
    ifc_path: Path
    manifest_path: Path
    manifest: IfcExportManifest
    validation: IfcValidationReport
```

- [ ] **Step 5: Build the IFC4 hierarchy**

Use a fixed UUID namespace with `uuid.uuid5()` and
`ifcopenshell.guid.compress(uuid_value.hex)`. Create:

```text
IfcProject(Name=<project_id>)
  IfcSite(Name="PLAN Site")
    IfcBuilding(Name=<project_id>)
      IfcBuildingStorey(Name="F001", Elevation=0.0)
      IfcBuildingStorey(Name="F002", Elevation=3.6)
```

Assign metre units; create Model and Body contexts; use origin
`(0.0, 0.0, 0.0)`. Give every spatial object a deterministic GUID. Put each
storey at its absolute elevation and later products at local Z offsets relative
to that storey.

The hierarchy test must reopen an in-memory serialized file and assert one
project/site/building, ordered varying-footprint storeys, aggregation
relationships, deterministic GUIDs, and no `IfcBuildingElementProxy`.

- [ ] **Step 6: Make IFC headers reproducible**

Before write, set fixed header fields:

```text
name=<sanitized project_id>.ifc
time_stamp=1970-01-01T00:00:00+00:00
author=("PLAN",)
organization=("PLAN",)
preprocessor_version=PLAN 0.1.0
originating_system=PLAN BIM IFC exporter
authorization=""
```

Use the empty string for `authorization`; the installed IFC header schema marks
that attribute as non-optional.

After all high-level API calls, replace auto-generated non-product `IfcRoot`
GUIDs deterministically by `(entity class, stable STEP creation ordinal)`.
Product GUIDs always remain source-ID-derived.
Every writer stage iterates storeys, elements, property sets, and relationship
members in canonical source-ID order even if a caller constructed the neutral
snapshot in a different tuple order.

- [ ] **Step 7: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py
python -m ruff check backend/app/modules/bim_ifc backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py
git diff --check
git add pyproject.toml backend/app/modules/bim_ifc backend/tests/bim_fixtures.py backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py
git commit -m "feat: establish IFC4 export foundation"
```

---

### Task 6: Architectural Bodies, Hosted Openings, Columns, and Grid

**Files:**
- Create: `backend/app/modules/bim_ifc/architecture.py`
- Create: `backend/app/modules/bim_ifc/structure.py`
- Modify: `backend/app/modules/bim_ifc/writer.py`
- Create: `backend/tests/test_bim_ifc_architecture.py`

**Interfaces:**
- Consumes: `BimExtrusion` elements and `IfcWriteContext`.
- Produces: `write_architecture(context, snapshot) -> None`.
- Produces: `write_structure(context, snapshot) -> None`.
- Writer helper: `assign_extruded_body(context, entity, extrusion) -> None`.

- [ ] **Step 1: Write a failing standard-class and host test**

```python
def test_architecture_uses_standard_classes_bodies_and_host_relationships():
    model, context, snapshot = write_fixture_ifc()

    assert source_class_count(context, snapshot, "slab", "IfcSlab") == len(
        elements(snapshot, "slab")
    )
    assert source_class_count(context, snapshot, "wall", "IfcWall") == len(
        elements(snapshot, "wall")
    )
    assert source_class_count(context, snapshot, "door", "IfcDoor") == len(
        elements(snapshot, "door")
    )
    assert source_class_count(context, snapshot, "window", "IfcWindow") == len(
        elements(snapshot, "window")
    )
    assert source_class_count(context, snapshot, "column", "IfcColumn") == len(
        elements(snapshot, "column")
    )
    assert all(
        entity.Representation
        for entity in source_backed_visible_leaf_products(context, snapshot)
    )
    assert len(model.by_type("IfcRelVoidsElement")) == (
        len(elements(snapshot, "door")) + len(elements(snapshot, "window"))
    )
    assert len(model.by_type("IfcRelFillsElement")) == (
        len(elements(snapshot, "door")) + len(elements(snapshot, "window"))
    )
    assert not model.by_type("IfcBuildingElementProxy")
```

Add tests that every opening voids the wall named by neutral `host_id`, every
door/window fills one opening, no opening has storey containment, each
door/window has exactly one storey containment, and all source-backed physical
elements have source-derived GUIDs.

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_architecture.py
```

Expected: import failure for `bim_ifc.architecture`.

- [ ] **Step 3: Implement extruded Body representations**

For each neutral extrusion:

1. Create `IfcArbitraryClosedProfileDef` with
   `profile.add_arbitrary_profile()`.
2. Create `IfcExtrudedAreaSolid` through
   `geometry.add_profile_representation(..., depth=extrusion.depth_m)`.
3. Assign it in the Body/MODEL_VIEW context.
4. Spatially contain the top-level product in exactly one storey.
5. Place it at storey-local `(0, 0, base_offset_m)` after containment exists,
   so `edit_object_placement()` resolves the relative placement correctly.

Map classes:

```text
slab      -> IfcSlab.PredefinedType=FLOOR
wall      -> IfcWall
door      -> IfcDoor.PredefinedType=DOOR
window    -> IfcWindow.PredefinedType=WINDOW
column    -> IfcColumn
furniture -> IfcFurniture
fixture wc/lavatory/sink -> IfcSanitaryTerminal
fixture utility_equipment -> IfcUnitaryEquipment
fixture it_rack -> IfcElectricAppliance
unknown fixture -> IfcBuildingElementProxy with recorded reason
```

Create an `IfcOpeningElement` body using opening width/height, wall thickness
plus `0.02`, and sill/base offset. Attach with `feature.add_feature()` and fill
with `feature.add_filling()`.

- [ ] **Step 4: Derive a deterministic structural grid from columns**

Group columns by rounded centroid X and Y coordinates across storeys. Create one
`IfcGrid` per building with `IfcGridAxis` U/V axes only when at least two
distinct values exist in each direction. Axis tags are `A`, `B`, ... and
`1`, `2`, ... in numeric coordinate order. The `IfcGrid` GUID uses source ID
`derived:grid`; `IfcGridAxis` has no IFC GlobalId, so its stable identity is its
axis tag plus canonical axis geometry. Do not import original generator grid
lines or infer a grid when columns do not support one.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_architecture.py
python -m ruff check backend/app/modules/bim_ifc/architecture.py backend/app/modules/bim_ifc/structure.py backend/app/modules/bim_ifc/writer.py backend/tests/test_bim_ifc_architecture.py
git diff --check
git add backend/app/modules/bim_ifc/architecture.py backend/app/modules/bim_ifc/structure.py backend/app/modules/bim_ifc/writer.py backend/tests/test_bim_ifc_architecture.py
git commit -m "feat: export IFC architectural and structural elements"
```

---

### Task 7: Spaces, Stairs, Elevators, Shafts, and Conceptual Systems

**Files:**
- Modify: `backend/app/modules/bim_ifc/hierarchy.py`
- Create: `backend/app/modules/bim_ifc/circulation.py`
- Create: `backend/app/modules/bim_ifc/systems.py`
- Create: `backend/tests/test_bim_ifc_circulation_systems.py`

**Interfaces:**
- Produces: `write_spaces(context, snapshot) -> None`.
- Produces: `write_circulation(context, snapshot) -> None`.
- Produces: `write_systems(context, snapshot) -> None`.

- [ ] **Step 1: Write failing space and assembly tests**

```python
def test_spaces_stairs_elevators_shafts_and_systems_round_trip():
    model, snapshot = write_fixture_ifc()

    assert len(source_backed(model, "IfcSpace")) == len(elements(snapshot, "space")) + len(
        elements(snapshot, "shaft")
    )
    assert len(model.by_type("IfcStair")) == len(elements(snapshot, "stair"))
    assert len(model.by_type("IfcStairFlight")) == sum(
        part.part_type == "flight"
        for stair in elements(snapshot, "stair")
        for part in stair.geometry.parts
    )
    assert len(model.by_type("IfcTransportElement")) == len(
        elements(snapshot, "elevator")
    )
    assert all(item.ObjectType == "SHAFT" for item in shaft_spaces(model))
    assert len(model.by_type("IfcDistributionSystem")) == 1
```

Also assert every PLAN room maps to one `IfcSpace`, core remains identifiable as
`ObjectType=CORE`, circulation and lobby use `ObjectType=CIRCULATION` and
`LOBBY`, shaft uses `ObjectType=SHAFT`, and no room/shaft is lost because its
geometry overlaps the core zone.

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_circulation_systems.py
```

Expected: import failure for circulation/system writers.

- [ ] **Step 3: Write spaces and vertical circulation**

Create `IfcSpace` bodies and decompose them under their storey. Create each
stair as an `IfcStair`; create each flight as `IfcStairFlight` with
`NumberOfRisers`, `NumberOfTreads`, `RiserHeight`, and `TreadLength`; create each
landing as `IfcSlab.PredefinedType=LANDING`. Aggregate flights/landings under
the stair. Spatially contain the stair once; do not also spatially contain its
parts.

Map elevator to `IfcTransportElement.PredefinedType=ELEVATOR`, with a Body and
one storey containment. The current source is one elevator footprint per
storey, so do not synthesize a building-height elevator object.

- [ ] **Step 4: Write shafts and wet-service relationships**

Map neutral shaft to `IfcSpace` with `ObjectType=SHAFT`. Create one
`IfcDistributionSystem(Name="PLAN Conceptual Wet Service",
LongName="Concept only; routing not designed")`. Assign all `wc`, `lavatory`,
and `sink` IFC distribution products to it with
`ifcopenshell.api.system.assign_system()`. When no wet fixture exists, omit the
system and emit warning `wet_service_system_empty`; do not invent products.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_circulation_systems.py
python -m ruff check backend/app/modules/bim_ifc/hierarchy.py backend/app/modules/bim_ifc/circulation.py backend/app/modules/bim_ifc/systems.py backend/tests/test_bim_ifc_circulation_systems.py
git diff --check
git add backend/app/modules/bim_ifc/hierarchy.py backend/app/modules/bim_ifc/circulation.py backend/app/modules/bim_ifc/systems.py backend/tests/test_bim_ifc_circulation_systems.py
git commit -m "feat: export IFC spaces circulation and systems"
```

---

### Task 8: IFC Property-Set Assignment and Round Trip

**Files:**
- Create: `backend/app/modules/bim_ifc/properties.py`
- Modify: `backend/tests/bim_fixtures.py`
- Create: `backend/tests/test_bim_ifc_properties.py`

**Interfaces:**
- Produces: `assign_plan_property_sets(context, snapshot) -> None`.
- Produces: `read_property_set(entity, name) -> Mapping[str, BimScalar]`.
- Test helper: `write_fixture_to_disk(tmp_path: Path, *, quality: bool = True) -> tuple[Path, BimProjectSnapshot]`, using Tasks 5-8 writer stages directly rather than the not-yet-created export service.

- [ ] **Step 1: Write failing exact property round-trip tests**

```python
def test_identity_and_quality_psets_round_trip_from_reopened_ifc(tmp_path):
    path, snapshot = write_fixture_to_disk(tmp_path, quality=True)
    reopened = ifcopenshell.open(path)

    building = reopened.by_type("IfcBuilding")[0]
    quality = read_property_set(building, "Pset_PLAN_Quality")
    assert quality["QualityPolicyVersion"] == "building-quality/v1"
    assert quality["HardPass"] is True
    assert quality["UnresolvedFactCount"] == 0

    entities = reopened_source_entities(reopened)
    assert set(entities) == {
        "project",
        "building",
        *(storey.source_id for storey in snapshot.storeys),
        *(element.source_id for element in snapshot.elements),
    }
    for source_id, entity in entities.items():
        identity = read_property_set(entity, "Pset_PLAN_Identity")
        assert identity["SourceId"] == source_id
        assert identity["SourceFingerprint"] == snapshot.source_fingerprint
```

- [ ] **Step 2: Run the property test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_properties.py
```

Expected: import failure for `bim_ifc.properties`.

- [ ] **Step 3: Assign exact IFC property sets**

Attach `Pset_PLAN_Identity` to project, building, storeys, and every source-backed product.
Attach the building quality set to `IfcBuilding` and floor quality sets to their
`IfcBuildingStorey`. Use `pset.add_pset()` and `pset.edit_pset()`; overwrite the
automatically created pset/relationship GUIDs during deterministic GUID
finalization. `read_property_set()` must decode IFC label/text/boolean/integer/
real values back to the neutral scalar values used by the snapshot.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_properties.py
python -m ruff check backend/app/modules/bim_ifc/properties.py backend/tests/test_bim_ifc_properties.py
git diff --check
git add backend/app/modules/bim_ifc/properties.py backend/tests/bim_fixtures.py backend/tests/test_bim_ifc_properties.py
git commit -m "feat: round trip PLAN IFC property sets"
```

---

### Task 9: Reopened IFC and Revit-Profile Validation

**Files:**
- Create: `backend/app/modules/bim_ifc/validation.py`
- Create: `backend/tests/test_bim_ifc_validation.py`

**Interfaces:**
- Consumes: Task 8 property extraction and the neutral snapshot.
- Produces: `validate_ifc_export(path: Path, snapshot: BimProjectSnapshot, options: IfcExportOptions) -> IfcValidationReport`.

- [ ] **Step 1: Write failing validation tests**

```python
def test_validation_reopens_real_file_and_passes_complete_profile(tmp_path):
    path, snapshot = write_fixture_to_disk(tmp_path, quality=True)
    report = validate_ifc_export(path, snapshot, IfcExportOptions())

    assert report.schema == "IFC4"
    assert report.ifc_validated is True
    assert report.revit_open_verified is False
    assert report.issues == ()


def test_revit_profile_requires_quality_evidence(tmp_path):
    path, snapshot = write_fixture_to_disk(tmp_path, quality=False)
    report = validate_ifc_export(path, snapshot, IfcExportOptions())

    assert report.ifc_validated is False
    assert "quality_pset_missing" in {issue.code for issue in report.issues}


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (remove_building, "spatial_hierarchy"),
        (duplicate_product_guid, "duplicate_guid"),
        (remove_body, "missing_body"),
        (orphan_opening, "orphan_opening"),
        (duplicate_containment, "duplicate_containment"),
        (remove_quality_pset, "quality_pset_missing"),
        (move_product_above_storey, "storey_elevation"),
    ],
)
def test_validation_rejects_corrupted_reopened_ifc(tmp_path, mutator, code):
    path, snapshot = write_fixture_to_disk(tmp_path, quality=True)
    mutator(path)
    report = validate_ifc_export(path, snapshot, IfcExportOptions())

    assert report.ifc_validated is False
    assert code in {issue.code for issue in report.issues}
```

Implement each mutator as a disk round trip: reopen the fixture, apply one
change, and write the same path. `remove_building` removes the sole building;
`duplicate_product_guid` copies the first source product GUID to the second;
`remove_body` sets one leaf product `Representation=None`; `orphan_opening`
removes its sole `IfcRelVoidsElement`; `duplicate_containment` directly creates
a second `IfcRelContainedInSpatialStructure` to the wrong storey;
`remove_quality_pset` removes the building's quality relation and pset; and
`move_product_above_storey` edits one product placement to
`storey.height_m + 1.0`.

- [ ] **Step 2: Run the validation test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_validation.py
```

Expected: import failure for `bim_ifc.validation`.

- [ ] **Step 3: Implement all deterministic validation gates**

Validation order:

1. Run `ifcopenshell.validate.validate(path, logger, express_rules=True)` and
   convert logger error statements to `schema_validation`.
2. Reopen with `ifcopenshell.open(path)` and require schema exactly `IFC4`.
3. Require one project, site, building and the snapshot storey count/order/
   elevations.
4. Build a reopened `SourceId -> entity` index from `Pset_PLAN_Identity` and
   require every snapshot storey/element once.
5. Compare expected IFC classes, including shaft-to-`IfcSpace`.
6. Require unique 22-character GUIDs for all rooted products and recompute every
   source-backed GUID from project/source ID.
7. Require every physical top-level source-backed product exactly once in its
   expected storey's `IfcRelContainedInSpatialStructure`; require every
   source-backed `IfcSpace` exactly once in its storey's `IfcRelAggregates`;
   require stair parts only under their stair.
8. Require a Body representation on every visible leaf physical product and
   space. An assembly such as `IfcStair` may omit its own Body only when every
   visible decomposed flight/landing has a Body.
9. Require each opening exactly once in `IfcRelVoidsElement`, each door/window
   exactly once in `IfcRelFillsElement`, and each neutral host ID to match the
   reopened host wall.
10. Triangulate each reopened Body with
    `ifcopenshell.geom.settings()` using world coordinates, read vertices with
    `ifcopenshell.util.shape.get_vertices()`, and require XY vertices within the
    expected storey footprint and Z vertices within `[elevation,
    elevation + height]` plus tolerance. An upper stair landing may equal the
    upper bound.
11. Compare every identity/quality property value after round trip.
12. Require zero unreported proxies. For each allowed proxy require
    `OriginalPLANKind` and `FallbackReason`.

For the only v1 profile, `revit-2026-link`, missing
`Pset_PLAN_Quality/building-quality-v1` is an error. A neutral snapshot may omit
quality evidence, but it cannot be exported successfully under this profile.

Always set `revit_open_verified=False`. There is no branch that guesses Revit
availability or converts successful IFC validation into a Revit claim.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_properties.py backend/tests/test_bim_ifc_validation.py
python -m ruff check backend/app/modules/bim_ifc/validation.py backend/tests/test_bim_ifc_validation.py
git diff --check
git add backend/app/modules/bim_ifc/validation.py backend/tests/test_bim_ifc_validation.py
git commit -m "feat: validate reopened IFC Revit profile"
```

---

### Task 10: Atomic Export Service, Manifest, Inventory, and Determinism

**Files:**
- Create: `backend/app/modules/bim_ifc/service.py`
- Modify: `backend/app/modules/bim_ifc/__init__.py`
- Modify: `backend/app/modules/bim_ifc/writer.py`
- Create: `backend/tests/test_bim_ifc_service.py`

**Interfaces:**
- Produces: `export_building_ifc(snapshot: BimProjectSnapshot, output_path: Path, *, options: IfcExportOptions = IfcExportOptions()) -> IfcExportArtifacts`.
- Export creates `<name>.ifc` and `<name>.ifc.manifest.json`.

- [ ] **Step 1: Write failing service and atomicity tests**

```python
def test_export_service_writes_valid_ifc_and_manifest_atomically(tmp_path):
    snapshot = build_fixture_snapshot(quality=True)
    artifacts = export_building_ifc(snapshot, tmp_path / "office.ifc")

    assert artifacts.ifc_path.is_file()
    assert artifacts.manifest_path.is_file()
    assert artifacts.validation.ifc_validated is True
    assert artifacts.manifest.ifc_sha256 == sha256(
        artifacts.ifc_path.read_bytes()
    ).hexdigest()
    assert artifacts.manifest.export_profile == "revit-2026-link"
    assert artifacts.manifest.revit_open_verified is False
    assert artifacts.manifest.inventory.counts["IfcBuildingStorey"] == 2


def test_unchanged_snapshot_reexports_byte_and_semantic_identically(tmp_path):
    snapshot = build_fixture_snapshot(quality=True)
    first = export_building_ifc(snapshot, tmp_path / "first.ifc")
    second = export_building_ifc(snapshot, tmp_path / "second.ifc")

    assert first.ifc_path.read_bytes() == second.ifc_path.read_bytes()
    assert first.manifest.ifc_sha256 == second.manifest.ifc_sha256
    assert product_guid_map(first.ifc_path) == product_guid_map(second.ifc_path)


def test_failed_validation_leaves_no_final_ifc_or_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "validate_ifc_export", failing_report)
    with pytest.raises(IfcExportError, match="validation"):
        export_building_ifc(build_fixture_snapshot(), tmp_path / "bad.ifc")
    assert not (tmp_path / "bad.ifc").exists()
    assert not (tmp_path / "bad.ifc.manifest.json").exists()
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_service.py
```

Expected: import failure for `export_building_ifc`.

- [ ] **Step 3: Implement the ordered writer pipeline**

```text
create_write_context
create_spatial_hierarchy
write_spaces
write_architecture
write_structure
write_circulation
write_systems
assign_plan_property_sets
finalize deterministic non-product GUIDs
write temporary IFC
validate temporary IFC by reopen
compute inventory and SHA-256
write temporary canonical JSON manifest
os.replace IFC then os.replace manifest
```

Create temporary files in the destination directory. Validate both before
publishing. Move existing final files to backup names, replace IFC then
manifest, restore both backups if either replacement fails, and delete backups
only after both replacements succeed. Remove only exporter-owned temporary and
backup files. Manifest JSON uses `sort_keys=True`, `indent=2`, UTF-8, and a
trailing newline; it contains no absolute paths or current timestamps.

Inventory must include counts for every emitted IFC class and the exact
`source_id -> IFC class` map. Warnings and fallback proxies are sorted tuples.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_service.py
python -m pytest -q backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py backend/tests/test_bim_ifc_architecture.py backend/tests/test_bim_ifc_circulation_systems.py backend/tests/test_bim_ifc_properties.py backend/tests/test_bim_ifc_validation.py backend/tests/test_bim_ifc_service.py
python -m ruff check backend/app/modules/bim_ifc backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py backend/tests/test_bim_ifc_architecture.py backend/tests/test_bim_ifc_circulation_systems.py backend/tests/test_bim_ifc_properties.py backend/tests/test_bim_ifc_validation.py backend/tests/test_bim_ifc_service.py
git diff --check
git add backend/app/modules/bim_ifc backend/tests/test_bim_ifc_service.py
git commit -m "feat: export deterministic validated IFC artifacts"
```

---

### Task 11: CLI Export, Review Integration, and Import-Boundary Guard

**Files:**
- Modify: `backend/app/cli.py`
- Create: `backend/tests/test_bim_ifc_cli.py`
- Create: `backend/tests/test_module_boundaries.py`

**Interfaces:**
- Produces CLI command:

```text
plan export-ifc --input <mass.json> --output-dir <dir> [--limit N]
                [--profile revit-2026-link]
```

- Extends `irregular-alternatives-review` accepted alternatives with
  `ifc`, `ifc_manifest`, `ifc_sha256`, `ifc_validated`, and
  `revit_open_verified`.

- [ ] **Step 1: Write failing standalone CLI test**

```python
def test_cli_export_ifc_writes_each_retained_alternative(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan",
            "export-ifc",
            "--input",
            str(IRREGULAR_MANIFEST),
            "--output-dir",
            str(tmp_path),
            "--limit",
            "2",
        ],
    )
    main()
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "plan-ifc-cli/v1"
    assert len(payload["exports"]) == 2
    assert all(Path(item["ifc"]).is_file() for item in payload["exports"])
    assert all(item["ifc_validated"] is True for item in payload["exports"])
    assert all(item["revit_open_verified"] is False for item in payload["exports"])
```

Mock only the expensive alternative composition in the fast unit test. Let
`build_bim_snapshot()`, real IfcOpenShell writing, reopen, and validation run.
Add an integration test without mocks under
`@pytest.mark.ifc_integration`.

- [ ] **Step 2: Write failing existing-review integration test**

Assert every hard-pass retained alternative in `alternatives.review.json` has a
relative IFC path and manifest, matching SHA-256, `ifc_validated=true`, and
`revit_open_verified=false`. If IFC export fails, the command exits non-zero and
records the exact export error without changing the quality verdict.

- [ ] **Step 3: Write the import-boundary AST test**

```python
FORBIDDEN_IMPORTERS = (
    "backend/app/modules/generation_loop",
    "backend/app/modules/layout_generator",
    "backend/app/modules/generator_adapters",
    "backend/app/modules/validator",
    "backend/app/modules/building_quality",
    "backend/app/modules/alternative_composer",
)


def test_upstream_modules_do_not_import_bim_packages():
    violations = imports_matching(
        FORBIDDEN_IMPORTERS,
        {"backend.app.modules.bim_model", "backend.app.modules.bim_ifc"},
    )
    assert violations == []


def test_bim_model_does_not_import_ifcopenshell_or_bim_ifc():
    assert imports_matching(
        ("backend/app/modules/bim_model",),
        {"ifcopenshell", "backend.app.modules.bim_ifc"},
    ) == []
```

Parse with `ast`, including `Import` and `ImportFrom`; do not use string grep as
the test implementation.

- [ ] **Step 4: Run tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_cli.py backend/tests/test_module_boundaries.py
```

Expected: CLI parser rejects `export-ifc` and review JSON lacks IFC fields.

- [ ] **Step 5: Implement CLI orchestration**

Import BIM public APIs locally inside the two IFC-producing command paths, so
all existing non-IFC commands run without the optional dependency.

For each selected hard-pass alternative:

```python
snapshot = build_bim_snapshot(
    alternative.building,
    quality=alternative.quality_report,
    generator_version="plan/0.1.0",
)
artifacts = export_building_ifc(
    snapshot,
    output_dir / candidate_id / f"{mass.project_id}-{candidate_id}.ifc",
)
```

Do not evaluate quality inside `bim_model` or `bim_ifc`; the CLI passes the
already computed report. Use relative artifact paths in JSON. Preserve the
existing requirement that fewer than two hard-pass, quality-distinct irregular
alternatives returns non-zero.

- [ ] **Step 6: Verify GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_bim_ifc_cli.py backend/tests/test_module_boundaries.py
python -m pytest -q backend/tests/test_cli.py
python -m ruff check backend/app/cli.py backend/tests/test_bim_ifc_cli.py backend/tests/test_module_boundaries.py
git diff --check
git add backend/app/cli.py backend/tests/test_bim_ifc_cli.py backend/tests/test_module_boundaries.py
git commit -m "feat: expose IFC export artifacts in CLI"
```

---

### Task 12: Real Irregular IFC Export, Retained Inventory/Hash, and Full Gate

**Files:**
- Create: `docs/bim-ifc-revit-export-2026-07-31/`
- Modify: `docs/architecture/module_map.md`
- Production code changes: none unless a preceding failing test identifies a defect.

**Interfaces:**
- Consumes: completed snapshot, exporter, validation, and CLI.
- Produces: retained real IFC/manifest/inventory/hash evidence and truthful
  compatibility status.

- [ ] **Step 1: Run all focused suites**

```powershell
python -m pytest -q backend/tests/test_bim_model_contracts.py backend/tests/test_bim_model_geometry.py backend/tests/test_bim_model_mapper.py backend/tests/test_bim_model_properties.py
python -m pytest -q backend/tests/test_bim_ifc_dependency.py backend/tests/test_bim_ifc_hierarchy.py backend/tests/test_bim_ifc_architecture.py backend/tests/test_bim_ifc_circulation_systems.py backend/tests/test_bim_ifc_properties.py backend/tests/test_bim_ifc_validation.py backend/tests/test_bim_ifc_service.py backend/tests/test_bim_ifc_cli.py backend/tests/test_module_boundaries.py
python -m pytest -q backend/tests/test_basic_design.py backend/tests/test_basic_design_validation.py
python -m pytest -q backend/tests/test_building_quality_building.py backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_diversity.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_hardening.py backend/tests/test_building_quality_service.py
python -m pytest -q backend/tests/test_cli.py
```

- [ ] **Step 2: Produce the real three-floor irregular export**

```powershell
python -m backend.app.cli export-ifc `
  --input datasets/manifests/sample_mass_irregular_12v_setback_office.json `
  --output-dir logs/runs/bim-ifc-revit-export-2026-07-31 `
  --limit 2 `
  --profile revit-2026-link
```

Require exit `0`, at least two hard-pass quality-distinct alternatives, three
different explicit floor footprints per alternative, and one validated IFC4
plus manifest per retained alternative. Do not weaken quality or IFC validation
to make the command pass.

- [ ] **Step 3: Independently reopen and inventory every IFC**

Run a small read-only script using `ifcopenshell.open()` that writes
`inventory.json` with:

```text
schema
IfcProject, IfcSite, IfcBuilding, IfcBuildingStorey counts
IfcSpace, IfcSlab, IfcWall, IfcDoor, IfcWindow counts
IfcStair, IfcStairFlight, IfcTransportElement counts
IfcColumn, IfcGrid, IfcFurniture, IfcSanitaryTerminal counts
IfcDistributionSystem and IfcBuildingElementProxy counts
unique rooted product GUID count
Pset_PLAN_Identity target count
Pset_PLAN_Quality target count
schema validation statement count
ifc_validated
revit_open_verified
```

Assert project/site/building counts are one, storeys are three, room-to-space
and source inventory match the sidecar, every required standard class is
present, rooted product GUIDs are unique, schema validation statements are
zero, proxies are zero for the real fixture, `ifc_validated=true`, and
`revit_open_verified=false`.

- [ ] **Step 4: Verify deterministic re-export**

Export the same selected alternative into a second temporary directory. Compare
the IFC bytes, SHA-256, source-to-GUID map, entity counts, storey elevations,
and property dictionaries. Require exact equality, then remove only the second
temporary export.

- [ ] **Step 5: Retain exact evidence**

Copy without byte changes into
`docs/bim-ifc-revit-export-2026-07-31/`:

```text
export-summary.json
alternative-01/model.ifc
alternative-01/model.ifc.manifest.json
alternative-01/inventory.json
alternative-02/model.ifc
alternative-02/model.ifc.manifest.json
alternative-02/inventory.json
sha256-manifest.json
README.md
```

`sha256-manifest.json` records relative path, byte count, source SHA-256,
retained SHA-256, and `hashes_match=true` for every retained file. `README.md`
states that the evidence verifies IFC4 schema/profile checks only, Revit was not
installed, native RVT was not produced, and Link/Open behavior remains
unverified until an installed-Revit smoke test exists.

- [ ] **Step 6: Update module ownership documentation**

Add `bim_model` and `bim_ifc` to `docs/architecture/module_map.md` with the
dependency arrows from Global Constraints. State that planning/generation is
upstream and may not import either package.

- [ ] **Step 7: Run the complete repository gate**

```powershell
python -m pytest -q
python -m ruff check backend engine
npm run test:browser
git diff --check
git status --short
```

Inspect the final `git status` and stage only files named by this plan. Browser
tests remain required because `irregular-alternatives-review` JSON/HTML artifact
behavior changes even though IFC itself is not browser-rendered.

- [ ] **Step 8: Commit retained evidence and ownership docs**

```powershell
git add docs/bim-ifc-revit-export-2026-07-31 docs/architecture/module_map.md
git commit -m "docs: retain validated BIM IFC evidence"
```

## Completion Gate

The implementation is complete only when all statements below are evidenced:

- `bim_model` imports and its tests pass without IfcOpenShell.
- `bim_ifc` is the only package that imports IfcOpenShell.
- The real irregular building preserves all three varying 12-vertex footprints.
- Rooms/core, slabs/walls, hosted doors/windows, stairs/flights/landings,
  elevators, shafts, columns/grid, furniture, fixtures, and conceptual wet
  services exist in the reopened IFC inventory.
- `Pset_PLAN_Identity` and `Pset_PLAN_Quality` round-trip with exact v1 fields.
- Product GUIDs and complete unchanged export bytes are deterministic.
- Schema validation, hierarchy, room inventory, containment, host,
  storey-footprint/elevation, Body, and property checks pass after disk reopen.
- The retained SHA-256 manifest proves copied IFC evidence is byte-identical.
- Local status is exactly `ifc_validated=true`,
  `revit_open_verified=false`; no native RVT claim appears anywhere.
- Full pytest, Ruff, browser tests, and `git diff --check` pass.

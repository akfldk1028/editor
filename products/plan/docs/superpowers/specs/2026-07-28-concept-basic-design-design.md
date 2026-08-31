# Concept Basic Design

## Goal

Raise PLAN from validated room zoning to a reviewable concept/basic-design
drawing. The generated plan must contain explicit architectural, egress,
structural, envelope, furnishing, fixture, site, and dimension data that is
validated before it is rendered.

## Compliance Boundary

This feature is a `concept-basic-v1` completeness policy, not a Korean
building-code approval. It does not decide whether a project legally requires
two direct stairs, calculate occupant load, certify travel distance, assign
fire ratings, size elevator traffic, design structure, or complete MEP.

The sample nevertheless receives two protected-stair symbols and two distinct
egress routes as a conservative design prior. Legal applicability and detailed
code checks remain explicitly `not_checked`.

## Data Contract

`LayoutCandidate.basic_design` optionally contains:

- polygonal `PlanElement` records with stable ID, category, kind, host ID,
  label, and footprint;
- polyline `PlanLine` records with stable ID, category, kind, optional host ID,
  label, measured value, and clear width;
- policy version `concept-basic-v1`.

Element categories:

- `vertical`: protected stair, elevator, lobby, shaft;
- `structure`: column;
- `furniture`: workstation, meeting table, reception desk, shelf, checkout
  counter, stock rack, staff table;
- `fixture`: WC, lavatory, sink, pantry counter, equipment, IT rack.

Line categories:

- `egress`: protected exit and room-to-exit route;
- `envelope`: entrance and window;
- `structure`: grid;
- `dimension`: overall width, overall depth, circulation width;
- `site`: street and north arrow.

Existing `OpeningSegment` remains dedicated to room-to-circulation doors.

## Generated Features

### Core And Egress

The existing vertically aligned core is subdivided, without double-counting
program area, into two protected-stair footprints, an elevator, a lobby, and a
shaft. Subspaces are contained inside the core and do not overlap.

Two 0.9 m protected-exit segments are placed on positive shared boundary
between the core and circulation. Their midpoint separation must satisfy the
project's explicit concept policy. Every occupied room receives two route
polylines starting at its validated room door and ending at different
protected exits. The route data is schematic and is not a legal travel-distance
calculation.

The first commercial floor also receives an exterior entrance on the supplied
street boundary.

### Structure

An approximately 6 m orthogonal planning grid is generated from the mass
bounds. Interior 0.4 m square columns are generated only where they remain
inside the mass and do not overlap the core, circulation, doors, exits, or
other columns. Grid and column geometry is deterministic and vertically
identical on every floor.

### Envelope

Occupied perimeter rooms receive centered windows on their real shared
exterior wall. Windows cannot float inside a room, reference an unknown room,
or overlap the commercial entrance.

### Furniture And Fixtures

Each use-specific room receives recognizable minimum content:

- office: workstation clusters, meeting table, reception desk, focus desk,
  pantry counter and sink, restroom WC and lavatory, IT racks;
- commercial: sales shelves, checkout counter, stock racks, staff table,
  restroom WC and lavatory, utility equipment.

Every footprint is contained by its host room and cannot overlap another
placed object. Failure to place required content is a hard generation error.

### Dimensions And Site

The plan includes overall width/depth, measured circulation width, structural
grid labels, a street line, north arrow, and scale bar. Dimension values are
recomputed from geometry during validation.

## Validation

With `require_basic_design=True`, the validator checks:

- finite, positive, unique feature geometry and known categories/kinds;
- two stairs, one elevator, one lobby, and one shaft inside the core;
- no overlapping core subspaces;
- two distinct protected exits on the core/circulation shared wall, at least
  0.9 m wide and separated by the concept policy minimum;
- two distinct route records from every occupied room door to different exits;
- structural columns inside the boundary and outside core/circulation and
  opening clear zones;
- windows on the referenced room's actual exterior shared wall;
- commercial entrance on the supplied street boundary;
- placed objects inside their hosts, non-overlapping, and complete by room
  profile;
- dimension annotations whose stored values equal recomputed geometry.

`ValidationReport` records `basic_design_checked`, a `BasicDesignMetric`, and
structured violation codes. Visual review reports `not_checked` when the strict
policy was not executed.

## Visual Contract

SVG and dependency-free PNG render the same data in stable layer order:

1. site and structural grids;
2. rooms and circulation;
3. furniture and fixtures;
4. columns and envelope openings;
5. room doors, protected exits, core/vertical transport;
6. egress routes, dimensions, and labels.

The PNG renderer gains deterministic 5x7 ASCII text so a PNG opened by itself
shows room IDs, dimensions, `UP`, `ELEV`, `N`, and `STREET`.

HTML provides working controls for rooms, circulation, doors, labels, core,
egress, structure, windows, furniture/fixtures, dimensions, and site. Control
state is synchronized after delayed iframe load.

## Acceptance

- The actual OpenAI five-floor 30 m by 12 m sample remains accepted.
- All floors share identical core subspaces, structure grid, and columns.
- Every floor passes room, door, circulation, room-form, and basic-design
  completeness gates.
- Commercial and office PNGs visibly show two stairs, elevator, exits, route
  arrows, columns/grid, windows, furniture/fixtures, dimensions, north, and
  street.
- Desktop and mobile HTML controls work without console or page errors.

## Research And Regulatory Basis

- Korean Building Act interpretation confirms that projects requiring two
  direct stairs must connect each stair to rooms by corridors or passages:
  https://www.law.go.kr/expcInfoP.do?expcSeq=343001
- Korean accessibility detailed criteria specify 0.9 m clear door width:
  https://www.law.go.kr/flDownload.do?bylClsCd=110201&flSeq=135226913&gubun=
- GSA P100 treats elevator quantity as a traffic-analysis decision, so this
  prototype displays one elevator without claiming capacity compliance:
  https://www.gsa.gov/system/files/P100%202024%20Final%20%281%29.pdf
- WBDG guidance coordinates structural grids with flexible open plans and
  facade systems:
  https://dod.wbdg.org/facilities-exteriors/structural-systems/systems-and-layouts/index.html

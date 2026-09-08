# V1 Data Contracts

## MassInput

JSON polygon input with project id, floor count, footprint points, site edges,
access candidates, and use mix. V1 accepts one finite, simple, positive-area
polygon ring only; a repeated closing point is normalized. Holes and
multipolygons are unsupported.

## ProgramGraph

Spaces are nodes. Adjacency, service, public access, and vertical access rules are edges.

## LayoutCandidate

Rooms are vector polygons. V1 stores circulation separately and keeps walls/doors for later exporters.

## ValidationReport

`accepted` and `is_valid` are true only if every hard gate passes. The report
contains `hard_violation_count`, normalized `violation_score`, structured
`violations` (`code`, `subject`, `message`), and per-room area measurements.
Hard codes cover invalid geometry, room identity, room area, boundary, overlap,
missing/disconnected circulation, and inaccessible rooms.

Score fields remain soft and comparable: area, overlap, boundary, circulation,
efficiency, adjacency, frontage, coverage, compactness, and total score. They
do not override a hard failure. `policy_version` identifies the evaluation
rules used for the result.

## VisualReviewArtifacts

Each search iteration renders only its `best_so_far` candidate as SVG, PNG,
HTML, and canonical review JSON.
Review JSON records the candidate fingerprint, lineage (`parent_id`, operator,
operator parameters), hard failure count, structured violations, scores,
deltas from the prior rendered iteration, hard checks, acceptance, and relative
artifact links. `needs_iteration` is exactly `not accepted`; non-rendered
evaluated candidates are represented only by aggregate search state, not by
per-candidate artifacts.

## VisualReviewLoopResult

Stores the number of iterations run, final iteration state, termination, and
all visual artifact paths. `review.index.json` duplicates the serializable
run contract: acceptance, termination reason, evaluation count, ordered
iterations, score and hard-failure trends, lineage, and relative links.

## Deterministic Search

For SHA-256 fingerprinting, shapes are sorted by their raw `room_id`,
`space_type`, and canonical polygon representation. Polygon rotations and
winding direction are canonicalized, while each coordinate is serialized with
exact `float.hex()` IEEE-754 text (with signed zero normalized to `0.0`). Room
IDs and space types are not normalized, and coordinates are not rounded; near
equal floating-point inputs can therefore have different fingerprints. Ranking
is accepted-first, then fewer hard failures, lower violation score, higher
total score, and fingerprint. Each candidate retains iteration and operator
lineage; duplicate fingerprints are evaluated once. `evaluation_count` and
deduplication cover the broader search, while the review history contains only
per-iteration `best_so_far` candidates. Valid termination reasons are
`accepted`, `search_exhausted`, `stagnated`, `evaluation_budget_exhausted`,
`iteration_budget_exhausted`, and `failed`. Any non-`accepted` termination
keeps `accepted=false`.

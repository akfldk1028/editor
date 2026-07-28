from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

Point = tuple[float, float]
JsonScalar = str | int | float | bool | None
GeneratorStatus = Literal["executed", "unavailable", "failed"]


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _require_scalar(value: JsonScalar, label: str) -> None:
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        raise TypeError(f"{label} must be a JSON scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must be finite")


def _require_points(points: tuple[Point, ...], label: str, minimum: int) -> None:
    if not isinstance(points, tuple) or len(points) < minimum:
        raise ValueError(f"{label} needs at least {minimum} points")
    if not all(
        isinstance(point, tuple)
        and len(point) == 2
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in point)
        for point in points
    ):
        raise ValueError(f"{label} must contain finite coordinate pairs")


@dataclass(frozen=True)
class GeneratorEntrance:
    edge_index: int
    position: float
    kind: str = "access"

    def __post_init__(self) -> None:
        if self.edge_index < 0:
            raise ValueError("entrance edge_index must be nonnegative")
        if not math.isfinite(self.position) or not 0.0 <= self.position <= 1.0:
            raise ValueError("entrance position must be between zero and one")
        _require_text(self.kind, "entrance kind")


@dataclass(frozen=True)
class GeneratorProgramNode:
    node_id: str
    space_type: str
    target_area: float
    min_area: float | None = None
    max_area: float | None = None
    frontage_required: bool = False
    min_width: float | None = None
    max_aspect_ratio: float | None = None
    zone: str | None = None
    tenant_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.node_id, "program node id")
        _require_text(self.space_type, "program node space_type")
        for name in (
            "target_area",
            "min_area",
            "max_area",
            "min_width",
            "max_aspect_ratio",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"program node {name} must be finite and nonnegative")


@dataclass(frozen=True)
class GeneratorProgramEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        _require_text(self.source, "program edge source")
        _require_text(self.target, "program edge target")
        _require_text(self.relation, "program edge relation")
        if not math.isfinite(self.weight):
            raise ValueError("program edge weight must be finite")


@dataclass(frozen=True)
class GeneratorFixedConstraint:
    constraint_id: str
    kind: str
    value: JsonScalar

    def __post_init__(self) -> None:
        _require_text(self.constraint_id, "constraint id")
        _require_text(self.kind, "constraint kind")
        _require_scalar(self.value, "constraint value")


@dataclass(frozen=True)
class GeneratorProjectFact:
    name: str
    value: JsonScalar

    def __post_init__(self) -> None:
        _require_text(self.name, "project fact name")
        _require_scalar(self.value, "project fact value")


@dataclass(frozen=True)
class NormalizedPolygon:
    polygon_id: str
    kind: str
    points: tuple[Point, ...]

    def __post_init__(self) -> None:
        _require_text(self.polygon_id, "polygon id")
        _require_text(self.kind, "polygon kind")
        _require_points(self.points, "normalized polygon", 3)


@dataclass(frozen=True)
class NormalizedOpening:
    opening_id: str
    kind: str
    connects: tuple[str, str]
    start: Point
    end: Point
    clear_width: float

    def __post_init__(self) -> None:
        _require_text(self.opening_id, "opening id")
        _require_text(self.kind, "opening kind")
        if not isinstance(self.connects, tuple) or len(self.connects) != 2:
            raise ValueError("opening connects must contain two ids")
        _require_points((self.start, self.end), "opening endpoints", 2)
        if not math.isfinite(self.clear_width) or self.clear_width <= 0:
            raise ValueError("opening clear_width must be finite and positive")


@dataclass(frozen=True)
class NormalizedElement:
    element_id: str
    category: str
    kind: str
    host_id: str
    label: str
    footprint: tuple[Point, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("element id", self.element_id),
            ("element category", self.category),
            ("element kind", self.kind),
            ("element host id", self.host_id),
        ):
            _require_text(value, name)
        if not isinstance(self.label, str):
            raise TypeError("element label must be a string")
        _require_points(self.footprint, "element footprint", 3)


@dataclass(frozen=True)
class NormalizedLine:
    line_id: str
    category: str
    kind: str
    points: tuple[Point, ...]
    host_id: str | None = None
    target_id: str | None = None
    label: str = ""
    measured_value: float | None = None
    clear_width: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("line id", self.line_id),
            ("line category", self.category),
            ("line kind", self.kind),
        ):
            _require_text(value, name)
        _require_points(self.points, "line points", 2)
        for name, value in (
            ("host_id", self.host_id),
            ("target_id", self.target_id),
        ):
            if value is not None:
                _require_text(value, name)
        if not isinstance(self.label, str):
            raise TypeError("line label must be a string")
        for name, value in (
            ("measured_value", self.measured_value),
            ("clear_width", self.clear_width),
        ):
            if value is not None and (
                not isinstance(value, (int, float)) or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite or None")


@dataclass(frozen=True)
class NormalizedPlanning:
    reception_to_lobby_route_line_id: str | None = None
    support_room_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.reception_to_lobby_route_line_id is not None:
            _require_text(
                self.reception_to_lobby_route_line_id,
                "reception route line id",
            )
        _require_tuple(self.support_room_ids, "support_room_ids")
        if any(not isinstance(room_id, str) or not room_id for room_id in self.support_room_ids):
            raise TypeError("support_room_ids must contain strings")


@dataclass(frozen=True)
class NormalizedBasicDesign:
    elements: tuple[NormalizedElement, ...]
    lines: tuple[NormalizedLine, ...]
    policy_version: str
    planning: NormalizedPlanning | None = None

    def __post_init__(self) -> None:
        _require_tuple(self.elements, "basic design elements")
        _require_members(
            self.elements,
            NormalizedElement,
            "basic design elements",
        )
        _require_tuple(self.lines, "basic design lines")
        _require_members(self.lines, NormalizedLine, "basic design lines")
        _require_text(self.policy_version, "basic design policy version")
        if self.planning is not None and not isinstance(
            self.planning,
            NormalizedPlanning,
        ):
            raise TypeError("basic design planning must be NormalizedPlanning or None")


@dataclass(frozen=True)
class NormalizedCandidate:
    candidate_id: str
    project_id: str
    floor_index: int
    boundary: tuple[Point, ...]
    rooms: tuple[NormalizedPolygon, ...]
    circulation: tuple[NormalizedPolygon, ...]
    openings: tuple[NormalizedOpening, ...]
    entrances: tuple[NormalizedLine, ...]
    routes: tuple[NormalizedLine, ...]
    remote_stair_footprint: tuple[Point, ...] | None
    basic_design: NormalizedBasicDesign | None
    score: float

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate id")
        _require_text(self.project_id, "candidate project id")
        if self.floor_index < 1:
            raise ValueError("candidate floor_index must be positive")
        _require_points(self.boundary, "candidate boundary", 3)
        for name in ("rooms", "circulation", "openings", "entrances", "routes"):
            _require_tuple(getattr(self, name), name)
        _require_members(self.rooms, NormalizedPolygon, "rooms")
        _require_members(self.circulation, NormalizedPolygon, "circulation")
        _require_members(self.openings, NormalizedOpening, "openings")
        _require_members(self.entrances, NormalizedLine, "entrances")
        _require_members(self.routes, NormalizedLine, "routes")
        if self.remote_stair_footprint is not None:
            _require_points(
                self.remote_stair_footprint,
                "remote stair footprint",
                3,
            )
        if self.basic_design is not None and not isinstance(
            self.basic_design,
            NormalizedBasicDesign,
        ):
            raise TypeError(
                "basic_design must be NormalizedBasicDesign or None"
            )
        if not math.isfinite(self.score):
            raise ValueError("candidate score must be finite")


@dataclass(frozen=True)
class GeneratorRequest:
    project_id: str
    floor_index: int
    boundary: tuple[Point, ...]
    entrances: tuple[GeneratorEntrance, ...]
    use_type: str
    program_nodes: tuple[GeneratorProgramNode, ...]
    program_edges: tuple[GeneratorProgramEdge, ...]
    fixed_constraints: tuple[GeneratorFixedConstraint, ...]
    seed: int
    project_facts: tuple[GeneratorProjectFact, ...]

    def __post_init__(self) -> None:
        _require_text(self.project_id, "request project id")
        _require_text(self.use_type, "request use_type")
        if self.floor_index < 1:
            raise ValueError("request floor_index must be positive")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TypeError("request seed must be an integer")
        _require_points(self.boundary, "request boundary", 3)
        for name in (
            "entrances",
            "program_nodes",
            "program_edges",
            "fixed_constraints",
            "project_facts",
        ):
            _require_tuple(getattr(self, name), name)
        _require_members(self.entrances, GeneratorEntrance, "entrances")
        _require_members(self.program_nodes, GeneratorProgramNode, "program_nodes")
        _require_members(self.program_edges, GeneratorProgramEdge, "program_edges")
        _require_members(
            self.fixed_constraints,
            GeneratorFixedConstraint,
            "fixed_constraints",
        )
        _require_members(self.project_facts, GeneratorProjectFact, "project_facts")
        _require_unique_names(
            (constraint.constraint_id for constraint in self.fixed_constraints),
            "constraint ids",
        )
        _require_unique_names(
            (fact.name for fact in self.project_facts),
            "project fact names",
        )

    def to_json(self) -> str:
        return _canonical_json(asdict(self))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, value: str) -> GeneratorRequest:
        payload = _json_object(value)
        return cls(
            project_id=payload["project_id"],
            floor_index=payload["floor_index"],
            boundary=_points(payload["boundary"]),
            entrances=tuple(GeneratorEntrance(**item) for item in payload["entrances"]),
            use_type=payload["use_type"],
            program_nodes=tuple(
                GeneratorProgramNode(**item) for item in payload["program_nodes"]
            ),
            program_edges=tuple(
                GeneratorProgramEdge(**item) for item in payload["program_edges"]
            ),
            fixed_constraints=tuple(
                GeneratorFixedConstraint(**item)
                for item in payload["fixed_constraints"]
            ),
            seed=payload["seed"],
            project_facts=tuple(
                GeneratorProjectFact(**item) for item in payload["project_facts"]
            ),
        )


@dataclass(frozen=True)
class GeneratorResponse:
    status: GeneratorStatus
    backend_id: str
    backend_version: str
    backend_domain: str
    request_digest: str
    raw_artifact_paths: tuple[str, ...] = ()
    normalized_candidate: NormalizedCandidate | None = None
    environment: tuple[GeneratorProjectFact, ...] = ()
    checkpoint: str | None = None
    dataset: str | None = None
    license: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"executed", "unavailable", "failed"}:
            raise ValueError("response status must be executed, unavailable, or failed")
        for label, value in (
            ("backend id", self.backend_id),
            ("backend version", self.backend_version),
            ("backend domain", self.backend_domain),
        ):
            _require_text(value, label)
        if (
            not isinstance(self.request_digest, str)
            or len(self.request_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.request_digest)
        ):
            raise ValueError("request_digest must be a lowercase SHA-256 hex digest")
        _require_tuple(self.raw_artifact_paths, "raw_artifact_paths")
        _require_tuple(self.environment, "environment")
        for path in self.raw_artifact_paths:
            if not _is_safe_relative_path(path):
                raise ValueError(
                    "raw artifact paths must be safe relative paths without '..'"
                )
        _require_members(
            self.environment,
            GeneratorProjectFact,
            "environment",
        )
        if self.normalized_candidate is not None and not isinstance(
            self.normalized_candidate,
            NormalizedCandidate,
        ):
            raise TypeError(
                "normalized_candidate must be NormalizedCandidate or None"
            )
        for label, value in (
            ("checkpoint", self.checkpoint),
            ("dataset", self.dataset),
            ("license", self.license),
            ("reason", self.reason),
        ):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{label} must be a string or None")
        if self.status != "executed" and self.normalized_candidate is not None:
            raise ValueError("only executed responses may contain a normalized candidate")
        if self.status == "executed" and self.normalized_candidate is None:
            raise ValueError("executed responses require a normalized candidate")
        if self.status != "executed" and not self.reason:
            raise ValueError("unavailable and failed responses require a reason")

    def to_json(self) -> str:
        return _canonical_json(asdict(self))

    @classmethod
    def from_json(cls, value: str) -> GeneratorResponse:
        payload = _json_object(value)
        candidate_payload = payload.get("normalized_candidate")
        candidate = (
            None
            if candidate_payload is None
            else NormalizedCandidate(
                candidate_id=candidate_payload["candidate_id"],
                project_id=candidate_payload["project_id"],
                floor_index=candidate_payload["floor_index"],
                boundary=_points(candidate_payload["boundary"]),
                rooms=tuple(
                    NormalizedPolygon(
                        item["polygon_id"], item["kind"], _points(item["points"])
                    )
                    for item in candidate_payload["rooms"]
                ),
                circulation=tuple(
                    NormalizedPolygon(
                        item["polygon_id"], item["kind"], _points(item["points"])
                    )
                    for item in candidate_payload["circulation"]
                ),
                openings=tuple(
                    NormalizedOpening(
                        opening_id=item["opening_id"],
                        kind=item["kind"],
                        connects=tuple(item["connects"]),
                        start=tuple(item["start"]),
                        end=tuple(item["end"]),
                        clear_width=item["clear_width"],
                    )
                    for item in candidate_payload["openings"]
                ),
                entrances=tuple(
                    _normalized_line(item)
                    for item in candidate_payload["entrances"]
                ),
                routes=tuple(
                    _normalized_line(item)
                    for item in candidate_payload["routes"]
                ),
                remote_stair_footprint=(
                    None
                    if candidate_payload.get("remote_stair_footprint") is None
                    else _points(candidate_payload["remote_stair_footprint"])
                ),
                basic_design=_normalized_basic_design(
                    candidate_payload.get("basic_design")
                ),
                score=candidate_payload["score"],
            )
        )
        return cls(
            status=payload["status"],
            backend_id=payload["backend_id"],
            backend_version=payload["backend_version"],
            backend_domain=payload["backend_domain"],
            request_digest=payload["request_digest"],
            raw_artifact_paths=tuple(payload.get("raw_artifact_paths", ())),
            normalized_candidate=candidate,
            environment=tuple(
                GeneratorProjectFact(**item)
                for item in payload.get("environment", ())
            ),
            checkpoint=payload.get("checkpoint"),
            dataset=payload.get("dataset"),
            license=payload.get("license"),
            reason=payload.get("reason"),
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object(value: str) -> dict[str, Any]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("generator protocol payload must be a JSON object")
    return payload


def _points(values) -> tuple[Point, ...]:
    return tuple((float(point[0]), float(point[1])) for point in values)


def _require_unique_names(values, label: str) -> None:
    names = tuple(values)
    if len(set(names)) != len(names):
        raise ValueError(f"{label} must be unique")


def _require_tuple(value, label: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{label} must be an immutable tuple")


def _require_members(values: tuple, expected_type: type, label: str) -> None:
    if any(not isinstance(value, expected_type) for value in values):
        raise TypeError(f"{label} must contain {expected_type.__name__} records")


def _is_safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and ".." not in posix.parts
        and ".." not in windows.parts
    )


def _normalized_line(payload: dict[str, Any]) -> NormalizedLine:
    return NormalizedLine(
        line_id=payload["line_id"],
        category=payload["category"],
        kind=payload["kind"],
        points=_points(payload["points"]),
        host_id=payload.get("host_id"),
        target_id=payload.get("target_id"),
        label=payload.get("label", ""),
        measured_value=payload.get("measured_value"),
        clear_width=payload.get("clear_width"),
    )


def _normalized_basic_design(
    payload: dict[str, Any] | None,
) -> NormalizedBasicDesign | None:
    if payload is None:
        return None
    planning_payload = payload.get("planning")
    return NormalizedBasicDesign(
        elements=tuple(
            NormalizedElement(
                element_id=item["element_id"],
                category=item["category"],
                kind=item["kind"],
                host_id=item["host_id"],
                label=item.get("label", ""),
                footprint=_points(item["footprint"]),
            )
            for item in payload["elements"]
        ),
        lines=tuple(_normalized_line(item) for item in payload["lines"]),
        policy_version=payload["policy_version"],
        planning=(
            None
            if planning_payload is None
            else NormalizedPlanning(
                reception_to_lobby_route_line_id=planning_payload.get(
                    "reception_to_lobby_route_line_id"
                ),
                support_room_ids=tuple(
                    planning_payload.get("support_room_ids", ())
                ),
            )
        ),
    )

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import sys

import pytest

from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.generator_adapters import (
    DeterministicGeneratorAdapter,
    Graph2PlanAdapter,
    HouseDiffusionAdapter,
    MansionAdapter,
    RlvrAdapter,
    SubprocessGeneratorAdapter,
    validate_normalized_response,
)
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.generator_adapter import (
    GeneratorEntrance,
    GeneratorFixedConstraint,
    GeneratorProgramEdge,
    GeneratorProgramNode,
    GeneratorProjectFact,
    GeneratorRequest,
    GeneratorResponse,
    NormalizedCandidate,
    NormalizedOpening,
    NormalizedPolygon,
)
from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    OpeningSegment,
    PlanElement,
    PlanLine,
    RoomPolygon,
    UsePlanningMetadata,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramEdge, ProgramGraph, ProgramNode


def _request() -> GeneratorRequest:
    return GeneratorRequest(
        project_id="adapter-contract",
        floor_index=1,
        boundary=((0.0, 0.0), (20.0, 0.0), (20.0, 12.0), (0.0, 12.0)),
        entrances=(GeneratorEntrance(edge_index=0, position=0.5),),
        use_type="neighborhood_commercial",
        program_nodes=(
            GeneratorProgramNode("sales", "sales", 120.0, 96.0, 144.0),
            GeneratorProgramNode("core", "core", 36.0, 30.0, 42.0),
        ),
        program_edges=(GeneratorProgramEdge("sales", "core", "near", 1.0),),
        fixed_constraints=(
            GeneratorFixedConstraint("street-0", "street_edge", 0),
        ),
        seed=17,
        project_facts=(
            GeneratorProjectFact("floors", 2),
            GeneratorProjectFact("source", "unit-test"),
        ),
    )


def _response() -> GeneratorResponse:
    request = _request()
    return GeneratorResponse(
        status="executed",
        backend_id="fixture",
        backend_version="1.2.3",
        backend_domain="graph-to-plan",
        request_digest=request.digest,
        raw_artifact_paths=("raw/output.json",),
        normalized_candidate=NormalizedCandidate(
            candidate_id="candidate-1",
            project_id="adapter-contract",
            floor_index=1,
            boundary=request.boundary,
            rooms=(
                NormalizedPolygon(
                    "sales",
                    "sales",
                    ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
                ),
            ),
            circulation=(
                NormalizedPolygon(
                    "corridor",
                    "circulation",
                    ((10.0, 0.0), (12.0, 0.0), (12.0, 10.0), (10.0, 10.0)),
                ),
            ),
            openings=(
                NormalizedOpening(
                    "sales-door",
                    "door",
                    ("sales", "corridor"),
                    (10.0, 4.0),
                    (10.0, 5.0),
                    1.0,
                ),
            ),
            entrances=(),
            routes=(),
            remote_stair_footprint=None,
            basic_design=None,
            score=0.75,
        ),
        environment=(GeneratorProjectFact("python", "3.11"),),
        checkpoint="checkpoint-v1",
        dataset="fixture-dataset",
        license="MIT",
        reason=None,
    )


def test_generator_request_is_frozen_and_has_canonical_json_roundtrip() -> None:
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.seed = 18  # type: ignore[misc]

    encoded = request.to_json()
    assert encoded == request.to_json()
    assert encoded == json.dumps(
        json.loads(encoded),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert request.digest == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert GeneratorRequest.from_json(encoded) == request


def test_generator_response_is_frozen_and_has_json_roundtrip() -> None:
    response = _response()

    with pytest.raises(FrozenInstanceError):
        response.status = "failed"  # type: ignore[misc]

    assert GeneratorResponse.from_json(response.to_json()) == response

    with pytest.raises(ValueError, match="executed responses require"):
        replace(response, normalized_candidate=None)


def test_generator_contract_rejects_mutable_collections_and_non_json_metadata() -> None:
    with pytest.raises(TypeError, match="entrances must be an immutable tuple"):
        replace(_request(), entrances=[])

    with pytest.raises(TypeError, match="raw_artifact_paths must be an immutable tuple"):
        replace(_response(), raw_artifact_paths=["raw/output.json"])

    with pytest.raises(TypeError, match="checkpoint must be a string or None"):
        replace(_response(), checkpoint={"name": "mutable"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("entrances", (object(),)),
        ("program_nodes", (object(),)),
        ("program_edges", (object(),)),
        ("fixed_constraints", (object(),)),
        ("project_facts", (object(),)),
    ],
)
def test_generator_request_rejects_wrong_member_types(field: str, value) -> None:
    with pytest.raises(TypeError, match=field):
        replace(_request(), **{field: value})


def test_generator_response_and_candidate_reject_wrong_member_types() -> None:
    candidate = _response().normalized_candidate
    assert candidate is not None
    with pytest.raises(TypeError, match="rooms"):
        replace(candidate, rooms=(object(),))
    with pytest.raises(TypeError, match="normalized_candidate"):
        replace(_response(), normalized_candidate=object())
    with pytest.raises(TypeError, match="environment"):
        replace(_response(), environment=(object(),))


@pytest.mark.parametrize(
    "path",
    [
        "../escape.json",
        "/absolute/output.json",
        r"C:\absolute\output.json",
        r"C:drive-relative.json",
        r"\root-relative.json",
        "CON",
        "safe/AUX.txt",
    ],
)
def test_generator_response_rejects_unsafe_raw_artifact_path(path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        replace(_response(), raw_artifact_paths=(path,))


def test_deterministic_adapter_rejects_program_contract_mismatch() -> None:
    response = DeterministicGeneratorAdapter().generate(_request())

    assert response.status == "failed"
    assert response.backend_id == "deterministic"
    assert response.normalized_candidate is None
    assert response.reason is not None
    assert "program contract mismatch" in response.reason


def test_deterministic_adapter_executes_exact_generated_program_contract() -> None:
    request = _request_for_generated_program()

    response = DeterministicGeneratorAdapter().generate(request)

    assert response.status == "executed"
    assert response.request_digest == request.digest
    assert response.backend_domain == "mass-to-plan"
    assert response.normalized_candidate is not None
    assert response.normalized_candidate.project_id == "adapter-contract"
    assert {room.polygon_id for room in response.normalized_candidate.rooms} == {
        node.node_id for node in request.program_nodes
    }
    assert response.raw_artifact_paths == ()
    assert {
        fact.name: fact.value for fact in response.environment
    }["seed_handling"] == "ignored-deterministic-backend"
    json.loads(response.to_json())


@pytest.mark.parametrize(
    "entrance",
    [
        GeneratorEntrance(edge_index=0, position=0.25),
        GeneratorEntrance(edge_index=0, position=0.5, kind="service"),
    ],
)
def test_deterministic_adapter_rejects_unsupported_entrance_semantics(
    entrance: GeneratorEntrance,
) -> None:
    request = replace(_request_for_generated_program(), entrances=(entrance,))

    response = DeterministicGeneratorAdapter().generate(request)

    assert response.status == "failed"
    assert response.reason is not None
    assert "supported entrance" in response.reason


def test_deterministic_candidate_preserves_concept_basic_validator_contract() -> None:
    request = _request_for_generated_program()
    response = DeterministicGeneratorAdapter().generate(request)
    assert response.normalized_candidate is not None

    layout = _restore_layout(response.normalized_candidate)
    program = ProgramGraph(
        project_id=request.project_id,
        floor_index=request.floor_index,
        use_type=request.use_type,
        nodes=[ProgramNode(**vars(node)) for node in request.program_nodes],
        edges=[ProgramEdge(**vars(edge)) for edge in request.program_edges],
        source="generator-adapter-contract",
    )
    report = validate_layout(
        layout,
        program,
        boundary=list(response.normalized_candidate.boundary),
        street_segments=[(request.boundary[0], request.boundary[1])],
        require_openings=True,
        min_circulation_width=1.2,
        require_basic_design=True,
    )

    assert report.basic_design_checked is True
    assert report.accepted is True


def test_adapter_preserves_and_validates_typed_floor_height_fact() -> None:
    request = replace(
        _request_for_generated_program(),
        project_facts=(
            GeneratorProjectFact("floors", 2),
            GeneratorProjectFact("source", "unit-test"),
            GeneratorProjectFact("floor_to_floor_height_m", 4.2),
        ),
    )
    response = DeterministicGeneratorAdapter().generate(request)

    assert response.status == "executed"
    assert response.normalized_candidate is not None
    stair = next(
        element
        for element in response.normalized_candidate.basic_design.elements
        if element.kind == "stair"
    )
    assert stair.stair_geometry.floor_to_floor_height_m == pytest.approx(4.2)
    assert validate_normalized_response(request, response).status == "executed"

    bad_stair = replace(
        stair,
        stair_geometry=replace(
            stair.stair_geometry,
            floor_to_floor_height_m=3.6,
        ),
    )
    bad_design = replace(
        response.normalized_candidate.basic_design,
        elements=tuple(
            bad_stair if element.element_id == stair.element_id else element
            for element in response.normalized_candidate.basic_design.elements
        ),
    )
    bad_response = replace(
        response,
        normalized_candidate=replace(
            response.normalized_candidate,
            basic_design=bad_design,
        ),
    )
    validated = validate_normalized_response(request, bad_response)
    assert validated.status == "failed"
    assert "stair_height_context" in validated.reason


def test_deterministic_adapter_rejects_unsupported_fixed_constraint() -> None:
    request = replace(
        _request_for_generated_program(),
        fixed_constraints=(
            GeneratorFixedConstraint("street-0", "street_edge", 0),
            GeneratorFixedConstraint("column-grid", "column_grid", "6x6"),
        ),
    )

    response = DeterministicGeneratorAdapter().generate(request)

    assert response.status == "failed"
    assert response.reason is not None
    assert "unsupported fixed constraint kind: column_grid" in response.reason


@pytest.mark.parametrize(
    "adapter_type, backend_id",
    [
        (Graph2PlanAdapter, "graph2plan"),
        (HouseDiffusionAdapter, "house_diffusion"),
        (RlvrAdapter, "rlvr"),
        (MansionAdapter, "mansion"),
    ],
)
def test_research_adapter_without_executable_is_explicitly_unavailable(
    adapter_type,
    backend_id: str,
) -> None:
    response = adapter_type().generate(_request())

    assert response.status == "unavailable"
    assert response.backend_id == backend_id
    assert response.normalized_candidate is None
    assert response.reason
    assert "not configured" in response.reason
    assert response.request_digest == _request().digest


def test_research_adapter_exposes_configured_provenance_when_unavailable() -> None:
    response = Graph2PlanAdapter(
        backend_version="paper-commit-a1",
        backend_domain="configured-graph-domain",
        checkpoint="graph.ckpt",
        dataset="rplan",
        license="research-only",
    ).generate(_request())

    assert response.status == "unavailable"
    assert response.backend_version == "paper-commit-a1"
    assert response.backend_domain == "configured-graph-domain"
    assert response.checkpoint == "graph.ckpt"
    assert response.dataset == "rplan"
    assert response.license == "research-only"


def test_mansion_remains_downstream_only_even_with_command() -> None:
    response = MansionAdapter(command=(sys.executable, "-c", "raise SystemExit(99)")).generate(
        _request()
    )

    assert response.status == "unavailable"
    assert response.reason is not None
    assert "downstream-only" in response.reason


def test_subprocess_adapter_uses_json_stdin_stdout_protocol() -> None:
    request = _request_for_generated_program()
    response = _valid_external_response(request)
    script = f"print({response.to_json()!r})"
    adapter = SubprocessGeneratorAdapter(
        command=(sys.executable, "-c", script),
        backend_id="fixture",
        backend_version="1",
        backend_domain="graph-to-plan",
        timeout_seconds=2.0,
    )

    response = adapter.generate(request)

    assert response.status == "executed"
    assert response.request_digest == request.digest
    assert response.raw_artifact_paths == ("raw.json",)


def test_subprocess_adapter_rejects_executed_candidate_that_fails_geometry() -> None:
    request = _request()
    adapter = SubprocessGeneratorAdapter(
        command=(sys.executable, "-c", _echo_response_script()),
        backend_id="fixture",
        backend_version="1",
        backend_domain="graph-to-plan",
        timeout_seconds=2.0,
    )

    response = adapter.generate(request)

    assert response.status == "failed"
    assert response.normalized_candidate is None
    assert response.reason is not None
    assert "basic_design" in response.reason


def test_common_normalized_response_validation_reuses_plan_validator() -> None:
    request = _request_for_generated_program()
    response = _valid_external_response(request)
    candidate = response.normalized_candidate
    assert candidate is not None
    assert validate_normalized_response(request, response).status == "executed"

    boundary_mismatch = replace(
        candidate,
        boundary=(
            (0.0, 0.0),
            (21.0, 0.0),
            (21.0, 12.0),
            (0.0, 12.0),
        ),
    )
    first_room, second_room, *remaining_rooms = candidate.rooms
    overlapping_room = replace(second_room, points=first_room.points)
    overlap = replace(
        candidate,
        rooms=(first_room, overlapping_room, *remaining_rooms),
    )
    first_opening, *remaining_openings = candidate.openings
    bad_opening = replace(
        candidate,
        openings=(
            replace(first_opening, connects=("missing-room", "corridor")),
            *remaining_openings,
        ),
    )
    missing_basic_contract = replace(candidate, basic_design=None)

    for malformed in (
        boundary_mismatch,
        overlap,
        bad_opening,
        missing_basic_contract,
    ):
        checked = validate_normalized_response(
            request,
            replace(response, normalized_candidate=malformed),
        )
        assert checked.status == "failed"
        assert checked.normalized_candidate is None
        assert checked.reason


def test_subprocess_adapter_rejects_wrong_request_digest() -> None:
    script = _echo_response_script(request_digest="0" * 64)
    adapter = SubprocessGeneratorAdapter(
        command=(sys.executable, "-c", script),
        backend_id="fixture",
        backend_version="1",
        backend_domain="graph-to-plan",
        timeout_seconds=2.0,
    )

    response = adapter.generate(_request())

    assert response.status == "failed"
    assert response.reason is not None
    assert "request digest" in response.reason


def test_subprocess_adapter_rejects_candidate_request_identity_mismatch() -> None:
    script = _echo_response_script(candidate_floor=2)
    adapter = SubprocessGeneratorAdapter(
        command=(sys.executable, "-c", script),
        backend_id="fixture",
        backend_version="1",
        backend_domain="graph-to-plan",
        timeout_seconds=2.0,
    )

    response = adapter.generate(_request())

    assert response.status == "failed"
    assert response.reason is not None
    assert "candidate identity" in response.reason


def test_subprocess_adapter_reports_timeout_as_failed() -> None:
    adapter = SubprocessGeneratorAdapter(
        command=(sys.executable, "-c", "import time; time.sleep(1)"),
        backend_id="slow",
        backend_version="1",
        backend_domain="diffusion",
        timeout_seconds=0.01,
    )

    response = adapter.generate(_request())

    assert response.status == "failed"
    assert response.reason is not None
    assert "timed out" in response.reason


def test_subprocess_adapter_reports_invalid_output_as_failed() -> None:
    adapter = SubprocessGeneratorAdapter(
        command=(sys.executable, "-c", "print('not-json')"),
        backend_id="broken",
        backend_version="1",
        backend_domain="external",
        timeout_seconds=2.0,
    )

    response = adapter.generate(_request())

    assert response.status == "failed"
    assert response.reason is not None
    assert "invalid JSON response" in response.reason


@pytest.mark.parametrize(
    "command,timeout",
    [
        (["python"], 1.0),
        ((), 1.0),
        ((sys.executable,), 0.0),
        ((sys.executable,), float("inf")),
    ],
)
def test_subprocess_adapter_rejects_invalid_process_configuration(
    command,
    timeout: float,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        SubprocessGeneratorAdapter(
            command=command,
            backend_id="invalid",
            backend_version="1",
            backend_domain="external",
            timeout_seconds=timeout,
        )


def _request_for_generated_program() -> GeneratorRequest:
    request = _request()
    mass = MassInput(
        project_id=request.project_id,
        floors=2,
        footprint_polygon=list(request.boundary),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5, "kind": "access"}],
        use_mix={request.use_type: 1.0},
    )
    building = run_building_generation(mass)
    result = next(
        floor
        for floor in building.floor_results
        if floor.program.floor_index == request.floor_index
    )
    return replace(
        request,
        program_nodes=tuple(
            GeneratorProgramNode(
                node.node_id,
                node.space_type,
                node.target_area,
                node.min_area,
                node.max_area,
                node.frontage_required,
                node.min_width,
                node.max_aspect_ratio,
                node.zone,
                node.tenant_id,
            )
            for node in result.program.nodes
        ),
        program_edges=tuple(
            GeneratorProgramEdge(edge.source, edge.target, edge.relation, edge.weight)
            for edge in result.program.edges
        ),
    )


def _valid_external_response(request: GeneratorRequest) -> GeneratorResponse:
    generated = DeterministicGeneratorAdapter().generate(request)
    assert generated.status == "executed"
    return replace(
        generated,
        backend_id="fixture",
        backend_version="1",
        backend_domain="graph-to-plan",
        raw_artifact_paths=("raw.json",),
    )


def _echo_response_script(
    *,
    request_digest: str | None = None,
    candidate_floor: int = 1,
) -> str:
    digest_expression = (
        repr(request_digest)
        if request_digest is not None
        else "hashlib.sha256(raw.encode('utf-8')).hexdigest()"
    )
    return (
        "import hashlib,json,sys;"
        "raw=sys.stdin.read();request=json.loads(raw);"
        "response={"
        "'status':'executed','backend_id':'fixture','backend_version':'1',"
        "'backend_domain':'graph-to-plan',"
        f"'request_digest':{digest_expression},"
        "'raw_artifact_paths':['raw.json'],"
        "'normalized_candidate':{"
        "'candidate_id':'external-1','project_id':request['project_id'],"
        f"'floor_index':{candidate_floor},'boundary':request['boundary'],"
        "'rooms':[],'circulation':[],'openings':[],'entrances':[],'routes':[],"
        "'remote_stair_footprint':None,'basic_design':None,'score':0.0},"
        "'environment':[],'checkpoint':None,'dataset':None,'license':None,"
        "'reason':None};print(json.dumps(response))"
    )


def _restore_layout(candidate: NormalizedCandidate) -> LayoutCandidate:
    basic_design = None
    if candidate.basic_design is not None:
        planning = candidate.basic_design.planning
        basic_design = BasicDesignFeatures(
            elements=tuple(
                PlanElement(
                    element.element_id,
                    element.category,
                    element.kind,
                    element.host_id,
                    element.label,
                    element.footprint,
                    element.stair_geometry,
                )
                for element in candidate.basic_design.elements
            ),
            lines=tuple(
                PlanLine(
                    line.line_id,
                    line.category,
                    line.kind,
                    line.points,
                    line.host_id,
                    line.target_id,
                    line.label,
                    line.measured_value,
                    line.clear_width,
                    line.door_swing,
                )
                for line in candidate.basic_design.lines
            ),
            policy_version=candidate.basic_design.policy_version,
            planning=(
                None
                if planning is None
                else UsePlanningMetadata(
                    planning.reception_to_lobby_route_line_id,
                    planning.support_room_ids,
                )
            ),
        )
    return LayoutCandidate(
        candidate_id=candidate.candidate_id,
        project_id=candidate.project_id,
        floor_index=candidate.floor_index,
        rooms=[
            RoomPolygon(room.polygon_id, room.kind, list(room.points))
            for room in candidate.rooms
        ],
        circulation=[
            RoomPolygon(path.polygon_id, path.kind, list(path.points))
            for path in candidate.circulation
        ],
        score=candidate.score,
        openings=[
            OpeningSegment(
                opening.opening_id,
                opening.kind,
                opening.connects,
                opening.start,
                opening.end,
                opening.clear_width,
            )
            for opening in candidate.openings
        ],
        basic_design=basic_design,
        remote_stair_footprint=candidate.remote_stair_footprint,
    )

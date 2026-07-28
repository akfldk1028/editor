from __future__ import annotations

import platform

from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.schemas.generator_adapter import (
    NormalizedBasicDesign,
    NormalizedElement,
    NormalizedLine,
    NormalizedPlanning,
    GeneratorProgramEdge,
    GeneratorProgramNode,
    GeneratorProjectFact,
    GeneratorRequest,
    GeneratorResponse,
    NormalizedCandidate,
    NormalizedOpening,
    NormalizedPolygon,
)
from backend.app.schemas.mass import MassInput


class DeterministicGeneratorAdapter:
    backend_id = "deterministic"
    backend_version = "internal-v1"
    backend_domain = "mass-to-plan"

    def generate(self, request: GeneratorRequest) -> GeneratorResponse:
        unsupported_entrance = next(
            (
                entrance
                for entrance in request.entrances
                if entrance.kind != "access" or entrance.position != 0.5
            ),
            None,
        )
        if unsupported_entrance is not None:
            return self._failed(
                request,
                "supported entrance requires kind='access' and position=0.5",
            )
        facts = {fact.name: fact.value for fact in request.project_facts}
        unsupported_facts = sorted(set(facts) - {"floors", "source"})
        if unsupported_facts:
            return self._failed(
                request,
                f"unsupported project fact: {unsupported_facts[0]}",
            )
        unsupported_constraints = sorted(
            {
                constraint.kind
                for constraint in request.fixed_constraints
                if constraint.kind != "street_edge"
            }
        )
        if unsupported_constraints:
            return self._failed(
                request,
                f"unsupported fixed constraint kind: {unsupported_constraints[0]}",
            )
        floors = facts.get("floors", request.floor_index)
        if (
            not isinstance(floors, int)
            or isinstance(floors, bool)
            or floors < request.floor_index
        ):
            return self._failed(
                request,
                "project fact floors must be an integer covering the requested floor",
            )
        invalid_street = next(
            (
                constraint
                for constraint in request.fixed_constraints
                if (
                    not isinstance(constraint.value, int)
                    or isinstance(constraint.value, bool)
                )
            ),
            None,
        )
        if invalid_street is not None:
            return self._failed(
                request,
                f"street_edge constraint {invalid_street.constraint_id} must be an integer",
            )
        site_edges = [
            {"edge_index": constraint.value, "kind": "street"}
            for constraint in request.fixed_constraints
            if constraint.kind == "street_edge"
        ]
        mass = MassInput(
            project_id=request.project_id,
            floors=int(floors),
            footprint_polygon=list(request.boundary),
            site_edges=site_edges,
            access_candidates=[
                {
                    "edge_index": entrance.edge_index,
                    "position": entrance.position,
                    "kind": entrance.kind,
                }
                for entrance in request.entrances
            ],
            use_mix={request.use_type: 1.0},
        )
        try:
            building = run_building_generation(
                mass,
            )
            result = next(
                floor
                for floor in building.floor_results
                if floor.program.floor_index == request.floor_index
            )
        except Exception as error:
            return self._failed(
                request,
                f"{type(error).__name__}: {error}",
            )
        generated_nodes = tuple(
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
        )
        generated_edges = tuple(
            GeneratorProgramEdge(
                edge.source,
                edge.target,
                edge.relation,
                edge.weight,
            )
            for edge in result.program.edges
        )
        mismatches = []
        if generated_nodes != request.program_nodes:
            mismatches.append("nodes")
        if generated_edges != request.program_edges:
            mismatches.append("edges")
        if mismatches:
            return self._failed(
                request,
                f"program contract mismatch: {', '.join(mismatches)}",
            )
        layout = result.layout
        basic_design = layout.basic_design
        normalized_basic_design = (
            None
            if basic_design is None
            else NormalizedBasicDesign(
                elements=tuple(
                    NormalizedElement(
                        element.element_id,
                        element.category,
                        element.kind,
                        element.host_id,
                        element.label,
                        element.footprint,
                    )
                    for element in basic_design.elements
                ),
                lines=tuple(
                    self._normalize_line(line)
                    for line in basic_design.lines
                ),
                policy_version=basic_design.policy_version,
                planning=(
                    None
                    if basic_design.planning is None
                    else NormalizedPlanning(
                        basic_design.planning.reception_to_lobby_route_line_id,
                        basic_design.planning.support_room_ids,
                    )
                ),
            )
        )
        return GeneratorResponse(
            status="executed",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            request_digest=request.digest,
            normalized_candidate=NormalizedCandidate(
                candidate_id=layout.candidate_id,
                project_id=layout.project_id,
                floor_index=layout.floor_index,
                boundary=request.boundary,
                rooms=tuple(
                    NormalizedPolygon(
                        room.room_id,
                        room.space_type,
                        tuple(room.polygon),
                    )
                    for room in layout.rooms
                ),
                circulation=tuple(
                    NormalizedPolygon(
                        room.room_id,
                        room.space_type,
                        tuple(room.polygon),
                    )
                    for room in layout.circulation
                ),
                openings=tuple(
                    NormalizedOpening(
                        opening.opening_id,
                        opening.kind,
                        opening.connects,
                        opening.start,
                        opening.end,
                        opening.clear_width,
                    )
                    for opening in layout.openings
                ),
                entrances=(
                    ()
                    if normalized_basic_design is None
                    else tuple(
                        line
                        for line in normalized_basic_design.lines
                        if line.kind == "entrance"
                    )
                ),
                routes=(
                    ()
                    if normalized_basic_design is None
                    else tuple(
                        line
                        for line in normalized_basic_design.lines
                        if line.category == "egress"
                    )
                ),
                remote_stair_footprint=layout.remote_stair_footprint,
                basic_design=normalized_basic_design,
                score=float(layout.score),
            ),
            environment=self._environment(request),
            dataset="internal-program-priors",
            license="project-internal",
        )

    def _failed(
        self,
        request: GeneratorRequest,
        reason: str,
    ) -> GeneratorResponse:
        return GeneratorResponse(
            status="failed",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            request_digest=request.digest,
            environment=self._environment(request),
            reason=reason,
        )

    @staticmethod
    def _normalize_line(line) -> NormalizedLine:
        return NormalizedLine(
            line.line_id,
            line.category,
            line.kind,
            line.points,
            line.host_id,
            line.target_id,
            line.label,
            line.measured_value,
            line.clear_width,
        )

    @staticmethod
    def _environment(
        request: GeneratorRequest,
    ) -> tuple[GeneratorProjectFact, ...]:
        values = [
            GeneratorProjectFact("python_implementation", platform.python_implementation()),
            GeneratorProjectFact("python_version", platform.python_version()),
            GeneratorProjectFact(
                "seed_handling",
                "ignored-deterministic-backend",
            ),
            GeneratorProjectFact("requested_seed", request.seed),
            GeneratorProjectFact(
                "fixed_constraint_support",
                "street_edge-only",
            ),
        ]
        source = next(
            (
                fact.value
                for fact in request.project_facts
                if fact.name == "source"
            ),
            None,
        )
        if source is not None:
            values.append(GeneratorProjectFact("request_source", source))
        return tuple(values)

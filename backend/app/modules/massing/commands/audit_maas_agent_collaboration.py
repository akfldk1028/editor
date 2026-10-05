"""Run the hash-bound specialist collaboration over an archived candidate pool.

The collaboration protocol was unit-tested but had never been exercised on a
real pool: every stored passport carried an empty ``agent_collaboration``.  This
command produces that missing distribution, and the ablation beside it, so the
fail-closed policy can be measured rather than asserted.

Archived candidates are recompiled from their ``geometry_program`` rather than
trusted from their persisted metrics: a persisted subset that omits a key the
GATE reads is indistinguishable from a violation, and reading it back would
measure the serializer instead of the geometry.

    python manage.py audit_maas_agent_collaboration \\
        --candidates-root tmp_mass_check/c260-book --pnu 4115011300106840001
"""

from __future__ import annotations

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from backend.app.modules.design.generation.maas.agents.law_graph_agent.evidence import bind_law_agent_evidence, collect_law_source_snapshot
from backend.app.modules.design.generation.maas.agents.orchestrator.execution_collaboration import build_default_execution_executors, run_execution_collaboration
from backend.app.modules.design.generation.maas.agents.shared.types import AgentEvidence, ExecutionIdentity
from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate


class Command(BaseCommand):
    help = (
        "Run the A2A specialist collaboration over archived MASS candidates "
        "and report the accepted / rejected / needs_evidence distribution "
        "against a gate-removed ablation."
    )

    def add_arguments(self, parser):
        parser.add_argument("--candidates-root", required=True, type=str)
        parser.add_argument("--pnu", required=True, type=str)
        parser.add_argument(
            "--building-type", default="제1종근린생활시설", type=str
        )
        parser.add_argument("--limit", default=0, type=int)
        parser.add_argument("--output-json", default="", type=str)
        parser.add_argument(
            "--legal-check",
            action="store_true",
            help=(
                "Measure each candidate against the parcel's real BCR/FAR "
                "capacities and hand the result to the law agent as numeric "
                "evidence. Without it the numeric gate never runs, and the "
                "law agent reports passed anyway."
            ),
        )

    def handle(self, *args, **options):
        root = Path(options["candidates_root"]).resolve()
        if not root.is_dir():
            raise CommandError(f"candidates root is not a directory: {root}")
        paths = sorted(root.glob("*/candidates/*.json"))
        if not paths:
            paths = sorted(root.glob("candidates/*.json"))
        if not paths:
            raise CommandError(f"no candidate JSON under {root}")
        limit = int(options["limit"] or 0)
        if limit > 0:
            paths = paths[:limit]

        building_type = str(options["building_type"])
        fallback_pnu = str(options["pnu"])

        started = perf_counter()
        compiled: list[tuple[dict[str, Any], Any]] = []
        compile_errors: Counter = Counter()
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                compile_errors["unreadable_candidate"] += 1
                continue
            program_payload = payload.get("geometry_program")
            if not isinstance(program_payload, dict):
                compile_errors["missing_geometry_program"] += 1
                continue
            try:
                program = GeometryProgram.from_dict(program_payload)
                compilation = compile_geometry_program(program)
            except (TypeError, ValueError) as exc:
                compile_errors[type(exc).__name__] += 1
                continue
            compiled.append((payload, compilation))
        compile_seconds = round(perf_counter() - started, 3)

        # One shared law source read, bound to every MASS. Reloading the graph
        # per candidate is what made an earlier run of this audit unusable.
        law_context = {"law": {}, "building_type": building_type}
        started = perf_counter()
        law_snapshot = collect_law_source_snapshot(law_context)
        law_seconds = round(perf_counter() - started, 3)
        # The snapshot reports the graph under "neo4j" and the domain service
        # under "law_search"; reading a "graph_status" key here reported an
        # available graph as unavailable.
        graph_status = law_snapshot.get("neo4j")
        graph_status = dict(graph_status) if isinstance(graph_status, dict) else {}
        law_search = law_snapshot.get("law_search")
        law_search = dict(law_search) if isinstance(law_search, dict) else {}

        legal_caps: dict[str, Any] = {}
        if options["legal_check"]:
            from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site

            site = load_legal_site(fallback_pnu, building_type=building_type)
            legal_caps = {
                "parcel_area_m2": float(site.parcel_area_m2),
                "ground_capacity_m2": float(site.ground_capacity_m2),
                "far_capacity_m2": float(site.far_capacity_m2),
                "max_storeys": site.max_storeys,
            }

        conditions = {
            "gates_on_parking_absent": self._run_condition(
                compiled,
                law_context=law_context,
                law_snapshot=law_snapshot,
                building_type=building_type,
                fallback_pnu=fallback_pnu,
                legal_caps=legal_caps,
                gates_on=True,
                parking_payload={},
            ),
            "gates_on_parking_passed": self._run_condition(
                compiled,
                law_context=law_context,
                law_snapshot=law_snapshot,
                building_type=building_type,
                fallback_pnu=fallback_pnu,
                legal_caps=legal_caps,
                gates_on=True,
                parking_payload={
                    "status": "passed",
                    "evaluated": True,
                    "hard_pass": True,
                },
            ),
            "ablation_gates_removed": self._run_condition(
                compiled,
                law_context=law_context,
                law_snapshot=law_snapshot,
                building_type=building_type,
                fallback_pnu=fallback_pnu,
                legal_caps=legal_caps,
                gates_on=False,
                parking_payload={},
            ),
        }

        report = {
            "schema_version": "arr.maas.agent_collaboration_audit.v1",
            "candidates_root": str(root),
            "candidate_count": len(paths),
            "compiled_count": len(compiled),
            "compile_errors": dict(compile_errors),
            "compile_seconds": compile_seconds,
            "law_source": {
                "seconds": law_seconds,
                "graph_available": bool(graph_status.get("available")),
                "graph_uri": str(graph_status.get("uri") or ""),
                "graph_resolved_count": graph_status.get("resolved_count"),
                "article_count": len(law_snapshot.get("articles") or ()),
                "law_search_available": bool(law_search.get("available")),
                "law_search_source": str(law_search.get("source") or ""),
                "law_search_error": str(law_search.get("error_category") or ""),
                "search_result_count": len(
                    law_snapshot.get("search_results") or ()
                ),
            },
            "conditions": conditions,
        }
        output_json = str(options["output_json"] or "").strip()
        if output_json:
            path = Path(output_json).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report["output_json"] = str(path)
        self.stdout.write(json.dumps(report, ensure_ascii=False))

    def _run_condition(
        self,
        compiled,
        *,
        law_context,
        law_snapshot,
        building_type: str,
        fallback_pnu: str,
        legal_caps: dict[str, Any],
        gates_on: bool,
        parking_payload: dict[str, Any],
    ) -> dict[str, Any]:
        finals: Counter = Counter()
        per_agent: dict[str, Counter] = defaultdict(Counter)
        missing_reasons: Counter = Counter()
        numeric: Counter = Counter()
        for index, (payload, compilation) in enumerate(compiled, start=1):
            identity = _identity_for(
                payload, compilation, index, fallback_pnu=fallback_pnu
            )
            law_payload = (
                _numeric_law_evidence(payload, legal_caps)
                if gates_on and legal_caps
                else {}
            )
            if law_payload:
                numeric[
                    "passed" if law_payload.get("hard_pass") else "failed"
                ] += 1
            executors = build_default_execution_executors(
                compilation=compilation,
                geometry_gate_issues=(
                    compilation_gate(compilation) if gates_on else ()
                ),
                downstream_evidence={
                    "law": law_payload,
                    "parking": parking_payload,
                },
                program_metadata={"building_type": building_type},
            )
            if gates_on:
                executors["law_graph_agent"] = _bound_law_executor(
                    {**law_context, "law": law_payload}, law_snapshot
                )
            else:
                executors = {
                    agent: _unconditional_pass(agent) for agent in executors
                }
            trace = run_execution_collaboration(identity, executors=executors)
            finals[trace.final_status] += 1
            for row in trace.evidence:
                per_agent[row.agent][row.status] += 1
                # Why a specialist held, not only that it held.
                for reason in (row.evidence or {}).get("missing_evidence") or ():
                    missing_reasons[f"{row.agent}:{reason}"] += 1
        return {
            "final_status": dict(finals),
            "per_agent": {
                agent: dict(counter) for agent, counter in per_agent.items()
            },
            "missing_evidence": dict(missing_reasons),
            "numeric_law": dict(numeric),
        }


def _numeric_law_evidence(
    payload: dict[str, Any], caps: dict[str, Any]
) -> dict[str, Any]:
    """Measure one candidate against the parcel's BCR and FAR capacities."""

    storey = payload.get("storey_evidence")
    storey = storey if isinstance(storey, dict) else {}
    gfa = storey.get("actual_gfa_m2")
    floor_areas = storey.get("actual_floor_areas_m2") or ()
    if gfa is None or not floor_areas:
        return {}
    footprint = max(float(area) for area in floor_areas)
    ground_cap = float(caps["ground_capacity_m2"])
    far_cap = float(caps["far_capacity_m2"])
    bcr_pass = footprint <= ground_cap
    far_pass = float(gfa) <= far_cap
    # The zoning policy carries a storey ceiling too; checking only BCR and FAR
    # leaves one of the three numeric limits unexercised.
    max_storeys = caps.get("max_storeys")
    storeys = int(storey.get("storey_count") or 0)
    storey_pass = True if max_storeys is None else storeys <= int(max_storeys)
    hard_pass = bool(bcr_pass and far_pass and storey_pass)
    return {
        "evaluated": True,
        "hard_pass": hard_pass,
        "status": "passed" if hard_pass else "failed",
        "footprint_m2": round(footprint, 3),
        "ground_capacity_m2": round(ground_cap, 3),
        "bcr_pass": bcr_pass,
        "gfa_m2": round(float(gfa), 3),
        "far_capacity_m2": round(far_cap, 3),
        "far_pass": far_pass,
        "storeys": storeys,
        "max_storeys": max_storeys,
        "storey_pass": storey_pass,
    }


def _identity_for(
    payload: dict[str, Any], compilation: Any, index: int, *, fallback_pnu: str
) -> ExecutionIdentity:
    storey_evidence = payload.get("storey_evidence")
    storey_evidence = storey_evidence if isinstance(storey_evidence, dict) else {}
    return ExecutionIdentity(
        execution_id=str(payload.get("candidate_id") or f"mass_{index:03d}"),
        program_hash=str(compilation.program.program_hash()),
        geometry_hash=str(
            compilation.geometry_hash or "GEOMETRY_HASH_UNRESOLVED"
        ),
        floor_capacity_plan_hash=str(
            storey_evidence.get("floor_capacity_plan_hash")
            or payload.get("normalized_authored_mesh_hash")
            or "FLOOR_CAPACITY_PLAN_HASH_UNRESOLVED"
        ),
        pnu=str(payload.get("pnu") or fallback_pnu),
    )


def _bound_law_executor(law_context, law_snapshot):
    def _execute(identity: ExecutionIdentity, accumulated) -> AgentEvidence:
        return bind_law_agent_evidence(identity, law_context, law_snapshot)

    return _execute


def _unconditional_pass(agent_id: str):
    """Ablation executor: report a pass without consulting any evidence."""

    def _execute(identity: ExecutionIdentity, accumulated) -> AgentEvidence:
        return AgentEvidence(
            evidence_id=f"evidence:{agent_id}",
            agent=agent_id,
            status="passed",
            summary=f"{agent_id} gate removed for ablation",
            identity=identity,
            evidence={"ablation": "gate_removed"},
        )

    return _execute

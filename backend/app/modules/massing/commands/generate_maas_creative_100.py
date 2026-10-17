"""Persist a bounded pre-legal creative MASS choice pool."""

from __future__ import annotations

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio, build_creative_floor_portfolio_report
from backend.app.modules.design.generation.maas.creative_author_supply import collect_creative_author_supply
from backend.app.modules.design.generation.maas.creative_morphology import morphology_distance
from backend.app.modules.design.generation.maas.creative_program_author import authored_programs_from_cache_pool, authored_programs_from_payload, cached_authored_programs
from backend.app.modules.design.generation.maas.creative_research_bundle import write_creative_mass_research_bundle
from backend.app.modules.design.generation.maas.design_memory.reference_events import build_reference_review_events, mutable_event
from backend.app.modules.design.generation.maas.geometry_language import CompilationResult, GeometryAuthorError, GeometryProgram, author_geometry_programs_with_openai, render_compilation_preview
from backend.app.modules.design.generation.maas.geometry_language.vlm_adapter import retrieve_geometry_reference_matches
from backend.app.modules.design.generation.maas.preference.vlm_scorer import score_candidate_with_openai_vlm


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BOARD_COLUMNS = 10
_BOARD_CARD_WIDTH = 300
_BOARD_IMAGE_HEIGHT = 227
_BOARD_LABEL_HEIGHT = 23
_VLM_PILOT_MAX_REQUESTS = 15


class Command(BaseCommand):
    help = (
        "Generate up to 100 compiled four-view creative MASS candidates. "
        "The output is a pre-legal choice pool; paid review is opt-in only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--count", default=100, type=int)
        parser.add_argument("--pnu", required=True, type=str)
        parser.add_argument(
            "--capacity-ceiling-m2",
            default=332.322,
            type=float,
        )
        parser.add_argument("--output-root", required=True, type=str)
        parser.add_argument("--run-id", default="", type=str)
        parser.add_argument(
            "--author-mode",
            required=True,
            choices=(
                "payload",
                "llm",
                "cache_pool",
                "hybrid",
                "recipe_fixture",
            ),
            help=(
                "payload or llm is the production path; recipe_fixture is "
                "an explicit deterministic regression/demo source"
            ),
        )
        parser.add_argument("--author-payload", default="", type=str)
        parser.add_argument("--development-parent-contract", default="", type=str,
                            help="Explicit exact-authored development with a verified parent contract; no BOOK exploration.")
        parser.add_argument("--author-cache-root", default="", type=str)
        parser.add_argument("--author-model", default="", type=str)
        parser.add_argument(
            "--max-fresh-author-requests",
            default=3,
            type=int,
        )
        parser.add_argument(
            "--vlm-pilot",
            action="store_true",
            help=(
                "Opt in to at most 15 low-detail VLM calls, one morphology "
                "medoid per family."
            ),
        )
        parser.add_argument("--vlm-model", default="", type=str)

    def handle(self, *args, **options):
        count = int(options["count"])
        # The name is the command's history, not its ceiling: the cycle's
        # BOOK track authors BOOK_COUNT programs (120 for comp18), and the
        # first batch to pass the importer stopped here.
        if count < 1 or count > 200:
            raise CommandError("--count must be between 1 and 200")
        pnu = str(options["pnu"] or "").strip()
        if not pnu:
            raise CommandError("--pnu is required")
        author_mode = str(options["author_mode"])
        if options.get('development_parent_contract') and author_mode != 'payload':
            raise CommandError('exact development requires payload author mode')
        max_fresh_author_requests = int(
            options.get("max_fresh_author_requests") or 0
        )
        if max_fresh_author_requests < 0 or max_fresh_author_requests > 3:
            raise CommandError(
                "--max-fresh-author-requests must be between 0 and 3"
            )
        if author_mode == "hybrid":
            if not str(options.get("author_cache_root") or "").strip():
                raise CommandError(
                    "--author-cache-root is required for hybrid author mode"
                )
            if bool(options.get("vlm_pilot")):
                raise CommandError(
                    "--vlm-pilot is unavailable in hybrid pre-legal mode"
                )
        run_id = str(options.get("run_id") or "").strip() or (
            f"maas-creative-{count}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
        if (
            not _RUN_ID_PATTERN.fullmatch(run_id)
            or run_id in {".", ".."}
        ):
            raise CommandError("--run-id contains unsupported characters")

        output_root = Path(options["output_root"]).resolve()
        run_directory = (output_root / run_id).resolve()
        if run_directory.parent != output_root:
            raise CommandError("--run-id must resolve inside --output-root")
        if run_directory.exists() and any(run_directory.iterdir()):
            raise CommandError(f"run directory is not empty: {run_directory}")
        candidates_directory = run_directory / "candidates"
        renders_directory = run_directory / "renders"
        candidates_directory.mkdir(parents=True, exist_ok=True)
        renders_directory.mkdir(parents=True, exist_ok=True)

        context = {
            "pnu": pnu,
            "capacity_ceiling_m2": float(
                options["capacity_ceiling_m2"]
            ),
            "creative_portfolio_run_id": run_id,
            "instruction": (
                "Author materially different executable typed MASS ASTs. "
                "Do not select or imitate a named family recipe."
            ),
        }
        author_supply = None
        portfolio_report = None
        delivery_probe = None
        try:
            if author_mode == "hybrid":
                cached = cached_authored_programs(
                    Path(str(options["author_cache_root"]))
                    .expanduser()
                    .resolve(),
                    limit=60,
                )

                def fresh_author(
                    requested_count: int,
                    attempt_index: int,
                ) -> tuple[GeometryProgram, ...]:
                    return tuple(author_geometry_programs_with_openai(
                        {
                            **context,
                            "creative_author_batch_index": (
                                attempt_index - 1
                            ),
                        },
                        target_count=min(20, requested_count),
                        model=(
                            str(options.get("author_model") or "")
                            or None
                        ),
                    ))

                def retained_count(programs) -> int:
                    report = build_creative_floor_portfolio_report(
                        target_count=count,
                        capacity_ceiling_m2=float(
                            options["capacity_ceiling_m2"]
                        ),
                        authored_programs=programs,
                    )
                    return sum(c.get('candidate_origin') != 'authored_original'
                               for c in report.candidates)

                author_supply = collect_creative_author_supply(
                    target_count=count,
                    cached_programs=cached,
                    fresh_author=fresh_author,
                    retained_count=retained_count,
                    max_fresh_requests=max_fresh_author_requests,
                )
                portfolio_report = build_creative_floor_portfolio_report(
                    target_count=count,
                    capacity_ceiling_m2=float(
                        options["capacity_ceiling_m2"]
                    ),
                    authored_programs=author_supply.programs,
                )
                portfolio = _hybrid_portfolio_payload(
                    portfolio_report,
                    capacity_ceiling_m2=float(
                        options["capacity_ceiling_m2"]
                    ),
                    author_supply=author_supply.evidence(),
                )
            else:
                development_contract = str(options.get('development_parent_contract') or '')
                if development_contract:
                    if author_mode != 'payload':
                        raise ValueError('exact development requires payload author mode')
                    from backend.app.modules.design.generation.maas.book_development import build_exact_development_portfolio
                    portfolio = build_exact_development_portfolio(
                        json.loads(Path(options['author_payload']).read_text(encoding='utf-8')),
                        json.loads(Path(development_contract).read_text(encoding='utf-8')),
                        expected_count=count)
                else:
                    authored_programs = _resolve_authored_programs(
                        mode=author_mode,
                        payload_path=str(options.get("author_payload") or ""),
                        cache_root=str(options.get("author_cache_root") or ""),
                        model=str(options.get("author_model") or ""),
                        count=count,
                        context=context,
                    )
                    delivery_probe = None
                    if author_mode in {'payload', 'llm'}:
                        from backend.app.modules.massing.workspace_tools.book_delivery_probe import BookDeliveryProbe
                        from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site
                        from backend.app.modules.design.generation.maas.massv2.parcel_policy import default_building_type
                        import os
                        site = load_legal_site(pnu, building_type=default_building_type(pnu, os.environ.get('BUILDING_TYPE')))
                        delivery_probe = BookDeliveryProbe(site, run_id=run_id)
                    portfolio = build_creative_floor_portfolio(
                        count=count,
                        capacity_ceiling_m2=float(
                            options["capacity_ceiling_m2"]
                        ),
                        authored_programs=authored_programs,
                        delivery_probe=delivery_probe,
                    )
        except (
            GeometryAuthorError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        candidates = portfolio.get("candidates")
        _validate_candidate_supply(candidates, count=count, hybrid=author_mode == 'hybrid', allow_partial=delivery_probe is not None)

        persisted_candidates: list[dict[str, Any]] = []
        preview_items: list[tuple[str, Path]] = []
        for candidate in candidates:
            persisted, preview = _persist_candidate(
                candidate,
                run_directory=run_directory,
                candidates_directory=candidates_directory,
                renders_directory=renders_directory,
                run_id=run_id,
                pnu=pnu,
            )
            persisted_candidates.append(persisted)
            preview_items.append((
                (
                    f"{persisted['candidate_id']} "
                    f"{persisted['family']} "
                    f"{persisted['capacity_band']}"
                ),
                preview,
            ))

        board_path = run_directory / "maas-creative-board.png"
        board = _write_board(
            preview_items,
            board_path,
            target_count=count if author_mode == "hybrid" or delivery_probe is not None else None,
        )
        graph = _frontend_graph(
            persisted_candidates,
            run_id=run_id,
            pnu=pnu,
        )
        pilot = (
            _run_bounded_vlm_pilot(
                persisted_candidates,
                run_directory=run_directory,
                model=str(options.get("vlm_model") or "") or None,
            )
            if bool(options.get("vlm_pilot"))
            else {
                "schema_version": "arr.maas.creative_vlm_pilot.v1",
                "status": "not_requested",
                "request_count": 0,
                "max_request_count": _VLM_PILOT_MAX_REQUESTS,
                "reference_limit_per_request": 3,
                "candidate_image_detail": "low",
                "records": [],
                "events": [],
            }
        )
        paid_author_response_ids = {
            str(
                (candidate.get("author_evidence") or {}).get(
                    "response_id"
                )
                or ""
            )
            for candidate in persisted_candidates
            if author_mode in {"llm", "hybrid"}
            and not bool(
                (candidate.get("author_evidence") or {}).get(
                    "cache_hit"
                )
            )
            and str(
                (candidate.get("author_evidence") or {}).get(
                    "response_id"
                )
                or ""
            )
        }
        paid_author_request_count = len(paid_author_response_ids)
        payload = {
            **{
                key: deepcopy(value)
                for key, value in portfolio.items()
                if key != "candidates"
            },
            "run_id": run_id,
            "author_mode": author_mode,
            "pnu": pnu,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": len(persisted_candidates),
            "candidates": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "family": candidate["family"],
                    "capacity_band": candidate["capacity_band"],
                    "storeys": candidate["storey_evidence"][
                        "storey_count"
                    ],
                    "legal_status": candidate["legal_review"]["status"],
                    "program_hash": candidate["program_hash"],
                    "geometry_hash": candidate["geometry_hash"],
                    **{key: candidate[key] for key in (
                        'candidate_origin', 'source_program_hash',
                        'normalized_source_program_hash', 'parent_program_hash') if key in candidate},
                    "candidate_json": candidate["candidate_json"],
                    "render_png": candidate["render_png"],
                    "mass_directory": candidate["mass_directory"],
                    "mass_manifest": candidate["mass_manifest"],
                    "elevation_research_handoff": candidate[
                        "elevation_research_handoff"
                    ],
                }
                for candidate in persisted_candidates
            ],
            "board": board,
            "vlm_pilot": pilot,
            "paid_vlm_request_count": int(pilot["request_count"]),
            "paid_author_request_count": paid_author_request_count,
            "paid_author_request_count_authority": (
                "confirmed_noncache_response_ids_in_current_llm_mode"
            ),
            "acceptance_label": (
                "PRE-LEGAL / NOT LAW, PARKING, CAPACITY OR VLM ACCEPTED"
            ),
            "frontend_graph": graph,
            "filter_facets": _filter_facets(persisted_candidates),
            "artifact_contract": {
                "candidate_json_contains_full_program_trace_and_mesh": True,
                "individual_render": "deterministic_four_view_png",
                "mass_research_folder": (
                    "program_matrix_mesh_obj_csv_six_views_elevation_handoff"
                ),
                "legal_authority": "not_evaluated",
                "paid_provider_calls": (
                    int(pilot["request_count"])
                    + paid_author_request_count
                ),
            },
        }
        portfolio_path = (
            run_directory / "maas-creative-portfolio.json"
        )
        if author_mode == "hybrid":
            assert portfolio_report is not None
            assert author_supply is not None
            ledger = {
                "schema_version": "arr.maas.prelegal_stage_ledger.v2",
                "status": portfolio_report.status,
                "target_count": count,
                "candidate_count": len(persisted_candidates),
                "deficit": portfolio_report.deficit,
                "author_supply": author_supply.evidence(),
                "stage_counts": dict(portfolio_report.stage_counts),
                "rejection_counts": dict(
                    portfolio_report.rejection_counts
                ),
                "rejections": [
                    item.evidence()
                    for item in portfolio_report.rejections
                ],
                "morphology_histograms": _morphology_histograms(
                    candidates
                ),
                "book_language_coverage": deepcopy(
                    portfolio.get("book_language_coverage") or {}
                ),
                "affine_authority_counts": _affine_authority_counts(
                    persisted_candidates
                ),
                "paid_vlm_request_count": 0,
                "acceptance_scope": "pre_legal_not_evaluated",
                "acceptance_label": (
                    "PRE-LEGAL / NOT LAW, PARKING, CAPACITY OR VLM ACCEPTED"
                ),
            }
            ledger_path = (
                run_directory / "maas-prelegal-stage-ledger.json"
            )
            _write_json_atomic(ledger_path, ledger)
            payload["stage_ledger"] = ledger_path.name
        _write_json_atomic(portfolio_path, payload)
        summary = {
            "run_id": run_id,
            "run_directory": str(run_directory),
            "candidate_count": len(persisted_candidates),
            "portfolio_json": str(portfolio_path),
            "board_png": str(board_path),
            "paid_vlm_request_count": int(
                payload.get("paid_vlm_request_count") or 0
            ),
            "paid_author_request_count": paid_author_request_count,
            "legal_review_status": payload["legal_review_status"],
            "status": payload.get("status"),
            "exploration_count": payload.get("exploration_count"),
            "original_count": payload.get("original_count"),
            "deficit": payload.get("deficit", 0),
        }
        if portfolio_report is not None:
            summary.update(portfolio_report.stage_counts)
        self.stdout.write(json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
        ))


def _affine_authority_counts(
    candidates: list[dict[str, Any]],
) -> dict[str, int]:
    """Audit the persisted one-UnitBox/direct-Matrix4 affine contract."""

    shorthand = {"scale", "rotate", "translate", "mirror", "shear"}
    missing_unitbox_count = 0
    missing_matrix4_count = 0
    shorthand_node_count = 0
    for candidate in candidates:
        payload = candidate.get("geometry_program")
        try:
            program = GeometryProgram.from_dict(payload)
        except (TypeError, ValueError):
            missing_unitbox_count += 1
            missing_matrix4_count += 1
            continue
        unitboxes = [
            node
            for node in program.nodes
            if node.kind == "primitive"
            and node.operator == "box"
            and bool((node.provenance or {}).get("unitbox_authority"))
        ]
        if len(unitboxes) != 1:
            missing_unitbox_count += 1
            missing_matrix4_count += 1
        else:
            unitbox_id = unitboxes[0].id
            if not any(
                node.kind == "transform"
                and node.operator == "matrix4"
                and node.inputs == (unitbox_id,)
                for node in program.nodes
            ):
                missing_matrix4_count += 1
        shorthand_node_count += sum(
            node.operator in shorthand
            for node in program.nodes
        )
    return {
        "candidate_count": len(candidates),
        "missing_unitbox_count": missing_unitbox_count,
        "missing_matrix4_count": missing_matrix4_count,
        "shorthand_node_count": shorthand_node_count,
    }


def _validate_candidate_supply(candidates, *, count, hybrid, allow_partial=False):
    """Bound exploration separately from preserved author originals."""
    error = 'creative portfolio candidate count or lineage does not match request'
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise CommandError(error)
    tagged = any('candidate_origin' in c for c in candidates)
    if not tagged:
        if len(candidates) > count or (not hybrid and len(candidates) != count):
            raise CommandError(error)
        return
    originals = 0
    explored = 0
    ids = set()
    for candidate in candidates:
        identity = candidate.get('candidate_id')
        source = candidate.get('source_program_hash')
        if not identity or identity in ids or not source:
            raise CommandError(error)
        ids.add(identity)
        if candidate.get('candidate_origin') == 'authored_original':
            originals += 1
            try:
                authored_hash = GeometryProgram.from_dict(candidate.get('authored_geometry_program') or {}).program_hash()
            except (TypeError, ValueError, KeyError) as exc:
                raise CommandError(error) from exc
            if authored_hash != source:
                raise CommandError(error)
        elif candidate.get('candidate_origin') == 'book_exploration':
            explored += 1
            if candidate.get('parent_program_hash') != source:
                raise CommandError(error)
            try:
                parent_hash = GeometryProgram.from_dict(candidate.get('parent_geometry_program') or {}).program_hash()
            except (TypeError, ValueError, KeyError) as exc:
                raise CommandError(error) from exc
            if parent_hash != source:
                raise CommandError(error)
        else:
            raise CommandError(error)
    if originals > count or explored > count or (not hybrid and not allow_partial and explored != count):
        raise CommandError(error)


def _hybrid_portfolio_payload(
    report,
    *,
    capacity_ceiling_m2: float,
    author_supply: dict[str, Any],
) -> dict[str, Any]:
    candidates = list(report.candidates)
    family_counts = Counter(
        str(candidate["family"]) for candidate in candidates
    )
    capacity_counts = Counter(
        str(candidate["capacity_band"]) for candidate in candidates
    )
    return {
        "schema_version": "arr.maas.creative_floor_portfolio.v1",
        "author_mode": "hybrid",
        "status": report.status,
        "choice_pool": True,
        "candidate_count": len(candidates),
        "capacity_ceiling_m2": round(capacity_ceiling_m2, 6),
        "capacity_authority": "user_supplied_prelegal_target",
        "family_quotas": dict(family_counts),
        "capacity_band_quotas": dict(capacity_counts),
        "legal_review_status": "not_evaluated",
        "paid_vlm_request_count": 0,
        "acceptance_scope": "pre_legal_not_evaluated",
        "acceptance_label": (
            "PRE-LEGAL / NOT LAW, PARKING, CAPACITY OR VLM ACCEPTED"
        ),
        "author_supply": author_supply,
        "exploration_count": report.exploration_count,
        "original_count": sum(c.get('candidate_origin') == 'authored_original' for c in candidates),
        "target_count_scope": "book_exploration",
        "stage_counts": dict(report.stage_counts),
        "rejection_counts": dict(report.rejection_counts),
        "rejections": [item.evidence() for item in report.rejections],
        "book_language_coverage": deepcopy(report.language_coverage),
        "book_schedule": deepcopy(report.schedule_evidence),
        "morphology_evidence": {
            "schema_version": "arr.maas.creative_morphology.v1",
            "decision": report.status,
            "accepted_count": len(candidates),
            "rejected_count": sum(report.rejection_counts.values()),
        },
        "candidates": candidates,
    }


def _morphology_histograms(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    families = Counter(
        str(candidate.get("posthoc_family") or candidate.get("family") or "")
        for candidate in candidates
    )
    capacity_bands = Counter(
        str(candidate.get("capacity_band") or "")
        for candidate in candidates
    )
    visible_stepped = Counter()
    distances: list[float] = []
    for candidate in candidates:
        morphology = candidate.get("morphology_evidence") or {}
        descriptor = morphology.get("descriptor") or {}
        stepped = descriptor.get("visible_stepped")
        visible_stepped[
            "unknown" if stepped is None else str(bool(stepped)).lower()
        ] += 1
        decision = morphology.get("decision") or {}
        distance = decision.get("nearest_distance")
        if isinstance(distance, (int, float)):
            distances.append(float(distance))
    ordered = sorted(distances)
    return {
        "posthoc_family": dict(sorted(families.items())),
        "capacity_band": dict(sorted(capacity_bands.items())),
        "visible_stepped": dict(sorted(visible_stepped.items())),
        "morphology_distance": {
            "count": len(ordered),
            "minimum": ordered[0] if ordered else None,
            "maximum": ordered[-1] if ordered else None,
            "median": (
                ordered[len(ordered) // 2] if ordered else None
            ),
        },
    }


def _resolve_authored_programs(
    *,
    mode: str,
    payload_path: str,
    cache_root: str,
    model: str,
    count: int,
    context: dict[str, Any],
) -> tuple[GeometryProgram, ...] | None:
    if mode == "recipe_fixture":
        return None
    if mode == "cache_pool":
        if not cache_root.strip():
            raise ValueError(
                "--author-cache-root is required for cache_pool author mode"
            )
        return tuple(
            item.program
            for item in authored_programs_from_cache_pool(
                Path(cache_root).expanduser().resolve(),
                expected_count=count,
            )
        )
    if mode == "payload":
        if not payload_path.strip():
            raise ValueError(
                "--author-payload is required for payload author mode"
            )
        path = Path(payload_path).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("author payload must be a JSON object")
        return tuple(
            item.program
            for item in authored_programs_from_payload(
                payload,
                expected_count=count,
                program_context=context,
            )
        )
    if mode != "llm":
        raise ValueError(f"unsupported author mode: {mode}")
    programs: list[GeometryProgram] = []
    for batch_index, start in enumerate(range(0, count, 20)):
        batch_count = min(20, count - start)
        programs.extend(author_geometry_programs_with_openai(
            {
                **context,
                "creative_author_batch_index": batch_index,
                "creative_author_batch_offset": start,
            },
            target_count=batch_count,
            model=model or None,
        ))
    if len(programs) < count:
        raise GeometryAuthorError(
            f"geometry author yielded {len(programs)}/{count} programs"
        )
    return tuple(programs[:count])


def _select_morphology_medoids(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Choose one deterministic minimum-total-distance member per family."""

    families: dict[str, list[dict[str, Any]]] = {}
    family_order: list[str] = []
    for candidate in candidates:
        family = str(candidate.get("family") or "")
        if family not in families:
            families[family] = []
            family_order.append(family)
        families[family].append(candidate)
    representatives: list[dict[str, Any]] = []
    for family in family_order[:_VLM_PILOT_MAX_REQUESTS]:
        members = families[family]
        representative = min(
            members,
            key=lambda candidate: (
                sum(
                    float(morphology_distance(
                        candidate["morphology_evidence"]["descriptor"],
                        other["morphology_evidence"]["descriptor"],
                    ))
                    for other in members
                ),
                str(candidate.get("candidate_id") or ""),
            ),
        )
        representatives.append(representative)
    return representatives


def _run_bounded_vlm_pilot(
    candidates: list[dict[str, Any]],
    *,
    run_directory: Path,
    model: str | None,
) -> dict[str, Any]:
    """Run only the explicit, family-medoid, low-detail paid pilot."""

    records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    representatives = _select_morphology_medoids(candidates)
    for candidate in representatives[:_VLM_PILOT_MAX_REQUESTS]:
        program_payload = candidate.get("geometry_program")
        program = (
            GeometryProgram.from_dict(program_payload)
            if isinstance(program_payload, dict)
            else program_payload
        )
        references = list(retrieve_geometry_reference_matches(
            program,
            building_type=str(candidate.get("family") or "generic"),
            limit=3,
        ))[:3]
        preview_path = (
            run_directory / str(candidate.get("render_png") or "")
        ).resolve()
        result = score_candidate_with_openai_vlm(
            feature={
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "candidate_id": str(candidate.get("candidate_id") or ""),
                    "geometry_program": deepcopy(program_payload),
                    "creative_family": str(candidate.get("family") or ""),
                },
            },
            image_path=preview_path,
            reference_matches=references,
            model=model,
            image_detail="low",
            program_hash=str(candidate.get("program_hash") or ""),
            geometry_hash=str(candidate.get("geometry_hash") or ""),
        )
        candidate_events = build_reference_review_events(
            retrieved_references=references,
            vlm_result=result,
            program_hash=str(candidate.get("program_hash") or ""),
            geometry_hash=str(candidate.get("geometry_hash") or ""),
        )
        events.extend(mutable_event(event) for event in candidate_events)
        records.append({
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "family": str(candidate.get("family") or ""),
            "program_hash": str(candidate.get("program_hash") or ""),
            "geometry_hash": str(candidate.get("geometry_hash") or ""),
            "reference_count": len(references),
            "model": str(result.get("model") or model or ""),
            "response_id": str(result.get("response_id") or ""),
            "vlm_result": deepcopy(result),
        })
    return {
        "schema_version": "arr.maas.creative_vlm_pilot.v1",
        "status": "completed",
        "request_count": len(records),
        "max_request_count": _VLM_PILOT_MAX_REQUESTS,
        "reference_limit_per_request": 3,
        "candidate_image_detail": "low",
        "representative_policy": "one_morphology_medoid_per_family",
        "records": records,
        "events": events,
    }


def _persist_candidate(
    candidate: Any,
    *,
    run_directory: Path,
    candidates_directory: Path,
    renders_directory: Path,
    run_id: str,
    pnu: str,
) -> tuple[dict[str, Any], Path]:
    if not isinstance(candidate, dict):
        raise CommandError("creative portfolio candidate must be an object")
    payload = deepcopy(candidate)
    candidate_id = str(payload.get("candidate_id") or "").strip()
    program_hash = str(payload.get("program_hash") or "").strip()
    geometry_hash = str(payload.get("geometry_hash") or "").strip()
    program_payload = payload.get("geometry_program")
    mesh = payload.get("mesh")
    if (
        not candidate_id
        or not program_hash
        or not geometry_hash
        or not isinstance(program_payload, dict)
        or not isinstance(mesh, dict)
        or not mesh.get("vertices")
        or not mesh.get("triangles")
    ):
        raise CommandError("creative portfolio candidate is incomplete")
    try:
        program = GeometryProgram.from_dict(program_payload)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"{candidate_id} has an invalid GeometryProgram"
        ) from exc
    if program.program_hash() != program_hash:
        raise CommandError(f"{candidate_id} program hash mismatch")

    vertices = tuple(
        tuple(float(value) for value in vertex)
        for vertex in mesh["vertices"]
    )
    triangles = tuple(
        tuple(int(value) for value in triangle)
        for triangle in mesh["triangles"]
    )
    mesh_evidence = (
        payload.get("mesh_evidence")
        if isinstance(payload.get("mesh_evidence"), dict)
        else {}
    )
    metrics = {
        **deepcopy(mesh_evidence),
        "triangle_count": len(triangles),
        "vertex_count": len(vertices),
    }
    result = CompilationResult(
        program=program,
        status="compiled",
        vertices=vertices,
        triangles=triangles,
        metrics=metrics,
        trace=tuple(deepcopy(payload.get("matrix4_trace") or ())),
        geometry_hash=geometry_hash,
    )
    preview_path = renders_directory / f"{candidate_id}.png"
    render_compilation_preview(
        result,
        preview_path,
        title=f"{candidate_id} {payload.get('family') or ''}",
    )

    candidate_path = candidates_directory / f"{candidate_id}.json"
    relative_candidate = candidate_path.relative_to(run_directory).as_posix()
    relative_preview = preview_path.relative_to(run_directory).as_posix()
    payload.update({
        "run_id": run_id,
        "pnu": pnu,
        "identity": {
            "schema_version": (
                "arr.maas.creative_candidate_identity.v1"
            ),
            "candidate_id": candidate_id,
            "program_hash": program_hash,
            "geometry_hash": geometry_hash,
        },
        "candidate_json": relative_candidate,
        "render_png": relative_preview,
    })
    legal_review = payload.get("legal_review")
    if (
        not isinstance(legal_review, dict)
        or legal_review.get("status") != "not_evaluated"
        or legal_review.get("hard_pass") is not False
    ):
        raise CommandError(
            f"{candidate_id} must remain legally not_evaluated"
        )
    try:
        research_bundle = write_creative_mass_research_bundle(
            payload,
            run_directory=run_directory,
            run_id=run_id,
            pnu=pnu,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise CommandError(
            f"{candidate_id} research bundle failed: {exc}"
        ) from exc
    payload.update({
        "mass_directory": research_bundle["mass_directory"],
        "mass_manifest": research_bundle["mass_manifest"],
        "elevation_research_handoff": research_bundle[
            "elevation_research_handoff"
        ],
    })
    _write_json_atomic(candidate_path, payload)
    return payload, preview_path


def _frontend_graph(
    candidates: list[dict[str, Any]],
    *,
    run_id: str,
    pnu: str,
) -> dict[str, Any]:
    portfolio_id = f"creative:portfolio:{run_id}"
    nodes: list[dict[str, Any]] = [{
        "id": portfolio_id,
        "kind": "geometry_portfolio",
        "identity": run_id,
        "label": f"Creative authored choice pool · {len(candidates)}",
        "attributes": {
            "run_id": run_id,
            "pnu": pnu,
            "candidate_count": len(candidates),
            "choice_pool": True,
            "legal_status": "not_evaluated",
        },
    }]
    edges: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        node_id = f"creative:candidate:{candidate_id}"
        nodes.append({
            "id": node_id,
            "kind": "creative_mass_candidate",
            "identity": candidate["geometry_hash"],
            "label": f"{candidate_id} · {candidate['family']}",
            "attributes": {
                "candidate_id": candidate_id,
                "family": candidate["family"],
                "capacity_band": candidate["capacity_band"],
                "storeys": candidate["storey_evidence"]["storey_count"],
                "legal_status": candidate["legal_review"]["status"],
                "program_hash": candidate["program_hash"],
                "geometry_hash": candidate["geometry_hash"],
                "candidate_json": candidate["candidate_json"],
                "render_png": candidate["render_png"],
            },
        })
        edges.append({
            "id": f"creative:member:{candidate_id}",
            "source": node_id,
            "target": portfolio_id,
            "kind": "member_of",
        })
    return {
        "schema_version": "arr.maas.creative_frontend_graph.v1",
        "graph_id": portfolio_id,
        "root_node_ids": [portfolio_id],
        "nodes": nodes,
        "edges": edges,
    }


def _filter_facets(
    candidates: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    values = {
        "family": Counter(
            str(candidate["family"]) for candidate in candidates
        ),
        "capacity_band": Counter(
            str(candidate["capacity_band"]) for candidate in candidates
        ),
        "storeys": Counter(
            str(candidate["storey_evidence"]["storey_count"])
            for candidate in candidates
        ),
        "legal_status": Counter(
            str(candidate["legal_review"]["status"])
            for candidate in candidates
        ),
    }
    return {
        facet: [
            {"value": value, "count": count}
            for value, count in sorted(counter.items())
        ]
        for facet, counter in values.items()
    }


def _write_board(
    items: list[tuple[str, Path]],
    output_path: Path,
    *,
    target_count: int | None = None,
) -> dict[str, Any]:
    columns = 5 if len(items) == 20 else _BOARD_COLUMNS
    rows = max(1, (len(items) + columns - 1) // columns)
    card_height = _BOARD_IMAGE_HEIGHT + _BOARD_LABEL_HEIGHT
    image = Image.new(
        "RGB",
        (_BOARD_CARD_WIDTH * columns, card_height * rows),
        "#e8eef5",
    )
    draw = ImageDraw.Draw(image)
    if not items:
        draw.text(
            (18, 18),
            f"PRE-LEGAL PARTIAL 0/{int(target_count or 0)}",
            fill="#172033",
        )
        draw.text(
            (18, 45),
            "NOT LAW, PARKING, CAPACITY OR VLM ACCEPTED",
            fill="#172033",
        )
    for index, (label, path) in enumerate(items):
        row, column = divmod(index, columns)
        x = column * _BOARD_CARD_WIDTH
        y = row * card_height
        with Image.open(path) as source:
            thumbnail = source.convert("RGB").crop(
                (0, 0, 450, 325)
            ).resize(
                (_BOARD_CARD_WIDTH, _BOARD_IMAGE_HEIGHT),
                Image.Resampling.LANCZOS,
            )
        image.paste(thumbnail, (x, y))
        draw.rectangle(
            (
                x,
                y + _BOARD_IMAGE_HEIGHT,
                x + _BOARD_CARD_WIDTH,
                y + card_height,
            ),
            fill="#ffffff",
        )
        draw.text(
            (x + 7, y + _BOARD_IMAGE_HEIGHT + 5),
            f"{index + 1:03d} PRE-LEGAL {label[:34]}",
            fill="#172033",
        )
    temporary = output_path.with_suffix(".tmp.png")
    image.save(temporary)
    temporary.replace(output_path)
    return {
        "path": output_path.name,
        "status": "pre_legal_not_evaluated",
        "columns": columns,
        "rows": rows,
        "card_width_px": _BOARD_CARD_WIDTH,
        "card_height_px": card_height,
        "candidate_count": len(items),
        "target_count": target_count,
        "acceptance_label": (
            "PRE-LEGAL / NOT LAW, PARKING, CAPACITY OR VLM ACCEPTED"
        ),
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)

"""Program-independent base-seed and chassis population.

The form bank is deliberately authored before a building use is known.  It
contains only normalized host proportions and topological relations.  BOOK
scope/operations are projected later, and program roles plus VLM judgement are
downstream consumers rather than geometry authors for this stage.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_SEED_SPECS
from backend.app.modules.design.generation.maas.geometry_language.chassis_taxonomy import classify_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.programs import architectural_shape_programs, rare_unitbox_capability_programs
from backend.app.modules.design.generation.maas.geometry_language.stacked_volume_bank import stacked_volume_programs
from backend.app.modules.design.generation.maas.geometry_language.synthesis import synthesize_architectural_programs
from backend.app.modules.design.generation.maas.geometry_language.typology_priors import TYPOLOGY_PRIORS


UNIVERSAL_FORM_BANK_SCHEMA = "arr.maas.universal_form_bank.v2"

_UNIVERSAL_INTENTS = (
    "calm_prismatic",
    "continuous_curve",
    "long_span",
    "oblique_section",
    "stepped_section",
    "carved_void",
    "lifted_ground",
    "daylight_section",
    "distributed_wings",
    "vertical_landmark",
    "profiled_span_section",
    "face_composition",
)

_UNIVERSAL_MACROS = (
    "courtyard",
    "carve_void",
    "notch",
    "setback",
    "terrace",
    "cantilever",
    "lift",
    "puncture",
    "cross_mass",
    "grid_mass",
    "bent_bar",
    "split_wing",
    "stepped_mass",
    "profiled_hall",
    "attach",
)


def universal_form_bank_contract() -> dict[str, Any]:
    """Return the immutable stage contract exposed to audits and the UI."""
    return {
        "schema_version": UNIVERSAL_FORM_BANK_SCHEMA,
        "stage_order": (
            "base_seed",
            "chassis",
            "base_volume",
            "book_principle",
            "book_variation",
            "program_projection",
            "capacity_alternative_projection",
            "hard_gates",
            "live_vlm",
        ),
        "program_conditioned": False,
        "parcel_coordinates_used": False,
        "base_seed_ids": tuple(spec.seed_id for spec in BASE_SEED_SPECS),
        "chassis_ids": tuple(prior.typology_id for prior in TYPOLOGY_PRIORS),
        "intent_tags": _UNIVERSAL_INTENTS,
        "operator_sampling": "balanced_unique_round_robin",
        "synthesis_lane_program_count": 64,
        "replenishment_page_size": 64,
        "maximum_cached_variation_pages": 8,
        "replenishment_rule": "advance_low_discrepancy_geometry_program_page",
        "executable_core_lane_program_count": len(architectural_shape_programs()),
        "rare_unitbox_capability_parent_count": len(
            rare_unitbox_capability_programs()
        ),
        "multi_volume_lane_program_count": len(stacked_volume_programs(0)),
        "multi_volume_lane": (
            "stacked_offset_volumes", "stacked_alternating_volumes",
            "lifted_stack_volumes", "plinth_and_upper_volumes",
            "twin_volume_bridge", "pinwheel_volumes",
        ),
        "executable_core_lane": (
            "bent_linear", "radial_fan", "l_mass", "u_mass", "courtyard",
            "attached_volume", "overlap", "setback", "cross", "taper",
            "lean", "notch", "slice", "cut_corner", "loft", "sweep",
            "split_bridge", "twist",
        ),
        "synthesis_capabilities": (
            "triangular_profiled_prism",
            "trapezoidal_profiled_prism",
            "chamfered_profiled_prism",
            "kite_profiled_prism",
            "oval_profiled_prism",
            "stadium_profiled_prism",
            "concave_l_profiled_prism",
            "hexagon_profiled_prism",
            "host_face_attachment",
        ),
    }


@lru_cache(maxsize=8)
def universal_form_programs(variation_page: int = 0) -> tuple[GeometryProgram, ...]:
    """Build one deterministic page of the program-independent form bank.

    Page zero is the public baseline and also carries the 18 executable core
    language examples.  Later pages continue the same low-discrepancy
    parameter lattice without replaying those fixed examples.  This gives a
    bounded replenishment cycle genuinely new Geometry Programs instead of
    renaming the same payload through a legacy program-role parent variant.
    """
    page = max(0, min(7, int(variation_page)))
    request = {
        "base_seeds": [spec.seed_id for spec in BASE_SEED_SPECS],
        "intent_tags": list(_UNIVERSAL_INTENTS),
        "typology_priors": [prior.typology_id for prior in TYPOLOGY_PRIORS],
        "candidate_count": 64,
        # One readable chassis relation precedes the later BOOK operation.
        "maximum_operator_depth": 1,
        "downstream_body_rule_reserve": 0,
        "allowed_macro_operators": list(_UNIVERSAL_MACROS),
        "balanced_operator_sampling": True,
        "variation_offset": page * 64,
    }
    canonical_supply: list[GeometryProgram] = []
    synthesis_hashes: set[str] = set()
    # PROFILED PRISM is a valid authoring-language seed, but the executable
    # MASS control lane has the stricter one-UnitBox authority required by the
    # downstream legal compiler.  Pull deterministic reserve lattice batches
    # until the public 64-record page is full instead of wasting diagnostic
    # evaluations on programs that the authority bridge must reject.
    reserve_offsets = (
        page * 64,
        512 + page * 128,
        576 + page * 128,
    )
    for variation_offset in reserve_offsets:
        batch = synthesize_architectural_programs(
            {
                **request,
                "variation_offset": variation_offset,
            },
            building_type="unconditioned_form_bank",
        )
        for program in batch:
            primitives = tuple(
                node for node in program.nodes
                if node.kind == "primitive"
            )
            if (
                len(primitives) != 1
                or primitives[0].operator != "box"
                or primitives[0].parameters
                != {"width": 1.0, "depth": 1.0, "height": 1.0}
            ):
                continue
            if not _is_one_connected_solid(program):
                # A composed mass is connected by construction, but a macro
                # applied after the union - a courtyard cut across a thin
                # engagement, say - can still sever it. The downstream loop
                # rejects a multi-component candidate anyway, at the cost of a
                # full legal materialization; refusing it here as supply costs
                # one 3ms compile.
                continue
            program_hash = program.program_hash()
            if program_hash in synthesis_hashes:
                continue
            synthesis_hashes.add(program_hash)
            canonical_supply.append(program)
    # Filtering the noncanonical seed must not collapse the advertised
    # balanced family distribution.  Preserve the public first three, then
    # take the deterministic reserve stream with the existing five-per-family
    # ceiling.
    synthesis_programs = list(canonical_supply[:3])
    family_counts: dict[str, int] = {}
    for program in synthesis_programs:
        family = str(program.metadata.get("family") or "")
        family_counts[family] = family_counts.get(family, 0) + 1
    for program in canonical_supply[3:]:
        family = str(program.metadata.get("family") or "")
        family_cap = (
            2 if family == "agent_profiled_hall"
            else 3 if family == "agent_split_wing"
            else 5
        )
        if family_counts.get(family, 0) >= family_cap:
            continue
        synthesis_programs.append(program)
        family_counts[family] = family_counts.get(family, 0) + 1
        if len(synthesis_programs) >= 64:
            break
    if len(synthesis_programs) != 64:
        raise RuntimeError(
            "universal form bank could not fill one canonical UnitBox page"
        )
    synthesis_lane = tuple(
        (program, "bounded_synthesis")
        for program in synthesis_programs
    )
    if page == 0:
        core_lane = tuple(
            (program, "executable_core_language")
            for program in architectural_shape_programs()
        )
        rare_capability_lane = tuple(
            (program, "rare_unitbox_capability")
            for program in rare_unitbox_capability_programs()
        )
        # The other three lanes are a one-body language: 80 of the 86 page-zero
        # programs are a single box with one modifier, so every selected mass
        # could only ever read as one solid carved by the legal envelope. This
        # lane supplies the relations between repeated volumes that the rest
        # of the bank cannot express.
        multi_volume_lane = tuple(
            (program, "multi_volume_composition")
            for program in stacked_volume_programs(page)
        )
        interleaved: list[tuple[GeometryProgram, str]] = []
        synthesis_tail = synthesis_lane[3:]
        for index in range(max(len(synthesis_tail), len(core_lane))):
            if index < len(synthesis_tail):
                interleaved.append(synthesis_tail[index])
            if index < len(core_lane):
                interleaved.append(core_lane[index])
        lanes = (
            *synthesis_lane[:3],
            *interleaved,
            *rare_capability_lane,
            *multi_volume_lane,
        )
    else:
        lanes = (
            *synthesis_lane,
            *tuple(
                (program, "multi_volume_composition")
                for program in stacked_volume_programs(page)
            ),
        )
    records: list[GeometryProgram] = []
    seen_hashes: set[str] = set()
    for program, lane in lanes:
        source_operators = tuple(node.operator for node in program.nodes)
        taxonomy = classify_geometry_program(
            family=str(program.metadata.get("family") or ""),
            source_operators=source_operators,
            declared_base_seed=program.metadata.get("base_seed"),
        )
        normalized = replace(program, metadata={
            **program.metadata,
            "language_layer": "universal_form_bank",
            "form_bank_schema_version": UNIVERSAL_FORM_BANK_SCHEMA,
            "form_bank_lane": lane,
            "form_bank_variation_page": page,
            "program_conditioned": False,
            "program_projection_applied": False,
            "parcel_coordinates_in_program": False,
            "base_seed": taxonomy["base_seed"],
            "chassis": taxonomy["chassis"],
            "chassis_taxonomy_authority": taxonomy["authority"],
        })
        program_hash = normalized.program_hash()
        if program_hash in seen_hashes:
            continue
        seen_hashes.add(program_hash)
        records.append(normalized)
    return tuple(records)


def _is_one_connected_solid(program: GeometryProgram) -> bool:
    """Does this program compile to a single closed component?"""

    from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program

    try:
        result = compile_geometry_program(program)
    except Exception:  # noqa: BLE001 - a broken supply entry is just not supply
        return False
    return (
        getattr(result, "status", "") == "compiled"
        and int((result.metrics or {}).get("component_count") or 0) == 1
    )


def stratified_form_supply_order(
    programs: tuple[GeometryProgram, ...] | list[GeometryProgram],
) -> tuple[GeometryProgram, ...]:
    """Reorder a supply so that any prefix of it still spans the bank.

    A caller downstream of this bank never evaluates the whole supply: the
    exact-compile cap truncates it to a head of a few dozen. In construction
    order that head is not representative. Measured on page 0 (86 programs,
    44 families): the first 20 hold only 18 distinct families because the
    five-strong families repeat inside it, the four ``rare_unitbox_capability``
    programs sit at indices 82-85, and the composition moves this project
    actually needs - lift, terrace, setback, bridge, attached and overlapping
    volumes - are scattered from 14 to 68. None of them were reachable.

    Round-robining the family groups makes the head proportional instead:
    every family contributes its first program before any family contributes
    a second. Within a round the lanes are then spread by fair share, because
    family order alone still stacked a whole lane at the back - the
    multi-volume families are declared last, so they landed at 44-49 of a
    supply that is only read ~21 deep. Nothing is added, dropped or edited,
    and a caller that consumes the whole supply sees the same set.
    """

    supply = tuple(programs)
    groups: dict[str, list[GeometryProgram]] = {}
    for program in supply:
        # Grouping on the program's own declared family keeps this bank-driven:
        # a new family joins the rotation without naming it here.
        family = str(program.metadata.get("family") or "")
        groups.setdefault(family, []).append(program)
    lane_rank: dict[str, int] = {}
    for program in supply:
        lane_rank.setdefault(str(program.metadata.get("form_bank_lane") or ""),
                             len(lane_rank))

    ordered: list[GeometryProgram] = []
    while groups:
        round_programs = [groups[family].pop(0) for family in tuple(groups)]
        for family in tuple(groups):
            if not groups[family]:
                del groups[family]
        ordered.extend(_lane_fair_share(round_programs, lane_rank))
    return tuple(ordered)


def _lane_fair_share(
    round_programs: list[GeometryProgram],
    lane_rank: dict[str, int],
) -> list[GeometryProgram]:
    """Spread one round's programs so each lane is even across its length.

    A lane holding 6 of 50 families should appear about every eighth program,
    not as a block. Each entry is placed at its own fractional midpoint within
    its lane, which is what makes any prefix proportional in lane too.
    """

    lane_totals: dict[str, int] = {}
    for program in round_programs:
        lane = str(program.metadata.get("form_bank_lane") or "")
        lane_totals[lane] = lane_totals.get(lane, 0) + 1
    seen: dict[str, int] = {}
    keyed = []
    for position, program in enumerate(round_programs):
        lane = str(program.metadata.get("form_bank_lane") or "")
        index = seen.get(lane, 0)
        seen[lane] = index + 1
        share = (index + 0.5) / lane_totals[lane]
        keyed.append((share, lane_rank.get(lane, 0), position, program))
    return [program for _share, _rank, _position, program in sorted(keyed)]


def universal_form_program_pages(
    variation_pages: tuple[int, ...] | list[int],
    *,
    envelope_conditioning: dict[str, Any] | None = None,
) -> tuple[GeometryProgram, ...]:
    """Resolve a bounded ordered set of form-bank pages once for a caller.

    The pages themselves stay exactly as generated and cached; supplying the
    lawful field's proportion guidance only reorders them, so a caller with no
    lawful context gets byte-identical supply.
    """

    pages = tuple(sorted({
        max(0, min(7, int(page))) for page in variation_pages
    })) or (0,)
    supply = tuple(
        program
        for page in pages
        for program in universal_form_programs(page)
    )
    if not envelope_conditioning:
        return supply
    from backend.app.modules.design.generation.maas.geometry_language.legal_envelope.supply_ranking import rank_programs_by_lawful_fit

    return rank_programs_by_lawful_fit(supply, envelope_conditioning)


__all__ = [
    "UNIVERSAL_FORM_BANK_SCHEMA",
    "stratified_form_supply_order",
    "universal_form_bank_contract",
    "universal_form_program_pages",
    "universal_form_programs",
]

"""BOOK sentences: what the author writes, and how one becomes a program.

The BOOK's grammar is a base volume, an orientation, one principle (an
operative word, a combination, an aggregation or a case study) and a bounded
variation - the composition lattice in `composition_lattice.py` enumerates
exactly those 13,662 paths, and the page audit builds every one of them
through the same adapter this module calls. The author's job is to choose
sentences from that lattice, size them and face them; the geometry is the
grammar's, not the author's.

The free typed-AST author remains for development, where a parent's exact
nodes are inherited. It is not the creative author any more: comp18's 120
free ASTs were four seeds, four or five nodes each and `notch` sixty-two
times, and not one of the six base volumes.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.app.modules.design.generation.maas.dimensional_intent import KEY as INTENT_KEY, intent_schema, validate_intent
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_program
from backend.app.modules.design.generation.maas.geometry_language.book_adapter import apply_book_projection_to_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.program_massing import book_sentence_variants, compose_program_with_book_operations, program_seed_sequences
from backend.app.modules.design.generation.maas.book_language.composition_lattice import book_composition_path_by_id, iter_book_composition_paths
from backend.app.modules.design.generation.maas.book_language.corpus_contract import BOOK_VARIATION_COUNT
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry

SIDES = ("east", "west", "north", "south")
SENTENCE_KEY = "sentences"
REPRESENTATION = "book_sentence"
_CONNECTED = GeometryGatePolicy(maximum_components=1)
_PROGRAM_SEED_FALLBACK = "gymnasium"


class BookSentenceError(ValueError):
    """One sentence that the grammar could not build; carries the index."""


def sentence_payload_schema(offered_path_ids: list[str] | tuple[str, ...], *, count: int) -> dict[str, Any]:
    """The strict JSON schema the author's file must satisfy."""

    facing = {
        "type": "object",
        "additionalProperties": False,
        "required": ["access_side", "north_side"],
        "properties": {
            "access_side": {"enum": list(SIDES)},
            "north_side": {"enum": list(SIDES)},
        },
    }
    sentence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "book_composition_path_id", INTENT_KEY, "facing", "site_fit", "rationale"],
        "properties": {
            "name": {"type": "string", "minLength": 3, "maxLength": 80, "pattern": "^[a-z0-9_]+$"},
            "book_composition_path_id": {"enum": list(offered_path_ids)},
            INTENT_KEY: intent_schema(),
            "facing": facing,
            # How the figure meets the parcel: fitted inside and trimmed
            # (impose) or placed at its size and cut to the outline (inherit).
            # The author's call, sentence by sentence; the harness only obeys it.
            "site_fit": {"type": "string", "enum": ["impose", "inherit"]},
            "base_seed": {"type": "string", "enum": ["block", "slab", "bar", "tower", "profiled_prism"]},
            "rationale": {"type": "string", "minLength": 10, "maxLength": 600},
        },
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": [SENTENCE_KEY],
        "properties": {
            SENTENCE_KEY: {"type": "array", "minItems": int(count), "maxItems": int(count), "items": sentence},
        },
    }


def offered_paths(count: int, *, seed: int = 0) -> list[dict[str, Any]]:
    """A stratified offer: every base volume x orientation x principle kind.

    Roughly two to three offers per sentence asked for, spread so that no
    label, orientation or kind is missing from what the author sees.
    """

    paths = [path for path in iter_book_composition_paths() if path.executable]
    buckets: dict[tuple[str, str, str], list] = {}
    for path in paths:
        buckets.setdefault((path.base_volume_label, path.orientation, path.principle_kind), []).append(path)
    target = max(24, int(count) * 5 // 2)
    per_bucket = max(1, -(-target // max(1, len(buckets))))
    chosen = []
    verbs = _principle_verbs()
    for index, key in enumerate(sorted(buckets)):
        pool = sorted(buckets[key], key=lambda item: (item.principle_id, item.variation_index))
        stride = max(1, len(pool) // per_bucket)
        offset = (seed + index) % stride
        # Walk the bucket from its offset and keep the first `per_bucket`
        # paths that build and stand; a path that floats is not offered.
        ordered = pool[offset:] + pool[:offset]
        kept = 0
        for path in ordered:
            if kept >= per_bucket:
                break
            if _path_stands(path, verbs):
                chosen.append(path)
                kept += 1
    return [{
        "path_id": path.path_id,
        "base_volume": path.base_volume_label,
        "orientation": path.orientation,
        "principle": path.principle_id,
        "kind": path.principle_kind,
        "words": list(path.ordered_operations),
        "variation": path.variation_index,
        "page": path.page,
    } for path in chosen]


def _path_stands(path, verbs: dict[str, tuple[str, ...]]) -> bool:
    probe = {"book_composition_path_id": path.path_id,
             "facing": {"access_side": "east", "north_side": "north"},
             INTENT_KEY: {"schema_version": "arr.maas.dimensional_intent.v1", "storey_count": 5,
                          "storey_height_m": 3.8, "target_gfa_m2": 4800.0,
                          "delivery_policy": "preserve_physical_dimensions", "programme_status": "unknown"}}
    try:
        program = realize_book_sentence(probe, principle_verbs=verbs)
        compilation = compile_geometry_program(program)
    except (BookSentenceError, ValueError, TypeError, KeyError):
        return False
    if compilation.status != "compiled" or compilation_gate(compilation, _CONNECTED):
        return False
    return not _stands(standing_evidence(compilation))


def _principle_verbs() -> dict[str, tuple[str, ...]]:
    registry = build_book_language_registry()
    return {
        str(item["principle_id"]): tuple(str(verb) for verb in item["execution_verbs"])
        for item in registry["principles"]
    }


def _program_seed(building_type: str | None):
    for candidate in (building_type, _PROGRAM_SEED_FALLBACK):
        if not candidate:
            continue
        try:
            sequences = program_seed_sequences(str(candidate))
        except Exception:  # noqa: BLE001 - an unregistered building type falls through
            continue
        if sequences:
            return sequences[0]
    raise BookSentenceError("no program seed sequence is registered")




def standing_evidence(compilation) -> dict[str, float | None]:
    """The standing margin and how much of the plan stands on the ground.

    The ground-contact ratio is evidence for the record; only the
    centre-of-mass margin refuses (physics, the same test the stage runs).
    """
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    margin = standing_margin(compilation)
    vertices = np.asarray(compilation.vertices, dtype=float)
    triangles = np.asarray(compilation.triangles, dtype=int)
    if margin is None or not len(triangles):
        return {"margin": margin, "ground_ratio": None}
    z_low = float(vertices[:, 2].min())
    eps = max(1e-9, float(vertices[:, 2].max() - z_low) * 1e-6)
    faces = [Polygon(face[:, :2]) for face in (vertices[t] for t in triangles)]
    faces = [(poly, float(abs(vertices[t][:, 2] - z_low).max()) <= eps) for poly, t in zip(faces, triangles) if poly.area > 1e-12]
    plan = unary_union([poly for poly, _ in faces]).area
    ground = unary_union([poly for poly, on_ground in faces if on_ground]).area
    return {"margin": margin, "ground_ratio": (ground / plan) if plan > 0 else None}


def _stands(evidence: dict[str, float | None]) -> str:
    """Empty when the body stands; otherwise why not."""
    margin, ratio = evidence["margin"], evidence["ground_ratio"]
    if margin is None:
        return "no_ground_contact"
    if margin <= 0.0:
        return f"centre_of_mass_{-margin:.3f}_outside_ground"
    # The ground-contact ratio is reported, not judged: how much of a plan
    # stands on the ground is taste, and taste is the jury's. Physics only.
    return ""


def standing_margin(compilation) -> float | None:
    """How far inside its ground contact the body's centre of mass stands.

    The book draws aggregations as bars floating against each other; a
    building's parts stand on the ground or on each other. comp24 built
    24 sentences that finally looked like the book's pages and the gravity
    screen refused 12 of them for a centre of mass 6-12 m outside the
    ground contact. The same measure at unit scale predicts the screen's
    verdict (axis-aligned scaling keeps the sign), so it is asked here,
    before the author is offered a path and again when a sentence is built.
    Positive: stands. Negative: overhangs by that much. None: no ground.
    """
    import numpy as np
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    vertices = np.asarray(compilation.vertices, dtype=float)
    triangles = np.asarray(compilation.triangles, dtype=int)
    if not len(vertices) or not len(triangles):
        return None
    a, b, c = vertices[triangles[:, 0]], vertices[triangles[:, 1]], vertices[triangles[:, 2]]
    signed = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    volume = float(signed.sum())
    if abs(volume) <= 1e-12:
        return None
    com = (signed[:, None] * (a + b + c) / 4.0).sum(axis=0) / volume
    z_low = float(vertices[:, 2].min())
    eps = max(1e-9, float(vertices[:, 2].max() - z_low) * 1e-6)
    ground = [Polygon(face[:, :2]) for face in (vertices[t] for t in triangles)
              if float(abs(face[:, 2] - z_low).max()) <= eps]
    ground = [poly for poly in ground if poly.area > 1e-12]
    if not ground:
        return None
    hull = unary_union(ground).convex_hull
    point = Point(float(com[0]), float(com[1]))
    distance = float(hull.boundary.distance(point))
    return distance if hull.covers(point) else -distance


def realize_book_sentence(
    sentence: dict[str, Any],
    *,
    site_extent: tuple[float, float, float] | None = None,
    building_type: str | None = None,
    principle_verbs: dict[str, tuple[str, ...]] | None = None,
) -> GeometryProgram:
    """Build the sentence's program the way the page audit builds a page."""

    path_id = str(sentence.get("book_composition_path_id") or "")
    path = book_composition_path_by_id(path_id)
    if path is None:
        raise BookSentenceError(f"unknown_path:{path_id}")
    if not path.executable:
        raise BookSentenceError(f"path_not_executable:{path_id}")
    verbs = (principle_verbs or _principle_verbs()).get(path.principle_id)
    if not verbs:
        raise BookSentenceError(f"principle_without_verbs:{path.principle_id}")
    intent = validate_intent(sentence.get(INTENT_KEY))
    facing = sentence.get("facing") or {}
    for key in ("access_side", "north_side"):
        if facing.get(key) not in SIDES:
            raise BookSentenceError(f"facing_{key}_must_be_one_of_{'/'.join(SIDES)}")
    site_fit = str(sentence.get("site_fit") or "inherit")
    if site_fit not in ("impose", "inherit"):
        raise BookSentenceError("site_fit_must_be_impose_or_inherit")
    variants = book_sentence_variants(verbs, count=BOOK_VARIATION_COUNT)
    if not 0 <= int(path.variation_index) < len(variants):
        raise BookSentenceError(f"variation_out_of_range:{path.variation_index}")
    sequence = compose_program_with_book_operations(
        _program_seed(building_type),
        variants[int(path.variation_index)],
        base_volume_label=path.base_volume_label,
        orientation=path.orientation,
    )
    base_seed_id = str(sentence.get("base_seed") or "")
    if not base_seed_id or base_seed_id not in ("block", "slab", "bar", "tower", "profiled_prism"):
        base_seed_id = "block"
    base = base_seed_program(base_seed_id, site_extent=site_extent, variation_index=int(path.variation_index))
    # The base volume is the object, not a cell of the block with the rest
    # of the block put back (that is the scope model massv2 edits with).
    program = apply_book_projection_to_geometry_program(base, sequence, recompose_remainder=False)
    name = str(sentence.get("name") or f"sentence_{path_id[-6:]}")
    return replace(program, name=name, metadata={
        **program.metadata,
        "author_representation": REPRESENTATION,
        "base_seed": path.base_volume_label,
        "book_base_volume_label": path.base_volume_label,
        "book_orientation": path.orientation,
        "book_composition_path_id": path.path_id,
        "book_principle_id": path.principle_id,
        "book_principle_kind": path.principle_kind,
        "book_words": list(path.ordered_operations),
        "book_variation_index": int(path.variation_index),
        INTENT_KEY: intent,
        "facing": {"access_side": facing["access_side"], "north_side": facing["north_side"]},
        "site_fit": site_fit,
        "rationale": str(sentence.get("rationale") or ""),
    })


def realize_sentence_payload(
    payload: dict[str, Any],
    *,
    expected_count: int,
    site_extent: tuple[float, float, float] | None = None,
    building_type: str | None = None,
) -> tuple[GeometryProgram, ...]:
    """Every sentence becomes a compiled, connected, unique program - or the
    batch is refused with the same 1-based verdict list the free-AST importer
    writes, so the cycle's retry reads it unchanged."""

    sentences = payload.get(SENTENCE_KEY)
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("sentence payload carries no sentences")
    verbs = _principle_verbs()
    programs: list[GeometryProgram] = []
    rejected: list[str] = []
    seen_hashes: set[str] = set()
    seen_paths: set[str] = set()
    for index, sentence in enumerate(sentences):
        label = f"{index + 1}"
        if not isinstance(sentence, dict):
            rejected.append(f"{label}:not_an_object")
            continue
        path_id = str(sentence.get("book_composition_path_id") or "")
        if path_id in seen_paths:
            rejected.append(f"{label}:duplicate_path:{path_id}")
            continue
        try:
            program = realize_book_sentence(
                sentence, site_extent=site_extent, building_type=building_type, principle_verbs=verbs)
        except (BookSentenceError, ValueError, TypeError, KeyError) as exc:
            rejected.append(f"{label}:{path_id or 'no_path'}:{type(exc).__name__}:{str(exc)[:160].replace(';', ',')}")
            continue
        compilation = compile_geometry_program(program)
        issues = compilation_gate(compilation, _CONNECTED)
        if compilation.status != "compiled" or issues:
            reason = (
                compilation.status if compilation.status != "compiled"
                else ",".join(issue.code for issue in issues[:3])
            )
            rejected.append(f"{label}:{path_id}:compile_or_clean_gate:{reason}")
            continue
        why = _stands(standing_evidence(compilation))
        if why:
            rejected.append(f"{label}:{path_id}:does_not_stand:{why}")
            continue
        program_hash = program.program_hash()
        if program_hash in seen_hashes:
            rejected.append(f"{label}:{path_id}:duplicate_program")
            continue
        seen_hashes.add(program_hash)
        seen_paths.add(path_id)
        programs.append(program)
    if len(programs) < max(1, int(expected_count)):
        from backend.app.modules.design.generation.maas.geometry_language.llm_adapter import GeometryAuthorError
        raise GeometryAuthorError(
            "geometry author batch yielded insufficient valid unique programs"
            + (": " + "; ".join(rejected) if rejected else "")
        )
    return tuple(programs)


__all__ = [
    "SENTENCE_KEY", "SIDES", "BookSentenceError", "offered_paths",
    "realize_book_sentence", "realize_sentence_payload", "sentence_payload_schema",
]


# ----------------------------------------------------------------- site facts
_COMPASS = (("east", (1.0, 0.0)), ("north", (0.0, 1.0)), ("west", (-1.0, 0.0)), ("south", (0.0, -1.0)))


def _compass(dx: float, dy: float) -> str | None:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return max(_COMPASS, key=lambda item: item[1][0] * dx + item[1][1] * dy)[0]


def site_facts_for_author(site, *, storey_cap: int | None = None) -> dict[str, Any]:
    """What the author must know about the parcel, from the site's own owners.

    Road/access: `site_open_side_evidence` (registered frontages when the
    plan has them). The sunlight side: the side of the ground plan that the
    top floor's legal plan no longer covers (정북일조 takes it), so no second
    owner of "north" is created. Areas by height: the legal floor field.
    """

    from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_evidence
    open_side = site_open_side_evidence(site) or {}
    direction = open_side.get("direction_world_xy") or (0.0, 0.0)
    ground = site.plan_at(0.0)
    cap = int(storey_cap or getattr(site, "max_storeys", 0) or 0)
    storey_m = float(getattr(site, "floor_height_m", 0.0) or 0.0)
    top = site.plan_at(max(0.0, cap * storey_m - 0.01)) if cap and storey_m else ground
    cut = ground.difference(top) if (ground is not None and top is not None) else None
    sunlight_side = None
    if cut is not None and not cut.is_empty and cut.area > 1.0:
        sunlight_side = _compass(cut.centroid.x - ground.centroid.x, cut.centroid.y - ground.centroid.y)
    field = getattr(site, "floor_field", {}) or {}
    heights = list(field.get("legal_floor_top_heights_m") or ())
    areas = list(field.get("legal_floor_section_areas_m2") or ())
    by_height = [{"top_m": float(h), "legal_plan_m2": round(float(a), 1)} for h, a in zip(heights, areas)][:max(1, cap or len(heights))]
    return {
        "pnu": str(getattr(site, "pnu", "")),
        "parcel_area_m2": round(float(getattr(site, "parcel_area_m2", 0.0) or 0.0), 1),
        "ground_capacity_m2": round(float(site.ground_capacity_m2), 3),
        "far_capacity_m2": round(float(site.far_capacity_m2), 3),
        "storey_cap": cap,
        "storey_height_m": storey_m,
        "access_side_world": _compass(float(direction[0]), float(direction[1])),
        "access_direction_world_xy": [round(float(direction[0]), 4), round(float(direction[1]), 4)],
        "access_basis": str(open_side.get("basis") or "unavailable"),
        "sunlight_setback_side_world": sunlight_side,
        "ground_legal_plan_m2": round(float(ground.area), 1) if ground is not None else None,
        "top_floor_legal_plan_m2": round(float(top.area), 1) if top is not None else None,
        "legal_plan_by_height": by_height,
        "frame": "program sides east(+x)/west(-x)/north(+y)/south(-y) are the program's own; "
                 "facing maps them onto the world sides named here",
    }


def sentence_prompt(context: dict[str, Any], offer: list[dict[str, Any]], *, count: int, output_path: str, schema_path: str) -> str:
    """The author's instructions - short, because the grammar does the work."""

    facts = context.get("site_facts") or {}
    far = facts.get("far_capacity_m2", context.get("capacity_ceiling_m2"))
    ground = facts.get("ground_capacity_m2", context.get("ground_capacity_m2"))
    cap = facts.get("storey_cap")
    storey_m = facts.get("storey_height_m")
    lines = [
        f"You are the BOOK author. Write exactly {count} BOOK sentences to {output_path}, valid against {schema_path}.",
        "",
        "A sentence is one path of the architect's BOOK: a base volume (1/1, 3/8, 1/2, 1/4, 1/8, 1/16 - cells of the unit cube; 3/8 is an L of three octants), "
        "an orientation (long_axis, short_axis, vertical), one principle (an operative word, a combination of two, an aggregation, or a case study) and a bounded variation. "
        "You choose the path from the OFFER below by its path_id; the grammar builds the geometry. You do not write nodes, operators or parameters.",
        "",
        "For each sentence give: name (snake_case, unique), book_composition_path_id (from the offer, each id at most once), dimensional_intent, facing, site_fit, base_seed, rationale.",
        "",
        "AUTHORING INTENT:",
        "  Author materially distinct spatial and sectional propositions for the project brief. "
        "Choose BOOK paths for their architectural purpose; there are no required operator counts, "
        "base-volume quotas, portfolio typologies or office styles.",
        "  Read the entire frozen project brief, including programme requirements and prior critique:",
        __import__("json").dumps(context.get("project_brief") or {"status": "unknown"}, ensure_ascii=False),
        "",
        "DIMENSIONAL INTENT - you decide the size; the law bounds it:",
        f"  FAR capacity m2: {far if far is not None else 'unknown'}; "
        f"coverage capacity m2: {ground if ground is not None else 'unknown'}; "
        f"legal storey cap: {cap if cap else 'unknown'}; "
        f"storey_height_m: {storey_m if storey_m else 'unknown'}. "
        "Choose target_gfa_m2 and storey_count from explicit programme requirements and the measured site constraints. "
        "Check the requested floor areas against coverage and legal_plan_by_height; "
        "do not infer a sunlight-setback exemption from a floor count or an assumed height threshold. "
        "For lifted or cantilevered schemes, ground support (piloti columns or grounded base) is required so the solid does not float in air. "
        "Internal cores and room layouts belong to schematic floor plans, not massing. "
        "Decide both from the figure and say the plan in rationale.",
        "  Missing site, legal or programme facts remain unknown. Capacity is a ceiling, not a programme target or minimum.",
        "",
        "SITE FIT - how the figure meets the parcel, your call per sentence:",
        "  site_fit: impose - the figure is scaled down until it stands almost entirely inside the parcel, then trimmed; its shape survives, its area shrinks. "
        "inherit - the figure is placed at its authored size and the parcel outline cuts it; its area survives, its shape takes the outline. "
        "Neither changes the law: both are checked against the same lines.",
        "  delivery_policy: preserve_physical_dimensions; programme_status: unknown; schema_version: arr.maas.dimensional_intent.v1.",
        "",
        "FACING - the program's own sides are east(+x), west(-x), north(+y), south(-y):",
        f"  access_side: which program side faces measured access. The evidenced parcel access side is {facts.get('access_side_world') or 'unknown'} "
        f"(basis: {facts.get('access_basis') or 'unknown'}); use access_direction_world_xy for alignment.",
        f"  north_side: which program side takes the sunlight setback. The evidenced parcel setback side is {facts.get('sunlight_setback_side_world') or 'unknown'}. "
        "Use legal_plan_by_height below to assess the actual legal section profile; a missing direction or profile is unknown.",
        "  Access alignment is exact. north_side must be a local cardinal side within 60 degrees of the legal setback direction after that rotation; a side turned further away is refused. "
        "If no directional legal setback is evidenced, north_side remains an explicitly unverified preference, not an executed true-north claim.",
        "",
        "SPREAD - no two sentences may share a path_id; choose distinct propositions that serve the brief.",
        "",
        "SITE FACTS (json):",
        __import__("json").dumps(facts, ensure_ascii=False),
        "",
        f"OFFER ({len(offer)} paths; path_id, base volume, orientation, principle, words, variation):",
    ]
    for item in offer:
        lines.append(f"  {item['path_id']}  {item['base_volume']:>4} {item['orientation']:<10} {item['principle']:<34} {'+'.join(item['words']):<24} v{item['variation']}")
    lines += [
        "",
        "Write the file with a JSON library, validate it against the schema, and write nothing else. Run no pipeline stages.",
    ]
    return chr(10).join(lines)


__all__ += ["site_facts_for_author", "sentence_prompt"]

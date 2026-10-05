"""Let the model author massing programs, not draw geometry.

CoMa (arXiv 2601.08464) tried the direct route - a VLM emitting footprint
polygons with bottom and top elevations, the same representation this pipeline
uses - and reported Site IoU 0.05 with frequent self-intersecting polygons. The
lesson is not that models cannot do massing; it is that they should not be asked
for coordinates. Asked instead for a short program in a vocabulary with a
deterministic executor, the same models do well (MeshCoder, CADSmith).

So the model writes `place(role, size, at, rotation)` calls. Every number it
emits is a fraction of the parcel's own limits rather than a metre value, which
keeps its answers parcel-independent and keeps it from having to reason about
UTM coordinates - the thing frontier models are measurably worst at
(GeoGramBench: 90% on basic geometric reasoning, 39% on complex abstract).

The legal gate stays deterministic. 3DCodeBench (Google DeepMind) measured that
a code-feedback loop lifts executability by 27 points and leaves shape quality
flat, so the model is not asked to satisfy the law - it is asked to compose.
"""

from __future__ import annotations

from typing import Any, Iterable

from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, place
from backend.app.modules.design.generation.maas.massv2.llm import LlmUnavailable, structured_call
from backend.app.modules.design.generation.maas.massv2.profiles import plan_names


_SYSTEM = (
    "You are an architect composing building massing for a competition entry. "
    "You compose masses across diverse architectural typologies - monolithic plinths, "
    "terraced slopes, porous courtyard fields, sculpted towers, or low-rise pavilions. "
    "Explore contrasting spatial philosophies across your schemes, from bold iconic moves "
    "to quiet, high-efficiency contextual responses. "
    "A deterministic legal solver sizes and clips whatever you propose, so do "
    "not try to satisfy floor area or setbacks. Compose."
)

_PLACEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "role", "kind", "width", "depth", "height", "x", "y", "z",
        "rotation_degrees", "lean_degrees", "lean_axis", "plan",
    ],
    "properties": {
        "role": {
            "type": "string",
            "description": "architectural name: plinth, bar, tower, wing, court, slot, cap",
        },
        "kind": {"type": "string", "enum": ["additive", "subtractive"]},
        # Plan terms are fractions of the site's own buildable width and depth;
        # height is a fraction of the legal height. Fractions travel between
        # parcels, metres do not.
        "width": {"type": "number", "description": "0.05..1.0 of buildable width"},
        "depth": {"type": "number", "description": "0.05..1.0 of buildable depth"},
        "height": {"type": "number", "description": "0.05..1.0 of legal height"},
        "x": {"type": "number", "description": "-0.2..1.0 lower corner, fraction of width"},
        "y": {"type": "number", "description": "-0.2..1.0 lower corner, fraction of depth"},
        "z": {"type": "number", "description": "-0.2..1.0 base, fraction of legal height"},
        "rotation_degrees": {"type": "number", "description": "-45..45 about its own centre"},
        "lean_degrees": {
            "type": "number",
            "description": "-45..45 off vertical about its own base; a leaning tower or raking bar",
        },
        "lean_axis": {"type": "string", "enum": ["x", "y"]},
        "plan": {
            "type": "string",
            # One owner: the executor's own plan table. A hand-copied list here
            # agreed with it by luck; the day they diverge, the model is offered
            # a shape the machine cannot build - or never offered one it can.
            "enum": sorted(plan_names()),
            "description": "the volume's base plan; a wedge or a folded plate is a base shape, not a transform",
        },
    },
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schemes"],
    "properties": {
        "schemes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name", "primary_language", "secondary_language",
                    "formal_principle", "dominant_gesture", "reference_basis",
                    "far_target", "placements",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "primary_language": {"type": "string"},
                    "secondary_language": {"type": "string"},
                    "formal_principle": {"type": "string"},
                    "dominant_gesture": {
                        "type": "string",
                        "description": "one sentence: the single move this scheme makes",
                    },
                    "far_target": {
                        "type": "number",
                        "description": (
                            "0.3..1.0 - how much of the allowed floor area this brief wants. "
                            "A shop block fills it; a gallery, a library or a scheme of "
                            "dispersed rooms does not, and forcing it to would destroy the move."
                        ),
                    },
                    "reference_basis": {
                        "type": "string",
                        "description": "a named built precedent this composition descends from",
                    },
                    "placements": {
                        "type": "array",
                        "items": _PLACEMENT_SCHEMA,
                        "minItems": 2,
                        "maxItems": 7,
                    },
                },
            },
        }
    },
}


def _prompt(
    *,
    count: int,
    buildable_width_m: float,
    buildable_depth_m: float,
    legal_height_m: float,
    ground_capacity_m2: float,
    far_capacity_m2: float,
    wanted_cells: Iterable[str],
) -> str:
    cells = ", ".join(wanted_cells) or "any"
    return (
        f"Compose {count} massing schemes for this parcel.\n\n"
        f"Buildable plan is about {buildable_width_m:.0f} m by {buildable_depth_m:.0f} m. "
        f"Legal height is about {legal_height_m:.0f} m. "
        f"The building footprint may cover at most {ground_capacity_m2:.0f} m2 measured as "
        f"the projection of the whole building, and total floor area at most "
        f"{far_capacity_m2:.0f} m2. The solver will enforce both - you do not have to.\n\n"
        "All numbers you emit are fractions, never metres: width/depth/x/y are "
        "fractions of the buildable plan, height/z are fractions of the legal height.\n\n"
        "Rules that make a scheme legible:\n"
        "- 2 to 5 additive volumes. More reads as noise, one reads as a box.\n"
        "- Volumes that stack must overlap slightly in z; a shared face is not a joint.\n"
        "- The result must stay one connected building.\n"
        "- A subtractive volume should overshoot the face it cuts so the cut lands clean.\n\n"
        "Make the schemes differ from each other in kind, not degree. A shifted "
        "stack, a pair of bars around a court, a cantilevered cross, a carved "
        "block and a splayed pair are five different buildings; five towers of "
        "different widths are one.\n\n"
        f"Aim to produce schemes that land in these positions: {cells}.\n"
        "Ground take is how much of the allowed footprint the building takes; "
        "void is how open the plan reads - solid_body, carved_body, open_figure, "
        "porous_field."
    )


def _to_form(record: dict[str, Any], *, width_m: float, depth_m: float, height_m: float) -> MatrixForm | None:
    placements = []
    for item in record.get("placements") or ():
        try:
            w = max(0.02, min(1.4, float(item["width"]))) * width_m
            d = max(0.02, min(1.4, float(item["depth"]))) * depth_m
            h = max(0.02, min(1.4, float(item["height"]))) * height_m
            x = max(-0.5, min(1.4, float(item["x"]))) * width_m
            y = max(-0.5, min(1.4, float(item["y"]))) * depth_m
            z = max(-0.5, min(1.4, float(item["z"]))) * height_m
            rotation = max(-60.0, min(60.0, float(item.get("rotation_degrees") or 0.0)))
            lean = max(-60.0, min(60.0, float(item.get("lean_degrees") or 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
        kind = "subtractive" if str(item.get("kind")) == "subtractive" else "additive"
        placements.append(
            place(str(item.get("role") or "volume"), size=(w, d, h), at=(x, y, z),
                  rotation_degrees=rotation, lean_degrees=lean,
                  lean_axis=str(item.get("lean_axis") or "x"),
                  plan=str(item.get("plan") or "square"), kind=kind)
        )
    if not any(item.kind == "additive" for item in placements):
        return None
    return MatrixForm(
        # The prefix marks these as model-authored for anything downstream that
        # distinguishes authored candidates from deterministic seeds.
        name=f"llm_{str(record.get('name') or 'scheme')}"[:60],
        placements=tuple(placements),
        primary_language=str(record.get("primary_language") or "authored"),
        secondary_language=str(record.get("secondary_language") or ""),
        formal_principle=str(record.get("formal_principle") or ""),
        dominant_gesture=str(record.get("dominant_gesture") or ""),
        reference_basis=str(record.get("reference_basis") or ""),
        notes=("authored_by=massv2_llm",),
        extra=(
            {"far_target": float(record["far_target"])}
            if isinstance(record.get("far_target"), (int, float))
            else {}
        ),
    )


def author_forms(
    *,
    count: int,
    buildable_width_m: float,
    buildable_depth_m: float,
    legal_height_m: float,
    ground_capacity_m2: float,
    far_capacity_m2: float,
    wanted_cells: Iterable[str] = (),
    model: str | None = None,
) -> list[MatrixForm]:
    """Ask the model for schemes and return the ones that parse into forms."""

    payload = structured_call(
        system=_SYSTEM,
        user=_prompt(
            count=count,
            buildable_width_m=buildable_width_m,
            buildable_depth_m=buildable_depth_m,
            legal_height_m=legal_height_m,
            ground_capacity_m2=ground_capacity_m2,
            far_capacity_m2=far_capacity_m2,
            wanted_cells=wanted_cells,
        ),
        schema=_SCHEMA,
        schema_name="massv2_schemes",
        model=model,
    )
    forms = [
        _to_form(record, width_m=buildable_width_m, depth_m=buildable_depth_m,
                 height_m=legal_height_m)
        for record in payload.get("schemes") or ()
    ]
    kept = [item for item in forms if item is not None]
    if not kept:
        raise LlmUnavailable("model returned no usable scheme")
    return kept

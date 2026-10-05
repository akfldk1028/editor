"""Multi-volume compositions built from repeated UnitBox instances.

The rest of the form bank is a one-body language: measured on page 0, 80 of
its 86 programs are a single box with a single modifier, and only one program
combines volumes more than once. Every selected mass therefore reads as one
solid carved by the legal envelope, which is not how the reference competition
massing for this project is composed - that is three or four clean orthogonal
volumes, stacked and shifted, with the ground lifted on piloti and the
setbacks read as intended terraces.

Nothing in the geometry layer prevented it. A plinth plus a shifted middle
volume plus a smaller upper volume, lifted, compiles to a single closed
component with no gate issues using only ``box``, ``translate``, ``union`` and
``lift``. What was missing was supply, so this module generates that supply.

Each program here is a parameter point, not a named building: the figures are
relations between repeated instances of the canonical 1/1 UnitBox (the builder
emits one UnitBox and one Matrix4 per instance), and no parcel dimension,
coordinate or completed-form template appears anywhere in this file.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import product

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.programs import GeometryProgramBuilder


# Normalized host proportions. These are the same order of magnitude as the
# rest of the bank's authored boxes and carry no site information; the legal
# field rescales every candidate downstream.
_PLAN_ASPECTS = (
    (12.0, 9.0),
    (14.0, 7.0),
    (10.0, 10.0),
)
_LEVEL_SCALES = (0.72, 0.86)
_VOLUME_COUNTS = (2, 3, 4)
_LEVEL_HEIGHT = 4.0
# Consecutive levels overlap rather than touch: a shared coplanar face is a
# degenerate boolean input, and the overlap is what keeps the union one
# component.
_LEVEL_OVERLAP = 0.1
_VARIANTS_PER_FAMILY = 4


def _level_origin(index: int) -> float:
    return index * _LEVEL_HEIGHT * (1.0 - _LEVEL_OVERLAP)


def _stacked_offsets(
    builder: GeometryProgramBuilder,
    width: float,
    depth: float,
    scale: float,
    count: int,
    *,
    alternating: bool,
) -> list[str]:
    """Stack ``count`` shrinking volumes, each shifted off the one below."""

    volumes: list[str] = []
    origin = 0.0
    previous_width = width
    for index in range(count):
        level_scale = scale ** index
        level_width = width * level_scale
        level_depth = depth * level_scale
        if index:
            # Shift is measured from the level below, and bounded so the two
            # always overlap in plan. Without that bound an alternating stack
            # walks a level clear of the one under it and the union comes back
            # as two or three separate components.
            slack = previous_width - level_width
            reach = min(slack, level_width * 0.8)
            direction = -1.0 if alternating and index % 2 == 0 else 1.0
            origin += reach * direction
            previous_width = level_width
        box = builder.add(
            "primitive",
            "box",
            parameters={
                "width": level_width,
                "depth": level_depth,
                "height": _LEVEL_HEIGHT,
            },
            semantic_role="main" if index == 0 else "support",
        )
        if index:
            volumes.append(builder.add(
                "transform",
                "translate",
                inputs=(box,),
                parameters={"vector": [
                    origin,
                    (depth - level_depth) * 0.5,
                    _level_origin(index),
                ]},
            ))
        else:
            volumes.append(box)
    return volumes


def _union_all(builder: GeometryProgramBuilder, volumes: list[str]) -> str:
    root = volumes[0]
    for volume in volumes[1:]:
        root = builder.add(
            "boolean",
            "union",
            inputs=(root, volume),
            semantic_role="main",
        )
    return root


def _stacked_offset_volumes(name, width, depth, scale, count) -> GeometryProgram:
    builder = GeometryProgramBuilder(name)
    volumes = _stacked_offsets(
        builder, width, depth, scale, count, alternating=False,
    )
    return builder.build(
        _union_all(builder, volumes),
        family="stacked_offset_volumes",
    )


def _stacked_alternating_volumes(name, width, depth, scale, count) -> GeometryProgram:
    builder = GeometryProgramBuilder(name)
    volumes = _stacked_offsets(
        builder, width, depth, scale, count, alternating=True,
    )
    return builder.build(
        _union_all(builder, volumes),
        family="stacked_alternating_volumes",
    )


def _lifted_stack_volumes(name, width, depth, scale, count) -> GeometryProgram:
    """The same stack, with the ground given away to a piloti condition."""

    builder = GeometryProgramBuilder(name)
    volumes = _stacked_offsets(
        builder, width, depth, scale, count, alternating=False,
    )
    lifted = builder.add(
        "macro",
        "lift",
        inputs=(volumes[0],),
        parameters={"rise_ratio": 0.34, "support_ratio": 0.16},
        semantic_role="main",
    )
    volumes[0] = lifted
    return builder.build(
        _union_all(builder, volumes),
        family="lifted_stack_volumes",
    )


def _plinth_and_upper_volumes(name, width, depth, scale, count) -> GeometryProgram:
    """A wide low base carrying distinctly smaller volumes above it."""

    builder = GeometryProgramBuilder(name)
    plinth = builder.add(
        "primitive",
        "box",
        parameters={
            "width": width,
            "depth": depth,
            "height": _LEVEL_HEIGHT * 0.6,
        },
        semantic_role="main",
    )
    volumes = [plinth]
    upper_count = max(1, count - 1)
    upper_width = width * scale / upper_count
    for index in range(upper_count):
        box = builder.add(
            "primitive",
            "box",
            parameters={
                "width": upper_width,
                "depth": depth * scale,
                "height": _LEVEL_HEIGHT * 1.4,
            },
            semantic_role="support",
        )
        volumes.append(builder.add(
            "transform",
            "translate",
            inputs=(box,),
            parameters={"vector": [
                index * upper_width * 1.05,
                (depth - depth * scale) * 0.5,
                _LEVEL_HEIGHT * 0.6 * (1.0 - _LEVEL_OVERLAP),
            ]},
        ))
    return builder.build(
        _union_all(builder, volumes),
        family="plinth_and_upper_volumes",
    )


def _twin_volume_bridge(name, width, depth, scale, count) -> GeometryProgram:
    """Two separated volumes made one body by a volume bridging above them."""

    builder = GeometryProgramBuilder(name)
    leg_width = width * 0.34
    gap = width - 2.0 * leg_width
    leg_height = _LEVEL_HEIGHT * max(1, count - 1)
    volumes: list[str] = []
    for index in range(2):
        box = builder.add(
            "primitive",
            "box",
            parameters={
                "width": leg_width,
                "depth": depth,
                "height": leg_height,
            },
            semantic_role="main" if index == 0 else "support",
        )
        volumes.append(box if index == 0 else builder.add(
            "transform",
            "translate",
            inputs=(box,),
            parameters={"vector": [leg_width + gap, 0.0, 0.0]},
        ))
    bridge = builder.add(
        "primitive",
        "box",
        parameters={
            "width": width,
            "depth": depth * scale,
            "height": _LEVEL_HEIGHT,
        },
        semantic_role="support",
    )
    volumes.append(builder.add(
        "transform",
        "translate",
        inputs=(bridge,),
        parameters={"vector": [
            0.0,
            (depth - depth * scale) * 0.5,
            leg_height * (1.0 - _LEVEL_OVERLAP),
        ]},
    ))
    return builder.build(
        _union_all(builder, volumes),
        family="twin_volume_bridge",
    )


def _pinwheel_volumes(name, width, depth, scale, count) -> GeometryProgram:
    """Levels turned about the shared vertical axis rather than shifted."""

    builder = GeometryProgramBuilder(name)
    volumes: list[str] = []
    for index in range(count):
        level_scale = scale ** index
        level_width = width * level_scale
        level_depth = depth * level_scale
        box = builder.add(
            "primitive",
            "box",
            parameters={
                "width": level_width,
                "depth": level_depth,
                "height": _LEVEL_HEIGHT,
            },
            semantic_role="main" if index == 0 else "support",
        )
        if not index:
            volumes.append(box)
            continue
        turned = builder.add(
            "transform",
            "rotate",
            inputs=(box,),
            parameters={
                "axis": "z",
                "angle_degrees": 24.0 * index,
                "pivot": [level_width * 0.5, level_depth * 0.5, 0.0],
            },
        )
        volumes.append(builder.add(
            "transform",
            "translate",
            inputs=(turned,),
            parameters={"vector": [
                (width - level_width) * 0.5,
                (depth - level_depth) * 0.5,
                _level_origin(index),
            ]},
        ))
    return builder.build(
        _union_all(builder, volumes),
        family="pinwheel_volumes",
    )


_FIGURES = (
    ("stacked_offset", _stacked_offset_volumes),
    ("stacked_alternating", _stacked_alternating_volumes),
    ("lifted_stack", _lifted_stack_volumes),
    ("plinth_and_upper", _plinth_and_upper_volumes),
    ("twin_bridge", _twin_volume_bridge),
    ("pinwheel", _pinwheel_volumes),
)


@lru_cache(maxsize=8)
def stacked_volume_programs(page: int = 0) -> tuple[GeometryProgram, ...]:
    """Return one bounded page of multi-volume compositions.

    The parameter grid is enumerated once and each page takes a stride through
    it, so a replenishment page reaches combinations the first page did not
    without any page repeating another's programs.
    """

    grid = tuple(product(_PLAN_ASPECTS, _LEVEL_SCALES, _VOLUME_COUNTS))
    offset = max(0, int(page)) * _VARIANTS_PER_FAMILY
    programs: list[GeometryProgram] = []
    for figure_index, (label, figure) in enumerate(_FIGURES):
        for variant in range(_VARIANTS_PER_FAMILY):
            # Stride by the figure index as well, so two figures never take the
            # same parameter point in the same page.
            position = (offset + variant + figure_index) % len(grid)
            (width, depth), scale, count = grid[position]
            programs.append(figure(
                f"stacked_{label}_{page}_{variant}",
                width,
                depth,
                scale,
                count,
            ))
    return tuple(programs)


__all__ = ["stacked_volume_programs"]

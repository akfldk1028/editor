from dataclasses import replace

import numpy as np
import pytest

from backend.app.modules.design.generation.maas.geometry_language.affine_normalization import normalize_affine_basevolume_program
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_volume_audit import book_base_volume_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program


def _append(program, operator, parameters, *, kind="transform"):
    node = GeometryNode(f"step_{len(program.nodes)}", kind, operator,
                        inputs=(program.root_id,), parameters=parameters)
    return replace(program, nodes=(*program.nodes, node), root_id=node.id)


def _compile(program, normalized):
    result = compile_geometry_program(
        normalize_affine_basevolume_program(program) if normalized else program)
    assert result.status == "compiled", result.issues
    return result


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize("pivot,expected", [
    ("centroid", ((1 / 6, 0, .5), (7 / 6, 1, 1))),
    ("center", ((0, 0, .5), (1, 1, 1))),
])
def test_l_rotation_distinguishes_volume_centroid_from_bounds_center(normalized, pivot, expected):
    program = book_base_volume_program("3/8", "long_axis")
    result = _compile(_append(program, "rotate", {
        "axis": "z", "angle_degrees": 90, "pivot": pivot}), normalized)
    np.testing.assert_allclose(result.metrics["bounds"], expected, atol=1e-6)
    assert result.metrics["volume"] == pytest.approx(.375)


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize("operator,parameters,expected", [
    ("scale", {"vector": (2, 3, 4)}, ((-7 / 12, -7 / 6, -.25), (17 / 12, 11 / 6, 1.75))),
    ("mirror", {"normal": (1, 0, 0)}, ((1 / 6, 0, .5), (7 / 6, 1, 1))),
    ("shear", {"axis": "x", "direction": "y", "amount": 1}, ((-1 / 12, 0, .5), (17 / 12, 1, 1))),
])
def test_affine_centroid_tracks_translated_input(normalized, operator, parameters, expected):
    program = book_base_volume_program("3/8", "long_axis")
    translation = (13.25, -7.5, 2.125)
    program = _append(program, "translate", {"vector": translation})
    result = _compile(_append(program, operator, {**parameters, "pivot": "centroid"}), normalized)
    np.testing.assert_allclose(result.metrics["bounds"], np.asarray(expected) + translation, atol=1e-6)


@pytest.mark.parametrize("normalized", [False, True])
def test_disconnected_centroid_weights_components_by_volume(normalized):
    program = GeometryProgram(nodes=(
        GeometryNode("box", "primitive", "box", parameters={"width": 1, "depth": 1, "height": 1}),
        GeometryNode("wide", "transform", "scale", inputs=("box",), parameters={"vector": (2, 1, 1)}),
        GeometryNode("moved", "transform", "translate", inputs=("wide",), parameters={"vector": (4, 0, 0)}),
        GeometryNode("both", "boolean", "union", inputs=("box", "moved")),
    ), root_id="both")
    result = _compile(_append(program, "mirror", {"normal": (1, 0, 0), "pivot": "centroid"}), normalized)
    np.testing.assert_allclose(result.metrics["bounds"], ((1, 0, 0), (7, 1, 1)), atol=1e-6)
    assert result.metrics["component_count"] == 2
    assert result.metrics["volume"] == pytest.approx(3)


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize("operator,parameters,expected", [
    ("radial_array", {"count": 2, "total_angle_degrees": 90}, ((0, 0, .5), (7 / 6, 1, 1))),
    ("mirror_array", {"normal": (1, 0, 0)}, ((0, 0, .5), (7 / 6, 1, 1))),
])
def test_pattern_symmetry_uses_volume_centroid(normalized, operator, parameters, expected):
    program = book_base_volume_program("3/8", "long_axis")
    result = _compile(_append(program, operator, {**parameters, "pivot": "centroid"}, kind="pattern"), normalized)
    np.testing.assert_allclose(result.metrics["bounds"], expected, atol=1e-6)


@pytest.mark.parametrize("normalized", [False, True])
def test_centroid_is_remeasured_after_nonuniform_scaling(normalized):
    program = book_base_volume_program("3/8", "long_axis")
    program = _append(program, "scale", {"vector": (2, 3, 4)})
    program = _append(program, "rotate", {"axis": "z", "angle_degrees": 90, "pivot": "centroid"})
    result = _compile(program, normalized)
    np.testing.assert_allclose(result.metrics["bounds"],
        ((-1 / 12, 7 / 12, 2), (35 / 12, 31 / 12, 4)), atol=1e-6)


@pytest.mark.parametrize("normalized", [False, True])
def test_centroid_subtracts_off_center_cavity_volume(normalized):
    program = GeometryProgram(nodes=(
        GeometryNode("outer", "primitive", "box", parameters={"width": 4, "depth": 4, "height": 4}),
        GeometryNode("cutter", "primitive", "box", parameters={"width": 1, "depth": 1, "height": 1}),
        GeometryNode("inside", "transform", "translate", inputs=("cutter",), parameters={"vector": (2.5, 1.5, 1.5)}),
        GeometryNode("hollow", "boolean", "difference", inputs=("outer", "inside")),
    ), root_id="hollow")
    result = _compile(_append(program, "mirror", {"normal": (1, 0, 0), "pivot": "centroid"}), normalized)
    np.testing.assert_allclose(result.metrics["bounds"],
        ((-2 / 63, 0, 0), (250 / 63, 4, 4)), atol=1e-6)
    assert result.metrics["volume"] == pytest.approx(63)

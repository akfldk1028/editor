import pytest
import manifold3d as m3d
from random import Random

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate


L_PROFILE = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]]
SQUARE = [[0, 0], [2, 0], [2, 2], [0, 2]]


def _loft(profiles):
    return compile_geometry_program(GeometryProgram(nodes=(
        GeometryNode("loft", "primitive", "loft", parameters={"profiles": profiles}),
    ), root_id="loft"))


def test_concave_loft_retains_missing_corner_and_volume():
    result = _loft([{"z": 0, "points": L_PROFILE}, {"z": 2, "points": L_PROFILE}])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(6)
    assert not compilation_gate(result)
    missing_corner = m3d.Manifold.cube((.8, .8, 1.8)).translate((1.1, 1.1, .1))
    assert (result._solid ^ missing_corner).is_empty()


def test_concave_loft_preserves_translated_tapered_profiles_at_each_level():
    upper = [[x * .5 + .25, y * .5 - .25] for x, y in L_PROFILE]
    result = _loft([
        {"z": 0, "points": L_PROFILE},
        {"z": 2, "points": upper},
        {"z": 3, "points": upper},
    ])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(4.25)
    assert not compilation_gate(result)
    assert result._solid.slice(2).area() == pytest.approx(.75)
    assert result._solid.slice(1).area() == pytest.approx(1.6875)


@pytest.mark.parametrize("clockwise", [False, True])
def test_convex_loft_retains_cap_winding_and_taper_volume(clockwise):
    lower = list(reversed(SQUARE)) if clockwise else SQUARE
    upper = [[x / 2, y / 2] for x, y in lower]
    result = _loft([{"z": -1, "points": lower}, {"z": 2, "points": upper}])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(7)
    assert not compilation_gate(result)


def test_different_vertex_counts_keep_all_authored_corners():
    split_square = [[0, 0], [1, 0], [2, 0], [2, 2], [0, 2]]
    result = _loft([{"z": 0, "points": SQUARE}, {"z": 2, "points": split_square}])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(8)
    assert not compilation_gate(result)


def test_different_concave_vertex_counts_do_not_fill_the_notch():
    split_l = [[0, 0], [1, 0], *L_PROFILE[1:]]
    result = _loft([{"z": 0, "points": L_PROFILE}, {"z": 2, "points": split_l}])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(6)
    assert not compilation_gate(result)


def test_square_to_triangle_loft_preserves_both_endpoint_sections():
    triangle = [[0, 0], [2, 0], [1, 2]]
    result = _loft([{"z": 0, "points": SQUARE}, {"z": 2, "points": triangle}])
    assert result.status == "compiled", result.issues
    assert not compilation_gate(result)
    assert result._solid.slice(.000001).area() == pytest.approx(4, abs=1e-5)
    assert result._solid.slice(1.999999).area() == pytest.approx(2, abs=1e-5)


def test_closed_profile_and_implicit_height_input_preserve_loft():
    closed = [*L_PROFILE, L_PROFILE[0]]
    result = _loft([closed, closed])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(3)
    assert not compilation_gate(result)


@pytest.mark.parametrize("points", [
    [[0, 0], [2, 2], [0, 2], [2, 0]],
    [[0, 0], [1, 0], [2, 0]],
    [[0, 0], [2, 0], [2, 0], [0, 2]],
])
def test_invalid_profiles_fail_instead_of_becoming_convex_hulls(points):
    result = _loft([{"z": 0, "points": points}, {"z": 2, "points": points}])
    assert result.status == "compile_failed"


def test_correspondence_that_collapses_mid_loft_is_rejected():
    result = _loft([{"z": 0, "points": SQUARE}, {"z": 2, "points": SQUARE[2:] + SQUARE[:2]}])
    assert result.status == "compile_failed"


def test_holes_are_not_silently_discarded():
    result = _loft([
        {"z": 0, "points": SQUARE, "holes": [[[.5, .5], [.5, 1], [1, 1], [1, .5]]]},
        {"z": 2, "points": SQUARE},
    ])
    assert result.status == "compile_failed"


@pytest.mark.parametrize("z", [0, float("nan"), float("inf")])
def test_invalid_height_cannot_form_a_loft(z):
    result = _loft([{"z": 0, "points": SQUARE}, {"z": z, "points": SQUARE}])
    assert result.status == "compile_failed"


@pytest.mark.parametrize("scale", [.7, 1.1])
def test_nonbinary_taper_and_translation_do_not_create_crossings(scale):
    upper = [[scale * x + .1, scale * y + .2] for x, y in L_PROFILE]
    result = _loft([{"z": 0, "points": L_PROFILE}, {"z": 2, "points": upper}])
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(2 * (1 + scale + scale ** 2))
    assert not compilation_gate(result)


def test_deterministic_positive_tapers_remain_valid():
    random = Random(20261014)
    for _ in range(100):
        scale = random.uniform(.15, 2.5)
        dx, dy = random.uniform(-2, 2), random.uniform(-2, 2)
        upper = [[scale * x + dx, scale * y + dy] for x, y in L_PROFILE]
        result = _loft([{"z": 0, "points": L_PROFILE}, {"z": 2, "points": upper}])
        assert result.status == "compiled", (scale, dx, dy, result.issues)
        assert result.metrics["volume"] == pytest.approx(2 * (1 + scale + scale ** 2))
        assert not compilation_gate(result)


@pytest.mark.parametrize("scale", [-1e-6, -1e6])
def test_true_side_collapse_near_an_endpoint_is_still_rejected(scale):
    upper = [[scale * x + .1, scale * y + .2] for x, y in SQUARE]
    result = _loft([{"z": 0, "points": SQUARE}, {"z": 2, "points": upper}])
    assert result.status == "compile_failed"

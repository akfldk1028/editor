import pytest

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.source_geometry.solid import PolynomialSurface, thickness_bounds


TOP = ((0, 0, .4), (1, 0, 1.2), (2, 0, -1.2), (0, 1, 1.2), (0, 2, -1.2))
BOTTOM = ((0, 0, .28), *TOP[1:])


def shell(top=TOP, bottom=BOTTOM):
    return compile_geometry_program(GeometryProgram(nodes=(
        GeometryNode('box', 'primitive', 'box', parameters={'width': 20, 'depth': 20, 'height': 10}),
        GeometryNode('shell', 'modifier', 'bound_surfaces', inputs=('box',), parameters={
            'top_surface': {'type': 'polynomial', 'terms': top},
            'bottom_surface': {'type': 'polynomial', 'terms': bottom},
        }),
    ), root_id='shell'))


def test_separation_uses_same_point_difference_not_unrelated_extrema():
    bounds = thickness_bounds(PolynomialSurface(TOP), PolynomialSurface(BOTTOM), (0, 0, 1, 1))
    assert bounds == pytest.approx((.12, .12))


def test_double_curved_shell_keeps_air_below_and_constant_occupied_thickness():
    result = shell()
    assert result.status == 'compiled', result.issues
    assert result.metrics['closed_solid']
    assert result.metrics['component_count'] == 1
    assert result.metrics['volume'] == pytest.approx(20 * 20 * 10 * .12)
    assert result._solid.slice(1).is_empty()


def test_reordered_and_repeated_terms_still_cancel():
    bottom = ((2, 0, -.6), (0, 0, .28), (1, 0, 1.2), (0, 2, -1.2), (0, 1, 1.2), (2, 0, -.6))
    assert thickness_bounds(PolynomialSurface(TOP), PolynomialSurface(bottom), (0, 0, 1, 1)) == pytest.approx((.12, .12))


def test_crossing_surfaces_are_rejected_even_when_corners_have_positive_thickness():
    result = shell(((0, 0, .6),), ((0, 0, .5), (1, 0, 1), (2, 0, -1)))
    assert result.status == 'invalid_program'
    assert any(issue.code == 'invalid_surface_bounds' for issue in result.issues)


def test_variable_thickness_bounds_retain_interior_minimum():
    top = PolynomialSurface(((0, 0, .6),))
    bottom = PolynomialSurface(((0, 0, .2), (1, 0, 1), (2, 0, -1)))
    assert thickness_bounds(top, bottom, (0, 0, 1, 1)) == pytest.approx((.15, .4))

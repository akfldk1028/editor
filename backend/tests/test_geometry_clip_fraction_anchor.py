import pytest

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program


def _program(anchor, *, operator="clip_fraction"):
    base = GeometryNode("base", "primitive", "box", parameters={"width": 8, "depth": 6, "height": 4})
    if operator == "attach":
        guest = GeometryNode("guest", "primitive", "box", parameters={"width": 1, "depth": 1, "height": 1})
        attached = GeometryNode("result", "composition", "attach", inputs=("base", "guest"),
                                parameters={"anchor": anchor, "host_face": "east"})
        return GeometryProgram(nodes=(base, guest, attached), root_id="result")
    clipped = GeometryNode("result", "modifier", "clip_fraction", inputs=("base",),
                           parameters={"axis": "x", "fraction": 0.25, "anchor": anchor})
    return GeometryProgram(nodes=(base, clipped), root_id="result")


@pytest.mark.parametrize("anchor,expected_x", [
    ("start", (0, 2)), ("low", (0, 2)), ("negative", (0, 2)),
    ("center", (3, 5)), ("middle", (3, 5)),
    ("end", (6, 8)), ("high", (6, 8)), ("positive", (6, 8)),
])
def test_clip_fraction_string_anchor_controls_selected_geometry(anchor, expected_x):
    program = _program(anchor)
    assert not program.validate()
    result = compile_geometry_program(program)
    assert result.status == "compiled", result.issues
    assert result.metrics["volume"] == pytest.approx(48)
    assert tuple(bound[0] for bound in result.metrics["bounds"]) == pytest.approx(expected_x)


@pytest.mark.parametrize("anchor", ["unknown", [0, 0], 1, None])
def test_clip_fraction_rejects_unsupported_anchor(anchor):
    assert "unsupported_parameter_value" in {issue.code for issue in _program(anchor).validate()}


@pytest.mark.parametrize("anchor", ["high", [0], [0, 0, 0], [0, "bad"]])
def test_attach_still_requires_two_numeric_anchor_coordinates(anchor):
    assert "invalid_vector_parameter" in {
        issue.code for issue in _program(anchor, operator="attach").validate()
    }


def test_attach_accepts_two_numeric_anchor_coordinates():
    assert not _program([0.2, -0.3], operator="attach").validate()

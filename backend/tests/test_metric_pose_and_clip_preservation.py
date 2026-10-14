from math import atan2, degrees
from types import SimpleNamespace

import manifold3d as m3d
import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.geometry_language.source_bridge import (
    _clip_world_mesh_to_host,
    _mesh_plan_projection_area,
    _mesh_plan_projection_inside_host,
    _pose_metric_vertices_to_host,
    mesh_section_solid,
    solid_section_polygon,
)


def _mesh(solid):
    mesh = solid.to_mesh64()
    return SimpleNamespace(
        vertices=tuple(tuple(float(v) for v in point[:3]) for point in mesh.vert_properties),
        triangles=tuple(tuple(int(v) for v in face) for face in mesh.tri_verts),
    )


@pytest.mark.parametrize("clip_to_host", [False, True])
@pytest.mark.parametrize("facing", [0.0, 31.0])
@pytest.mark.parametrize("impose_fit", [False, True])
def test_metric_pose_finds_intact_lobe_placement_at_authored_facing(clip_to_host, facing, impose_fit):
    host = unary_union([box(-5, -5, 5, 5), box(5, -1, 20, 1)])
    host = translate(rotate(host, facing, origin=(0, 0)), xoff=143.25, yoff=-97.5)
    compiled = _mesh(m3d.Manifold.cube((8, 8, 4), center=True))

    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=clip_to_host, facing_angle_deg=facing,
        impose_fit=impose_fit,
    )

    assert fitted is not None
    assert _mesh_plan_projection_inside_host(fitted.world_vertices, compiled.triangles, host)
    assert _mesh_plan_projection_area(fitted.world_vertices, compiled.triangles) == pytest.approx(64)
    assert degrees(atan2(fitted.matrix4[1][0], fitted.matrix4[0][0])) == pytest.approx(facing)


def test_metric_pose_does_not_mistake_vertex_containment_for_legal_courtyard():
    compiled = _mesh(m3d.Manifold.cube((8, 8, 4), center=True))
    host = box(-5, -5, 5, 5).difference(box(-1, -1, 1, 1))

    assert _pose_metric_vertices_to_host(compiled, host, facing_angle_deg=0) is None


def test_impose_fit_still_permits_explicit_uniform_shrink():
    compiled = _mesh(m3d.Manifold.cube((8, 8, 4), center=True))
    host = box(-3, -3, 3, 3)
    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, impose_fit=True, facing_angle_deg=0,
    )
    assert fitted is not None
    whole = _mesh_plan_projection_area(fitted.world_vertices, compiled.triangles)
    kept = _mesh_plan_projection_area(fitted.world_vertices, compiled.triangles, host)
    assert 0.6 < fitted.matrix4[0][0] < 1.0
    assert fitted.matrix4[0][0] == fitted.matrix4[1][1]
    assert kept == pytest.approx(whole)


def test_impose_fit_continues_past_nearly_retained_upper_band_without_stair_cut():
    compiled = _mesh(m3d.Manifold.cube((10, 10, 4), center=True))
    host = box(-10, -10, 10, 10)
    upper = box(-4.8, -5, 4.8, 5)
    sections = ((0, 0.5, host), (0.5, 1, upper))

    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, clip_sections=sections,
        impose_fit=True, facing_angle_deg=0,
    )

    assert fitted is not None
    posed = mesh_section_solid(fitted.world_vertices, compiled.triangles)
    clipped = _clip_world_mesh_to_host(fitted.world_vertices, compiled.triangles, host, sections)
    assert clipped is not None
    delivered = mesh_section_solid(*clipped)
    assert delivered.volume() == pytest.approx(posed.volume(), abs=1e-7)
    assert upper.buffer(1e-7).covers(solid_section_polygon(posed, 0.75))
    assert solid_section_polygon(delivered, 0.25).symmetric_difference(
        solid_section_polygon(delivered, 0.75)).area < 1e-7


def test_impose_fit_refuses_when_bounded_search_cannot_preserve_whole_body():
    compiled = _mesh(m3d.Manifold.cube((10, 10, 4), center=True))
    host = box(-0.5, -0.5, 0.5, 0.5)

    assert _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, impose_fit=True, facing_angle_deg=0,
    ) is None


def test_inherit_fit_keeps_metric_size_and_intentional_height_band_cut():
    compiled = _mesh(m3d.Manifold.cube((10, 10, 4), center=True))
    host = box(-10, -10, 10, 10)
    upper = box(-4.8, -5, 4.8, 5)
    sections = ((0, 0.5, host), (0.5, 1, upper))

    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, clip_sections=sections,
        impose_fit=False, facing_angle_deg=0,
    )

    assert fitted is not None
    assert fitted.matrix4[0][0] == pytest.approx(1)
    assert fitted.matrix4[1][1] == pytest.approx(1)
    clipped = _clip_world_mesh_to_host(fitted.world_vertices, compiled.triangles, host, sections)
    assert clipped is not None
    delivered = mesh_section_solid(*clipped)
    assert solid_section_polygon(delivered, 0.25).area == pytest.approx(100)
    assert solid_section_polygon(delivered, 0.75).area == pytest.approx(96)


def test_metric_pose_finds_narrow_upper_legal_translation_domain():
    compiled = _mesh(m3d.Manifold.cube((2, 2, 2), center=True))
    host = box(0, 0, 20, 20)
    upper = box(1.9, 1.9, 4.1, 4.1)
    sections = ((0, 0.5, host), (0.5, 1, upper))
    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, clip_sections=sections, facing_angle_deg=0,
    )
    assert fitted is not None
    clipped = _clip_world_mesh_to_host(fitted.world_vertices, compiled.triangles, host, sections)
    assert clipped is not None
    assert mesh_section_solid(*clipped).volume() == pytest.approx(4)
    assert fitted.matrix4[0][3] == pytest.approx(3, abs=0.1)
    assert fitted.matrix4[1][3] == pytest.approx(3, abs=0.1)


def test_metric_pose_uses_actual_upper_body_not_whole_projection_in_upper_host():
    solid = (m3d.Manifold.cube((8, 8, 1), center=True)
             + m3d.Manifold.cube((2, 2, 1), center=True).translate((2, 0, 1)))
    compiled = _mesh(solid)
    host = box(0, 0, 20, 20)
    upper = box(5.9, 5.9, 8.1, 8.1)
    sections = ((0, 0.5, host), (0.5, 1, upper))
    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, clip_sections=sections, facing_angle_deg=0,
    )
    assert fitted is not None
    posed = mesh_section_solid(fitted.world_vertices, compiled.triangles)
    clipped = _clip_world_mesh_to_host(fitted.world_vertices, compiled.triangles, host, sections)
    assert clipped is not None
    assert mesh_section_solid(*clipped).volume() == pytest.approx(posed.volume())
    assert posed.volume() == pytest.approx(34)
    assert upper.buffer(1e-7).covers(solid_section_polygon(posed, 0.75))
    assert host.covers(solid_section_polygon(posed, 0.25))


@pytest.mark.parametrize('facing', [0, 31])
def test_metric_pose_preserves_upper_courtyard_in_height_specific_host(facing):
    upper_solid = (m3d.Manifold.cylinder(1, 2, 2, 48)
                   - m3d.Manifold.cylinder(1, 0.6, 0.6, 48)).translate((0, 0, 1))
    solid = m3d.Manifold.cube((8, 8, 1)).translate((-4, -4, 0)) + upper_solid
    compiled = _mesh(solid)
    host = box(0, 0, 20, 20)
    upper = translate(rotate(solid_section_polygon(solid, 1.5).buffer(0.05),
                             facing, origin=(0, 0)), xoff=6, yoff=6)
    sections = ((0, 0.5, host), (0.5, 1, upper))
    fitted = _pose_metric_vertices_to_host(
        compiled, host, clip_to_host=True, clip_sections=sections, facing_angle_deg=facing,
    )
    assert fitted is not None
    posed = mesh_section_solid(fitted.world_vertices, compiled.triangles)
    clipped = _clip_world_mesh_to_host(fitted.world_vertices, compiled.triangles, host, sections)
    assert clipped is not None
    assert mesh_section_solid(*clipped).volume() == pytest.approx(posed.volume())
    actual = solid_section_polygon(posed, 0.75)
    assert len(actual.interiors) == 1
    assert upper.buffer(1e-7).covers(actual)


@pytest.mark.parametrize("sections", [False, True])
def test_legal_clip_preserves_both_severed_wings(sections):
    solid = (
        m3d.Manifold.cube((2, 4, 1))
        + m3d.Manifold.cube((2, 4, 1)).translate((5, 0, 0))
        + m3d.Manifold.cube((7, 1, 1)).translate((0, 3, 0))
    )
    assert len(solid.decompose()) == 1
    compiled = _mesh(solid)
    host = box(-1, -1, 8, 2)
    result = _clip_world_mesh_to_host(
        compiled.vertices, compiled.triangles, host,
        sections=((0, 0.5, host), (0.5, 1, host)) if sections else None,
    )

    assert result is not None
    vertices, triangles = result
    assert _mesh_plan_projection_area(vertices, triangles) == pytest.approx(8)
    delivered = mesh_section_solid(vertices, triangles)
    assert len(delivered.decompose()) == 2
    assert delivered.volume() == pytest.approx(8)
    expected = unary_union([box(0, 0, 2, 2), box(5, 0, 7, 2)])
    assert solid_section_polygon(delivered, 0.5).symmetric_difference(expected).area < 1e-8


def test_legal_clip_keeps_tapered_skin_and_courtyard():
    outer = m3d.Manifold.cylinder(1, 4, 2, 48)
    courtyard = m3d.Manifold.cylinder(2, 0.5, 0.5, 24).translate((0, 0, -0.5))
    solid = outer - courtyard
    compiled = _mesh(solid)
    host = box(-5, -5, 0.75, 5)
    result = _clip_world_mesh_to_host(compiled.vertices, compiled.triangles, host)
    assert result is not None
    clipped = mesh_section_solid(*result)
    for z in (0.1, 0.35, 0.8):
        expected = solid_section_polygon(solid, z).intersection(host)
        actual = solid_section_polygon(clipped, z)
        assert actual.symmetric_difference(expected).area < 1e-6
        assert len(actual.interiors) == 1

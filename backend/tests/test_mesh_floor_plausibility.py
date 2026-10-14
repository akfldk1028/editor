from copy import deepcopy
from dataclasses import replace

import pytest
from shapely.geometry import box

from backend.app.modules.design.generation.maas.delivered.book_floors import delivered_floor_evidence
from backend.app.modules.design.generation.maas.dimensional_intent import POLICY
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import compile_geometry_program_to_source_mass
from backend.app.modules.design.generation.maas.massv2.plausibility import assess
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceVolume


def _book_source(program, *, components=1):
    source = compile_geometry_program_to_source_mass(
        program, box(-100, -100, 100, 100), placement_policy=POLICY,
        max_volume_bands=3, height_m=11.4,
        gate_policy=GeometryGatePolicy(maximum_components=components),
    )
    assert source is not None
    storeys = {'typical_storey_height_m': 3.8}
    source = replace(source, metadata={
        **source.metadata, 'book_height_certificate': 'test_physical_height',
        'book_floor_count': 3, 'book_storey_height_m': 3.8,
        'book_original_storey_evidence': storeys,
    })
    evidence = delivered_floor_evidence(source, storeys, floor_count=3, storey_m=3.8)
    assert evidence['measurement_consistent'], evidence['measurement_issues']
    return replace(source, metadata={**source.metadata,
        'book_delivered_floor_evidence': evidence,
        'book_floor_area_m2': evidence['actual_gfa_m2'],
    })


def _folded_source():
    body = GeometryNode('body', 'primitive', 'box', parameters={
        'width': 33.6555556, 'depth': 21.5660416, 'height': 11.4,
    })
    fold = GeometryNode('fold', 'modifier', 'bound_surfaces', inputs=('body',), parameters={
        'top_surface': {'type': 'profile', 'axis': [0, 1], 'span': [0, 1],
                        'points': [[0, .92], [.16, 1], [.55, .34], [1, .76]]},
    })
    return _book_source(GeometryProgram((body, fold), 'fold'))


def _verdict(source):
    return assess(source, parcel_area_m2=2500, max_slenderness=4.17, floor_height_m=3.8)


def test_continuous_fold_roof_tip_is_not_an_additive_occupied_shard():
    source = _folded_source()

    verdict = _verdict(source)

    assert verdict.occupiable, verdict.reasons
    assert verdict.viable_band_share == pytest.approx(1)
    assert verdict.occupiable_mass_share == pytest.approx(1)


def test_legacy_additive_shard_keeps_room_rejection():
    main = box(0, 0, 20, 20)
    source = SourceMass('additive', main, volumes=(
        SourceVolume('main', main, 0, 1, 'base'),
        SourceVolume('shard', box(22, 0, 23, 1), 0, 1, 'attach'),
    ), metadata={'authored_height_m': 11.4})

    assert 'crumb_1_shard_volume' in _verdict(source).reasons


@pytest.mark.parametrize('bottom, thickness', [(0, 1.), (7.7, 1.), (0, .0005)])
def test_exact_small_component_between_floor_centers_is_not_exempt(bottom, thickness):
    main = GeometryNode('main', 'primitive', 'box', parameters={
        'width': 20., 'depth': 20., 'height': 11.4,
    })
    small = GeometryNode('small', 'primitive', 'box', parameters={
        'width': 1., 'depth': 1., 'height': thickness,
    })
    moved = GeometryNode('moved', 'transform', 'translate', inputs=('small',),
                         parameters={'vector': [25., 0., bottom]})
    union = GeometryNode('union', 'boolean', 'union', inputs=('main', 'moved'))
    source = _book_source(GeometryProgram((main, small, moved, union), 'union'), components=2)

    verdict = _verdict(source)

    assert not verdict.occupiable
    assert any('crumb' in reason for reason in verdict.reasons)
    if bottom:
        assert not verdict.standing.stands


def test_narrow_actual_upper_floor_still_fails_room_gate():
    main = GeometryNode('main', 'primitive', 'box', parameters={
        'width': 20., 'depth': 20., 'height': 7.,
    })
    upper = GeometryNode('upper', 'primitive', 'box', parameters={
        'width': 1., 'depth': 1., 'height': 4.4,
    })
    moved = GeometryNode('moved', 'transform', 'translate', inputs=('upper',),
                         parameters={'vector': [10., 10., 7.]})
    union = GeometryNode('union', 'boolean', 'union', inputs=('main', 'moved'))
    source = _book_source(GeometryProgram((main, upper, moved, union), 'union'))

    assert 'crumb_1_shard_volume' in _verdict(source).reasons


def test_exact_floor_sections_preserve_declared_support_exemption():
    leg = GeometryNode('leg', 'primitive', 'box', parameters={
        'width': 1., 'depth': 1., 'height': 4.4,
    })
    plate = GeometryNode('plate', 'primitive', 'box', parameters={
        'width': 20., 'depth': 20., 'height': 7.,
    })
    moved = GeometryNode('moved', 'transform', 'translate', inputs=('plate',),
                         parameters={'vector': [0., 0., 4.4]})
    union = GeometryNode('union', 'boolean', 'union', inputs=('leg', 'moved'))
    source = _book_source(GeometryProgram((leg, plate, moved, union), 'union'))
    metadata = {**source.metadata, 'structural_bands': [
        i for i, volume in enumerate(source.volumes) if volume.footprint.area < 9
    ]}
    assert metadata['structural_bands']
    source = replace(source, metadata=metadata)
    metadata['book_delivered_floor_evidence'] = delivered_floor_evidence(
        source, metadata['book_original_storey_evidence'], floor_count=3, storey_m=3.8)

    verdict = _verdict(source)

    assert not any('crumb' in reason for reason in verdict.reasons)
    assert verdict.viable_band_share == pytest.approx(1)
    assert verdict.occupiable_mass_share == pytest.approx(1)


@pytest.mark.parametrize('exact', [False, True])
def test_structure_dominating_mass_keeps_existing_half_mass_refusal(exact):
    if exact:
        body = GeometryNode('body', 'primitive', 'box', parameters={
            'width': 20., 'depth': 20., 'height': 11.4,
        })
        source = _book_source(GeometryProgram((body,), 'body'))
    else:
        plan = box(0, 0, 20, 20)
        source = SourceMass('additive', plan, volumes=tuple(
            SourceVolume(str(i), plan, i / 3, (i + 1) / 3, 'base')
            for i in range(3)), metadata={'authored_height_m': 11.4})
    metadata = {**source.metadata, 'structural_bands': [0, 1]}
    source = replace(source, metadata=metadata)
    if exact:
        metadata['book_delivered_floor_evidence'] = delivered_floor_evidence(
            source, metadata['book_original_storey_evidence'], floor_count=3, storey_m=3.8)

    verdict = _verdict(source)

    assert '67%_of_the_mass_is_structure_rather_than_room' in verdict.reasons
    assert not verdict.occupiable


def test_exact_component_crumb_share_excludes_declared_support_mass():
    main = GeometryNode('main', 'primitive', 'box', parameters={
        'width': 20., 'depth': 20., 'height': 11.4,
    })
    pavilion = GeometryNode('pavilion', 'primitive', 'box', parameters={
        'width': 4., 'depth': 4., 'height': 11.4,
    })
    moved = GeometryNode('moved', 'transform', 'translate', inputs=('pavilion',),
                         parameters={'vector': [25., 0., 0.]})
    union = GeometryNode('union', 'boolean', 'union', inputs=('main', 'moved'))
    source = _book_source(GeometryProgram((main, pavilion, moved, union), 'union'), components=2)
    assert source.volumes[0].footprint.area == pytest.approx(400)
    metadata = {**source.metadata, 'structural_bands': [0]}
    source = replace(source, metadata=metadata)
    metadata['book_delivered_floor_evidence'] = delivered_floor_evidence(
        source, metadata['book_original_storey_evidence'], floor_count=3, storey_m=3.8)

    verdict = _verdict(source)

    assert verdict.occupiable, verdict.reasons


@pytest.mark.parametrize('tamper', ['missing', 'areas', 'centers'])
def test_mesh_floor_authority_must_be_present_and_match_exact_geometry(tamper):
    source = _folded_source()
    metadata = deepcopy(source.metadata)
    if tamper == 'missing':
        del metadata['book_delivered_floor_evidence']
    elif tamper == 'areas':
        metadata['book_delivered_floor_evidence']['actual_floor_areas_m2'][0] += 100
    else:
        metadata['book_delivered_floor_evidence']['delivered_floor_center_elevations_m'][2] = 6

    with pytest.raises(ValueError, match='floor.*evidence'):
        _verdict(replace(source, metadata=metadata))

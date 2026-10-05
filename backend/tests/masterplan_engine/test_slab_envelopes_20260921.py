from shapely.geometry import box
from backend.app.modules.design.generation.maas.masterplan.basement_layout import slab_envelopes


def test_demand_grows_connected_slab_without_excavating_whole_available_site():
    envelope=box(0,0,100,80)
    seed=box(10,10,30,30)
    required=box(12,12,18,18)
    candidates=slab_envelopes(seed,envelope,required,1600,16)
    assert 1 < len(candidates) <= 5
    assert any(1599.99 <= c.area < 2000 for c in candidates)
    assert all(envelope.buffer(1e-6).covers(c) and c.buffer(1e-6).covers(required) for c in candidates)
    # A whole half-module growth is a large area jump. Keep a bounded
    # intermediate construction size for programmes which just miss the budget.
    assert any(1900 < c.area < 2300 for c in candidates)


def test_authorized_envelope_cannot_be_overridden_by_mass_hull():
    envelope=box(0,0,20,40)
    candidates=slab_envelopes(box(0,0,30,30),envelope,box(2,2,8,8),700,16)
    assert candidates and all(envelope.buffer(1e-6).covers(c) for c in candidates)
    assert slab_envelopes(box(0,0,30,30),envelope,box(19,2,25,8),700,16)==[]


def test_rotated_seed_near_corner_retains_complete_authorized_host_candidate():
    from shapely.affinity import rotate
    host=box(0,0,100,100)
    seed=rotate(box(1,1,3,3),45,origin=(2,2))
    candidates=slab_envelopes(seed,host,seed,10000,16)
    assert any(c.symmetric_difference(host).area<1e-7 for c in candidates)

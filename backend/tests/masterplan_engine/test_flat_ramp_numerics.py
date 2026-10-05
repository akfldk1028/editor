from collections import defaultdict
from shapely.geometry import LineString
from backend.app.modules.design.generation.maas.masterplan.validation import _flat_ramp_area


def test_flat_ramp_station_roundoff_does_not_create_a_buffer_spike_or_admit_slope():
    # The first measured segment is 6m minus one ulp; substring(0,6)
    # otherwise adds an almost-duplicate endpoint and GEOS buffers its false turn.
    coords = [(19.743803172754465, 1.105845555516312, 0.),
              (17.53211206172184, 6.683338041336375, 0.),
              (16.42626650620553, 9.472084284246408, -.255),
              (10.376640820145704, 24.728166671930698, -3.045),
              (9.270795264629392, 27.516912914840727, -3.3),
              (7.0591041535967705, 33.09440540066079, -3.3)]
    center = LineString(coords)
    spine = LineString([c[:2] for c in coords])
    ramp = spine.buffer(3, cap_style=2)
    profile = [{'distance_m': d, 'z_m': z} for d,z in
               [(0,0),(6,0),(9,-.255),(25.41176470588235,-3.045),(28.41176470588235,-3.3),(34.41176470588235,-3.3)]]
    props = {'from_level': 0, 'to_level': -1, 'width_m': 6., 'profile': profile}
    grouped = defaultdict(list)
    grouped[(-1, 'ramp_centerline')] = [(center, props)]
    flat = _flat_ramp_area(grouped, ramp, props, 0)
    true_flat = LineString([c[:2] for c in coords[:2]]).buffer(3, cap_style=2)
    assert flat.symmetric_difference(true_flat).area < 1e-6
    sloping = LineString([c[:2] for c in coords[1:3]]).buffer(3, cap_style=2)
    assert flat.intersection(sloping).area < 1e-6

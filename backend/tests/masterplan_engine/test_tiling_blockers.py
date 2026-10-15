import pytest
from shapely.geometry import box, Polygon

from backend.app.modules.design.generation.maas.masterplan.rows_tiling import _tile_bands_at


def candidate(blocked):
    return _tile_bands_at(box(0, 0, 50, 50), blocked, 5, 6, 2.5, 5, 3.3, 5,
                         0, 50, 0, None, 0, None, 0, ring=False)


@pytest.mark.parametrize('blocker', [box(20, 21, 26, 27), box(20, 23, 26, 24)])
def test_longitudinal_band_stops_before_obstacle_at_full_aisle_width(blocker):
    result = candidate(blocker)
    assert result is not None
    assert result['drive'].intersection(blocker).area == pytest.approx(0)
    # A shallow obstacle must not leave a narrowed passage around it.
    assert result['drive'].intersection(box(20, 21, 26, 27)).area == pytest.approx(0)
    assert result['drive'].covers(box(6, 21, 19, 27))


def test_unblocked_tiling_retains_three_connected_bands():
    result = candidate(Polygon())
    assert result['bands'] == 3
    assert result['drive'].geom_type == 'Polygon'
    assert result['drive'].covers(box(6, 21, 49, 27))

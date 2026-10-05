import json
from pathlib import Path
from shapely.geometry import shape
from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected


def test_valid_world_drive_with_invalid_rotated_frame_is_rejected_without_aborting_search():
    data = json.loads((Path(__file__).parent/'fixtures'/'width_frame_daechi_20260921.json').read_text())
    candidate = {'drive': shape(data['drive']), 'stalls': [{'front': shape(g)} for g in data['fronts']]}
    assert candidate['drive'].is_valid
    # The two disconnected eroded components serve 2 and 5 cells respectively;
    # repairing an evaluation frame must not union them into a false route.
    assert _width_connected(candidate, [shape(g) for g in data['anchors']], data['aisle_width']) is False

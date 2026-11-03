"""The chosen Mass form is read from the editor's own delivered export and cut into storey volumes the 3D view draws."""
import json

from backend.app.modules.platform.run_results.agents import chosen_mass
from backend.app.modules.platform.run_results.parse import parse_run_results

ORIGIN = [333272.15, 4177512.12]


def box_mesh(w, d, h, x0=0.0, y0=0.0):
    v = [[x0, y0, 0], [x0 + w, y0, 0], [x0 + w, y0 + d, 0], [x0, y0 + d, 0],
         [x0, y0, h], [x0 + w, y0, h], [x0 + w, y0 + d, h], [x0, y0 + d, h]]
    t = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
         [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    return {'vertices': v, 'triangles': t}


def ring_mesh(outer, inner, h):
    """A courtyard block: a square `outer` wide around a square `inner` court, `h` high (quads as two triangles)."""
    v, t = [], []

    def quad(a, b, c, d):
        base = len(v)
        v.extend([a, b, c, d])
        t.extend([[base, base + 1, base + 2], [base, base + 2, base + 3]])
    o, i = outer / 2, inner / 2
    for z0, z1 in ((0, h),):
        for (x1, y1), (x2, y2) in (((-o, -o), (o, -o)), ((o, -o), (o, o)), ((o, o), (-o, o)), ((-o, o), (-o, -o))):
            quad([x1, y1, z0], [x2, y2, z0], [x2, y2, z1], [x1, y1, z1])
        for (x1, y1), (x2, y2) in (((-i, -i), (i, -i)), ((i, -i), (i, i)), ((i, i), (-i, i)), ((-i, i), (-i, -i))):
            quad([x1, y1, z0], [x2, y2, z0], [x2, y2, z1], [x1, y1, z1])
        for z in (z0, z1):
            quad([-o, -o, z], [o, -o, z], [i, -i, z], [-i, -i, z])
            quad([o, -o, z], [o, o, z], [i, i, z], [i, -i, z])
            quad([o, o, z], [-o, o, z], [-i, i, z], [i, i, z])
            quad([-o, o, z], [-o, -o, z], [-i, -i, z], [-i, i, z])
    return {'vertices': v, 'triangles': t}


def test_a_plane_cut_through_a_box_is_its_footprint():
    plans = chosen_mass.plan_rings(box_mesh(30, 20, 8.4), 2.1)
    assert len(plans) == 1 and plans[0]['holes'] == []
    xs, ys = [p[0] for p in plans[0]['ring']], [p[1] for p in plans[0]['ring']]
    assert (min(xs), max(xs), min(ys), max(ys)) == (0, 30, 0, 20)


def test_a_courtyard_block_cuts_as_one_ring_with_its_court_as_a_hole():
    plans = chosen_mass.plan_rings(ring_mesh(30, 10, 8.4), 6.3)
    assert len(plans) == 1 and len(plans[0]['holes']) == 1
    xs = [p[0] for p in plans[0]['ring']]
    hx = [p[0] for p in plans[0]['holes'][0]]
    assert (min(xs), max(xs), min(hx), max(hx)) == (-15, 15, -5, 5)


def test_volumes_follow_the_storey_bands_and_land_in_wgs84():
    candidate = {'mesh': box_mesh(30, 20, 8.4), 'coordinate_frame': {'crs': 'EPSG:32652', 'origin_utm': ORIGIN},
                 'storey_evidence': {'floor_elevations_m': [0.0, 4.2, 8.4], 'storey_count': 2},
                 'numeric_certificate': {'height_m': 8.4}}
    volumes = chosen_mass.volumes_of(candidate)
    assert [(v['base_m'], v['top_m']) for v in volumes] == [(0.0, 4.2), (4.2, 8.4)]
    lng, lat = volumes[0]['ring'][0]
    assert 127.0 < lng < 127.2 and 37.7 < lat < 37.8        # 의정부 산곡동, not the UTM metres


def test_the_run_reads_its_own_export_by_source_run_id(tmp_path):
    folder = tmp_path / 'abc'
    (folder / 'dataset' / 'candidates' / 'mass-1').mkdir(parents=True)
    (folder / 'receipt.json').write_text(json.dumps({'result': {
        'status': 'succeeded', 'source_run_id': 'run-1', 'selected_mass_id': 'book:x', 'selection_mode': 'user_selected',
        'identity': {'name': 'book:x', 'shape_id': 'shape9'},
        'elevation_handoff': {'request': {'candidate': 'mass-1', 'selected_glb_href': 'design/x/selected.glb'}}}}), encoding='utf-8')
    (folder / 'dataset' / 'candidates' / 'mass-1' / 'candidate.json').write_text(json.dumps({
        'mesh': box_mesh(30, 20, 8.4), 'coordinate_frame': {'crs': 'EPSG:32652', 'origin_utm': ORIGIN},
        'storey_evidence': {'floor_elevations_m': [0.0, 4.2, 8.4], 'storey_count': 2},
        'numeric_certificate': {'height_m': 8.4, 'ground_m2': 600.0, 'gross_m2': 1200.0}}), encoding='utf-8')
    rows = [{'tool': 'mass_export', 'agent': 'mass', 'state': 'succeeded'}]
    mass = chosen_mass.parse({'run_id': 'run-1'}, rows, root=tmp_path)
    assert mass['label'] == 'shape9' and mass['storeys'] == 2 and len(mass['volumes']) == 2
    assert mass['glb_href'] == 'design/x/selected.glb' and mass['gross_m2'] == 1200.0
    assert chosen_mass.parse({'run_id': 'run-2'}, rows, root=tmp_path) is None     # another run's export is not ours
    assert chosen_mass.parse({'run_id': 'run-1'}, [], root=tmp_path) is None       # nothing exported yet


def test_a_run_without_an_export_has_no_mass():
    assert parse_run_results({'run_id': 'r', 'status': 'ok', 'communications': []})['mass'] is None


def test_a_result_kept_before_the_contract_gained_mass_is_not_served_again():
    from backend.app.modules.platform import runs
    from backend.app.modules.platform.run_results import parse
    assert runs._run_state({'run_id': 'r', 'status': 'blocked', 'communications': []})[0] == parse.CONTRACT_VERSION


def test_the_chosen_form_is_also_drawn_as_its_delivered_mesh_at_its_frame_origin():
    from backend.app.modules.platform.run_results.agents.chosen_mass import model_of
    candidate = {'coordinate_frame': {'crs': 'EPSG:32652', 'origin_utm': [333272.15357276343, 4177512.1171267903]}}
    model = model_of(candidate, 'design/maas/delivered-mass-export/h/files/selected.glb')
    assert model['href'].endswith('selected.glb')
    assert abs(model['origin'][0] - 127.108) < 0.001 and abs(model['origin'][1] - 37.7297) < 0.001
    assert -1.3 < model['heading_deg'] < -1.0   # UTM zone 52 grid north, west of the central meridian
    assert model_of(candidate, '') is None and model_of({}, 'x.glb') is None

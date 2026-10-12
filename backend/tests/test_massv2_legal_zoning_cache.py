"""The per-parcel zoning cache only answers when it was written by the current split rule."""
import json

from backend.app.modules.design.generation.maas.massv2 import legal
from backend.app.modules.land.reference.services.zone_split import SPLIT_VERSION


def test_a_cache_from_before_the_split_rule_is_ignored_and_a_current_one_round_trips(tmp_path):
    path = tmp_path / '4115011300106840001.zoning.json'
    old = {'pnu': '4115011300106840001', 'land_info': {'zones': ['제2종일반주거지역', '자연녹지지역']},
           'areas': {'제2종일반주거지역': 2499.69, '자연녹지지역': 4.85}}
    path.write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
    assert legal._read_zoning_cache(path) is None
    assert legal._read_zoning_cache(tmp_path / 'missing.zoning.json') is None
    path.write_text('not json', encoding='utf-8')
    assert legal._read_zoning_cache(path) is None

    split = {'version': SPLIT_VERSION, 'areas_m2': {'제2종일반주거지역': 2499.6912},
             'excluded_slivers': [{'zone': '자연녹지지역', 'area_m2': 4.852, 'width_m': 0.089, 'share': 0.001941, 'reason': 'zone_overlap', 'folded_into': '제2종일반주거지역'}],
             'uncovered_m2': 0.0, 'notes': ['자연녹지지역: … 제외']}
    legal._write_zoning_cache(path, '4115011300106840001', old['land_info'], {'제2종일반주거지역': 2499.6912}, split)
    cached = legal._read_zoning_cache(path)
    assert cached['split_version'] == SPLIT_VERSION
    assert cached['areas'] == {'제2종일반주거지역': 2499.6912}
    assert cached['zone_split'] == split and cached['land_info'] == old['land_info']

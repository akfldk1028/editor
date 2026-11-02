import importlib.util
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString


def owner(tmp_path):
    path = Path(__file__).with_name('ngii_index_resolver.py')
    spec = importlib.util.spec_from_file_location('national_test_resolver', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DATA_ROOT = tmp_path
    module.RAW_NGII = tmp_path / 'raw/ngii_map'
    module.INDEX_FILE = tmp_path / 'index/registry.json'
    return module


def roads(folder, suffix, lon, ident):
    folder.mkdir(parents=True, exist_ok=True)
    frame = gpd.GeoDataFrame({'UFID': [ident], 'RVWD': [12], 'RDLN': [3]},
        geometry=[LineString([(lon, 37.5), (lon + .001, 37.5)])], crs=4326)
    frame.to_crs(5179).to_file(folder / f'N3L_A0020000_{suffix}.shp', encoding='UTF-8')


def test_road_only_split_folder_is_registered_and_bbox_filters(tmp_path):
    module = owner(tmp_path)
    folder = module.RAW_NGII / 'b020/_전국/(B020)national'
    roads(folder, '001', 127, 'near')
    roads(folder, '002', 129, 'far')
    module.build_index_registry()
    assert module.find_sheets_for_bbox(126.99, 37.49, 127.01, 37.51) == [folder]
    frame = module.read_layer(folder, 'N3L_A0020000', 'roads', bbox=(126.99, 37.49, 127.01, 37.51))
    assert list(frame['UFID']) == ['near']
    assert list(frame['도로폭']) == [12]


def test_incomplete_install_is_not_indexed(tmp_path):
    module = owner(tmp_path)
    folder = module.RAW_NGII / 'b020/_전국/(B020)national'
    roads(folder, '001', 127, 'near')
    (folder / '.sitecontext-install-incomplete.json').write_text('{}')
    assert module.scan_sheets() == []

import unittest
from pathlib import Path
from paths import DataPaths

class PathTests(unittest.TestCase):
    def test_local_defaults_resolve_data_not_agent_checkout(self):
        p=DataPaths.from_env({'EDITOR_ROOT':'D:/Data/25_ACE/editor'})
        self.assertEqual(p.tiles,Path('C:/Data/25_ACE/tiles/buildings'))
        self.assertEqual(p.catalog,p.buildings)
        self.assertEqual(p.buildings,Path('C:/Data/25_ACE/world-buildings'))
        self.assertEqual(p.dem,Path('D:/Data/NGII_DEM'))

    def test_data_root_collects_outputs_and_keeps_explicit_input_override(self):
        p=DataPaths.from_env({'DATA_ROOT':'E:/storage','NGII_DEM_ROOT':'D:/old-dem'})
        self.assertEqual(p.buildings,Path('E:/storage/world-buildings'))
        self.assertEqual(p.catalog,p.buildings);self.assertEqual(p.dem,Path('D:/old-dem'))
        env=p.building_env('https://tiles.example/tiles/buildings/20261009-2f30a80f/buildings.pmtiles',env={})
        self.assertEqual(Path(env['WORLD_BUILDINGS_ARCHIVE']),Path('E:/storage/tiles/buildings/20261009-2f30a80f/buildings.pmtiles'))

    def test_invalid_version_and_direct_archive_override(self):
        p=DataPaths.from_env({})
        with self.assertRaises(ValueError):p.building_archive('https://x/a/../buildings.pmtiles',{})
        self.assertEqual(p.building_archive('https://x/ignored',{'WORLD_BUILDINGS_ARCHIVE':'E:/kept.pmtiles'}),Path('E:/kept.pmtiles'))

if __name__=='__main__':unittest.main()

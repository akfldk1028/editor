"""Publication paths: configured storage, with existing local inputs as defaults."""
import os,re,shutil,sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

@dataclass(frozen=True)
class DataPaths:
    editor: Path
    data: Path
    dem: Path
    originals: Path
    tiles: Path
    buildings: Path
    catalog: Path
    python: str
    bun: str

    @classmethod
    def from_env(cls,env=None):
        env=os.environ if env is None else env
        editor=Path(env.get('EDITOR_ROOT') or Path(__file__).resolve().parents[2])
        workspace=Path(env.get('ACE_WORKSPACE_ROOT') or editor.parent)
        configured=env.get('DATA_ROOT');data=Path(configured or workspace/'data')
        legacy_output=Path('C:/Data/25_ACE')
        default_bun=Path(os.environ.get('APPDATA',''))/'npm/node_modules/bun/bin/bun.exe'
        return cls(editor,data,
            Path(env.get('NGII_DEM_ROOT') or (data/'dem' if configured else workspace.parent/'NGII_DEM')),
            Path(env.get('NGII_ORIGINAL_ROOT') or (data if configured else legacy_output)/'ngii-original-batch'),
            Path(env.get('SCENE_TILES_DIR') or (data if configured else legacy_output)/'tiles/buildings'),
            Path(env.get('WORLD_BUILDINGS_ASSET_OUTPUT') or (data if configured else legacy_output)/'world-buildings'),
            Path(env.get('WORLD_BUILDINGS_OUTPUT') or (data if configured else legacy_output)/'world-buildings'),
            env.get('WORLD_PYTHON') or sys.executable,
            env.get('BUN_EXE') or (str(default_bun) if default_bun.is_file() else shutil.which('bun') or 'bun'))

    @property
    def app(self):return self.editor/'frontend/app/editor'

    def publish_catalog(self):
        from catalog_release import build
        # Run only after the single-writer bake finishes. Advance the small
        # pointer only after every dependency of the new catalog is available.
        return build(self.catalog/'catalog.json',self.catalog.parent,self.buildings,publish=True)

    def building_archive(self,source,env=None):
        env=os.environ if env is None else env
        if env.get('WORLD_BUILDINGS_ARCHIVE'):return Path(env['WORLD_BUILDINGS_ARCHIVE'])
        path=urlsplit(source).path.rstrip('/').split('/')
        if len(path)<2 or path[-1]!='buildings.pmtiles' or not re.fullmatch(r'\d{8}-[a-f0-9]{8}',path[-2]):raise ValueError('Invalid building source version')
        return self.tiles/path[-2]/'buildings.pmtiles'

    def building_env(self,source,snapshot=None,env=None):
        values=dict(os.environ if env is None else env)
        values.update(WORLD_PYTHON=self.python,WORLD_BUILDINGS_SOURCE=source,
            WORLD_BUILDINGS_ARCHIVE=str(self.building_archive(source,values)),
            WORLD_BUILDINGS_OUTPUT=str(self.catalog),WORLD_BUILDINGS_ASSET_OUTPUT=str(self.buildings))
        if snapshot is not None:values['WORLD_DEM_PATH']=str(snapshot)
        return values

"""Isolated native specification API with real storage and synthetic identities."""
import json
import os
from pathlib import Path

from fastapi import FastAPI
import uvicorn

from backend.app.api.routes_platform import create_platform_router
from backend.app.modules.design.execution_catalog import ExecutionCatalog
from backend.app.modules.design.native_service import NativeDesignService
from backend.app.modules.design.repository import DesignRepository
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


class Sources:
    async def list_projects(self):
        return [{'owner_project_id': 'native-design-fixture', 'branch_id': 'main'}]

    async def get_scene(self, scene_id):
        return {'id': scene_id, 'projectId': 'native-scene-project', 'version': 2, 'ownerId': 'local'}

    async def context(self, *args):
        return {}

    async def list_runs(self, *args):
        return []


directory = Path(os.environ['EDITOR_NATIVE_DESIGN_FIXTURE_DIR']).resolve()
projects = ProjectRepository(directory / 'projects')
project = projects.create('local', ProjectCreate(
    owner_project_id='native-design-fixture', branch_id='main', scene_id='native-scene',
    scene_project_id='native-scene-project', scene_revision=2,
))
(directory / 'project.json').write_text(json.dumps(project.model_dump()), encoding='utf-8')
sources = Sources()
app = FastAPI()
app.include_router(create_platform_router(
    sources, project_service=ProjectService(projects, sources, sources),
    public_origin='http://127.0.0.1:5186',
    design_repository=DesignRepository(directory / 'design'),
    execution_catalog=ExecutionCatalog(directory / 'design'),
    native_design_service=NativeDesignService(directory / 'design'),
))

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=18446)

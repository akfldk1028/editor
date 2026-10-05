import sqlite3
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from backend.app.modules.workspace.catalog import CatalogRepository, CatalogConflict, validate_component


class TeamPayload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    component: dict


class GalleryPayload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    config: dict


class ValidationPayload(TeamPayload):
    pass


def create_catalog_router(directory):
    router = APIRouter()

    def operation(callback):
        try:
            return callback(CatalogRepository(directory()))
        except CatalogConflict as error:
            raise HTTPException(409, str(error)) from None
        except LookupError:
            raise HTTPException(404, 'Template not found') from None
        except (ValueError, RecursionError):
            raise HTTPException(422, 'Invalid or oversized template') from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, 'Template storage is unavailable') from None

    def payload(collection, body):
        try:
            result = (TeamPayload if collection == 'teams' else GalleryPayload).model_validate(body).model_dump()
        except ValidationError:
            raise HTTPException(422, 'Invalid template fields') from None
        if collection == 'teams':
            component = result['component']
            if component.get('component_type') != 'team' or not isinstance(component.get('config'), dict) or not isinstance(component.get('provider'), str):
                raise HTTPException(422, 'A team component with provider and config is required')
        else:
            config = result['config']
            if not isinstance(config.get('name'), str) or not config['name'].strip() or not isinstance(config.get('components'), dict):
                raise HTTPException(422, 'Gallery name and components are required')
            for kind, items in config['components'].items():
                if kind not in ('teams', 'agents', 'models', 'tools', 'terminations', 'workbenches') or not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    raise HTTPException(422, 'Invalid gallery component collection')
                expected_type = {'teams': 'team', 'agents': 'agent', 'models': 'model', 'tools': 'tool', 'terminations': 'termination', 'workbenches': 'workbench'}[kind]
                if any(item.get('component_type') != expected_type or not isinstance(item.get('provider'), str) or not item['provider'].strip() or not isinstance(item.get('config'), dict) for item in items):
                    raise HTTPException(422, 'Gallery entries must have a matching component type, provider and config')
        return result

    @router.post('/validate')
    def validate(body: ValidationPayload):
        try:
            return validate_component(body.component)
        except RecursionError:
            raise HTTPException(422, 'Component nesting exceeds supported depth') from None

    @router.get('/{collection}')
    def listing(collection: Literal['teams', 'galleries']):
        return operation(lambda repo: repo.list(collection))

    @router.get('/{collection}/{identifier}')
    def detail(collection: Literal['teams', 'galleries'], identifier: int):
        return operation(lambda repo: repo.get(collection, identifier))

    @router.post('/{collection}', status_code=201)
    def create(collection: Literal['teams', 'galleries'], body: dict):
        value = payload(collection, body)
        return operation(lambda repo: repo.create(collection, value))

    @router.put('/{collection}/{identifier}')
    def update(collection: Literal['teams', 'galleries'], identifier: int, body: dict):
        body = dict(body)
        version = body.pop('version', None)
        if type(version) is not int or version < 0:
            raise HTTPException(422, 'Template version is required')
        value = payload(collection, body)
        return operation(lambda repo: repo.update(collection, identifier, version, value))

    @router.delete('/{collection}/{identifier}')
    def delete(collection: Literal['teams', 'galleries'], identifier: int):
        return operation(lambda repo: repo.delete(collection, identifier))

    return router

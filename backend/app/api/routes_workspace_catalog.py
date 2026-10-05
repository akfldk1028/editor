import sqlite3
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from backend.app.modules.workspace.catalog import CatalogRepository, CatalogConflict, validate_component
from backend.app.modules.workspace.validation import validate_template_shape


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
            try:
                validate_template_shape(component, ('team',))
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        else:
            config = result['config']
            if not isinstance(config.get('name'), str) or not config['name'].strip() or not isinstance(config.get('components'), dict):
                raise HTTPException(422, 'Gallery name and components are required')
            metadata = config.get('metadata', {})
            if not isinstance(metadata, dict) or any(metadata.get(key) is not None and not isinstance(metadata[key], str) for key in ('description', 'author', 'version')):
                raise HTTPException(422, 'Gallery metadata must contain text fields')
            if 'tags' in metadata and (not isinstance(metadata['tags'], list) or any(not isinstance(tag, str) for tag in metadata['tags'])):
                raise HTTPException(422, 'Gallery tags must be a list of text values')
            for kind, items in config['components'].items():
                if kind not in ('teams', 'agents', 'models', 'tools', 'terminations', 'workbenches') or not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    raise HTTPException(422, 'Invalid gallery component collection')
                expected_type = {'teams': 'team', 'agents': 'agent', 'models': 'model', 'tools': 'tool', 'terminations': 'termination', 'workbenches': 'workbench'}[kind]
                try:
                    for item in items:
                        validate_template_shape(item, (expected_type,))
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
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

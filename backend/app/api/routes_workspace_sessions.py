import sqlite3

from fastapi import APIRouter, HTTPException
from backend.app.schemas.workspace import SessionCreate
from backend.app.modules.workspace.catalog import CatalogRepository
from backend.app.modules.workspace.sessions import SessionRepository


def create_sessions_router(directory):
    router = APIRouter(prefix='/sessions')

    def operation(callback):
        try:
            return callback(SessionRepository(directory()))
        except LookupError:
            raise HTTPException(404, 'Session or team template not found') from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, 'Session storage is unavailable') from None

    @router.get('')
    def listing():
        return operation(lambda repo: repo.list())

    @router.post('', status_code=201)
    def create(body: SessionCreate):
        return operation(lambda repo: repo.create(body.name, body.team_id,
                          CatalogRepository(directory()).get('teams', body.team_id)['component']))

    @router.get('/{identifier}/runs')
    def runs(identifier: int):
        return operation(lambda repo: repo.runs(identifier))

    @router.delete('/{identifier}')
    def archive(identifier: int):
        return operation(lambda repo: repo.archive(identifier))

    return router

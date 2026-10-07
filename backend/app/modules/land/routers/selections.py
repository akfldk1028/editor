import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from backend.app.modules.land.selection_facts import UpstreamBudgetExceeded, describe_site
from backend.app.modules.land.selections import (DEFAULT_SCOPE, SCOPE_PATTERN, SelectionRequest, check_parcels,
                                                 list_selections, save_selection)


def create_land_selections_router(services, check_origin) -> APIRouter:
    """The selected site (a bundle of parcels).

    POST /selections/preview describes a bundle with outlines for drawing (nothing stored);
    POST /selections describes and saves it under `scope` (no geometry); GET lists newest first;
    /latest?scope= is the current one of that scope (a project id, or `default`).
    """
    router = APIRouter(tags=['land'])

    def storage():
        try:
            repository = services.local_repository()
        except (OSError, ValueError):
            repository = None
        if repository is None:
            raise HTTPException(503, 'Land storage is not configured')
        return repository

    async def described(body):
        try:
            picks = check_parcels(body)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        try:
            return await describe_site(services, picks, body.label)
        except UpstreamBudgetExceeded as error:
            raise HTTPException(400, str(error)) from None

    @router.post('/selections/preview')
    async def preview(body: SelectionRequest, request: Request):
        check_origin(request)
        return await described(body)

    @router.post('/selections')
    async def create(body: SelectionRequest, request: Request):
        check_origin(request)
        repository = storage()
        site = await described(body)
        try:
            return await run_in_threadpool(save_selection, repository, site, body.scope)
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(503, 'Land storage unavailable') from None

    async def read(limit, scope=None):
        repository = storage()
        try:
            return await run_in_threadpool(list_selections, repository, limit, scope)
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(503, 'Land storage unavailable') from None

    @router.get('/selections')
    async def recent(limit: int = Query(default=20, ge=1, le=100)):
        return {'selections': await read(limit)}

    @router.get('/selections/latest')
    async def latest(scope: str = Query(default=DEFAULT_SCOPE, pattern=SCOPE_PATTERN)):
        rows = await read(1, scope)
        if not rows:
            raise HTTPException(404, 'No site has been selected')
        return rows[0]

    return router

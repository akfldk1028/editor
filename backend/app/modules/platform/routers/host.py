from fastapi import APIRouter, HTTPException, Request

from backend.app.modules.platform import host
from backend.app.schemas.host import HostEnsure


def create_host_router(allowed_origin, ensure=host.ensure):
    """`POST /host/ensure` — bring the named agents up and wait for their health (same-origin only: it starts
    processes on this machine). 503 when the host CLI is missing or silent, 422 when it refuses an id."""
    router = APIRouter()

    def same_origin(request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')

    @router.post('/host/ensure')
    async def ensure_agents(body: HostEnsure, request: Request):
        same_origin(request)
        try:
            return await ensure(body.ids(), timeout_s=body.timeout_s)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except host.HostRefused as exc:
            raise HTTPException(422, f'host_refused: {exc}') from None
        except host.HostUnavailable as exc:
            raise HTTPException(503, f'host_unavailable: {exc}') from None

    return router

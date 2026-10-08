from fastapi import APIRouter, HTTPException, Request

from backend.app.modules.platform import host
from backend.app.schemas.host import HostEnsure, HostTouch


def create_host_router(allowed_origin, ensure=host.ensure, touch=host.touch, status=host.status):
    """`POST /host/ensure` — bring the named agents up and wait for their health (same-origin only: it starts
    processes on this machine). 503 when the host CLI is missing or silent, 422 when it refuses an id."""
    router = APIRouter()

    def same_origin(request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')

    async def answer(operation):
        try:
            return await operation
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except host.HostRefused as exc:
            raise HTTPException(422, f'host_refused: {exc}') from None
        except host.HostUnavailable as exc:
            raise HTTPException(503, f'host_unavailable: {exc}') from None

    @router.get('/host/status')
    async def host_status():
        """Agent states from the host's last tick (cached 5 s): what the conversation reads to know whom to wake."""
        return await answer(status())

    @router.post('/host/ensure')
    async def ensure_agents(body: HostEnsure, request: Request):
        same_origin(request)

        async def operation():
            return await ensure(body.ids(), timeout_s=body.timeout_s, lease_s=body.lease_s)
        return await answer(operation())

    @router.post('/host/touch')
    async def touch_agents(body: HostTouch, request: Request):
        """Keeps agents in use (lease extended) without starting anything."""
        same_origin(request)

        async def operation():
            return await touch(body.ids(), lease_s=body.lease_s)
        return await answer(operation())

    return router

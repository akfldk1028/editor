"""`Owner`: the FastAPI dependency every route that reads or writes someone's data takes instead of the literal
`'local'` it used when the editor had one user.

An app without an identity on its state (a router mounted alone in a test) is a one-person editor: owner `local`.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .settings import LOCAL_OWNER


def current_owner(request: Request) -> str:
    identity = getattr(request.app.state, 'identity', None)
    if identity is None:
        return LOCAL_OWNER
    owner = identity.owner_of(request)
    if owner is None:
        raise HTTPException(401, 'sign in required')
    return owner


Owner = Annotated[str, Depends(current_owner)]

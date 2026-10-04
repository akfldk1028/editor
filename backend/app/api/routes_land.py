import os
import re
from typing import Annotated, Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.adapters.land import LandClient, LandContractError, LandUnavailable, LandRejected


class LandRequest(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    input: str=Field(max_length=500)
    input_type: Literal['address','pnu','raw']
    zones: list[Annotated[str,Field(min_length=1,max_length=100)]]=Field(default_factory=list,max_length=50)
    include_law: bool=True

    @model_validator(mode='after')
    def check_input(self):
        self.input=self.input.strip()
        if self.input_type=='pnu':
            self.input=self.input.replace('-','')
            if not re.fullmatch(r'[0-9]{19}',self.input):
                raise ValueError('PNU requires 19 digits')
        if self.input_type=='raw':
            if not self.zones: raise ValueError('zones are required')
        elif not self.input:
            raise ValueError('input is required')
        return self


def create_land_router(client=None, *, public_origin=None):
    owner=client or LandClient(os.environ.get('EDITOR_ARR_URL'),
        analysis_timeout=float(os.environ.get('EDITOR_ARR_ANALYSIS_TIMEOUT','180')))
    origin=public_origin or os.environ.get('EDITOR_PUBLIC_URL','http://127.0.0.1:5173')
    router=APIRouter(prefix='/api/v1/land',tags=['land'])

    async def respond(operation):
        try: return await operation
        except LandRejected: raise HTTPException(422,'ARR rejected the land input') from None
        except LandUnavailable: raise HTTPException(503,'ARR land service unavailable') from None
        except LandContractError: raise HTTPException(502,'Invalid ARR land response') from None

    @router.get('/zones')
    async def zones(): return await respond(owner.zones())

    @router.get('/stats')
    async def stats(): return await respond(owner.stats())

    @router.post('/analyze')
    async def analyze(body: LandRequest, request: Request):
        if request.headers.get('sec-fetch-site')=='cross-site' or (request.headers.get('origin') and request.headers['origin']!=origin):
            raise HTTPException(403,'Cross-origin analysis is not allowed')
        return await respond(owner.analyze(body.model_dump()))

    return router

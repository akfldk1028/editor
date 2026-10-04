"""Actual Editor land routes with isolated storage and no legacy/provider service."""
import os
from fastapi import FastAPI
import uvicorn

from backend.app.api.routes_land import create_land_router
from backend.app.modules.land.repository import LandRepository

app = FastAPI()
app.include_router(create_land_router(
     public_origin='http://127.0.0.1:5186',
    repository=LandRepository(os.environ['EDITOR_LAND_DATA_DIR'])))

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=18438)

from fastapi import APIRouter
from app.api.endpoints import health, imports, well_pads, wells

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(imports.router)
api_router.include_router(well_pads.router)
api_router.include_router(wells.router)

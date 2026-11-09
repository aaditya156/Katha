from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.series import router as series_router
from app.api.v1.episodes import router as episodes_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(series_router)
api_v1_router.include_router(episodes_router)

from fastapi import APIRouter
from app.api.v1.audio import router as audio_router
from app.api.v1.auth import router as auth_router
from app.api.v1.episodes import router as episodes_router
from app.api.v1.evaluations import router as evaluations_router
from app.api.v1.generation import router as generation_router
from app.api.v1.series import router as series_router
from app.api.v1.story_bible import router as story_bible_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(series_router)
api_v1_router.include_router(episodes_router)
api_v1_router.include_router(generation_router)
api_v1_router.include_router(audio_router)
api_v1_router.include_router(story_bible_router)
api_v1_router.include_router(evaluations_router)



"""API routes module."""

from fastapi import APIRouter

from .routes import router as main_router
from .chat import router as chat_router
from .auth import router as auth_router
from .embed_house import router as embed_house_router
from .content import router as content_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(main_router, tags=["main"])
router.include_router(chat_router, prefix="/chat", tags=["chat"])
router.include_router(embed_house_router)
router.include_router(content_router)

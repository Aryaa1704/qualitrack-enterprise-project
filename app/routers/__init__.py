"""Application routers for QualiTrack."""

from app.routers.auth import router as auth_router
from app.routers.factories import router as factories_router

__all__ = ["auth_router", "factories_router"]

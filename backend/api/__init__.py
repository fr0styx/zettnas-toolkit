"""
ZettNAS Toolkit API Package
Aggregates all modular sub-routers into api_router.
"""

from fastapi import APIRouter

from backend.api.auth import router as auth_router
from backend.api.fans import router as fans_router
from backend.api.led import router as led_router
from backend.api.notifications import router as notifications_router
from backend.api.stats import router as stats_router
from backend.api.system import router as system_router
from backend.api.wallpapers import router as wallpapers_router
from backend.api.metrics import router as metrics_router
from backend.api.backup import router as backup_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(stats_router)
api_router.include_router(fans_router)
api_router.include_router(led_router)
api_router.include_router(wallpapers_router)
api_router.include_router(system_router)
api_router.include_router(notifications_router)
api_router.include_router(metrics_router)
api_router.include_router(backup_router)

__all__ = [
    "api_router",
    "auth_router",
    "stats_router",
    "fans_router",
    "led_router",
    "notifications_router",
    "wallpapers_router",
    "system_router",
    "metrics_router",
    "backup_router",
]

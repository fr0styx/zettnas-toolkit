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
from backend.api.chassis import router as chassis_router
from backend.api.storage import router as storage_router
from backend.api.webdav import router as webdav_router
from backend.api.remotes import router as remotes_router
from backend.api.samba import router as samba_router

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
api_router.include_router(chassis_router)
api_router.include_router(storage_router)
api_router.include_router(webdav_router)
api_router.include_router(remotes_router)
api_router.include_router(samba_router)

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
    "chassis_router",
    "storage_router",
    "webdav_router",
    "remotes_router",
    "samba_router",
]

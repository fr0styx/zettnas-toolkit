"""
ZettNAS Toolkit API Package
Aggregates all modular sub-routers into api_router.
"""

from fastapi import APIRouter

from backend.api.ai_conversations import router as ai_conversations_router
from backend.api.auth import router as auth_router
from backend.api.backup import router as backup_router
from backend.api.calendar import router as calendar_router
from backend.api.catalog import router as catalog_router
from backend.api.chassis import router as chassis_router
from backend.api.diagnostics import router as diagnostics_router
from backend.api.docker import router as docker_router
from backend.api.drives import router as drives_router
from backend.api.fans import router as fans_router
from backend.api.file_versions import router as file_versions_router  # noqa: E402
from backend.api.fs import router as fs_router
from backend.api.immich import router as immich_router  # noqa: E402
from backend.api.invites import router as invites_router  # noqa: E402
from backend.api.jobs import router as jobs_router  # noqa: E402
from backend.api.led import router as led_router
from backend.api.mcp import router as mcp_router
from backend.api.media import router as media_router
from backend.api.metrics import router as metrics_router
from backend.api.network import router as network_router
from backend.api.notifications import router as notifications_router
from backend.api.offsite import router as offsite_router  # noqa: E402
from backend.api.oidc import ldap_router
from backend.api.oidc import router as oidc_router
from backend.api.push import router as push_router
from backend.api.remotes import router as remotes_router
from backend.api.replication import router as replication_router
from backend.api.samba import router as samba_router
from backend.api.security import router as security_router
from backend.api.setup import router as setup_router  # noqa: E402
from backend.api.sftp import router as sftp_router
from backend.api.snapshots import router as snapshots_router  # noqa: E402
from backend.api.snmp import router as snmp_router
from backend.api.stats import router as stats_router
from backend.api.storage import router as storage_router
from backend.api.system import router as system_router
from backend.api.ups import router as ups_router
from backend.api.vms import router as vms_router
from backend.api.wallpapers import router as wallpapers_router
from backend.api.webdav import router as webdav_router

api_router = APIRouter()
api_router.include_router(jobs_router)
api_router.include_router(setup_router)
api_router.include_router(snapshots_router)
api_router.include_router(file_versions_router)
api_router.include_router(offsite_router)
api_router.include_router(invites_router)
api_router.include_router(immich_router)
api_router.include_router(auth_router)
api_router.include_router(oidc_router)
api_router.include_router(ldap_router)
api_router.include_router(mcp_router)
api_router.include_router(push_router)
api_router.include_router(stats_router)
api_router.include_router(fans_router)
api_router.include_router(led_router)
api_router.include_router(drives_router)
api_router.include_router(wallpapers_router)
api_router.include_router(system_router)
api_router.include_router(docker_router)
api_router.include_router(catalog_router)
api_router.include_router(fs_router)
api_router.include_router(diagnostics_router)
api_router.include_router(notifications_router)
api_router.include_router(metrics_router)
api_router.include_router(backup_router)
api_router.include_router(chassis_router)
api_router.include_router(storage_router)
api_router.include_router(webdav_router)
api_router.include_router(remotes_router)
api_router.include_router(samba_router)
api_router.include_router(security_router)
api_router.include_router(ups_router)
api_router.include_router(network_router)
api_router.include_router(replication_router)
api_router.include_router(media_router)
api_router.include_router(sftp_router)
api_router.include_router(vms_router)
api_router.include_router(snmp_router)
api_router.include_router(ai_conversations_router)
api_router.include_router(calendar_router)

__all__ = [
    "api_router",
    "auth_router",
    "stats_router",
    "fans_router",
    "led_router",
    "drives_router",
    "notifications_router",
    "wallpapers_router",
    "system_router",
    "docker_router",
    "catalog_router",
    "fs_router",
    "diagnostics_router",
    "metrics_router",
    "backup_router",
    "chassis_router",
    "storage_router",
    "webdav_router",
    "remotes_router",
    "samba_router",
    "ups_router",
    "network_router",
    "replication_router",
    "media_router",
    "sftp_router",
    "vms_router",
    "snmp_router",
    "ai_conversations_router",
]

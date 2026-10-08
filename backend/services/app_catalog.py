"""
ZettNAS Curated Homelab App Catalog & Pre-flight Conflict Resolver
Provides 25+ verified container blueprints, automated volume path resolution,
and intelligent host port conflict detection.
"""

from typing import Any, Dict, List, Optional
from backend.services.container_mutator import check_port_available

CURATED_APP_CATALOG: List[Dict[str, Any]] = [
    # Media & Streaming
    {
        "id": "jellyfin",
        "name": "Jellyfin Media Server",
        "category": "media",
        "description": "Free, open-source media streaming system for movies, TV shows, and music.",
        "image": "jellyfin/jellyfin:latest",
        "default_port": 8096,
        "webui_path": "/web/index.html",
        "env": {"PUID": "1000", "PGID": "100", "TZ": "UTC"},
        "volumes": {"config": "/config", "cache": "/cache", "media": "/media"},
    },
    {
        "id": "plex",
        "name": "Plex Media Server",
        "category": "media",
        "description": "Organize your video, music, and photo collections and stream them to all your devices.",
        "image": "lscr.io/linuxserver/plex:latest",
        "default_port": 32400,
        "webui_path": "/web",
        "env": {"PUID": "1000", "PGID": "100", "VERSION": "docker"},
        "volumes": {"config": "/config", "media": "/tv", "movies": "/movies"},
    },
    {
        "id": "emby",
        "name": "Emby Server",
        "category": "media",
        "description": "Personal media server with live TV, multi-screen streaming, and mobile sync.",
        "image": "emby/embyserver:latest",
        "default_port": 8096,
        "webui_path": "/",
        "env": {"UID": "1000", "GID": "100"},
        "volumes": {"config": "/config", "media": "/mnt/share1"},
    },
    {
        "id": "audiobookshelf",
        "name": "Audiobookshelf",
        "category": "media",
        "description": "Self-hosted audiobook and podcast server with progress tracking and mobile apps.",
        "image": "ghcr.io/advplyr/audiobookshelf:latest",
        "default_port": 13378,
        "webui_path": "/",
        "env": {"AUDIOBOOKSHELF_UID": "1000", "AUDIOBOOKSHELF_GID": "100"},
        "volumes": {"config": "/config", "metadata": "/metadata", "audiobooks": "/audiobooks"},
    },
    {
        "id": "calibre-web",
        "name": "Calibre-Web",
        "category": "media",
        "description": "Web app for browsing, reading, and downloading eBooks stored in a Calibre database.",
        "image": "lscr.io/linuxserver/calibre-web:latest",
        "default_port": 8083,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100", "DOCKER_MODS": "linuxserver/mods:universal-calibre"},
        "volumes": {"config": "/config", "books": "/books"},
    },
    # Cloud & Photos
    {
        "id": "immich",
        "name": "Immich Photo Backup",
        "category": "photos",
        "description": "High-performance self-hosted photo and video backup solution with AI search.",
        "image": "ghcr.io/immich-app/immich-server:release",
        "default_port": 2283,
        "webui_path": "/",
        "env": {"NODE_ENV": "production", "DB_HOSTNAME": "immich-postgres"},
        "volumes": {"upload": "/usr/src/app/upload"},
    },
    {
        "id": "photoprism",
        "name": "PhotoPrism",
        "category": "photos",
        "description": "AI-powered photos app for decentralized web with face recognition and world map.",
        "image": "photoprism/photoprism:latest",
        "default_port": 2342,
        "webui_path": "/",
        "env": {"PHOTOPRISM_ADMIN_USER": "admin", "PHOTOPRISM_AUTH_MODE": "password"},
        "volumes": {"storage": "/photoprism/storage", "originals": "/photoprism/originals"},
    },
    {
        "id": "nextcloud",
        "name": "Nextcloud Hub",
        "category": "cloud",
        "description": "Self-hosted productivity platform for files, calendars, contacts, and office docs.",
        "image": "lscr.io/linuxserver/nextcloud:latest",
        "default_port": 8080,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config", "data": "/data"},
    },
    {
        "id": "owncloud",
        "name": "ownCloud Infinite Scale",
        "category": "cloud",
        "description": "Cloud native file sync and share built in Go with microservices architecture.",
        "image": "owncloud/ocis:latest",
        "default_port": 9200,
        "webui_path": "/",
        "env": {"OCIS_INSECURE": "true"},
        "volumes": {"data": "/var/lib/ocis"},
    },
    # Smart Home & Automation
    {
        "id": "homeassistant",
        "name": "Home Assistant",
        "category": "automation",
        "description": "Open source home automation that puts local control and privacy first.",
        "image": "ghcr.io/home-assistant/home-assistant:stable",
        "default_port": 8123,
        "webui_path": "/",
        "env": {"TZ": "UTC"},
        "volumes": {"config": "/config"},
    },
    {
        "id": "nodered",
        "name": "Node-RED",
        "category": "automation",
        "description": "Flow-based visual programming for wiring hardware devices, APIs, and online services.",
        "image": "nodered/node-red:latest",
        "default_port": 1880,
        "webui_path": "/",
        "env": {"TZ": "UTC"},
        "volumes": {"data": "/data"},
    },
    {
        "id": "scrypted",
        "name": "Scrypted",
        "category": "automation",
        "description": "High-performance video integration platform for HomeKit, Google Home, and Alexa.",
        "image": "koush/scrypted:latest",
        "default_port": 10443,
        "webui_path": "/",
        "env": {},
        "volumes": {"server-volume": "/server/volume"},
    },
    {
        "id": "zigbee2mqtt",
        "name": "Zigbee2MQTT",
        "category": "automation",
        "description": "Bridge Zigbee devices directly to MQTT without proprietary vendor hubs.",
        "image": "koenkk/zigbee2mqtt:latest",
        "default_port": 8080,
        "webui_path": "/",
        "env": {"TZ": "UTC"},
        "volumes": {"data": "/app/data"},
    },
    # Network & Utilities
    {
        "id": "vaultwarden",
        "name": "Vaultwarden",
        "category": "utilities",
        "description": "Lightweight, full-featured Bitwarden compatible password and secrets manager in Rust.",
        "image": "vaultwarden/server:latest",
        "default_port": 8088,
        "webui_path": "/",
        "env": {"WEBSOCKET_ENABLED": "true"},
        "volumes": {"data": "/data"},
    },
    {
        "id": "pihole",
        "name": "Pi-hole DNS Sinkhole",
        "category": "network",
        "description": "Network-wide ad and telemetry blocking via local DNS sinkhole.",
        "image": "pihole/pihole:latest",
        "default_port": 8080,
        "webui_path": "/admin",
        "env": {"TZ": "UTC", "WEBPASSWORD": "admin"},
        "volumes": {"etc-pihole": "/etc/pihole", "etc-dnsmasq.d": "/etc/dnsmasq.d"},
    },
    {
        "id": "adguardhome",
        "name": "AdGuard Home",
        "category": "network",
        "description": "Network-wide software for blocking ads, tracking, and parental control.",
        "image": "adguard/adguardhome:latest",
        "default_port": 3000,
        "webui_path": "/",
        "env": {},
        "volumes": {"work": "/opt/adguardhome/work", "conf": "/opt/adguardhome/conf"},
    },
    {
        "id": "nginx-proxy-manager",
        "name": "Nginx Proxy Manager",
        "category": "network",
        "description": "Intuitive web interface for reverse proxying, SSL certs, and access lists.",
        "image": "jc21/nginx-proxy-manager:latest",
        "default_port": 81,
        "webui_path": "/",
        "env": {},
        "volumes": {"data": "/data", "letsencrypt": "/etc/letsencrypt"},
    },
    {
        "id": "uptime-kuma",
        "name": "Uptime Kuma",
        "category": "utilities",
        "description": "Self-hosted monitoring tool with notification integrations and status pages.",
        "image": "louislam/uptime-kuma:1",
        "default_port": 3001,
        "webui_path": "/",
        "env": {},
        "volumes": {"data": "/app/data"},
    },
    # Download & Media Management
    {
        "id": "radarr",
        "name": "Radarr",
        "category": "downloads",
        "description": "Automated movie collection manager for Usenet and BitTorrent.",
        "image": "lscr.io/linuxserver/radarr:latest",
        "default_port": 7878,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config", "movies": "/movies", "downloads": "/downloads"},
    },
    {
        "id": "sonarr",
        "name": "Sonarr",
        "category": "downloads",
        "description": "Smart TV series manager and grabber for Usenet and BitTorrent.",
        "image": "lscr.io/linuxserver/sonarr:latest",
        "default_port": 8989,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config", "tv": "/tv", "downloads": "/downloads"},
    },
    {
        "id": "prowlarr",
        "name": "Prowlarr",
        "category": "downloads",
        "description": "Indexer proxy for Usenet and Torrent indexers with seamless Arr app integration.",
        "image": "lscr.io/linuxserver/prowlarr:latest",
        "default_port": 9696,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config"},
    },
    {
        "id": "bazarr",
        "name": "Bazarr",
        "category": "downloads",
        "description": "Companion application to Sonarr and Radarr that manages and downloads subtitles.",
        "image": "lscr.io/linuxserver/bazarr:latest",
        "default_port": 6767,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config", "movies": "/movies", "tv": "/tv"},
    },
    {
        "id": "qbittorrent",
        "name": "qBittorrent",
        "category": "downloads",
        "description": "Fast, feature-rich BitTorrent client with built-in search engine and web UI.",
        "image": "lscr.io/linuxserver/qbittorrent:latest",
        "default_port": 8085,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100", "WEBUI_PORT": "8085"},
        "volumes": {"config": "/config", "downloads": "/downloads"},
    },
    {
        "id": "transmission",
        "name": "Transmission",
        "category": "downloads",
        "description": "Lightweight, reliable BitTorrent client with remote web control.",
        "image": "lscr.io/linuxserver/transmission:latest",
        "default_port": 9091,
        "webui_path": "/transmission/web/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config", "downloads": "/downloads", "watch": "/watch"},
    },
    {
        "id": "sabnzbd",
        "name": "SABnzbd",
        "category": "downloads",
        "description": "Automated Usenet binary newsreader with automated post-processing and web GUI.",
        "image": "lscr.io/linuxserver/sabnzbd:latest",
        "default_port": 8080,
        "webui_path": "/",
        "env": {"PUID": "1000", "PGID": "100"},
        "volumes": {"config": "/config", "downloads": "/downloads", "incomplete": "/incomplete-downloads"},
    },
]


def get_all_catalog_apps() -> List[Dict[str, Any]]:
    """Returns all available curated homelab applications."""
    return CURATED_APP_CATALOG


def get_catalog_app(app_id: str) -> Optional[Dict[str, Any]]:
    """Finds an application template by ID."""
    for app in CURATED_APP_CATALOG:
        if app["id"] == app_id:
            return dict(app)
    return None


def resolve_app_port_conflict(app_id: str) -> Dict[str, Any]:
    """
    Pre-flight Port Conflict Resolver:
    Checks if the default host port is available.
    If occupied, scans ascending port numbers to suggest the next free port.
    """
    app = get_catalog_app(app_id)
    if not app:
        return {"error": f"App '{app_id}' not found in catalog."}

    default_port = int(app.get("default_port", 8080))
    is_avail = check_port_available(default_port)

    if is_avail:
        return {
            "app_id": app_id,
            "default_port": default_port,
            "suggested_port": default_port,
            "conflict_detected": False,
        }

    # Search for next available port
    candidate = default_port + 1
    found_port = None
    for _ in range(100):
        if check_port_available(candidate):
            found_port = candidate
            break
        candidate += 1

    return {
        "app_id": app_id,
        "default_port": default_port,
        "suggested_port": found_port or (default_port + 100),
        "conflict_detected": True,
        "reason": f"Port {default_port} is already in use by another service on this host.",
    }


def generate_compose_for_app(app_id: str, host_port: Optional[int] = None, storage_root: str = "/mnt/user/appdata") -> Dict[str, Any]:
    """
    Generates a valid Docker Compose definition for 1-click deployment.
    """
    app = get_catalog_app(app_id)
    if not app:
        return {"error": f"App '{app_id}' not found."}

    port = host_port or app.get("default_port", 8080)
    service_name = app_id

    volumes_list = []
    for vol_key, vol_target in app.get("volumes", {}).items():
        host_path = f"{storage_root.rstrip('/')}/{app_id}/{vol_key}"
        volumes_list.append(f"{host_path}:{vol_target}")

    environment_list = [f"{k}={v}" for k, v in app.get("env", {}).items()]

    compose_dict = {
        "version": "3.8",
        "services": {
            service_name: {
                "container_name": service_name,
                "image": app["image"],
                "restart": "unless-stopped",
                "ports": [f"{port}:{app['default_port']}"],
                "environment": environment_list,
                "volumes": volumes_list,
            }
        },
    }

    yaml_lines = [
        f"# ZettNAS 1-Click Homelab Stack: {app['name']}",
        "version: '3.8'",
        "services:",
        f"  {service_name}:",
        f"    container_name: {service_name}",
        f"    image: {app['image']}",
        "    restart: unless-stopped",
        "    ports:",
        f"      - \"{port}:{app['default_port']}\"",
    ]
    if environment_list:
        yaml_lines.append("    environment:")
        for env_item in environment_list:
            yaml_lines.append(f"      - {env_item}")
    if volumes_list:
        yaml_lines.append("    volumes:")
        for vol_item in volumes_list:
            yaml_lines.append(f"      - {vol_item}")

    return {
        "app_id": app_id,
        "service_name": service_name,
        "port": port,
        "compose_dict": compose_dict,
        "compose_yaml": "\n".join(yaml_lines),
    }

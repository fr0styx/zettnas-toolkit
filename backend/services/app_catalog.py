import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from backend.config import logger
from backend.hardware.docker_stats import UnixHTTPConnection
from backend.services.container_mutator import _docker_request, check_port_available
from backend.state import add_event

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


def generate_compose_for_app(
    app_id: str, host_port: Optional[int] = None, storage_root: str = "/mnt/user/appdata"
) -> Dict[str, Any]:
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
        f'      - "{port}:{app["default_port"]}"',
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


def stream_deploy_catalog_app(
    app_id: str, host_port: Optional[int] = None, storage_root: str = "/mnt/user/appdata"
) -> Iterator[Dict[str, Any]]:
    """
    Deploys a curated application stack from the catalog, streaming real-time progress
    events (pre-flight checks, storage creation, image pulling, container creation, and startup).
    """
    app = get_catalog_app(app_id)
    if not app:
        yield {
            "step": "error",
            "percent": 0,
            "message": f"Application '{app_id}' was not found in the curated catalog.",
            "done": True,
        }
        return

    port = host_port or app.get("default_port", 8080)
    service_name = app_id
    image_name = app["image"]

    yield {
        "step": "init",
        "percent": 5,
        "message": f"Initializing deployment for {app['name']} (Port :{port})...",
        "done": False,
    }

    # 1. Volume Directories & Compose File
    yield {
        "step": "storage",
        "percent": 12,
        "message": f"Preparing persistent storage directories under {storage_root}/{app_id}...",
        "done": False,
    }

    resolved_root = storage_root
    try:
        os.makedirs(resolved_root, exist_ok=True)
    except Exception:
        resolved_root = os.environ.get("DATA_DIR", "/tmp/zettnas-appdata")
        os.makedirs(resolved_root, exist_ok=True)

    app_dir = os.path.join(resolved_root, app_id)
    binds = []
    try:
        os.makedirs(app_dir, exist_ok=True)
        for vol_key, vol_target in app.get("volumes", {}).items():
            vol_host_path = os.path.join(app_dir, vol_key)
            os.makedirs(vol_host_path, exist_ok=True)
            binds.append(f"{vol_host_path}:{vol_target}:rw")

        comp_info = generate_compose_for_app(app_id, host_port=port, storage_root=resolved_root)
        if "compose_yaml" in comp_info:
            compose_file = os.path.join(app_dir, "docker-compose.yml")
            with open(compose_file, "w", encoding="utf-8") as f:
                f.write(comp_info["compose_yaml"])
    except Exception as e:
        logger.warning(f"Storage setup notice for {app_id}: {e}")

    yield {
        "step": "preflight",
        "percent": 20,
        "message": "Storage prepared. Checking existing container state...",
        "done": False,
    }

    # 2. Check and clean up existing container with same name if any
    try:
        st, old_c = _docker_request("GET", f"/containers/{service_name}/json")
        if st == 200:
            yield {
                "step": "clean",
                "percent": 25,
                "message": f"Found existing container '{service_name}'. Stopping and replacing...",
                "done": False,
            }
            if old_c.get("State", {}).get("Running"):
                _docker_request("POST", f"/containers/{service_name}/stop?t=5")
            _docker_request("DELETE", f"/containers/{service_name}?v=false")
    except Exception as e:
        logger.warning(f"Notice during old container cleanup for {service_name}: {e}")

    # 3. Pull image with streaming progress
    yield {
        "step": "pull",
        "percent": 30,
        "message": f"Inspecting local image cache for {image_name}...",
        "done": False,
    }

    st, _ = _docker_request("GET", f"/images/{image_name}/json")
    if st == 200:
        yield {
            "step": "pull",
            "percent": 70,
            "message": f"Image {image_name} is already present locally.",
            "done": False,
        }
    else:
        yield {
            "step": "pull",
            "percent": 32,
            "message": f"Pulling {image_name} from registry (downloading layers)...",
            "done": False,
        }
        if ":" in image_name:
            repo, tag = image_name.rsplit(":", 1)
        else:
            repo, tag = image_name, "latest"

        sock_path = "/var/run/docker.sock"
        if not os.path.exists(sock_path):
            yield {
                "step": "error",
                "percent": 0,
                "message": "Docker socket /var/run/docker.sock not available.",
                "error": "Docker socket missing",
                "done": True,
            }
            return

        pull_conn = None
        try:
            pull_conn = UnixHTTPConnection(sock_path, timeout=600.0)
            pull_conn.request("POST", f"/images/create?fromImage={repo}&tag={tag}")
            pull_res = pull_conn.getresponse()

            if pull_res.status != 200:
                raw_err = pull_res.read().decode("utf-8", errors="replace")
                yield {
                    "step": "error",
                    "percent": 0,
                    "message": f"Failed to pull image {image_name}: {raw_err}",
                    "error": raw_err,
                    "done": True,
                }
                return

            layers = {}
            last_yield_time = time.time()
            last_percent = 32

            while True:
                line = pull_res.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8", errors="ignore"))
                    status_text = payload.get("status", "")
                    layer_id = payload.get("id")
                    progress_detail = payload.get("progressDetail", {})

                    if layer_id and progress_detail.get("total", 0) > 0:
                        layers[layer_id] = {
                            "current": progress_detail.get("current", 0),
                            "total": progress_detail.get("total", 0),
                        }

                    now = time.time()
                    if now - last_yield_time >= 0.5:
                        if layers:
                            total_bytes = sum(layer_data["total"] for layer_data in layers.values())
                            cur_bytes = sum(layer_data["current"] for layer_data in layers.values())
                            ratio = cur_bytes / max(total_bytes, 1)
                            calc_pct = 32 + int(ratio * 38)
                        else:
                            calc_pct = min(70, last_percent + 2)

                        calc_pct = max(last_percent, min(72, calc_pct))
                        last_percent = calc_pct
                        last_yield_time = now

                        detail_msg = f"Pulling {image_name}: {status_text}"
                        if layer_id:
                            detail_msg += f" [{layer_id}]"
                        yield {
                            "step": "pull",
                            "percent": calc_pct,
                            "message": detail_msg,
                            "done": False,
                        }
                except Exception:
                    pass

            yield {
                "step": "pull",
                "percent": 75,
                "message": f"Image {image_name} successfully downloaded and verified.",
                "done": False,
            }
        except Exception as e:
            yield {
                "step": "error",
                "percent": 0,
                "message": f"Image pull error: {str(e)}",
                "error": str(e),
                "done": True,
            }
            return
        finally:
            if pull_conn:
                try:
                    pull_conn.close()
                except Exception:
                    pass

    # 4. Create container
    yield {
        "step": "create",
        "percent": 80,
        "message": f"Creating container '{service_name}' with port bindings...",
        "done": False,
    }

    env_list = [f"{k}={v}" for k, v in app.get("env", {}).items()]
    target_port = app.get("default_port", 8080)
    port_key = f"{target_port}/tcp"

    create_body = {
        "Image": image_name,
        "Env": env_list,
        "ExposedPorts": {port_key: {}},
        "HostConfig": {
            "PortBindings": {port_key: [{"HostIp": "", "HostPort": str(port)}]},
            "Binds": binds,
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Labels": {
            "com.docker.compose.project": app_id,
            "com.docker.compose.service": app_id,
            "net.unraid.docker.managed": "dockerman",
            "net.unraid.docker.webui": f"http://[IP]:[PORT:{port}]{app.get('webui_path', '/')}",
            "net.unraid.docker.icon": f"https://raw.githubusercontent.com/fr0styx/zettnas-toolkit/main/static/img/icons/{app_id}.png",
        },
    }

    st, create_resp = _docker_request("POST", f"/containers/create?name={service_name}", body=create_body)
    if st != 201:
        yield {
            "step": "error",
            "percent": 0,
            "message": f"Container creation failed: {create_resp}",
            "error": str(create_resp),
            "done": True,
        }
        return

    cid = create_resp.get("Id")
    if not cid:
        yield {
            "step": "error",
            "percent": 0,
            "message": f"Docker did not return container ID: {create_resp}",
            "error": "Missing container ID",
            "done": True,
        }
        return

    yield {
        "step": "create",
        "percent": 88,
        "message": f"Container created successfully (ID: {cid[:12]}).",
        "done": False,
    }

    # 5. Start container
    yield {
        "step": "start",
        "percent": 92,
        "message": f"Starting container '{service_name}'...",
        "done": False,
    }

    st, start_resp = _docker_request("POST", f"/containers/{cid}/start")
    if st not in (204, 304):
        yield {
            "step": "error",
            "percent": 0,
            "message": f"Failed to start container '{service_name}': {start_resp}",
            "error": str(start_resp),
            "done": True,
        }
        return

    # 6. Verify running state
    time.sleep(0.5)
    st, inspect_resp = _docker_request("GET", f"/containers/{cid}/json")
    is_running = inspect_resp.get("State", {}).get("Running", False) if st == 200 else False

    try:
        add_event("info", "AppCatalog", f"Deployed {app['name']} stack on port {port}")
    except Exception:
        pass

    webui_url = f"http://[HOST]:{port}{app.get('webui_path', '/')}"

    yield {
        "step": "success",
        "percent": 100,
        "message": f"✓ {app['name']} deployed and running successfully!",
        "container_id": cid,
        "container_name": service_name,
        "port": port,
        "webui_url": webui_url,
        "is_running": is_running,
        "done": True,
    }

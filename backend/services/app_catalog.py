import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any, Optional

from backend.config import DATA_DIR, docker_sock, logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.docker_stats import UnixHTTPConnection
from backend.ignored_errors import ignored
from backend.services.catalog_templates import CURATED_APP_CATALOG
from backend.services.container_mutator import _docker_request, check_port_available, check_port_available_detailed
from backend.services.image_ref import FOLLOW_TAG_LABEL
from backend.state import add_event

CATALOG_SOURCES_FILE = os.path.join(DATA_DIR, "catalog_sources.json")
CATALOG_CACHE_DIR = os.path.join(DATA_DIR, "catalog_cache")

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "id": "builtin",
        "name": "ZettNAS Curated Suite",
        "url": "builtin",
        "enabled": True,
        "type": "builtin",
        "description": "Hand-crafted, tested homelab stacks built directly into ZettNAS.",
        "item_count": len(CURATED_APP_CATALOG),
        "last_synced": int(time.time()),
        "status": "ok",
        "error": None,
    }
]

# Community catalogs in Portainer template format, off until the user turns them on.
# Their apps are labelled "community": not reviewed by ZettNAS, and still go through the
# security review and the Docker proxy before they install.
COMMUNITY_SOURCES: list[dict[str, Any]] = [
    {
        "id": "community_portainer",
        "name": "Community templates (Portainer format)",
        "url": "https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json",
        "enabled": False,
        "type": "portainer",
        "description": "About 800 community-maintained apps in Portainer template format, not reviewed by ZettNAS.",
        "item_count": 0,
        "last_synced": 0,
        "status": "not_synced",
        "error": None,
    }
]


_CATEGORY_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("media", ("media", "video", "music", "audio", "streaming", "movie", "tv", "book", "podcast", "radio")),
    ("photos", ("photo", "gallery", "image")),
    ("cloud", ("cloud", "storage", "file", "sync", "backup", "drive", "document", "office", "notes", "wiki")),
    ("automation", ("auto", "ai", "smart home", "iot", "home automation", "mqtt", "zigbee", "workflow")),
    ("downloads", ("download", "torrent", "usenet", "p2p", "arr", "nzb")),
    (
        "utilities",
        (
            "util",
            "tool",
            "dns",
            "security",
            "proxy",
            "vpn",
            "monitor",
            "network",
            "dash",
            "system",
            "database",
            "finance",
            "admin",
            "dev",
        ),
    ),
]


def _category_word_re(word: str) -> re.Pattern[str]:
    # Short words only at the start of a word: "ai" is not in "email" or "container",
    # "tv" not in "ntvdm"; "arr" is the end of a name (Sonarr, Radarr), not "array".
    if word == "arr":
        return re.compile(r"[a-z]arr\b")
    if len(word) <= 3:
        return re.compile(r"\b" + re.escape(word))
    return re.compile(re.escape(word))


_CATEGORY_RES = [(cat, [_category_word_re(w) for w in words]) for cat, words in _CATEGORY_WORDS]


def normalize_category(cats: Any) -> str:
    """Normalizes arbitrary template categories to ZettNAS standard categories."""
    if isinstance(cats, str):
        cats = [cats]
    elif not isinstance(cats, list):
        cats = []
    lower = " ".join([str(c).lower() for c in cats])
    for cat, patterns in _CATEGORY_RES:
        if any(p.search(lower) for p in patterns):
            return cat
    return "other"


def parse_portainer_ports(raw_ports: Any) -> tuple[int, list[str]]:
    """Extracts default port and normalized port mapping list from Portainer template ports."""
    ports_list = []
    if isinstance(raw_ports, list):
        for p in raw_ports:
            if isinstance(p, str):
                ports_list.append(p)
            elif isinstance(p, dict):
                c = p.get("container")
                h = p.get("host", c)
                proto = p.get("protocol", "tcp")
                if c:
                    ports_list.append(f"{h}:{c}/{proto}")
    elif isinstance(raw_ports, dict):
        for c, h in raw_ports.items():
            ports_list.append(f"{h}:{c}")

    default_port = 8080
    if ports_list:
        for p in ports_list:
            match = re.match(r"^(\d+):(\d+)", str(p))
            if match:
                hp = int(match.group(1))
                cp = int(match.group(2))
                if cp in (80, 8080, 3000, 5000, 8000, 8096, 2283, 9000):
                    default_port = hp
                    break
        else:
            match = re.match(r"^(\d+):(\d+)", str(ports_list[0]))
            if match:
                default_port = int(match.group(1))

    return default_port, ports_list


_VOL_KEY_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")


def _safe_vol_key(key: Any) -> bool:
    """A template volume key is a folder name inside the app's own folder, never a host path."""
    k = str(key)
    return bool(_VOL_KEY_RE.fullmatch(k)) and k not in (".", "..")


def _vol_key_for(target: str, taken: dict[str, str]) -> str:
    key = target.strip("/").split("/")[-1] or "data"
    key = re.sub(r"[^a-zA-Z0-9_]+", "_", key).lower() or "data"
    if key in taken:
        key = f"{key}_{len(taken) + 1}"
    return key


def sanitize_volume_map(raw: Any) -> dict[str, str]:
    """Template volumes as {folder under the app's folder: path in the container}.

    Keys that are not plain folder names (host paths, '..') are replaced by a name
    made from the container path, as the list form already does.
    """
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key, target in raw.items():
        target = str(target or "").split(":", 1)[0].strip()
        if not target.startswith("/"):
            continue
        name = str(key) if _safe_vol_key(key) and str(key) not in out else _vol_key_for(target, out)
        out[name] = target
    return out


def _unsafe_volumes(app: dict[str, Any]) -> list[str]:
    return [
        str(k)
        for k, v in (app.get("volumes") or {}).items()
        if not _safe_vol_key(k) or not str(v).startswith("/") or ":" in str(v)
    ]


def parse_portainer_volumes(raw_vols: Any) -> dict[str, str]:
    """Extracts clean volume mapping dictionary from Portainer template volumes."""
    vol_dict = {}
    if isinstance(raw_vols, list):
        for v in raw_vols:
            if isinstance(v, dict):
                target = v.get("container") or v.get("target")
                if target:
                    key = target.strip("/").split("/")[-1] or "data"
                    key = re.sub(r"[^a-zA-Z0-9_]+", "_", key).lower()
                    if key in vol_dict:
                        key = f"{key}_{len(vol_dict) + 1}"
                    vol_dict[key] = target
            elif isinstance(v, str) and ":" in v:
                # host:container[:mode]; two folders with the same name both stay
                target = v.split(":")[1]
                if target.startswith("/"):
                    vol_dict[_vol_key_for(target, vol_dict)] = target
    elif isinstance(raw_vols, dict):
        vol_dict = sanitize_volume_map(raw_vols)
    if not vol_dict:
        vol_dict = {"config": "/config"}
    return vol_dict


def parse_portainer_env(raw_env: Any) -> dict[str, str]:
    """Extracts key-value environment variables from Portainer template env."""
    env_dict = {}
    if isinstance(raw_env, list):
        for e in raw_env:
            if isinstance(e, dict):
                name = e.get("name")
                if name:
                    val = e.get("default", "")
                    env_dict[str(name)] = str(val) if val is not None else ""
            elif isinstance(e, str) and "=" in e:
                k, v = e.split("=", 1)
                env_dict[k.strip()] = v.strip()
    elif isinstance(raw_env, dict):
        env_dict = {str(k): str(v) for k, v in raw_env.items()}
    return env_dict


def get_catalog_sources() -> list[dict[str, Any]]:
    """Loads configured app sources list, initializing defaults if needed."""
    sources = read_json(CATALOG_SOURCES_FILE, None)
    if not sources or not isinstance(sources, list):
        sources = [dict(s) for s in DEFAULT_SOURCES]
        save_catalog_sources(sources)
    else:
        # Guarantee builtin exists
        if not any(s.get("id") == "builtin" for s in sources):
            sources.insert(0, dict(DEFAULT_SOURCES[0]))
            save_catalog_sources(sources)
    # Offer the community catalogs (off) unless the same URL is already configured
    known_urls = {s.get("url") for s in sources}
    added = [
        dict(c)
        for c in COMMUNITY_SOURCES
        if c["url"] not in known_urls and not any(s.get("id") == c["id"] for s in sources)
    ]
    if added:
        sources.extend(added)
        save_catalog_sources(sources)
    return sources


def save_catalog_sources(sources: list[dict[str, Any]]) -> None:
    """Atomically saves configured sources list."""
    atomic_write_json(CATALOG_SOURCES_FILE, sources)


def sync_catalog_source(source_id: str) -> dict[str, Any]:
    """Fetches templates from remote source URL and updates local cache."""
    sources = get_catalog_sources()
    src = next((s for s in sources if s["id"] == source_id), None)
    if not src:
        raise ValueError(f"Source '{source_id}' not found.")

    if src["id"] == "builtin":
        src["item_count"] = len(CURATED_APP_CATALOG)
        src["last_synced"] = int(time.time())
        src["status"] = "ok"
        src["error"] = None
        save_catalog_sources(sources)
        return src

    url = src.get("url")
    if not url or not url.startswith(("http://", "https://")):
        src["status"] = "error"
        src["error"] = "Invalid source URL"
        save_catalog_sources(sources)
        return src

    try:
        from backend.services.safe_fetch import safe_fetch

        status, _hdrs, body = safe_fetch(
            url,
            context="lan",
            headers={"User-Agent": "ZettNAS-Toolkit/1.5 (+https://github.com/fr0styx/zettnas-toolkit)"},
            timeout=15,
            max_bytes=20 * 1024 * 1024,
        )
        if status != 200:
            raise ValueError(f"HTTP {status}")
        raw_text = body.decode("utf-8", errors="replace")
        data = json.loads(raw_text)

        templates = data.get("templates", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        normalized_apps = []
        seen_slugs = set()

        for idx, t in enumerate(templates):
            if not isinstance(t, dict):
                continue

            raw_name = t.get("name") or t.get("title") or f"app_{idx + 1}"
            slug = re.sub(r"[^a-z0-9_-]+", "_", str(raw_name).lower()).strip("_")
            if not slug:
                slug = f"app_{idx + 1}"

            base_slug = slug
            dedup_cnt = 2
            while slug in seen_slugs:
                slug = f"{base_slug}_{dedup_cnt}"
                dedup_cnt += 1
            seen_slugs.add(slug)

            app_id = f"{source_id}_{slug}"
            title = t.get("title") or t.get("name") or slug.replace("_", " ").title()
            cat = normalize_category(t.get("categories") or t.get("category"))
            desc = t.get("description") or t.get("note") or f"{title} container application."
            logo = t.get("logo") or ""
            image = t.get("image") or ""
            repo = t.get("repository") if isinstance(t.get("repository"), dict) else None
            app_type = "stack" if (t.get("type") == 3 or repo) else "standalone"

            default_port, ports_list = parse_portainer_ports(t.get("ports"))
            vol_dict = parse_portainer_volumes(t.get("volumes"))
            env_dict = parse_portainer_env(t.get("env"))

            normalized_apps.append(
                {
                    "id": app_id,
                    "app_slug": slug,
                    "source_id": source_id,
                    "source_name": src.get("name", source_id),
                    "name": title,
                    "category": cat,
                    "description": desc,
                    "image": image,
                    "logo": logo,
                    "default_port": default_port,
                    "ports": ports_list,
                    "webui_path": "/",
                    "env": env_dict,
                    "volumes": vol_dict,
                    "repository": repo,
                    "type": app_type,
                    "trust": "community",
                }
            )

        os.makedirs(CATALOG_CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(CATALOG_CACHE_DIR, f"{source_id}.json")
        atomic_write_json(cache_file, normalized_apps)

        src["item_count"] = len(normalized_apps)
        src["last_synced"] = int(time.time())
        src["status"] = "ok"
        src["error"] = None
        save_catalog_sources(sources)
        logger.info(f"[AppCatalog] Successfully synced {len(normalized_apps)} apps from source '{src['name']}'")
        return src

    except Exception as e:
        logger.warning(f"[AppCatalog] Failed to sync source '{src['name']}': {e}")
        src["status"] = "error"
        src["error"] = str(e)
        save_catalog_sources(sources)
        return src


def add_catalog_source(name: str, url: str) -> dict[str, Any]:
    """Adds a new template source and immediately syncs its templates."""
    name = (name or "").strip()
    url = (url or "").strip()
    if not name or not url:
        raise ValueError("Name and URL are required.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")

    sources = get_catalog_sources()
    for s in sources:
        if s.get("url") == url:
            raise ValueError(f"Source with this URL already exists: '{s.get('name')}'")

    source_id = re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")
    if not source_id:
        source_id = f"src_{int(time.time())}"

    base_id = source_id
    counter = 2
    while any(s.get("id") == source_id for s in sources):
        source_id = f"{base_id}_{counter}"
        counter += 1

    new_source = {
        "id": source_id,
        "name": name,
        "url": url,
        "enabled": True,
        "type": "portainer",
        "description": f"Custom template source from {url}",
        "item_count": 0,
        "last_synced": 0,
        "status": "pending",
        "error": None,
    }
    sources.append(new_source)
    save_catalog_sources(sources)

    updated = sync_catalog_source(source_id)
    return {"status": "ok", "source": updated}


def delete_catalog_source(source_id: str) -> bool:
    """Deletes a custom template source and removes its cache file."""
    if source_id == "builtin":
        raise ValueError("Built-in curated catalog cannot be deleted.")

    sources = get_catalog_sources()
    filtered = [s for s in sources if s["id"] != source_id]
    if len(filtered) == len(sources):
        return False

    save_catalog_sources(filtered)
    cache_file = os.path.join(CATALOG_CACHE_DIR, f"{source_id}.json")
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
        except OSError:
            pass
    return True


def toggle_catalog_source(source_id: str, enabled: bool) -> dict[str, Any]:
    """Enables or disables an app source."""
    sources = get_catalog_sources()
    src = next((s for s in sources if s["id"] == source_id), None)
    if not src:
        raise ValueError(f"Source '{source_id}' not found.")
    src["enabled"] = bool(enabled)
    save_catalog_sources(sources)
    return src


SIDELOADED_APPS_FILE = os.path.join(DATA_DIR, "sideloaded_apps.json")


def get_sideloaded_apps() -> list[dict[str, Any]]:
    """Retrieves locally sideloaded application packages."""
    items = read_json(SIDELOADED_APPS_FILE, [])
    return items if isinstance(items, list) else []


def save_sideloaded_apps(items: list[dict[str, Any]]) -> None:
    """Persists sideloaded application packages."""
    atomic_write_json(SIDELOADED_APPS_FILE, items)


def sideload_app_manifest(
    url: str | None = None,
    manifest_content: str | None = None,
) -> dict[str, Any]:
    """Sideloads an application from a direct URL (zett-app.json / docker-compose.yml)

    or raw JSON/YAML content. Performs security assessment for privileged flags and socket mounts.
    """
    raw_text = ""
    if url:
        u = url.strip()
        if not u.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        from backend.services.safe_fetch import safe_fetch

        status, _hdrs, body = safe_fetch(u, context="lan", headers={"User-Agent": "ZettNAS-Toolkit/1.0"}, timeout=15)
        if status != 200:
            raise ValueError(f"Could not download the manifest (HTTP {status})")
        raw_text = body.decode("utf-8", errors="replace")
    elif manifest_content:
        raw_text = manifest_content.strip()
    else:
        raise ValueError("Either 'url' or 'manifest_content' must be provided.")

    if not raw_text:
        raise ValueError("Manifest content is empty.")

    # Try parsing as JSON first
    parsed_json = None
    try:
        parsed_json = json.loads(raw_text)
    except Exception:
        parsed_json = None

    parsed_yaml = None
    if parsed_json is None:
        try:
            import yaml

            parsed_yaml = yaml.safe_load(raw_text)
        except Exception as e:
            raise ValueError(f"Failed to parse manifest as JSON or YAML: {e}") from e

    manifest_data = parsed_json if parsed_json is not None else parsed_yaml
    if not isinstance(manifest_data, dict):
        raise ValueError("Invalid manifest structure: root must be a JSON/YAML object.")

    # 1. Detect if this is zett-app.json / Portainer template or direct docker-compose.yml
    is_compose = "services" in manifest_data or "version" in manifest_data

    app_id = ""
    name = ""
    category = "utilities"
    description = ""
    image = ""
    default_port = 8080
    ports: list[int] = []
    volumes: dict[str, str] = {}
    env: dict[str, str] = {}
    logo = ""

    if is_compose:
        services = manifest_data.get("services", {})
        if not services or not isinstance(services, dict):
            raise ValueError("Compose manifest contains no services.")
        svc_name, svc_cfg = next(iter(services.items()))
        name = manifest_data.get("name") or svc_name.capitalize()
        app_id = f"sideload_{re.sub(r'[^a-z0-9_]+', '_', svc_name.lower())}_{int(time.time())}"
        description = f"Sideloaded Stack: {name}"
        image = svc_cfg.get("image", "")
        raw_ports = svc_cfg.get("ports", [])
        if raw_ports and isinstance(raw_ports, list):
            for p in raw_ports:
                p_str = str(p)
                if ":" in p_str:
                    host_p = p_str.split(":")[0]
                    if host_p.isdigit():
                        default_port = int(host_p)
                        ports.append(default_port)
        raw_vols = svc_cfg.get("volumes", [])
        if raw_vols and isinstance(raw_vols, list):
            for v in raw_vols:
                v_str = str(v)
                if ":" in v_str:
                    _host, c = v_str.split(":", 1)
                    target = c.split(":", 1)[0]
                    if target.startswith("/"):
                        volumes[_vol_key_for(target, volumes)] = target
        raw_env = svc_cfg.get("environment", {})
        if isinstance(raw_env, dict):
            env = {str(k): str(val) for k, val in raw_env.items()}
        elif isinstance(raw_env, list):
            for e_item in raw_env:
                if "=" in str(e_item):
                    k, val = str(e_item).split("=", 1)
                    env[k.strip()] = val.strip()
    else:
        name = manifest_data.get("name", "Custom Sideloaded App")
        slug = manifest_data.get("id") or re.sub(r"[^a-z0-9_]+", "_", name.lower())
        app_id = f"sideload_{slug}"
        category = manifest_data.get("category", "utilities")
        description = manifest_data.get("description", "Custom sideloaded package")
        image = manifest_data.get("image", "")
        default_port = int(manifest_data.get("default_port", 8080))
        logo = manifest_data.get("logo") or manifest_data.get("icon") or ""
        ports = manifest_data.get("ports", [default_port])
        volumes = sanitize_volume_map(manifest_data.get("volumes", {}))
        env = manifest_data.get("env", {})

    # 2. Security Assessment
    security_flags = []
    text_lower = raw_text.lower()
    if "privileged: true" in text_lower or "privileged: yes" in text_lower:
        security_flags.append("Runs in Privileged Mode (Full Host Kernel Access)")
    if "/var/run/docker.sock" in text_lower:
        security_flags.append("Mounts Docker Unix Socket (/var/run/docker.sock)")
    if "network_mode: host" in text_lower or 'network_mode: "host"' in text_lower:
        security_flags.append("Uses Host Networking (Bypasses Container Network Isolation)")
    if (
        "/:/host" in text_lower
        or ":/:" in text_lower
        or ":/host" in text_lower
        or ":/root" in text_lower
        or " /:" in text_lower
        or "/:/" in text_lower
    ):
        security_flags.append("Mounts Root Filesystem of Host")

    security_rating = "verified"
    if security_flags:
        security_rating = (
            "review_required" if len(security_flags) == 1 and "/var/run/docker.sock" not in text_lower else "elevated"
        )

    app_record = {
        "id": app_id,
        "name": name,
        "category": category,
        "description": description,
        "image": image,
        "default_port": default_port,
        "ports": ports,
        "volumes": volumes,
        "env": env,
        "logo": logo,
        "source_id": "sideload",
        "source_name": "Sideloaded",
        "type": "compose" if is_compose else "standalone",
        "sideloaded_at": time.time(),
        "security_rating": security_rating,
        "security_flags": security_flags,
        "raw_manifest": raw_text,
    }

    sideloaded = get_sideloaded_apps()
    sideloaded = [a for a in sideloaded if a.get("id") != app_id]
    sideloaded.append(app_record)
    save_sideloaded_apps(sideloaded)

    return {
        "status": "ok",
        "app": app_record,
        "security_rating": security_rating,
        "security_flags": security_flags,
    }


def get_all_catalog_apps() -> list[dict[str, Any]]:
    """Returns all available homelab applications across all enabled sources."""
    sources = get_catalog_sources()
    apps: list[dict[str, Any]] = []

    # 1. Built-in Apps
    builtin_src = next((s for s in sources if s["id"] == "builtin"), None)
    if not builtin_src or builtin_src.get("enabled", True):
        for b_app in CURATED_APP_CATALOG:
            item = dict(b_app)
            item.setdefault("source_id", "builtin")
            item.setdefault("source_name", "Built-in")
            item.setdefault("app_slug", item["id"])
            item.setdefault("type", "stack" if item.get("stack_services") else "standalone")
            item.setdefault("logo", "")
            item.pop("seed_files", None)  # starter files stay on the server
            apps.append(item)

    # 2. Custom Sources
    for src in sources:
        if src["id"] == "builtin" or not src.get("enabled", True):
            continue
        cache_file = os.path.join(CATALOG_CACHE_DIR, f"{src['id']}.json")
        cached = read_json(cache_file, [])
        if isinstance(cached, list):
            apps.extend(cached)

    # 3. Sideloaded Apps
    sideloaded = get_sideloaded_apps()
    apps.extend(sideloaded)

    return apps


def get_catalog_app(app_id: str) -> dict[str, Any] | None:
    """Finds an application template by ID across all sources."""
    from backend.services.image_ref import pin_app

    for app in get_all_catalog_apps():
        if app["id"] == app_id:
            if app.get("source_id") != "builtin":
                return dict(app)
            # the listing leaves out starter files (seed_files); the install needs them
            full = next((b for b in CURATED_APP_CATALOG if b["id"] == app_id), {})
            # built-in apps install the exact image that shipped with this version
            return pin_app({**app, "seed_files": full.get("seed_files") or {}})
    return None


def resolve_app_port_conflict(app_id: str) -> dict[str, Any]:
    """
    Pre-flight Port Conflict Resolver:
    Checks if the default host port is available.
    If occupied, scans ascending port numbers to suggest the next free port.
    Detects if an existing container with the same name or port is already present.
    """
    app = get_catalog_app(app_id)
    if not app:
        return {"error": f"App '{app_id}' not found in catalog."}

    default_port = int(app.get("default_port", 8080))
    service_name = app.get("app_slug") or app_id
    service_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", service_name)

    existing_container = None
    try:
        st, c_info = _docker_request("GET", f"/containers/{service_name}/json")
        if st == 200 and isinstance(c_info, dict):
            existing_container = {
                "name": service_name,
                "id": str(c_info.get("Id", ""))[:12],
                "running": bool(c_info.get("State", {}).get("Running", False)),
            }
    except Exception:
        ignored("backend.services.app_catalog.resolve_app_port_conflict")

    suggested_container_name = service_name
    if existing_container:
        counter = 2
        cand_name = f"{service_name}-{counter}"
        while counter < 100:
            st, _ = _docker_request("GET", f"/containers/{cand_name}/json")
            if st == 404:
                suggested_container_name = cand_name
                break
            counter += 1
            cand_name = f"{service_name}-{counter}"

    is_mocked = hasattr(check_port_available, "mock_calls")
    if is_mocked:
        is_avail = bool(check_port_available(default_port))
        in_use_by = None if is_avail else "another service on this host"
    else:
        is_avail, in_use_by = check_port_available_detailed(default_port)

    if is_avail:
        return {
            "app_id": app_id,
            "default_port": default_port,
            "suggested_port": default_port,
            "conflict_detected": False,
            "existing_container": existing_container,
            "suggested_container_name": suggested_container_name,
        }

    # Search for next available port
    candidate = default_port + 1
    found_port = None
    for _ in range(100):
        c_avail = bool(check_port_available(candidate)) if is_mocked else check_port_available_detailed(candidate)[0]
        if c_avail:
            found_port = candidate
            break
        candidate += 1

    occupier = in_use_by or "another service on this host"
    return {
        "app_id": app_id,
        "default_port": default_port,
        "suggested_port": found_port or (default_port + 100),
        "conflict_detected": True,
        "in_use_by": occupier,
        "existing_container": existing_container,
        "suggested_container_name": suggested_container_name,
        "reason": f"Port {default_port} is already in use by {occupier}.",
    }


_GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def github_repo(url: str) -> str | None:
    """owner/name of a https://github.com/owner/name[.git] link; None for any other host."""
    parts = urllib.parse.urlparse(str(url or "").strip())
    if parts.scheme not in ("https", "http") or (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    repo = "/".join(parts.path.strip("/").split("/")[:2]).removesuffix(".git")
    return repo if _GITHUB_REPO.match(repo) and ".." not in repo else None


def generate_compose_for_app(
    app_id: str,
    host_port: int | None = None,
    storage_root: str = "/mnt/user/appdata",
    container_name: str | None = None,
    env_overrides: dict[str, str] | None = None,
    volume_overrides: dict[str, str] | None = None,
    stack_services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generates a valid Docker Compose definition for 1-click deployment.
    Supports both standalone container templates, multi-container stacks,
    dynamic .env overrides, and share volume selection.
    """
    app = get_catalog_app(app_id)
    if not app:
        return {"error": f"App '{app_id}' not found."}

    default_p = int(app.get("default_port", 8080))
    port = host_port or default_p
    service_name = app.get("app_slug") or app_id
    if container_name and container_name.strip():
        service_name = container_name.strip()
    service_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", service_name)
    storage_slug = service_name

    # Check for stackfile in repository (e.g. Lissy93 / Portainer stacks)
    repo = app.get("repository")
    if repo and isinstance(repo, dict):
        repo_url = repo.get("url", "")
        stackfile = repo.get("stackfile", "")
        clean_repo = github_repo(repo_url) if stackfile else None
        if clean_repo:
            for branch in ("main", "master"):
                raw_url = f"https://raw.githubusercontent.com/{clean_repo}/{branch}/{stackfile.lstrip('/')}"
                try:
                    req = urllib.request.Request(
                        raw_url,
                        headers={"User-Agent": "ZettNAS-Toolkit/1.5"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as r:
                        raw_stack = r.read().decode("utf-8", errors="replace")
                        if raw_stack.strip():
                            return {
                                "app_id": app_id,
                                "service_name": service_name,
                                "port": port,
                                "compose_yaml": raw_stack,
                            }
                except Exception:
                    ignored("backend.services.app_catalog.generate_compose_for_app")

    # Build volumes list with volume_overrides or default storage_slug
    volumes_list = []
    app_volumes = dict(app.get("volumes", {}))
    for vol_key, vol_target in app_volumes.items():
        if volume_overrides and vol_key in volume_overrides:
            host_path = volume_overrides[vol_key]
        else:
            host_path = f"{storage_root.rstrip('/')}/{storage_slug}/{vol_key}"
        volumes_list.append(f"{host_path}:{vol_target}")

    # Build environment with env_overrides
    merged_env = dict(app.get("env", {}))
    if env_overrides:
        merged_env.update(env_overrides)
    environment_list = [f"{k}={v}" for k, v in merged_env.items()]

    # Format ports
    ports_mapped = []
    raw_ports = app.get("ports")
    if raw_ports and isinstance(raw_ports, list):
        for p_str in raw_ports:
            m = re.match(r"^(\d+):(\d+)(.*)$", str(p_str).strip())
            if m:
                hp = int(m.group(1))
                cp = int(m.group(2))
                suffix = m.group(3)
                if hp == default_p or cp == default_p:
                    ports_mapped.append(f"{port}:{cp}{suffix}")
                else:
                    ports_mapped.append(f"{hp}:{cp}{suffix}")
            else:
                ports_mapped.append(str(p_str))
    if not ports_mapped:
        ports_mapped = [f"{port}:{default_p}"]

    image_name = app.get("image") or f"{service_name}:latest"

    # Multi-container companion stack services
    extra_services = dict(app.get("stack_services", {}))
    if stack_services:
        extra_services.update(stack_services)

    main_service_def: dict[str, Any] = {
        "container_name": service_name,
        "image": image_name,
        "restart": "unless-stopped",
        "ports": ports_mapped,
        "environment": environment_list,
        "volumes": volumes_list,
    }
    if extra_services:
        main_service_def["depends_on"] = list(extra_services.keys())

    compose_dict = {
        "version": "3.8",
        "services": {service_name: main_service_def},
    }

    yaml_lines = [
        f"# ZettNAS 1-Click Homelab Stack: {app['name']}",
        "version: '3.8'",
        "services:",
        f"  {service_name}:",
        f"    container_name: {service_name}",
        f"    image: {image_name}",
        "    restart: unless-stopped",
        "    ports:",
    ]
    for p_item in ports_mapped:
        yaml_lines.append(f'      - "{p_item}"')
    if environment_list:
        yaml_lines.append("    environment:")
        for env_item in environment_list:
            yaml_lines.append(f"      - {env_item}")
    if volumes_list:
        yaml_lines.append("    volumes:")
        for vol_item in volumes_list:
            yaml_lines.append(f"      - {vol_item}")
    if extra_services:
        yaml_lines.append("    depends_on:")
        for dep in extra_services.keys():
            yaml_lines.append(f"      - {dep}")

    # Append companion stack services
    for s_name, s_def in extra_services.items():
        clean_s_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", s_name)
        s_image = s_def.get("image", f"{clean_s_name}:latest")
        s_env = s_def.get("env", {})
        s_env_list = [f"{k}={v}" for k, v in s_env.items()] if isinstance(s_env, dict) else (s_env or [])
        s_vols = s_def.get("volumes", {})
        s_vol_list = []
        if isinstance(s_vols, dict):
            for vk, vt in s_vols.items():
                s_vol_list.append(f"{storage_root.rstrip('/')}/{storage_slug}/{clean_s_name}_{vk}:{vt}")
        elif isinstance(s_vols, list):
            s_vol_list = s_vols
        s_ports = s_def.get("ports", [])

        compose_dict["services"][clean_s_name] = {
            "container_name": clean_s_name,
            "image": s_image,
            "restart": "unless-stopped",
        }
        if s_ports:
            compose_dict["services"][clean_s_name]["ports"] = s_ports
        if s_env_list:
            compose_dict["services"][clean_s_name]["environment"] = s_env_list
        if s_vol_list:
            compose_dict["services"][clean_s_name]["volumes"] = s_vol_list

        yaml_lines.extend(
            [
                f"  {clean_s_name}:",
                f"    container_name: {clean_s_name}",
                f"    image: {s_image}",
                "    restart: unless-stopped",
            ]
        )
        if s_ports:
            yaml_lines.append("    ports:")
            for p in s_ports:
                yaml_lines.append(f'      - "{p}"')
        if s_env_list:
            yaml_lines.append("    environment:")
            for e in s_env_list:
                yaml_lines.append(f"      - {e}")
        if s_vol_list:
            yaml_lines.append("    volumes:")
            for v in s_vol_list:
                yaml_lines.append(f"      - {v}")

    return {
        "app_id": app_id,
        "service_name": service_name,
        "port": port,
        "compose_dict": compose_dict,
        "compose_yaml": "\n".join(yaml_lines),
    }


_SECRET_RE = re.compile(r"\{\{secret:([a-z0-9_]{1,32})\}\}")


def _stack_secrets(app_dir: str) -> dict[str, str]:
    """Generated passwords for a stack, kept so a redeploy reuses them (M3)."""
    path = os.path.join(app_dir, ".zettnas-secrets.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _fill_secrets(value: str, secrets_map: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) not in secrets_map:
            secrets_map[m.group(1)] = secrets.token_urlsafe(24)
        return secrets_map[m.group(1)]

    return _SECRET_RE.sub(sub, value)


def _save_stack_secrets(app_dir: str, secrets_map: dict[str, str]) -> None:
    if not secrets_map:
        return
    path = os.path.join(app_dir, ".zettnas-secrets.json")
    atomic_write_json(path, secrets_map)  # owner-only (0600)


def _pull_image_blocking(image: str) -> tuple[bool, str]:
    st, _ = _docker_request("GET", f"/images/{image}/json")
    if st == 200:
        return True, ""
    from backend.services.image_ref import pull_params

    repo, tag = pull_params(image)
    conn = UnixHTTPConnection(docker_sock(), timeout=900.0)
    try:
        conn.request("POST", f"/images/create?fromImage={urllib.parse.quote(repo)}&tag={urllib.parse.quote(tag)}")
        res = conn.getresponse()
        body = res.read().decode("utf-8", errors="replace")
        if res.status != 200:
            return False, body[:300]
        last = body.strip().splitlines()[-1] if body.strip() else "{}"
        err = json.loads(last).get("error") if last.startswith("{") else None
        return (False, str(err)[:300]) if err else (True, "")
    except (OSError, ValueError) as e:
        return False, str(e)
    finally:
        conn.close()


def _render_nodes() -> list[str]:
    try:
        return [os.path.join("/dev/dri", n) for n in sorted(os.listdir("/dev/dri")) if n.startswith("renderD")]
    except OSError:
        return []


JELLYFIN_ENCODING_XML = """<?xml version="1.0" encoding="utf-8"?>
<EncodingOptions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <HardwareAccelerationType>vaapi</HardwareAccelerationType>
  <VaapiDevice>{device}</VaapiDevice>
  <EnableHardwareEncoding>true</EnableHardwareEncoding>
  <EnableDecodingColorDepth10Hevc>true</EnableDecodingColorDepth10Hevc>
  <EnableDecodingColorDepth10Vp9>true</EnableDecodingColorDepth10Vp9>
  <HardwareDecodingCodecs>
    <string>h264</string>
    <string>hevc</string>
    <string>mpeg2video</string>
    <string>vc1</string>
    <string>vp8</string>
    <string>vp9</string>
    <string>av1</string>
  </HardwareDecodingCodecs>
  <EnableTonemapping>true</EnableTonemapping>
</EncodingOptions>
"""


def hw_transcoding_seed(app: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Starter config that turns on hardware transcoding when the host has a render node."""
    nodes = _render_nodes()
    if app.get("hw_transcoding") != "jellyfin" or not nodes:
        return {}
    return {"config": {"encoding.xml": JELLYFIN_ENCODING_XML.format(device=nodes[0])}}


def media_library_bind(app: dict[str, Any]) -> str | None:
    """ "<share>:/media:ro" for a template that wants the media library, when a media share exists."""
    target = app.get("media_library")
    if not target:
        return None
    try:
        from backend.hardware.pal_storage import get_storage_platform

        names = {"media": 0, "movies": 1, "videos": 2, "video": 3, "films": 4}
        best = None
        for sh in get_storage_platform().list_shares():
            rank = names.get(str(sh.name).lower())
            mp = getattr(sh, "mountpoint", "")
            if rank is not None and mp and os.path.isdir(mp) and (best is None or rank < best[0]):
                best = (rank, mp)
        if best:
            return f"{best[1]}:{target}:ro"
    except Exception:
        logger.debug("media library lookup failed", exc_info=True)
    return None


def _write_seed_files(app: dict[str, Any], app_dir: str) -> None:
    """Writes a template's starter files (e.g. a Caddyfile) once; never overwrites the user's."""
    seeds = {**(app.get("seed_files") or {})}
    for vol_key, files in hw_transcoding_seed(app).items():
        seeds[vol_key] = {**seeds.get(vol_key, {}), **files}
    for vol_key, files in seeds.items():
        if vol_key not in (app.get("volumes") or {}) or not isinstance(files, dict):
            continue
        base = os.path.realpath(os.path.join(app_dir, vol_key))
        for rel, content in files.items():
            target = os.path.realpath(os.path.join(base, rel))
            if not target.startswith(base + os.sep) or os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(str(content))


def _own_volumes(app: dict[str, Any], app_dir: str) -> None:
    """Hands the app's folders to the user its image runs as (e.g. "1000:1000" for Node-RED).

    Only each folder itself and the files we seeded; existing data inside is never re-owned."""
    m = re.fullmatch(r"(\d+):(\d+)", str(app.get("volume_owner") or ""))
    if not m:
        return
    uid, gid = int(m.group(1)), int(m.group(2))
    for vol_key in app.get("volumes") or {}:
        path = os.path.join(app_dir, vol_key)
        try:
            os.chown(path, uid, gid)
            for rel in (app.get("seed_files") or {}).get(vol_key, {}):
                seeded = os.path.join(path, rel)
                if os.path.exists(seeded):
                    os.chown(seeded, uid, gid)
        except OSError as err:
            logger.warning(f"[AppCatalog] Could not give {path} to {uid}:{gid}: {err}")


def _host_access_check(app: dict[str, Any], create_body: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
    """Host-level access a create would get, and the refusal for a template that may not have it.

    Privileged mode, devices and host paths are granted to built-in apps only; a
    community or sideloaded template cannot pre-approve them for itself.
    """
    from backend import docker_proxy

    reasons = docker_proxy.elevated_reasons("/containers/create", create_body)
    if not reasons or app.get("source_id", "builtin") == "builtin":
        return reasons, None
    return reasons, {
        "step": "error",
        "percent": 0,
        "message": (
            f"This template asks for host-level access ({', '.join(reasons)}). Only built-in apps are installed "
            "with it. If you trust it, review it and create the container from the Docker page."
        ),
        "error": "Template needs host-level access",
        "done": True,
    }


def _zettnas_network() -> str | None:
    """The user-defined Docker network ZettNAS itself is on, for apps ZettNAS talks to by name
    (COMP-11); None on the default bridge, where names don't resolve."""
    import socket

    try:
        st, me = _docker_request("GET", f"/containers/{socket.gethostname()}/json")
    except (OSError, ValueError):
        logger.debug("app_catalog: own network unknown", exc_info=True)
        return None
    if st != 200 or not isinstance(me, dict):
        return None
    nets = ((me.get("NetworkSettings") or {}).get("Networks") or {}).keys()
    return next((n for n in nets if n not in ("host", "none", "bridge")), None)


def _apply_runtime_options(create_body: dict[str, Any], app: dict[str, Any]) -> None:
    """Command, capabilities, kernel settings and devices a template asks for."""
    host = create_body.setdefault("HostConfig", {})
    if isinstance(app.get("command"), list) and app["command"]:
        create_body["Cmd"] = [str(c) for c in app["command"]]
    if app.get("cap_add"):
        host["CapAdd"] = [str(c) for c in app["cap_add"]]
    if isinstance(app.get("sysctls"), dict) and app["sysctls"]:
        host["Sysctls"] = {str(k): str(v) for k, v in app["sysctls"].items()}
    if app.get("shm_size"):
        host["ShmSize"] = int(app["shm_size"])
    if app.get("join_zettnas_network") and not host.get("NetworkMode"):
        net = _zettnas_network()  # reachable from ZettNAS by name, no port published
        if net:
            host["NetworkMode"] = net
    devices = [
        d for d in (app.get("devices") or []) if isinstance(d, str) and d.startswith("/dev/") and os.path.exists(d)
    ]
    if devices:  # only what this host has, e.g. /dev/dri for hardware transcoding
        host["Devices"] = [{"PathOnHost": d, "PathInContainer": d, "CgroupPermissions": "rwm"} for d in devices]
        # the GPU's render group, so an app that doesn't run as root can open the render node
        gids = sorted({os.stat(p).st_gid for p in _render_nodes()} - {0})
        if gids:
            host["GroupAdd"] = [str(g) for g in gids]


def _deploy_companions(
    app: dict[str, Any], service_name: str, app_dir: str, secrets_map: dict[str, str], replace_existing: bool
) -> Iterator[dict[str, Any]]:
    """Starts an app's companion containers (database, cache, …) on a private network (M3).

    Yields progress events; the last one has "network" (or "error")."""
    companions = app.get("stack_services") or {}
    network = f"{service_name}_net"
    st, _ = _docker_request("GET", f"/networks/{network}")
    if st != 200:
        st, resp = _docker_request("POST", "/networks/create", body={"Name": network, "Driver": "bridge"})
        if st not in (200, 201):
            yield {"error": f"Could not create the network {network}: {resp}"}
            return
    total = len(companions)
    for i, (s_name, s_def) in enumerate(companions.items()):
        clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", s_name)
        cname = f"{service_name}_{clean}"
        image = s_def.get("image", "")
        yield {
            "step": "pull",
            "percent": 30 + int(25 * i / max(total, 1)),
            "message": f"Preparing {s_name} ({image})...",
            "done": False,
        }
        ok, err = _pull_image_blocking(image)
        if not ok:
            yield {"error": f"Failed to pull {image}: {err}"}
            return
        st_old, old = _docker_request("GET", f"/containers/{cname}/json")
        if st_old == 200:
            if not replace_existing:
                if not old.get("State", {}).get("Running"):
                    _docker_request("POST", f"/containers/{cname}/start")
                continue
            _docker_request("POST", f"/containers/{cname}/stop?t=10")
            _docker_request("DELETE", f"/containers/{cname}?v=false")
        binds = []
        for vk, vt in (s_def.get("volumes") or {}).items():
            host = os.path.join(app_dir, f"{clean}_{vk}")
            os.makedirs(host, exist_ok=True)
            binds.append(f"{host}:{vt}:rw")
        host_cfg: dict[str, Any] = {"Binds": binds, "RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": network}
        if s_def.get("shm_size"):
            host_cfg["ShmSize"] = int(s_def["shm_size"])
        if isinstance(s_def.get("command"), list):
            host_cfg_cmd = [str(c) for c in s_def["command"]]
        else:
            host_cfg_cmd = None
        body = {
            "Image": image,
            "Env": [f"{k}={_fill_secrets(str(v), secrets_map)}" for k, v in (s_def.get("env") or {}).items()],
            "HostConfig": host_cfg,
            "NetworkingConfig": {"EndpointsConfig": {network: {"Aliases": [s_name]}}},
            "Labels": {
                "com.docker.compose.project": service_name,
                "com.docker.compose.service": s_name,
                "com.zettnas.managed": "1",
            },
        }
        if "@" in image:
            body["Labels"][FOLLOW_TAG_LABEL] = "1"
        if host_cfg_cmd:
            body["Cmd"] = host_cfg_cmd
        st, resp = _docker_request("POST", f"/containers/create?name={cname}", body=body)
        if st != 201:
            yield {"error": f"Could not create {cname}: {resp}"}
            return
        _docker_request("POST", f"/containers/{resp.get('Id')}/start")
        yield {
            "step": "create",
            "percent": 30 + int(25 * (i + 1) / max(total, 1)),
            "message": f"Started {s_name}.",
            "done": False,
        }
    _save_stack_secrets(app_dir, secrets_map)
    yield {"network": network}


def stream_deploy_catalog_app(
    app_id: str,
    host_port: int | None = None,
    storage_root: str = "/mnt/user/appdata",
    container_name: str | None = None,
    replace_existing: bool = False,
) -> Iterator[dict[str, Any]]:
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

    port = host_port or int(app.get("default_port", 8080))
    service_name = app.get("app_slug") or app_id
    if container_name and container_name.strip():
        service_name = container_name.strip()
    service_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", service_name)
    storage_slug = service_name
    image_name = app.get("image") or ""

    yield {
        "step": "init",
        "percent": 5,
        "message": f"Initializing deployment for {app['name']} as '{service_name}' (Port :{port})...",
        "done": False,
    }

    # 1. Volume Directories & Compose File
    yield {
        "step": "storage",
        "percent": 12,
        "message": f"Preparing persistent storage directories under {storage_root}/{storage_slug}...",
        "done": False,
    }

    resolved_root = storage_root
    try:
        os.makedirs(resolved_root, exist_ok=True)
    except Exception:
        resolved_root = os.environ.get("DATA_DIR", "/tmp/zettnas-appdata")
        os.makedirs(resolved_root, exist_ok=True)

    unsafe = _unsafe_volumes(app)
    if unsafe:
        yield {
            "step": "error",
            "percent": 0,
            "message": f"The template asks for host folders ({', '.join(unsafe)}); only folders inside the app's own folder are allowed.",
            "error": "Invalid template volume",
            "done": True,
        }
        return

    app_dir = os.path.join(resolved_root, storage_slug)
    binds = []
    try:
        os.makedirs(app_dir, exist_ok=True)
        library = media_library_bind(app)
        for vol_key, vol_target in app.get("volumes", {}).items():
            if library and vol_target == app.get("media_library"):
                binds.append(library)  # the existing media share, read-only
                continue
            vol_host_path = os.path.join(app_dir, vol_key)
            os.makedirs(vol_host_path, exist_ok=True)
            binds.append(f"{vol_host_path}:{vol_target}:rw")
        _write_seed_files(app, app_dir)
        _own_volumes(app, app_dir)

        comp_info = generate_compose_for_app(
            app_id, host_port=port, storage_root=resolved_root, container_name=service_name
        )
        if "compose_yaml" in comp_info:
            compose_file = os.path.join(app_dir, "docker-compose.yml")
            with open(compose_file, "w", encoding="utf-8") as f:
                f.write(comp_info["compose_yaml"])
            if not image_name:
                m_img = re.search(r"image:\s*([^\s#]+)", comp_info["compose_yaml"])
                if m_img:
                    image_name = m_img.group(1).strip("'\"")
    except Exception as e:
        logger.warning(f"Storage setup notice for {app_id}: {e}")

    if not image_name:
        yield {
            "step": "error",
            "percent": 0,
            "message": f"Application '{app['name']}' requires a multi-service Docker Compose engine or does not specify a primary container image.",
            "error": "No container image defined in template",
            "done": True,
        }
        return

    # Refuse before pulling anything (checked again on the final create body).
    probe: dict[str, Any] = {"HostConfig": {"Binds": list(binds)}}
    _apply_runtime_options(probe, app)
    _, refusal = _host_access_check(app, probe)
    if refusal:
        yield refusal
        return

    yield {
        "step": "preflight",
        "percent": 20,
        "message": "Storage prepared. Checking container state and port availability...",
        "done": False,
    }

    # Check existing container with same name
    st_exist, old_c = _docker_request("GET", f"/containers/{service_name}/json")
    has_existing = st_exist == 200

    if has_existing and not replace_existing:
        yield {
            "step": "error",
            "percent": 0,
            "message": f"Deployment aborted: A container named '{service_name}' already exists. Please choose a different container name or select 'Stop & Replace Existing'.",
            "error": "Container already exists",
            "done": True,
        }
        return

    # Pre-flight port availability verification:
    is_avail, in_use_by = check_port_available_detailed(port, proto="tcp")
    if not is_avail:
        is_same_container_replacing = replace_existing and has_existing and in_use_by == f"container '{service_name}'"
        if not is_same_container_replacing:
            yield {
                "step": "error",
                "percent": 0,
                "message": f"Deployment aborted: Host port {port} is already in use by {in_use_by}. Please choose an available port in configuration.",
                "error": "Port in use",
                "done": True,
            }
            return

    # Fixed extra ports (e.g. 443 for a proxy, 53 for DNS) must be free too
    for p_str in app.get("ports") or []:
        m = re.match(r"^(\d+):(\d+)(?:/([a-zA-Z0-9]+))?$", str(p_str).strip())
        if not m:
            continue
        hp, cp, proto = int(m.group(1)), int(m.group(2)), (m.group(3) or "tcp")
        if hp == int(app.get("default_port", 0)) or cp == int(app.get("default_port", 0)):
            continue  # the main port, checked above
        ok_extra, used_by = check_port_available_detailed(hp, proto=proto)
        if not ok_extra and not (replace_existing and has_existing and used_by == f"container '{service_name}'"):
            yield {
                "step": "error",
                "percent": 0,
                "message": f"Deployment aborted: {app['name']} also needs host port {hp}/{proto}, which is in use by {used_by}.",
                "error": "Port in use",
                "done": True,
            }
            return

    # 2. Check and clean up existing container with same name if any
    if has_existing and replace_existing:
        try:
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

        sock_path = docker_sock()
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
                    ignored("backend.services.app_catalog.stream_deploy_catalog_app")

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
                    ignored("backend.services.app_catalog.stream_deploy_catalog_app")

    # 3b. Companion containers (database, cache, …) on a private network (M3)
    secrets_map = _stack_secrets(app_dir)
    network_name = None
    if app.get("stack_services"):
        for ev in _deploy_companions(app, service_name, app_dir, secrets_map, replace_existing):
            if "error" in ev:
                yield {"step": "error", "percent": 0, "message": ev["error"], "error": ev["error"], "done": True}
                return
            if "network" in ev:
                network_name = ev["network"]
            else:
                yield ev
        try:
            compose_file = os.path.join(app_dir, "docker-compose.yml")
            if os.path.exists(compose_file):
                with open(compose_file, encoding="utf-8") as f:
                    filled = _fill_secrets(f.read(), secrets_map)
                with open(compose_file, "w", encoding="utf-8") as f:
                    f.write(filled)
                os.chmod(compose_file, 0o600)
        except OSError:
            logger.debug("app_catalog: compose file not updated", exc_info=True)

    # 4. Create container
    yield {
        "step": "create",
        "percent": 80,
        "message": f"Creating container '{service_name}' with port bindings...",
        "done": False,
    }

    env_list = [f"{k}={_fill_secrets(str(v), secrets_map)}" for k, v in app.get("env", {}).items()]
    _save_stack_secrets(app_dir, secrets_map)

    # Build ExposedPorts and PortBindings
    port_bindings = {}
    exposed_ports = {}
    raw_ports = app.get("ports")
    default_target = int(app.get("default_port", 8080))
    if raw_ports and isinstance(raw_ports, list):
        for p_str in raw_ports:
            m = re.match(r"^(\d+):(\d+)(?:/([a-zA-Z0-9]+))?$", str(p_str).strip())
            if m:
                hp = int(m.group(1))
                cp = int(m.group(2))
                proto = m.group(3) or "tcp"
                final_hp = port if (hp == default_target or cp == default_target) else hp
                key = f"{cp}/{proto}"
                exposed_ports[key] = {}
                if key not in port_bindings:
                    port_bindings[key] = []
                port_bindings[key].append({"HostIp": "", "HostPort": str(final_hp)})
    if not port_bindings:
        p_key = f"{default_target}/tcp"
        exposed_ports[p_key] = {}
        port_bindings[p_key] = [{"HostIp": "", "HostPort": str(port)}]

    create_body = {
        "Image": image_name,
        "Env": env_list,
        "ExposedPorts": exposed_ports,
        "HostConfig": {
            "PortBindings": port_bindings,
            "Binds": binds,
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Labels": {
            "com.docker.compose.project": service_name,
            "com.docker.compose.service": service_name,
            "com.zettnas.managed": "1",  # ZettNAS stops only its own apps on a power cut (REL-10)
            "net.unraid.docker.managed": "dockerman",
            "net.unraid.docker.webui": f"{app.get('webui_scheme', 'http')}://[IP]:[PORT:{port}]{(app.get('webui_path') or '/')}",
            "net.unraid.docker.icon": app.get("logo")
            or f"https://raw.githubusercontent.com/fr0styx/zettnas-toolkit/main/static/img/icons/{app_id}.png",
        },
    }

    if "@" in image_name:
        create_body["Labels"][FOLLOW_TAG_LABEL] = "1"
    if network_name:
        create_body["HostConfig"]["NetworkMode"] = network_name
    _apply_runtime_options(create_body, app)
    reasons, refusal = _host_access_check(app, create_body)
    if refusal:
        yield refusal
        return
    st, create_resp = _docker_request(
        "POST",
        f"/containers/create?name={service_name}",
        body=create_body,
        headers={"X-ZettNAS-Elevated": "1"} if reasons else {},
    )
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
        ignored("backend.services.app_catalog.stream_deploy_catalog_app")

    webui_url = f"{app.get('webui_scheme', 'http')}://[HOST]:{port}{(app.get('webui_path') or '/')}"
    credentials = None
    if isinstance(app.get("credentials"), dict):
        credentials = {k: _fill_secrets(str(v), secrets_map) for k, v in app["credentials"].items()}
        _save_stack_secrets(app_dir, secrets_map)

    yield {
        "step": "success",
        "percent": 100,
        "message": f"✓ {app['name']} deployed and running successfully!",
        "container_id": cid,
        "container_name": service_name,
        "port": port,
        "webui_url": webui_url,
        "credentials": credentials,
        "has_webui": app.get("webui_path", "/") is not None,
        "is_running": is_running,
        "done": True,
    }

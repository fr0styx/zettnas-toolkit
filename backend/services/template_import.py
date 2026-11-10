"""Apps from other systems' templates (RES-8): Unraid (Community Applications XML), CasaOS
(compose with x-casaos) and Umbrel (umbrel-app.yml beside a compose file).

Each becomes one Kiboto app manifest (the sideload format of app_catalog): the image, the web
port, the container's folders (Kiboto picks where they live on the host, so nothing points at
/mnt/user/appdata, /DATA or ${APP_DATA_DIR}), the settings it asks for, a name, a picture and
a description. Imports are marked untested: Kiboto has not reviewed them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405 - DOCTYPE and entities are refused before parsing
from typing import Any

UNRAID = "unraid"
CASAOS = "casaos"
UMBREL = "umbrel"
COMPOSE = "compose"
KIND_NAMES = {UNRAID: "Unraid template", CASAOS: "CasaOS app", UMBREL: "Umbrel app", COMPOSE: "Compose file"}

MAX_BYTES = 512 * 1024
_HOST_VARS = re.compile(r"\$\{?(APP_DATA_DIR|AppID|APP_ID|DATA_DIR|UMBREL_ROOT|APP_DOMAIN|DEVICE_DOMAIN_NAME)\}?")
_IDS = {"PUID": "99", "PGID": "100"}  # Kiboto's owner of app folders (nobody:users), as Unraid uses
_UMBREL_HELPERS = {"app_proxy", "tor_server", "tor"}


class TemplateError(ValueError):
    """Not a template Kiboto can turn into an app."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")[:40] or "app"


def _text(node: ET.Element | None, tag: str) -> str:
    found = node.find(tag) if node is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def _port(value: Any) -> int | None:
    m = re.search(r"\d{2,5}", str(value or ""))
    if not m:
        return None
    n = int(m.group(0))
    return n if 1 <= n <= 65535 else None


def detect(text: str, extra: dict[str, str] | None = None) -> str:
    """Which kind of template the text is."""
    head = (text or "").lstrip()[:4096]
    if head.startswith("<") and "<Container" in head:
        return UNRAID
    if re.search(r"^x-casaos\s*:", text or "", re.M):
        return CASAOS
    if (extra or {}).get("umbrel-app.yml") or re.search(r"^\s*app_proxy\s*:", text or "", re.M):
        return UMBREL
    if re.search(r"^services\s*:", text or "", re.M):
        return COMPOSE
    raise TemplateError("This is not an Unraid template, a CasaOS or Umbrel app, or a compose file.")


# ---- Unraid ----


def from_unraid(text: str) -> dict[str, Any]:
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        raise TemplateError("Templates with a DOCTYPE or entities are not accepted.")
    try:
        root = ET.fromstring(text)  # nosec B314 - see above
    except ET.ParseError as e:
        raise TemplateError(f"The Unraid template is not valid XML: {e}") from e
    if root.tag != "Container":
        inner = root.find(".//Container")
        if inner is None:
            raise TemplateError("The XML holds no Unraid <Container> template.")
        root = inner
    image = _text(root, "Repository")
    if not image:
        raise TemplateError("The Unraid template names no image (Repository).")
    name = _text(root, "Name") or image.split("/")[-1].split(":")[0]
    ports: list[int] = []
    volumes: dict[str, str] = {}
    env: dict[str, str] = {}
    flags: list[str] = []
    for cfg in root.findall("Config"):
        kind = (cfg.get("Type") or "").lower()
        target = (cfg.get("Target") or "").strip()
        value = (cfg.text or cfg.get("Default") or "").strip()
        if kind == "port":
            p = _port(target)
            if p and p not in ports:
                ports.append(p)
        elif kind == "path" and target.startswith("/"):
            volumes[_slug(cfg.get("Name") or target) or f"v{len(volumes)}"] = target
        elif kind == "variable" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target):
            env[target] = _IDS.get(target, value.split("|")[0])
        elif kind == "device" and target:
            flags.append(f"Uses the host device {target}")
    for path, label in (
        (_text(root, "Network").lower() == "host", "Uses host networking"),
        (_text(root, "Privileged").lower() == "true", "Runs privileged"),
    ):
        if path:
            flags.append(label)
    webui = _port(_text(root, "WebUI"))
    default_port = webui or (ports[0] if ports else 8080)
    if default_port not in ports:
        ports.insert(0, default_port)
    category = (_text(root, "Category").split() or ["utilities"])[0].split(":")[0]
    return {
        "name": name,
        "id": _slug(name),
        "image": image,
        "default_port": default_port,
        "ports": ports,
        "volumes": volumes,
        "env": env,
        "logo": _text(root, "Icon"),
        "description": re.sub(r"\s+", " ", re.sub(r"\[/?[a-z]+\]|<[^>]+>", " ", _text(root, "Overview")))[:500],
        "category": category.lower(),
        "flags": flags,
    }


# ---- compose based: CasaOS, Umbrel, plain ----


def _yaml(text: str) -> dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise TemplateError(f"The file is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise TemplateError("The file has no services.")
    return data


def _lang(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("en_us") or value.get("en_US") or value.get("en") or next(iter(value.values()), ""))
    return str(value or "")


def _service_parts(svc: dict[str, Any]) -> tuple[list[int], dict[str, str], dict[str, str], list[str]]:
    ports: list[int] = []
    for p in svc.get("ports") or []:
        if isinstance(p, dict):
            n = _port(p.get("target"))
        else:
            parts = str(p).split("/")[0].split(":")
            n = _port(parts[-1])
        if n and n not in ports:
            ports.append(n)
    volumes: dict[str, str] = {}
    for v in svc.get("volumes") or []:
        target = v.get("target") if isinstance(v, dict) else (str(v).split(":")[1] if ":" in str(v) else "")
        target = str(target or "").split(":")[0]
        if target.startswith("/") and not target.startswith(("/var/run/docker.sock", "/run/docker.sock")):
            volumes[_slug(target.strip("/").replace("/", "_")) or f"v{len(volumes)}"] = target
    raw = svc.get("environment") or {}
    pairs = (
        raw.items() if isinstance(raw, dict) else (str(e).split("=", 1) if "=" in str(e) else (str(e), "") for e in raw)
    )
    env = {}
    for k, val in pairs:
        key = str(k).strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            env[key] = _IDS.get(key, _HOST_VARS.sub("", "" if val is None else str(val)))
    flags = []
    if svc.get("privileged"):
        flags.append("Runs privileged")
    if str(svc.get("network_mode") or "") == "host":
        flags.append("Uses host networking")
    if any("docker.sock" in str(v) for v in svc.get("volumes") or []):
        flags.append("Asks for the Docker socket (left out)")
    for d in svc.get("devices") or []:
        flags.append(f"Uses the host device {str(d).split(':')[0]}")
    return ports, volumes, env, flags


def _main_service(services: dict[str, Any], preferred: str = "") -> tuple[str, dict[str, Any]]:
    if not isinstance(services, dict):
        raise TemplateError("The file has no service with an image.")
    usable = {k: v for k, v in services.items() if isinstance(v, dict) and v.get("image") and k not in _UMBREL_HELPERS}
    if not usable:
        raise TemplateError("The file has no service with an image.")
    if preferred in usable:
        return preferred, usable[preferred]
    with_ports = [k for k, v in usable.items() if v.get("ports")]
    key = with_ports[0] if with_ports else next(iter(usable))
    return key, usable[key]


def _manifest(name: str, svc: dict[str, Any], port: int | None, **extra: Any) -> dict[str, Any]:
    ports, volumes, env, flags = _service_parts(svc)
    default_port = port or (ports[0] if ports else 8080)
    if default_port not in ports:
        ports.insert(0, default_port)
    return {
        "name": name,
        "id": _slug(name),
        "image": str(svc.get("image")),
        "default_port": default_port,
        "ports": ports,
        "volumes": volumes,
        "env": env,
        "flags": flags + list(extra.pop("flags", [])),
        **extra,
    }


def from_casaos(text: str) -> dict[str, Any]:
    data = _yaml(text)
    meta = data.get("x-casaos") or {}
    key, svc = _main_service(data.get("services") or {}, str(meta.get("main") or ""))
    name = _lang(meta.get("title")) or str(data.get("name") or key)
    others = [k for k in (data.get("services") or {}) if k != key]
    return _manifest(
        name,
        svc,
        _port(meta.get("port_map")),
        logo=str(meta.get("icon") or ""),
        description=(_lang(meta.get("tagline")) or _lang(meta.get("description")))[:500],
        category=str(meta.get("category") or "utilities").lower(),
        flags=[f"Also needs {', '.join(others)}: only {key} is imported"] if others else [],
    )


def from_umbrel(text: str, app_yml: str = "") -> dict[str, Any]:
    data = _yaml(text)
    meta = _yaml(app_yml) if app_yml.strip() else {}
    services = data.get("services") or {}
    proxy = services.get("app_proxy") or {}
    proxy_env = proxy.get("environment") or {}
    if isinstance(proxy_env, list):
        proxy_env = dict(str(e).split("=", 1) for e in proxy_env if "=" in str(e))
    host = str(proxy_env.get("APP_HOST") or "")
    preferred = host.split("_")[-2] if host.count("_") >= 2 else ""
    key, svc = _main_service(services, preferred)
    others = [k for k in services if k != key and k not in _UMBREL_HELPERS]
    return _manifest(
        str(meta.get("name") or key),
        svc,
        _port(proxy_env.get("APP_PORT")) or _port(meta.get("port")),
        logo=str(meta.get("icon") or ""),
        description=str(meta.get("tagline") or meta.get("description") or "")[:500],
        category=str(meta.get("category") or "utilities").lower(),
        flags=[f"Also needs {', '.join(others)}: only {key} is imported"] if others else [],
    )


def from_compose(text: str) -> dict[str, Any]:
    data = _yaml(text)
    key, svc = _main_service(data.get("services") or {})
    others = [k for k in (data.get("services") or {}) if k != key]
    return _manifest(
        str(data.get("name") or key),
        svc,
        None,
        flags=[f"Also needs {', '.join(others)}: only {key} is imported"] if others else [],
    )


def convert(text: str, extra: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
    """The kind of template and the Kiboto manifest made from it."""
    if len((text or "").encode("utf-8")) > MAX_BYTES:
        raise TemplateError("The template is too big.")
    kind = detect(text, extra)
    if kind == UNRAID:
        manifest = from_unraid(text)
    elif kind == CASAOS:
        manifest = from_casaos(text)
    elif kind == UMBREL:
        manifest = from_umbrel(text, (extra or {}).get("umbrel-app.yml", ""))
    else:
        manifest = from_compose(text)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}", manifest["image"]):
        raise TemplateError("The image name in the template is not valid.")
    return kind, manifest


_GITHUB_TREE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/tree/([\w.-]+)/(.+?)/?$")


def is_store_folder(url: str) -> bool:
    """A GitHub folder (…/tree/<branch>/<app>), as Umbrel's and CasaOS's app stores have."""
    return bool(_GITHUB_TREE.match((url or "").strip()))


def is_foreign(text: str) -> bool:
    """An Unraid template or a CasaOS or Umbrel app (a plain compose file is not)."""
    try:
        return detect(text) in (UNRAID, CASAOS, UMBREL)
    except TemplateError:
        return False


def fetch(url: str) -> tuple[str, dict[str, str]]:
    """Downloads a template. A GitHub folder of an Umbrel or CasaOS app store is read as its
    docker-compose.yml (and umbrel-app.yml when there is one)."""
    from backend.services.safe_fetch import safe_fetch

    def get(u: str, required: bool = True) -> str:
        status, _h, body = safe_fetch(u, context="public", headers={"User-Agent": "Kiboto"}, timeout=15)
        if status != 200:
            if required:
                raise TemplateError(f"Could not download {u} (HTTP {status}).")
            return ""
        if len(body) > MAX_BYTES:
            raise TemplateError("The template is too big.")
        return body.decode("utf-8", errors="replace")

    u = (url or "").strip()
    if not u.startswith("https://"):
        raise TemplateError("Use an https:// address.")
    m = _GITHUB_TREE.match(u)
    if m:
        owner, repo, ref, path = m.groups()
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
        app_yml = get(f"{raw}/umbrel-app.yml", required=False)
        return get(f"{raw}/docker-compose.yml"), ({"umbrel-app.yml": app_yml} if app_yml else {})
    return get(u), {}

"""
ZettNAS Toolkit - Docker Container Update Detection & Management Subsystem
Provides zero-bandwidth remote image update checks via Docker distribution API,
individual container updates, and batch 'Update All' functionality with automated rollback.
100% OS-agnostic and hardware-agnostic.
"""

import base64
import hashlib
import json
import os
import socket
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json
from backend.services.container_mutator import _docker_request, pull_container_image, recreate_container

# Container update policy configuration persistence
DOCKER_POLICIES_FILE = os.path.join(DATA_DIR, "docker_update_policies.json")
_policies_lock = threading.Lock()


def get_container_update_policies() -> dict[str, str]:
    """Returns the map of container name/id to policy ('notify', 'auto', 'off')."""
    with _policies_lock:
        try:
            if os.path.exists(DOCKER_POLICIES_FILE):
                with open(DOCKER_POLICIES_FILE, encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[Docker Updates] Error reading update policies: {e}")
        return {}


def get_container_update_policy(name_or_id: str) -> str:
    """Returns the update policy for a container, defaulting to 'notify'."""
    policies = get_container_update_policies()
    return policies.get(name_or_id, policies.get("default", "notify"))


def set_container_update_policy(name_or_id: str, policy: str) -> dict[str, str]:
    """Sets the update policy for a container ('notify', 'auto', 'off')."""
    clean_policy = (policy or "notify").lower().strip()
    if clean_policy not in ("notify", "auto", "off"):
        raise ValueError("Invalid update policy. Must be 'notify', 'auto', or 'off'.")
    with _policies_lock:
        policies = {}
        try:
            if os.path.exists(DOCKER_POLICIES_FILE):
                with open(DOCKER_POLICIES_FILE, encoding="utf-8") as f:
                    policies = json.load(f)
        except Exception:
            policies = {}
        policies[name_or_id] = clean_policy
        try:
            atomic_write_json(DOCKER_POLICIES_FILE, policies, indent=2)
        except Exception as e:
            logger.error(f"[Docker Updates] Failed to save policies: {e}")
        return policies


# In-memory cache for update status
_update_cache: dict[str, Any] = {
    "checked_at": 0,
    "total_containers": 0,
    "updates_available_count": 0,
    "containers": {},
}
_update_lock = threading.Lock()
CACHE_TTL_SECS = 300  # 5 minutes


def load_docker_host_credentials() -> dict[str, Any]:
    """
    Parses Docker host configuration credentials from standard paths:
    1. DOCKER_CONFIG_JSON environment variable
    2. ~/.docker/config.json
    3. /root/.docker/config.json
    4. /host/root/.docker/config.json
    5. DATA_DIR/docker_config.json
    Returns the parsed 'auths' dictionary.
    """
    candidates = [
        os.environ.get("DOCKER_CONFIG_JSON"),
        os.path.expanduser("~/.docker/config.json"),
        "/root/.docker/config.json",
        "/host/root/.docker/config.json",
        os.path.join(DATA_DIR, "docker_config.json"),
    ]

    for p in candidates:
        if p and os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        auths = data.get("auths", {})
                        if isinstance(auths, dict) and auths:
                            return auths
            except Exception as e:
                logger.debug(f"[Docker Updates] Error reading docker config at {p}: {e}")
    return {}


def extract_registry_from_image(img: str) -> tuple[str, str, str]:
    """
    Parses an image string into (registry, repository, tag).
    Examples:
    - ghcr.io/org/repo:1.0 -> ('ghcr.io', 'org/repo', '1.0')
    - harbor.internal:8443/library/app:latest -> ('harbor.internal:8443', 'library/app', 'latest')
    - library/ubuntu:22.04 -> ('docker.io', 'library/ubuntu', '22.04')
    - nginx:alpine -> ('docker.io', 'library/nginx', 'alpine')
    """
    img_clean = img.strip()
    tag = "latest"
    if ":" in img_clean and not img_clean.endswith(":"):
        img_no_tag, tag = img_clean.rsplit(":", 1)
        if "/" in tag:
            img_no_tag = img_clean
            tag = "latest"
    else:
        img_no_tag = img_clean

    parts = img_no_tag.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        repo = parts[1]
    else:
        registry = "docker.io"
        repo = img_no_tag if "/" in img_no_tag else f"library/{img_no_tag}"

    return registry, repo, tag


def get_registry_auth_for_image(img: str) -> dict[str, Any] | None:
    """
    Finds matching authentication configuration from Docker host credentials for the specified image.
    """
    registry, _, _ = extract_registry_from_image(img)
    auths = load_docker_host_credentials()
    if not auths:
        return None

    # Exact or normalized matching
    candidate_keys = [
        registry,
        f"https://{registry}",
        f"https://{registry}/v1/",
        f"https://{registry}/v2/",
        f"http://{registry}",
        f"http://{registry}/v1/",
    ]
    if registry in ("docker.io", "index.docker.io"):
        candidate_keys.extend(["https://index.docker.io/v1/", "index.docker.io", "docker.io"])

    for k in candidate_keys:
        if k in auths:
            val = auths[k]
            if isinstance(val, dict):
                entry = dict(val)
                entry.setdefault("serveraddress", k)
                return entry

    return None


def get_registry_auth_header(img: str) -> dict[str, str]:
    """
    Generates the X-Registry-Auth base64 JSON header required by Docker Engine API
    for private repository queries.
    """
    auth_entry = get_registry_auth_for_image(img)
    if not auth_entry:
        return {}
    try:
        raw_json = json.dumps(auth_entry).encode("utf-8")
        b64 = base64.b64encode(raw_json).decode("ascii")
        return {"X-Registry-Auth": b64}
    except Exception as e:
        logger.warning(f"[Docker Updates] Failed to encode registry auth header: {e}")
        return {}


def query_remote_registry_v2_manifest(img: str, timeout: float = 10.0) -> str | None:
    """
    Queries the remote OCI / Registry v2 manifest directly over HTTPS with Bearer or Basic authentication.
    Returns the image digest (e.g. 'sha256:...'), or None if unreadable.
    """
    registry, repo, tag = extract_registry_from_image(img)
    host = "registry-1.docker.io" if registry in ("docker.io", "index.docker.io") else registry
    url = f"https://{host}/v2/{repo}/manifests/{tag}"

    req = urllib.request.Request(url, method="GET")
    req.add_header(
        "Accept",
        "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json",
    )

    auth = get_registry_auth_for_image(img)
    if auth:
        if "auth" in auth:
            req.add_header("Authorization", f"Basic {auth['auth']}")
        elif "username" in auth and "password" in auth:
            token = base64.b64encode(f"{auth['username']}:{auth['password']}".encode()).decode("ascii")
            req.add_header("Authorization", f"Basic {token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            digest = resp.headers.get("Docker-Content-Digest")
            if digest:
                return digest
            body = resp.read()
            return f"sha256:{hashlib.sha256(body).hexdigest()}"
    except Exception as e:
        logger.debug(f"[Docker Updates] Direct registry v2 query failed for {img}: {e}")
        return None


def _check_container_image_update(c: dict) -> dict[str, Any]:
    """
    Checks if a newer image exists on the remote registry for a single container.
    Queries GET /distribution/{image}/json over the Docker socket with authenticated
    headers from host Docker config credentials, falling back to direct registry v2 query.
    """
    names = c.get("Names", ["unknown"])
    name = names[0].lstrip("/") if names else "unknown"
    cid = c.get("Id", "")[:12]
    img = c.get("Image", "")

    policy = get_container_update_policy(name)
    res: dict[str, Any] = {
        "id": cid,
        "name": name,
        "image": img,
        "has_update": False,
        "status": "up_to_date",
        "update_policy": policy,
        "remote_digest": None,
        "local_digest": None,
        "error": None,
    }

    if not img:
        res["status"] = "unknown"
        return res

    if policy == "off":
        res["status"] = "policy_off"
        return res

    # Pinned digests (e.g. image@sha256:...) cannot be auto-checked against a tag
    if "@sha256:" in img:
        res["status"] = "pinned"
        return res

    try:
        auth_headers = get_registry_auth_header(img)

        # 1. Query remote descriptor digest from registry via Docker Engine daemon with X-Registry-Auth
        st, dist = _docker_request(
            "GET",
            f"/distribution/{img}/json",
            timeout=6.0,
            headers=auth_headers if auth_headers else None,
        )
        remote_digest = None
        if st == 200 and isinstance(dist, dict):
            desc = dist.get("Descriptor", {})
            remote_digest = desc.get("digest")

        # Fallback to direct registry v2 query if Docker daemon did not return digest
        if not remote_digest and (st in (401, 403, 404, 500) or st != 200):
            remote_digest = query_remote_registry_v2_manifest(img)

        if remote_digest:
            res["remote_digest"] = remote_digest

            # 2. Query local image details to check RepoDigests
            st2, img_data = _docker_request("GET", f"/images/{img}/json", timeout=6.0)
            repo_digests = img_data.get("RepoDigests", []) if st2 == 200 and isinstance(img_data, dict) else []
            res["local_digest"] = repo_digests[0] if repo_digests else None

            # 3. If remote digest is known and none of local RepoDigests contain it, update is ready!
            if not any(remote_digest in rd for rd in repo_digests):
                res["has_update"] = True
                res["status"] = "update_available"
            else:
                res["has_update"] = False
                res["status"] = "up_to_date"
        elif st == 401 or st == 403:
            res["status"] = "auth_required"
            if auth_headers:
                res["error"] = "Private registry authentication rejected"
        elif st == 404:
            res["status"] = "not_found"
        else:
            res["status"] = "unknown"
    except Exception as exc:
        res["status"] = "error"
        res["error"] = str(exc)

    return res


def get_cached_update_status() -> dict[str, Any]:
    """Returns the current cached update status without making remote calls."""
    with _update_lock:
        return dict(_update_cache)


def check_all_container_updates(force: bool = False) -> dict[str, Any]:
    """
    Checks all containers concurrently for remote image updates.
    Caches the results to prevent repeated registry hits.
    """
    global _update_cache
    now = time.time()

    with _update_lock:
        if not force and _update_cache["checked_at"] > 0 and (now - _update_cache["checked_at"] < CACHE_TTL_SECS):
            return dict(_update_cache)

    try:
        status, containers = _docker_request("GET", "/containers/json?all=1", timeout=10.0)
        if status != 200 or not isinstance(containers, list):
            return dict(_update_cache)

        # Check containers concurrently with up to 8 threads
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(_check_container_image_update, containers))

        container_map: dict[str, Any] = {}
        updates_count = 0
        for r in results:
            if r.get("has_update") and r.get("update_policy") == "auto":
                cname = r.get("name")
                if cname and cname not in ("zettnas-toolkit", "zettnas"):
                    try:
                        update_single_container(cname)
                        r["has_update"] = False
                        r["status"] = "auto_updated"
                    except Exception as e:
                        logger.error(f"[Docker Updates] Auto-update failed for '{cname}': {e}")

            container_map[r["name"]] = r
            if r["id"]:
                container_map[r["id"]] = r
            if r.get("has_update"):
                updates_count += 1

        with _update_lock:
            _update_cache = {
                "checked_at": int(now),
                "total_containers": len(containers),
                "updates_available_count": updates_count,
                "containers": container_map,
            }
            return dict(_update_cache)

    except Exception as exc:
        logger.error(f"[Docker Updates] Error checking container updates: {exc}")
        return dict(_update_cache)


def update_single_container(cid: str) -> dict[str, Any]:
    """
    Pulls the latest image for a container and recreates it with automated rollback.
    """
    from backend.services.compose_synthesizer import fetch_container_raw_inspect

    inspect_data = fetch_container_raw_inspect(cid)
    if not inspect_data:
        raise ValueError(f"Container '{cid}' not found.")

    orig_name = inspect_data.get("Name", "").lstrip("/")
    self_hostname = socket.gethostname()
    if (self_hostname and cid.startswith(self_hostname)) or orig_name in ("zettnas-toolkit", "zettnas"):
        raise ValueError(
            "Cannot update the active ZettNAS Toolkit container from within the app. "
            "Please update via Docker Compose or host CLI."
        )

    img = inspect_data.get("Config", {}).get("Image", "")
    if not img:
        raise ValueError(f"No image configured for container '{orig_name}'.")

    logger.info(f"[Docker Updates] Pulling newest image for '{orig_name}' ({img})...")
    pull_container_image(img, timeout=240.0)

    logger.info(f"[Docker Updates] Recreating container '{orig_name}' with new image layers...")
    res = recreate_container(cid, image=img, pull_image=False, keep_backup=False)

    # Invalidate / update cache for this container
    with _update_lock:
        if orig_name in _update_cache.get("containers", {}):
            _update_cache["containers"][orig_name]["has_update"] = False
            _update_cache["containers"][orig_name]["status"] = "up_to_date"
            _update_cache["updates_available_count"] = max(0, _update_cache.get("updates_available_count", 1) - 1)

    return res


def update_all_containers() -> dict[str, Any]:
    """
    Applies updates to all containers that have an update available.
    Skips the toolkit container itself to prevent host disconnection.
    """
    check_status = check_all_container_updates(force=True)
    containers = check_status.get("containers", {})

    # Deduplicate by container name
    unique_candidates = {}
    for entry in containers.values():
        name = entry.get("name")
        if name and entry.get("has_update"):
            unique_candidates[name] = entry

    updated = []
    failed = []
    skipped = []

    for name, _cinfo in unique_candidates.items():
        if name in ("zettnas-toolkit", "zettnas"):
            skipped.append({"name": name, "reason": "Self-recreation protected"})
            continue

        try:
            res = update_single_container(name)
            updated.append({"name": name, "new_id": res.get("new_id")})
        except Exception as exc:
            logger.error(f"[Docker Updates] Failed to update '{name}': {exc}")
            failed.append({"name": name, "error": str(exc)})

    # Refresh update cache
    check_all_container_updates(force=True)

    return {
        "status": "completed",
        "updated": updated,
        "failed": failed,
        "skipped": skipped,
        "total_updated": len(updated),
    }

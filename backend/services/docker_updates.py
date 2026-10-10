"""
ZettNAS Toolkit - Docker Container Update Detection & Management Subsystem
Provides zero-bandwidth remote image update checks via Docker distribution API,
individual container updates, and batch 'Update All' functionality with automated rollback.
100% OS-agnostic and hardware-agnostic.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import socket
import threading
import time
from typing import Any, Dict, List, Optional

from backend.config import logger
from backend.services.container_mutator import _docker_request, pull_container_image, recreate_container

# In-memory cache for update status
_update_cache: Dict[str, Any] = {
    "checked_at": 0,
    "total_containers": 0,
    "updates_available_count": 0,
    "containers": {},
}
_update_lock = threading.Lock()
CACHE_TTL_SECS = 300  # 5 minutes


def _check_container_image_update(c: dict) -> Dict[str, Any]:
    """
    Checks if a newer image exists on the remote registry for a single container.
    Queries GET /distribution/{image}/json over the Docker socket without downloading layers.
    """
    names = c.get("Names", ["unknown"])
    name = names[0].lstrip("/") if names else "unknown"
    cid = c.get("Id", "")[:12]
    img = c.get("Image", "")

    res: Dict[str, Any] = {
        "id": cid,
        "name": name,
        "image": img,
        "has_update": False,
        "status": "up_to_date",
        "remote_digest": None,
        "local_digest": None,
        "error": None,
    }

    if not img:
        res["status"] = "unknown"
        return res

    # Pinned digests (e.g. image@sha256:...) cannot be auto-checked against a tag
    if "@sha256:" in img:
        res["status"] = "pinned"
        return res

    try:
        # 1. Query remote descriptor digest from registry via Docker Engine daemon
        st, dist = _docker_request("GET", f"/distribution/{img}/json", timeout=6.0)
        if st == 200:
            desc = dist.get("Descriptor", {})
            remote_digest = desc.get("digest")
            res["remote_digest"] = remote_digest

            # 2. Query local image details to check RepoDigests
            st2, img_data = _docker_request("GET", f"/images/{img}/json", timeout=6.0)
            repo_digests = img_data.get("RepoDigests", []) if st2 == 200 else []
            res["local_digest"] = repo_digests[0] if repo_digests else None

            # 3. If remote digest is known and none of local RepoDigests contain it, update is ready!
            if remote_digest and not any(remote_digest in rd for rd in repo_digests):
                res["has_update"] = True
                res["status"] = "update_available"
            else:
                res["has_update"] = False
                res["status"] = "up_to_date"
        elif st == 401 or st == 403:
            res["status"] = "auth_required"
        elif st == 404:
            res["status"] = "not_found"
        else:
            res["status"] = "unknown"
    except Exception as exc:
        res["status"] = "error"
        res["error"] = str(exc)

    return res


def get_cached_update_status() -> Dict[str, Any]:
    """Returns the current cached update status without making remote calls."""
    with _update_lock:
        return dict(_update_cache)


def check_all_container_updates(force: bool = False) -> Dict[str, Any]:
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

        container_map: Dict[str, Any] = {}
        updates_count = 0
        for r in results:
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


def update_single_container(cid: str) -> Dict[str, Any]:
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


def update_all_containers() -> Dict[str, Any]:
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

    for name, cinfo in unique_candidates.items():
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

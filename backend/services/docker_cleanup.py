"""
ZettNAS Toolkit - Docker Container Destruction & System Cleanup Subsystem
Supports:
1. Deletion / Destruction of containers with optional volume & image removal.
2. Self-deletion protection (blocks destroying zettnas-toolkit itself).
3. Docker system df disk usage analysis.
4. Docker system prune: unused images, dangling volumes, stopped containers, build cache, networks.
100% OS-agnostic and hardware-agnostic via official Docker Engine API.
"""

import json
import re
import socket
import urllib.parse
from typing import Any, Dict, List

from backend.config import logger
from backend.hardware import docker_stats
from backend.services.container_mutator import _docker_request
from backend.state import add_event


def _format_bytes(num_bytes: int) -> str:
    """Formats bytes into human readable format (KB, MB, GB)."""
    if num_bytes < 0:
        return "0 B"
    num_f = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_f) < 1024.0:
            return f"{num_f:.1f} {unit}" if unit != "B" else f"{int(num_f)} B"
        num_f /= 1024.0
    return f"{num_f:.1f} PB"


def is_self_container(cid: str, name: str = "") -> bool:
    """
    Checks if the container is the zettnas-toolkit management container itself
    to prevent accidental self-destruction.
    """
    self_hostname = socket.gethostname()
    clean_name = (name or "").lstrip("/").lower()
    if clean_name in ("zettnas-toolkit", "zettnas", "zettnas_toolkit"):
        return True
    if self_hostname and cid and (cid.startswith(self_hostname) or self_hostname.startswith(cid)):
        return True
    return False


def destroy_container(
    container_id: str,
    force: bool = False,
    remove_volumes: bool = True,
    remove_image: bool = False,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """
    Destroys/deletes a Docker container via official Docker API:
    DELETE /containers/{id}?v={remove_volumes}&force={force}

    Optionally removes the container's associated image after deletion.
    Guarantees self-deletion protection for zettnas-toolkit.
    """
    # Sanitize container ID
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise ValueError("Invalid container ID or name.")

    # 1. Inspect container to get its name, state, and image reference
    status, inspect_data = _docker_request("GET", f"/containers/{container_id}/json", timeout=timeout)
    if status != 200:
        err_msg = inspect_data.get("message") or f"Container '{container_id}' not found (HTTP {status})"
        raise ValueError(err_msg)

    cname = inspect_data.get("Name", "").lstrip("/") or container_id[:12]
    full_id = inspect_data.get("Id", container_id)
    image_id = inspect_data.get("Image", "")
    image_tag = inspect_data.get("Config", {}).get("Image", "")

    # 2. Check self-protection
    if is_self_container(full_id, cname):
        raise ValueError("Safety lock: Cannot destroy the zettnas-toolkit container itself.")

    # 3. Delete the container
    v_param = "true" if remove_volumes else "false"
    force_param = "true" if force else "false"
    del_status, del_resp = _docker_request(
        "DELETE",
        f"/containers/{container_id}?v={v_param}&force={force_param}",
        timeout=timeout,
    )

    if del_status not in (200, 204):
        err = del_resp.get("message") or f"HTTP {del_status}"
        if del_status == 409:
            raise RuntimeError(f"Container '{cname}' is running. Please stop it first or enable 'Force' removal.")
        raise RuntimeError(f"Failed to delete container '{cname}': {err}")

    logger.info(f"[Docker Cleanup] Deleted container '{cname}' (ID: {full_id[:12]}, volumes={remove_volumes})")

    # Invalidate cached lists
    docker_stats._CACHED_CONTAINERS = []
    docker_stats._LAST_DOCKER_POLL = 0.0
    with docker_stats._INSPECT_LOCK:
        docker_stats._CONTAINER_INSPECT_CACHE.clear()

    # 4. If remove_image requested, attempt image deletion
    image_deleted = False
    image_error = None
    target_image = image_tag or image_id
    if remove_image and target_image:
        try:
            img_status, img_resp = _docker_request("DELETE", f"/images/{target_image}?force=false", timeout=timeout)
            if img_status == 200:
                image_deleted = True
                logger.info(f"[Docker Cleanup] Successfully deleted image '{target_image}'")
            elif img_status == 409:
                image_error = "Image in use by another container"
                logger.info(f"[Docker Cleanup] Image '{target_image}' still in use by other containers, kept.")
            else:
                image_error = img_resp.get("message") or f"HTTP {img_status}"
        except Exception as e:
            image_error = str(e)
            logger.warning(f"[Docker Cleanup] Could not delete image '{target_image}': {e}")

    add_event("docker", f"Destroyed container '{cname}' ({full_id[:12]})", "warning")

    return {
        "success": True,
        "container_id": full_id[:12],
        "name": cname,
        "removed": True,
        "volumes_removed": remove_volumes,
        "image_removed": image_deleted,
        "image_ref": target_image,
        "image_error": image_error,
        "message": f"Container '{cname}' destroyed successfully.",
    }


def get_docker_system_df(timeout: float = 15.0) -> Dict[str, Any]:
    """
    Returns Docker disk usage statistics from GET /system/df:
    Breakdown of images, containers, local volumes, build cache, and reclaimable space.
    """
    status, df = _docker_request("GET", "/system/df", timeout=timeout)
    if status != 200:
        err = df.get("message") or f"HTTP {status}"
        raise RuntimeError(f"Failed to fetch Docker disk usage: {err}")

    images = df.get("Images") or []
    containers = df.get("Containers") or []
    volumes = df.get("Volumes") or []
    build_cache = df.get("BuildCache") or []

    # Calculate image statistics
    total_images_size = sum(img.get("Size", 0) for img in images)
    unused_images = [img for img in images if img.get("Containers", 0) == 0]
    unused_images_size = sum(img.get("Size", 0) for img in unused_images)

    # Calculate container statistics
    total_containers_size = sum(c.get("SizeRw", 0) for c in containers)
    stopped_containers = [c for c in containers if c.get("State", "").lower() not in ("running", "restarting")]

    # Calculate volume statistics
    total_volumes_size = 0
    unused_volumes_size = 0
    unused_volumes_count = 0
    for v in volumes:
        ud = v.get("UsageData") or {}
        vsize = ud.get("Size", 0)
        total_volumes_size += vsize
        if ud.get("RefCount", 0) <= 0:
            unused_volumes_count += 1
            unused_volumes_size += vsize

    # Calculate build cache
    total_build_cache_size = sum(bc.get("Size", 0) for bc in build_cache)
    reclaimable_build_cache = sum(bc.get("Size", 0) for bc in build_cache if not bc.get("InUse", False))

    total_reclaimable = unused_images_size + unused_volumes_size + reclaimable_build_cache

    return {
        "images": {
            "total_count": len(images),
            "unused_count": len(unused_images),
            "total_size_bytes": total_images_size,
            "total_size_human": _format_bytes(total_images_size),
            "reclaimable_bytes": unused_images_size,
            "reclaimable_human": _format_bytes(unused_images_size),
        },
        "containers": {
            "total_count": len(containers),
            "stopped_count": len(stopped_containers),
            "size_rw_bytes": total_containers_size,
            "size_rw_human": _format_bytes(total_containers_size),
        },
        "volumes": {
            "total_count": len(volumes),
            "unused_count": unused_volumes_count,
            "total_size_bytes": total_volumes_size,
            "total_size_human": _format_bytes(total_volumes_size),
            "reclaimable_bytes": unused_volumes_size,
            "reclaimable_human": _format_bytes(unused_volumes_size),
        },
        "build_cache": {
            "total_size_bytes": total_build_cache_size,
            "total_size_human": _format_bytes(total_build_cache_size),
            "reclaimable_bytes": reclaimable_build_cache,
            "reclaimable_human": _format_bytes(reclaimable_build_cache),
        },
        "total_reclaimable_bytes": total_reclaimable,
        "total_reclaimable_human": _format_bytes(total_reclaimable),
    }


def prune_docker_system(
    prune_containers: bool = True,
    prune_images: bool = True,
    all_images: bool = False,
    prune_volumes: bool = False,
    prune_networks: bool = True,
    prune_build_cache: bool = True,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    Executes selective Docker system prune actions:
    1. POST /containers/prune (removes stopped containers)
    2. POST /images/prune (removes dangling or all unused images)
    3. POST /volumes/prune (removes unused local volumes)
    4. POST /networks/prune (removes unused networks)
    5. POST /build/prune (removes build cache)

    Returns aggregated results with reclaimed space metrics.
    """
    reclaimed_bytes = 0
    containers_deleted: List[str] = []
    images_deleted: List[str] = []
    volumes_deleted: List[str] = []
    networks_deleted: List[str] = []
    build_caches_deleted: int = 0

    # 1. Prune stopped containers
    if prune_containers:
        try:
            status, res = _docker_request("POST", "/containers/prune", timeout=timeout)
            if status == 200:
                c_del = res.get("ContainersDeleted") or []
                containers_deleted.extend(c_del)
                reclaimed_bytes += res.get("SpaceReclaimed", 0)
        except Exception as e:
            logger.warning(f"[Docker Prune] Containers prune error: {e}")

    # 2. Prune images
    if prune_images or all_images:
        try:
            dangling_flag = "false" if all_images else "true"
            filters = urllib.parse.quote(json.dumps({"dangling": [dangling_flag]}))
            status, res = _docker_request("POST", f"/images/prune?filters={filters}", timeout=timeout)
            if status == 200:
                i_del = [
                    item.get("Deleted") or item.get("Untagged") for item in (res.get("ImagesDeleted") or []) if item
                ]
                images_deleted.extend([i for i in i_del if i])
                reclaimed_bytes += res.get("SpaceReclaimed", 0)
            else:
                logger.warning(f"[Docker Prune] Images prune returned HTTP {status}: {res}")
        except Exception as e:
            logger.warning(f"[Docker Prune] Images prune error: {e}")

    # 3. Prune volumes
    if prune_volumes:
        try:
            status, res = _docker_request("POST", "/volumes/prune", timeout=timeout)
            if status == 200:
                v_del = res.get("VolumesDeleted") or []
                volumes_deleted.extend(v_del)
                reclaimed_bytes += res.get("SpaceReclaimed", 0)
            else:
                logger.warning(f"[Docker Prune] Volumes prune returned HTTP {status}: {res}")
        except Exception as e:
            logger.warning(f"[Docker Prune] Volumes prune error: {e}")

    # 4. Prune networks
    if prune_networks:
        try:
            status, res = _docker_request("POST", "/networks/prune", timeout=timeout)
            if status == 200:
                n_del = res.get("NetworksDeleted") or []
                networks_deleted.extend(n_del)
            else:
                logger.warning(f"[Docker Prune] Networks prune returned HTTP {status}: {res}")
        except Exception as e:
            logger.warning(f"[Docker Prune] Networks prune error: {e}")

    # 5. Prune build cache
    if prune_build_cache:
        try:
            status, res = _docker_request("POST", "/build/prune?all=true", timeout=timeout)
            if status == 200:
                c_del = res.get("CachesDeleted") or []
                build_caches_deleted += len(c_del)
                reclaimed_bytes += res.get("SpaceReclaimed", 0)
            else:
                logger.warning(f"[Docker Prune] Build cache prune returned HTTP {status}: {res}")
        except Exception as e:
            logger.warning(f"[Docker Prune] Build cache prune error: {e}")

    # Invalidate cache
    docker_stats._CACHED_CONTAINERS = []
    docker_stats._LAST_DOCKER_POLL = 0.0
    with docker_stats._INSPECT_LOCK:
        docker_stats._CONTAINER_INSPECT_CACHE.clear()

    space_human = _format_bytes(reclaimed_bytes)
    summary_msg = (
        f"Prune reclaimed {space_human} (Containers: {len(containers_deleted)}, "
        f"Images: {len(images_deleted)}, Volumes: {len(volumes_deleted)})."
    )
    logger.info(f"[Docker Prune] {summary_msg}")
    add_event("docker", summary_msg, "info")

    return {
        "success": True,
        "space_reclaimed_bytes": reclaimed_bytes,
        "space_reclaimed_human": space_human,
        "containers_deleted_count": len(containers_deleted),
        "containers_deleted": containers_deleted,
        "images_deleted_count": len(images_deleted),
        "images_deleted": images_deleted,
        "volumes_deleted_count": len(volumes_deleted),
        "volumes_deleted": volumes_deleted,
        "networks_deleted_count": len(networks_deleted),
        "networks_deleted": networks_deleted,
        "build_caches_deleted_count": build_caches_deleted,
        "message": summary_msg,
    }

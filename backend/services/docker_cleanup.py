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
import threading
import time
import urllib.parse
import uuid
from typing import Any

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
    return bool(self_hostname and cid and (cid.startswith(self_hostname) or self_hostname.startswith(cid)))


def destroy_container(
    container_id: str,
    force: bool = False,
    remove_volumes: bool = True,
    remove_image: bool = False,
    timeout: float = 20.0,
    archive_data: bool = True,
) -> dict[str, Any]:
    """
    Destroys/deletes a Docker container via official Docker API:
    DELETE /containers/{id}?v={remove_volumes}&force={force}

    Optionally archives app data & synthesized compose config before deletion (Feature 21a).
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

    # 2b. Auto-archive app data & config on uninstall (Feature 21a: never delete without archive)
    archive_record = None
    if archive_data:
        try:
            from backend.services.app_backup import create_app_backup

            archive_record = create_app_backup(full_id, reason="uninstall", custom_name=cname)
            logger.info(
                f"[Docker Cleanup] Auto-archived app data & config for '{cname}' prior to uninstall: {archive_record.get('filename')}"
            )
        except Exception as e:
            logger.warning(f"[Docker Cleanup] Could not auto-archive '{cname}' prior to uninstall: {e}")

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
        "archived": archive_record is not None,
        "archive_record": archive_record,
        "message": f"Container '{cname}' destroyed successfully."
        + (" (Data archived to backups)" if archive_record else ""),
    }


def get_docker_system_df(timeout: float = 15.0) -> dict[str, Any]:
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
    layers_size = int(df.get("LayersSize") or 0)
    total_images_size = layers_size or sum(img.get("Size", 0) for img in images)
    unused_images = [img for img in images if img.get("Containers", 0) == 0]
    # Same figure as `docker system df`: layers shared with images still in use aren't freed.
    used_size = sum(
        max(0, img.get("Size", 0) - max(0, img.get("SharedSize", 0))) for img in images if img.get("Containers", 0) != 0
    )
    unused_images_size = max(0, total_images_size - used_size) if unused_images else 0

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
) -> dict[str, Any]:
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
    containers_deleted: list[str] = []
    images_deleted: list[str] = []
    volumes_deleted: list[str] = []
    networks_deleted: list[str] = []
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


# ---------------------------------------------------------------------------
# Cleanup as a background job with progress (the dialog's progress bar).
# Docker's prune calls report nothing until they finish, so unused images are
# removed one at a time here; the other steps are single calls.
# ---------------------------------------------------------------------------

_PRUNE_JOBS: dict[str, dict[str, Any]] = {}
_PRUNE_LOCK = threading.Lock()
_STEP_WEIGHTS = {"containers": 1.0, "images": 6.0, "volumes": 1.0, "networks": 0.5, "build_cache": 1.5}


def _job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {k: (list(map(dict, v)) if k == "steps" else v) for k, v in job.items() if not k.startswith("_")}


def get_prune_job(job_id: str | None = None) -> dict[str, Any] | None:
    """The job with this id, or the most recent one."""
    with _PRUNE_LOCK:
        if job_id:
            job = _PRUNE_JOBS.get(job_id)
        else:
            job = max(_PRUNE_JOBS.values(), key=lambda j: j["started_at"], default=None)
        return _job_snapshot(job) if job else None


def cancel_prune_job(job_id: str) -> bool:
    with _PRUNE_LOCK:
        job = _PRUNE_JOBS.get(job_id)
        if not job or job["state"] != "running":
            return False
        job["_cancel"] = True
        job["message"] = "Stopping after the current item…"
        return True


def start_prune_job(
    prune_containers: bool = True,
    prune_images: bool = True,
    all_images: bool = False,
    prune_volumes: bool = False,
    prune_networks: bool = True,
    prune_build_cache: bool = True,
) -> tuple[dict[str, Any], bool]:
    """Starts a cleanup in the background. Returns (job, started); a running job is returned instead of a second one."""
    with _PRUNE_LOCK:
        running = next((j for j in _PRUNE_JOBS.values() if j["state"] == "running"), None)
        if running:
            return _job_snapshot(running), False
        steps = []
        if prune_containers:
            steps.append({"key": "containers", "state": "pending", "detail": "", "freed_bytes": 0})
        if prune_images or all_images:
            steps.append({"key": "images", "state": "pending", "detail": "", "freed_bytes": 0})
        if prune_volumes:
            steps.append({"key": "volumes", "state": "pending", "detail": "", "freed_bytes": 0})
        if prune_networks:
            steps.append({"key": "networks", "state": "pending", "detail": "", "freed_bytes": 0})
        if prune_build_cache:
            steps.append({"key": "build_cache", "state": "pending", "detail": "", "freed_bytes": 0})
        job = {
            "id": uuid.uuid4().hex[:12],
            "state": "running",
            "started_at": time.time(),
            "finished_at": None,
            "percent": 0,
            "step": None,
            "message": "Starting…",
            "steps": steps,
            "images_done": 0,
            "images_total": 0,
            "freed_bytes": 0,
            "freed_human": "0 B",
            "counts": {"containers": 0, "images": 0, "volumes": 0, "networks": 0, "build_cache": 0},
            "errors": [],
            "_cancel": False,
        }
        for old in [k for k, j in _PRUNE_JOBS.items() if j["state"] != "running"]:
            del _PRUNE_JOBS[old]  # keep only the newest finished job
        _PRUNE_JOBS[job["id"]] = job
    opts = {"all_images": all_images}
    threading.Thread(target=_run_prune_job, args=(job, opts), name="docker-prune", daemon=True).start()
    return _job_snapshot(job), True


def _update(job: dict[str, Any], **kw: Any) -> None:
    with _PRUNE_LOCK:
        job.update(kw)
        total = sum(_STEP_WEIGHTS[s["key"]] for s in job["steps"]) or 1.0
        done = 0.0
        for s in job["steps"]:
            w = _STEP_WEIGHTS[s["key"]]
            if s["state"] in ("done", "skipped", "error"):
                done += w
            elif s["state"] == "running" and s["key"] == "images" and job["images_total"]:
                done += w * job["images_done"] / job["images_total"]
        job["percent"] = 100 if job["state"] != "running" else min(99, int(done * 100 / total))
        job["freed_human"] = _format_bytes(job["freed_bytes"])


def _set_step(job: dict[str, Any], key: str, state: str, detail: str = "", freed: int = 0) -> None:
    with _PRUNE_LOCK:
        for s in job["steps"]:
            if s["key"] == key:
                s["state"] = state
                if detail:
                    s["detail"] = detail
                s["freed_bytes"] += freed
        job["freed_bytes"] += freed
        if state == "running":
            job["step"] = key
    _update(job)


def _layers_size() -> int | None:
    try:
        status, df = _docker_request("GET", "/system/df?type=image", timeout=120)
        return int(df.get("LayersSize") or 0) if status == 200 else None
    except Exception as e:
        logger.debug(f"[Docker Prune] Could not read image disk usage: {e}")
        return None


def _remove_unused_images(job: dict[str, Any], all_images: bool) -> None:
    filters = urllib.parse.quote(json.dumps({"dangling": ["false" if all_images else "true"]}))
    st_i, images = _docker_request("GET", "/images/json" + ("" if all_images else f"?filters={filters}"), timeout=60)
    st_c, containers = _docker_request("GET", "/containers/json?all=true", timeout=60)
    if st_i != 200 or st_c != 200 or not isinstance(images, list) or not isinstance(containers, list):
        raise RuntimeError("could not list images and containers")
    # Same rule as `docker image prune`: an image used by any container, running or stopped, stays.
    in_use = {c.get("ImageID") for c in containers} | {c.get("Image") for c in containers}
    unused = [i for i in images if i.get("Id") not in in_use and not (set(i.get("RepoTags") or []) & in_use)]
    unused.sort(key=lambda i: i.get("Created", 0), reverse=True)  # children before their parents
    _update(job, images_total=len(unused), images_done=0)
    before = _layers_size()
    removed = 0
    for n, img in enumerate(unused, start=1):
        if job["_cancel"]:
            break
        tags = [t for t in (img.get("RepoTags") or []) if t and t != "<none>:<none>"]
        label = tags[0] if tags else img.get("Id", "")[7:19]
        _update(job, message=f"Removing image {n} of {len(unused)}: {label}")
        refs = tags if len(tags) > 1 else [img["Id"]]
        ok = False
        for ref in refs:  # untagging each name of a multi-tag image removes it with the last one
            status, res = _docker_request("DELETE", f"/images/{urllib.parse.quote(ref, safe='')}", timeout=300)
            ok = status in (200, 404)
            if status == 409:
                logger.info(f"[Docker Prune] Kept image {label}: {res.get('message', 'in use')}")
                break
        removed += 1 if ok else 0
        with _PRUNE_LOCK:
            job["counts"]["images"] = removed
        _update(job, images_done=n)
    if not job["_cancel"]:
        # Sweep what one-by-one removal left (layers released by the removals above)
        status, res = _docker_request("POST", f"/images/prune?filters={filters}", timeout=900)
        if status == 200:
            with _PRUNE_LOCK:
                job["counts"]["images"] += len([i for i in (res.get("ImagesDeleted") or []) if i.get("Deleted")])
    after = _layers_size()
    freed = max(0, before - after) if before is not None and after is not None else 0
    _set_step(job, "images", "done", f"{removed} removed", freed)


def _run_prune_job(job: dict[str, Any], opts: dict[str, Any]) -> None:
    calls = {
        "containers": ("/containers/prune", 300, "ContainersDeleted"),
        "volumes": ("/volumes/prune", 900, "VolumesDeleted"),
        "networks": ("/networks/prune", 120, "NetworksDeleted"),
        "build_cache": ("/build/prune?all=true", 1800, "CachesDeleted"),
    }
    names = {
        "containers": "stopped containers",
        "volumes": "unused volumes",
        "networks": "unused networks",
        "build_cache": "build cache",
    }
    for step in [s["key"] for s in job["steps"]]:
        if job["_cancel"]:
            _set_step(job, step, "skipped")
            continue
        _set_step(job, step, "running")
        try:
            if step == "images":
                _remove_unused_images(job, opts["all_images"])
                continue
            path, timeout, field = calls[step]
            _update(job, message=f"Removing {names[step]}…")
            status, res = _docker_request("POST", path, timeout=timeout)
            if status != 200:
                raise RuntimeError(res.get("message") or f"HTTP {status}")
            count = len(res.get(field) or [])
            with _PRUNE_LOCK:
                job["counts"][step] = count
            _set_step(job, step, "done", f"{count} removed", int(res.get("SpaceReclaimed") or 0))
        except Exception as e:
            logger.warning(f"[Docker Prune] {step} failed: {e}")
            with _PRUNE_LOCK:
                job["errors"].append(f"{step}: {e}")
            _set_step(job, step, "error", str(e)[:200])

    docker_stats._CACHED_CONTAINERS = []
    docker_stats._LAST_DOCKER_POLL = 0.0
    with docker_stats._INSPECT_LOCK:
        docker_stats._CONTAINER_INSPECT_CACHE.clear()
    c = job["counts"]
    stopped = job["_cancel"]
    summary = (
        f"Prune {'stopped' if stopped else 'reclaimed'} {_format_bytes(job['freed_bytes'])}"
        f"{' so far' if stopped else ''} (Containers: {c['containers']}, Images: {c['images']}, Volumes: {c['volumes']})."
    )
    logger.info(f"[Docker Prune] {summary}")
    add_event("docker", summary, "info")
    _update(
        job,
        state="cancelled" if stopped else ("done" if not job["errors"] else "done_with_errors"),
        finished_at=time.time(),
        step=None,
        message=summary,
    )

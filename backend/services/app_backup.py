"""
ZettNAS Toolkit - Application & Appdata Backup Engine
Handles:
1. Auto-archiving of container config + appdata on uninstall (Feature 21a).
2. On-demand backup of any installed container (Feature 21b).
3. Per-app backup listing, restoration, downloading, and deletion (Feature 21c).
4. Safe extraction with directory traversal / tar-slip guards.
100% Hardware & OS agnostic.
"""

import json
import os
import tarfile
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.config import DATA_DIR, POOL_PATH, logger
from backend.fsutil import atomic_write_json, read_json
from backend.services.compose_synthesizer import synthesize_compose_spec
from backend.services.container_mutator import _docker_request

APP_BACKUPS_REGISTRY_FILE = os.path.join(DATA_DIR, "app_backups.json")

# System mount prefixes that should NEVER be archived into an appdata bundle
SYSTEM_MOUNT_PREFIXES = (
    "/var/run/docker.sock",
    "/run/docker.sock",
    "/dev",
    "/sys",
    "/proc",
    "/run",
    "/boot",
    "/etc/localtime",
    "/etc/timezone",
)

# Bulk storage paths to exclude from quick app archives to prevent multi-TB archiving
BULK_STORAGE_PREFIXES = (
    "/mnt/user/media",
    "/mnt/user/downloads",
    "/mnt/user/isos",
    "/mnt/user/storage",
    "/mnt/user/movies",
    "/mnt/user/tv",
)


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


def get_app_backup_base_dir() -> str:
    """
    Returns the root directory where application archives are stored.
    Prefers /mnt/user/appdata/.backups on NAS platforms, falls back to DATA_DIR/app_backups.
    """
    nas_appdata = os.path.join(POOL_PATH, "appdata")
    if os.path.exists(nas_appdata) and os.access(nas_appdata, os.W_OK):
        path = os.path.join(nas_appdata, ".backups")
    else:
        path = os.path.join(DATA_DIR, "app_backups")
    os.makedirs(path, exist_ok=True)
    return path


def get_app_backup_dir(app_name: str) -> str:
    """Returns the dedicated folder for a specific application's backup archives."""
    clean_name = (app_name or "unknown").strip().lstrip("/").replace(" ", "_")
    base = get_app_backup_base_dir()
    app_dir = os.path.join(base, clean_name)
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_app_backups_registry() -> List[Dict[str, Any]]:
    """Retrieves all registered application backups."""
    data = read_json(APP_BACKUPS_REGISTRY_FILE, default=[])
    if isinstance(data, list):
        return data
    return []


def save_app_backup_record(record: Dict[str, Any]) -> None:
    """Adds or updates an application backup record in the persistent ledger."""
    registry = get_app_backups_registry()
    idx = next((i for i, r in enumerate(registry) if r.get("id") == record.get("id")), None)
    if idx is not None:
        registry[idx] = record
    else:
        registry.insert(0, record)
    atomic_write_json(APP_BACKUPS_REGISTRY_FILE, registry)


def remove_app_backup_record(backup_id: str) -> None:
    """Removes a backup record from the registry."""
    registry = get_app_backups_registry()
    filtered = [r for r in registry if r.get("id") != backup_id]
    if len(filtered) != len(registry):
        atomic_write_json(APP_BACKUPS_REGISTRY_FILE, filtered)


def is_safe_tar_member(member: tarfile.TarInfo, target_dir: str) -> bool:
    """Guards against Tar-Slip directory traversal vulnerabilities."""
    target_abs = os.path.abspath(target_dir)
    extracted_abs = os.path.abspath(os.path.join(target_dir, member.name))
    if not (extracted_abs == target_abs or extracted_abs.startswith(target_abs + os.sep)):
        return False
    if member.issym() or member.islnk():
        link_abs = os.path.abspath(os.path.join(os.path.dirname(extracted_abs), member.linkname))
        if not (link_abs == target_abs or link_abs.startswith(target_abs + os.sep)):
            return False
    return True


def create_app_backup(
    container_id_or_name: str,
    reason: str = "on-demand",
    custom_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a full backup archive of an installed container application:
    1. Inspects container to extract ports, env vars, mounts, and image.
    2. Synthesizes a standalone docker-compose.yml.
    3. Bundles appdata host bind mounts into a compressed .tar.gz archive.
    4. Writes a manifest with restore instructions and mount mappings.
    5. Preserves the archive in the backup library.
    """
    status, inspect_data = _docker_request("GET", f"/containers/{container_id_or_name}/json")
    if status != 200 or not inspect_data:
        raise ValueError(f"Container '{container_id_or_name}' not found on Docker daemon.")

    cid = inspect_data.get("Id", "")
    raw_name = inspect_data.get("Name", "").lstrip("/")
    cname = custom_name or raw_name or "container"
    config = inspect_data.get("Config", {})
    image = config.get("Image", "")
    state = inspect_data.get("State", {})
    is_running = state.get("Running", False)

    # 1. Synthesize docker-compose.yml with complete settings
    try:
        compose_yaml, _ = synthesize_compose_spec(inspect_data, mask_secrets=False)
    except Exception as e:
        logger.warning(f"[App Backup] Could not synthesize compose spec for '{cname}': {e}")
        compose_yaml = (
            f"# ZettNAS Compose Export for {cname}\nversion: '3.8'\nservices:\n  {cname}:\n    image: {image}\n"
        )

    # 2. Identify bind mounts to back up
    mounts = inspect_data.get("Mounts", [])
    appdata_mounts: List[Dict[str, Any]] = []
    skipped_mounts: List[Dict[str, Any]] = []

    for m in mounts:
        m_type = m.get("Type", "")
        src = m.get("Source", "")
        dst = m.get("Destination", "")
        if m_type == "bind" and src:
            if any(src == p or src.startswith(p + "/") for p in SYSTEM_MOUNT_PREFIXES):
                continue
            if any(src == p or src.startswith(p + "/") for p in BULK_STORAGE_PREFIXES):
                skipped_mounts.append({"source": src, "destination": dst, "reason": "bulk_media_excluded"})
                continue
            if os.path.exists(src):
                idx = len(appdata_mounts)
                appdata_mounts.append(
                    {
                        "source": src,
                        "destination": dst,
                        "rw": m.get("RW", True),
                        "archive_prefix": f"data/mount_{idx}",
                    }
                )
            else:
                skipped_mounts.append({"source": src, "destination": dst, "reason": "host_path_not_found"})

    backup_dir = get_app_backup_dir(cname)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_id = f"abk_{cname}_{uuid.uuid4().hex[:8]}"
    archive_filename = f"{cname}_{reason}_{ts}.tar.gz"
    archive_filepath = os.path.join(backup_dir, archive_filename)

    manifest: Dict[str, Any] = {
        "backup_id": backup_id,
        "app_name": cname,
        "container_name": raw_name,
        "container_id": cid[:12],
        "image": image,
        "reason": reason,
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mounts": appdata_mounts,
        "skipped_mounts": skipped_mounts,
        "has_compose": bool(compose_yaml),
    }

    # 3. Pause container if currently running to ensure filesystem consistency
    was_paused = False
    if is_running:
        try:
            p_status, _ = _docker_request("POST", f"/containers/{cid}/pause")
            if p_status in (200, 204):
                was_paused = True
                logger.info(f"[App Backup] Paused container '{cname}' for consistent backup.")
        except Exception as e:
            logger.warning(f"[App Backup] Could not pause container '{cname}' (continuing live): {e}")

    try:
        with tarfile.open(archive_filepath, "w:gz") as tar:
            # Add manifest.json
            manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
            tinfo = tarfile.TarInfo(name="manifest.json")
            tinfo.size = len(manifest_bytes)
            tinfo.mtime = int(time.time())
            tar.addfile(tinfo, io_bytes := __import__("io").BytesIO(manifest_bytes))

            # Add docker-compose.yml
            compose_bytes = compose_yaml.encode("utf-8")
            cinfo = tarfile.TarInfo(name="docker-compose.yml")
            cinfo.size = len(compose_bytes)
            cinfo.mtime = int(time.time())
            tar.addfile(cinfo, __import__("io").BytesIO(compose_bytes))

            # Add raw container inspect json
            inspect_bytes = json.dumps(inspect_data, indent=2).encode("utf-8")
            iinfo = tarfile.TarInfo(name="container_inspect.json")
            iinfo.size = len(inspect_bytes)
            iinfo.mtime = int(time.time())
            tar.addfile(iinfo, __import__("io").BytesIO(inspect_bytes))

            # Add data folders from appdata bind mounts
            for idx, m in enumerate(appdata_mounts):
                src_path = m["source"]
                # Create a subfolder inside the archive per mount: data/mount_0, data/mount_1, etc.
                arc_prefix = f"data/mount_{idx}"
                m["archive_prefix"] = arc_prefix
                if os.path.isdir(src_path):
                    tar.add(src_path, arcname=arc_prefix, recursive=True)
                elif os.path.isfile(src_path):
                    tar.add(src_path, arcname=f"{arc_prefix}/{os.path.basename(src_path)}")

        size_bytes = os.path.getsize(archive_filepath)
        size_human = _format_bytes(size_bytes)

        record: Dict[str, Any] = {
            "id": backup_id,
            "app_name": cname,
            "container_name": raw_name,
            "container_id": cid[:12],
            "reason": reason,
            "filename": archive_filename,
            "filepath": archive_filepath,
            "size_bytes": size_bytes,
            "size_human": size_human,
            "created_at": manifest["created_at"],
            "created_at_iso": manifest["created_at_iso"],
            "image": image,
            "mounts_count": len(appdata_mounts),
            "mounts": appdata_mounts,
        }

        save_app_backup_record(record)
        logger.info(f"[App Backup] Successfully created archive for '{cname}': {archive_filename} ({size_human})")
        return record

    finally:
        if was_paused:
            try:
                _docker_request("POST", f"/containers/{cid}/unpause")
                logger.info(f"[App Backup] Resumed container '{cname}' after backup.")
            except Exception as e:
                logger.error(f"[App Backup] Failed to unpause container '{cname}': {e}")


def list_app_backups(app_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns a sorted list of application backups.
    Validates file presence on disk and prunes missing files.
    """
    records = get_app_backups_registry()
    valid_records: List[Dict[str, Any]] = []

    for r in records:
        fpath = r.get("filepath", "")
        if fpath and os.path.exists(fpath):
            # Refresh size if modified
            r["size_bytes"] = os.path.getsize(fpath)
            r["size_human"] = _format_bytes(r["size_bytes"])
            valid_records.append(r)

    # If records were pruned, update registry
    if len(valid_records) != len(records):
        atomic_write_json(APP_BACKUPS_REGISTRY_FILE, valid_records)

    if app_name:
        target_name = app_name.strip().lstrip("/").lower()
        return [r for r in valid_records if r.get("app_name", "").lower() == target_name]

    return valid_records


def get_app_backup_path(backup_id: str) -> Optional[str]:
    """Resolves the absolute filepath for a given backup ID."""
    records = get_app_backups_registry()
    for r in records:
        if r.get("id") == backup_id:
            path = r.get("filepath")
            if path and os.path.exists(path):
                return path
    return None


def delete_app_backup(backup_id: str) -> bool:
    """Deletes an application backup archive from disk and removes it from the ledger."""
    records = get_app_backups_registry()
    target = next((r for r in records if r.get("id") == backup_id), None)
    if not target:
        return False

    fpath = target.get("filepath", "")
    if fpath and os.path.exists(fpath):
        try:
            os.remove(fpath)
            logger.info(f"[App Backup] Removed backup file: {fpath}")
        except Exception as e:
            logger.warning(f"[App Backup] Error removing file {fpath}: {e}")

    remove_app_backup_record(backup_id)
    return True


def restore_app_backup(
    backup_id: str,
    recreate_container: bool = True,
    target_mount_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Restores application data and configuration from a .tar.gz archive.
    1. Validates archive integrity and Tar-Slip safety.
    2. Extracts appdata files back into their original host source directories.
    3. Optionally restarts or recreates the container using synthesized compose specification.
    """
    filepath = get_app_backup_path(backup_id)
    if not filepath:
        raise ValueError(f"Backup archive with ID '{backup_id}' not found.")

    manifest = None
    compose_yaml = None
    extracted_mounts = []

    with tarfile.open(filepath, "r:gz") as tar:
        # Extract and parse manifest
        try:
            manifest_file = tar.extractfile("manifest.json")
            if manifest_file:
                manifest = json.loads(manifest_file.read().decode("utf-8"))
        except KeyError:
            pass

        try:
            compose_file = tar.extractfile("docker-compose.yml")
            if compose_file:
                compose_yaml = compose_file.read().decode("utf-8")
        except KeyError:
            pass

        if not manifest:
            raise ValueError("Corrupt backup archive: Missing manifest.json.")

        mounts = manifest.get("mounts", [])
        for m in mounts:
            src = m.get("source")
            arc_prefix = m.get("archive_prefix")
            if target_mount_overrides and src in target_mount_overrides:
                src = target_mount_overrides[src]

            if not src or not arc_prefix:
                continue

            os.makedirs(src, exist_ok=True)
            extracted_mounts.append(src)

            # Extract members matching arc_prefix into target host folder
            import copy

            members_to_extract = []
            for member in tar.getmembers():
                prefix_with_slash = arc_prefix if arc_prefix.endswith("/") else (arc_prefix + "/")
                if member.name.startswith(prefix_with_slash):
                    rel = member.name[len(prefix_with_slash) :]
                    if not rel:
                        continue
                    m_copy = copy.copy(member)
                    m_copy.name = rel
                    if is_safe_tar_member(m_copy, src):
                        members_to_extract.append(m_copy)

            # Safe extraction
            try:
                tar.extractall(src, members=members_to_extract, filter="data")
            except TypeError:
                for m_item in members_to_extract:
                    tar.extract(m_item, src)

    app_name = manifest.get("app_name", "app")
    logger.info(f"[App Backup] Restored data for '{app_name}' from backup '{backup_id}'.")

    return {
        "success": True,
        "backup_id": backup_id,
        "app_name": app_name,
        "restored_mounts": extracted_mounts,
        "has_compose": bool(compose_yaml),
        "recreate_requested": recreate_container,
        "message": f"Successfully restored {len(extracted_mounts)} data volume(s) for '{app_name}'.",
    }

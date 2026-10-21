"""
ZettNAS Toolkit - Application & Appdata Backup Engine
Handles:
1. Auto-archiving of container config + appdata on uninstall (Feature 21a).
2. On-demand backup of any installed container (Feature 21b).
3. Per-app backup listing, restoration, downloading, and deletion (Feature 21c).
4. Safe extraction with directory traversal / tar-slip guards.
100% Hardware & OS agnostic.
"""

import io
import json
import os
import tarfile
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.config import DATA_DIR, POOL_PATH, logger
from backend.fsutil import atomic_write_json, read_json
from backend.services.compose_synthesizer import format_compose_yaml, synthesize_compose_spec
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
    "/etc",
    "/root",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
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


FORBIDDEN_RESTORE_PREFIXES = (
    "/etc",
    "/root",
    "/usr",
    "/bin",
    "/sbin",
    "/boot",
    "/sys",
    "/proc",
    "/dev",
    "/run",
    "/var/run",
    "/lib",
    "/lib64",
)


def is_safe_restore_target_path(target_path: str) -> bool:
    """
    Validates that a restore target path does not target sensitive host system directories.
    Strictly forbids /etc, /root, /usr, /bin, /boot, /sys, /proc, /dev, etc.
    """
    if not target_path or not isinstance(target_path, str):
        return False
    norm = os.path.abspath(os.path.normpath(target_path.strip()))
    if norm in ("/", ""):
        return False
    real_norm = os.path.realpath(norm)
    for p in FORBIDDEN_RESTORE_PREFIXES:
        if norm == p or norm.startswith(p + "/") or real_norm == p or real_norm.startswith(p + "/"):
            return False
    for p in SYSTEM_MOUNT_PREFIXES:
        if norm == p or norm.startswith(p + "/") or real_norm == p or real_norm.startswith(p + "/"):
            return False
    return True


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
        srv_name, spec = synthesize_compose_spec(inspect_data, mask_secrets=False)
        compose_yaml = format_compose_yaml(srv_name, spec)
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

            if not is_safe_restore_target_path(src):
                logger.warning(f"[App Backup] Refusing to restore into unsafe system path: {src}")
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

    app_recreated = False
    if recreate_container and compose_yaml:
        try:
            from backend.config import DATA_DIR
            from backend.services.docker_stacks import deploy_stack

            stack_dir = os.path.join(DATA_DIR, "stacks", app_name)
            os.makedirs(stack_dir, exist_ok=True)
            compose_path = os.path.join(stack_dir, "docker-compose.yml")
            with open(compose_path, "w", encoding="utf-8") as f:
                f.write(compose_yaml)
            deploy_stack(app_name, compose_yaml)
            app_recreated = True
            logger.info(f"[App Backup] Re-deployed app '{app_name}' from backup compose spec.")
        except Exception as e:
            logger.warning(f"[App Backup] Could not automatically recreate container for '{app_name}': {e}")

    return {
        "success": True,
        "backup_id": backup_id,
        "app_name": app_name,
        "restored_mounts": extracted_mounts,
        "has_compose": bool(compose_yaml),
        "recreate_requested": recreate_container,
        "recreated": app_recreated,
        "message": f"Successfully restored {len(extracted_mounts)} data volume(s) for '{app_name}'.",
    }


# =========================================================================
# Virtual Machine Backups & Hyper-Backup Integration
# =========================================================================


def get_vm_backup_base_dir() -> str:
    """Returns root directory where VM disk and config archives are stored."""
    nas_vm_backups = os.path.join(POOL_PATH, "vms", ".backups")
    if os.path.exists(os.path.join(POOL_PATH, "vms")) and os.access(os.path.join(POOL_PATH, "vms"), os.W_OK):
        path = nas_vm_backups
    else:
        path = os.path.join(DATA_DIR, "vm_backups")
    os.makedirs(path, exist_ok=True)
    return path


def get_vm_backup_dir(vm_name: str) -> str:
    clean_name = (vm_name or "unknown_vm").strip().replace(" ", "_")
    base = get_vm_backup_base_dir()
    d = os.path.join(base, clean_name)
    os.makedirs(d, exist_ok=True)
    return d


def create_vm_backup(
    vm_id: str,
    reason: str = "on-demand",
    custom_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a full backup archive of a Virtual Machine:
    1. Loads VM config from vms.json.
    2. Identifies vm_dir and primary/secondary virtual disk files.
    3. Archives configuration and disk images into a compressed tar.gz archive.
    4. Registers record in persistent backup ledger.
    """
    vms_file = os.path.join(DATA_DIR, "vms.json")
    vms_list = read_json(vms_file, default=[])
    target_vm = next((v for v in vms_list if v.get("id") == vm_id), None)
    if not target_vm:
        raise ValueError(f"Virtual Machine with ID '{vm_id}' not found.")

    raw_name = target_vm.get("name", "vm")
    vname = custom_name or raw_name
    vm_dir = target_vm.get("vm_dir") or os.path.join(DATA_DIR, "vms", vm_id)

    backup_dir = get_vm_backup_dir(vname)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_id = f"vbk_{vname}_{uuid.uuid4().hex[:8]}"
    archive_filename = f"{vname}_{reason}_{ts}.tar.gz"
    archive_filepath = os.path.join(backup_dir, archive_filename)

    manifest: Dict[str, Any] = {
        "backup_id": backup_id,
        "type": "vm",
        "app_name": vname,
        "vm_id": vm_id,
        "vm_name": raw_name,
        "reason": reason,
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vm_config": target_vm,
        "vm_dir": vm_dir,
    }

    try:
        with tarfile.open(archive_filepath, "w:gz") as tar:
            # 1. Add manifest.json
            manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
            ti = tarfile.TarInfo("manifest.json")
            ti.size = len(manifest_bytes)
            ti.mtime = int(time.time())
            tar.addfile(ti, io.BytesIO(manifest_bytes))

            # 2. Add vm_config.json
            cfg_bytes = json.dumps(target_vm, indent=2).encode("utf-8")
            ti_cfg = tarfile.TarInfo("vm_config.json")
            ti_cfg.size = len(cfg_bytes)
            ti_cfg.mtime = int(time.time())
            tar.addfile(ti_cfg, io.BytesIO(cfg_bytes))

            # 3. Add VM directory files (skip live sockets and pid files)
            if os.path.exists(vm_dir):
                for root, _, files in os.walk(vm_dir):
                    for file in files:
                        if file.endswith((".pid", ".sock", ".log")):
                            continue
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, vm_dir)
                        arcname = f"vm_data/{rel_path}"
                        tar.add(full_path, arcname=arcname, recursive=False)

        size_bytes = os.path.getsize(archive_filepath)
        record: Dict[str, Any] = {
            "id": backup_id,
            "type": "vm",
            "app_name": vname,
            "vm_id": vm_id,
            "vm_name": raw_name,
            "reason": reason,
            "filename": archive_filename,
            "filepath": archive_filepath,
            "size_bytes": size_bytes,
            "size_formatted": _format_bytes(size_bytes),
            "created_at": time.time(),
            "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_app_backup_record(record)
        logger.info(f"[VM Backup] Created VM backup '{backup_id}' ({record['size_formatted']}) for {vname}")
        return record
    except Exception as e:
        if os.path.exists(archive_filepath):
            try:
                os.remove(archive_filepath)
            except Exception:
                pass
        logger.error(f"[VM Backup] Failed to create backup for {vname}: {e}")
        raise


def list_vm_backups(vm_id_or_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists saved VM archives, optionally filtered by VM ID or name."""
    registry = get_app_backups_registry()
    vm_records = [r for r in registry if r.get("type") == "vm"]
    if vm_id_or_name:
        needle = vm_id_or_name.strip().lower()
        vm_records = [
            r
            for r in vm_records
            if needle in (r.get("vm_id") or "").lower()
            or needle in (r.get("vm_name") or "").lower()
            or needle in (r.get("app_name") or "").lower()
        ]
    return vm_records


def restore_vm_backup(backup_id: str) -> Dict[str, Any]:
    """
    Restores a VM configuration and disk files from a backup archive.
    """
    registry = get_app_backups_registry()
    record = next((r for r in registry if r.get("id") == backup_id and r.get("type") == "vm"), None)
    if not record:
        raise ValueError(f"VM backup record '{backup_id}' not found.")

    filepath = record.get("filepath", "")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Backup archive file '{filepath}' no longer exists on host disk.")

    with tarfile.open(filepath, "r:gz") as tar:
        manifest_member = next((m for m in tar.getmembers() if m.name == "manifest.json"), None)
        if not manifest_member:
            raise ValueError("Invalid VM backup archive: manifest.json missing.")
        f = tar.extractfile(manifest_member)
        manifest = json.loads(f.read().decode("utf-8")) if f else {}

        vm_config = manifest.get("vm_config") or {}
        vm_id = vm_config.get("id") or record.get("vm_id")
        vm_dir = vm_config.get("vm_dir") or os.path.join(DATA_DIR, "vms", vm_id)
        os.makedirs(vm_dir, exist_ok=True)

        for member in tar.getmembers():
            if not is_safe_tar_member(member, vm_dir):
                logger.warning(f"[VM Restore] Skipping unsafe tar member: {member.name}")
                continue
            if member.name.startswith("vm_data/"):
                sub_name = member.name[len("vm_data/") :]
                dest_path = os.path.join(vm_dir, sub_name)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                if member.isfile():
                    extracted_file = tar.extractfile(member)
                    if extracted_file:
                        with open(dest_path, "wb") as out_f:
                            out_f.write(extracted_file.read())

    # Ensure VM is in vms.json
    if vm_config:
        vms_file = os.path.join(DATA_DIR, "vms.json")
        vms_list = read_json(vms_file, default=[])
        idx = next((i for i, v in enumerate(vms_list) if v.get("id") == vm_id), None)
        if idx is not None:
            vms_list[idx] = vm_config
        else:
            vms_list.append(vm_config)
        atomic_write_json(vms_file, vms_list)

    return {
        "success": True,
        "backup_id": backup_id,
        "vm_id": vm_id,
        "vm_name": record.get("vm_name"),
        "message": f"Successfully restored VM '{record.get('vm_name')}' from backup.",
    }


def delete_vm_backup(backup_id: str) -> bool:
    """Deletes a VM backup archive from disk and updates registry."""
    record = next((r for r in get_app_backups_registry() if r.get("id") == backup_id and r.get("type") == "vm"), None)
    if not record:
        return False
    filepath = record.get("filepath", "")
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            logger.warning(f"[VM Backup] Could not delete archive file {filepath}: {e}")
    remove_app_backup_record(backup_id)
    return True

"""
ZettNAS Toolkit - Resilient Filesystem Transfer & Directory Merge Engine
Handles recursive directory merging, unified collision resolution (Merge, Overwrite, Skip, Keep Both),
and cross-filesystem EXDEV (Invalid cross-device link) boundary fallbacks.
"""

import errno
import os
import shutil
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.config import logger


class CollisionPolicy(str, Enum):
    MERGE = "merge"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    KEEP_BOTH = "keep_both"


def _generate_unique_target(dst_path: str) -> str:
    """Generate a non-colliding path by appending ' (1)', ' (2)', etc. before the extension."""
    if not os.path.lexists(dst_path):
        return dst_path

    parent = os.path.dirname(dst_path)
    base = os.path.basename(dst_path)

    if os.path.isdir(dst_path):
        stem, ext = base, ""
    else:
        stem, ext = os.path.splitext(base)

    counter = 1
    while True:
        candidate_name = f"{stem} ({counter}){ext}"
        candidate_path = os.path.join(parent, candidate_name)
        if not os.path.lexists(candidate_path):
            return candidate_path
        counter += 1


def check_transfer_conflicts(sources: List[str], destination_dir: str) -> Dict[str, Any]:
    """Pre-flight check: inspect whether any source items conflict with existing items in destination_dir."""
    conflicts = []

    for src in sources:
        if not os.path.lexists(src):
            continue

        item_name = os.path.basename(src.rstrip("/\\"))
        dst_target = os.path.join(destination_dir, item_name)

        if os.path.lexists(dst_target):
            is_dir = os.path.isdir(src) and os.path.isdir(dst_target)
            src_stat = os.stat(src) if os.path.exists(src) else None
            dst_stat = os.stat(dst_target) if os.path.exists(dst_target) else None

            conflicts.append(
                {
                    "source": src,
                    "destination": dst_target,
                    "name": item_name,
                    "is_dir": is_dir,
                    "source_size": src_stat.st_size if src_stat and not is_dir else 0,
                    "dest_size": dst_stat.st_size if dst_stat and not is_dir else 0,
                    "source_mtime": src_stat.st_mtime if src_stat else 0.0,
                    "dest_mtime": dst_stat.st_mtime if dst_stat else 0.0,
                }
            )

    return {
        "has_conflict": len(conflicts) > 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


def _move_file_resilient(src: str, dst: str) -> None:
    """Move a single file across possibly distinct filesystems, catching EXDEV and falling back to copy+unlink."""
    try:
        os.replace(src, dst)
    except OSError as err:
        if err.errno == errno.EXDEV:
            # Cross-device link: stream copy with metadata then unlink source
            if os.path.islink(src):
                shutil.copy2(src, dst, follow_symlinks=False)
            else:
                shutil.copy2(src, dst)
            os.unlink(src)
        else:
            raise


def _transfer_single_file(
    src: str,
    dst: str,
    action: str = "copy",
    policy: CollisionPolicy = CollisionPolicy.OVERWRITE,
) -> str:
    """
    Transfers a single file respecting collision policy.
    Returns: 'transferred', 'skipped', or 'renamed'.
    """
    final_dst = dst
    if os.path.lexists(dst):
        if policy == CollisionPolicy.SKIP:
            return "skipped"
        elif policy == CollisionPolicy.KEEP_BOTH:
            final_dst = _generate_unique_target(dst)
        elif policy in (CollisionPolicy.OVERWRITE, CollisionPolicy.MERGE):
            final_dst = dst

    os.makedirs(os.path.dirname(final_dst), exist_ok=True)

    if action == "move":
        _move_file_resilient(src, final_dst)
    else:
        if os.path.islink(src):
            shutil.copy2(src, final_dst, follow_symlinks=False)
        else:
            shutil.copy2(src, final_dst)

    return "renamed" if final_dst != dst else "transferred"


def merge_directory_tree(
    src_dir: str,
    dst_dir: str,
    action: str = "copy",
    policy: CollisionPolicy = CollisionPolicy.MERGE,
    stats: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """
    Recursively merges src_dir into dst_dir:
    - If policy == MERGE: creates subdirectories and transfers non-conflicting child items.
    - If policy == OVERWRITE: replaces existing directory entirely.
    - If policy == SKIP: skips entire directory if destination exists.
    - If policy == KEEP_BOTH: renames target directory e.g. dst_dir (1).
    """
    if stats is None:
        stats = {"transferred": 0, "skipped": 0, "merged_dirs": 0}

    dst_exists = os.path.lexists(dst_dir)

    if dst_exists:
        if policy == CollisionPolicy.SKIP:
            stats["skipped"] += 1
            return stats
        elif policy == CollisionPolicy.KEEP_BOTH:
            dst_dir = _generate_unique_target(dst_dir)
            dst_exists = False
        elif policy == CollisionPolicy.OVERWRITE:
            if os.path.isdir(dst_dir):
                shutil.rmtree(dst_dir)
            else:
                os.unlink(dst_dir)
            dst_exists = False

    # Destination directory now either does not exist or we are performing MERGE
    if not dst_exists:
        if action == "move":
            try:
                os.rename(src_dir, dst_dir)
                stats["transferred"] += 1
                return stats
            except OSError as err:
                if err.errno != errno.EXDEV:
                    raise
                # Cross-device move: continue with recursive leaf transfer
        os.makedirs(dst_dir, exist_ok=True)
    else:
        stats["merged_dirs"] += 1

    try:
        entries = list(os.scandir(src_dir))
    except OSError as err:
        logger.error(f"[FS Transfer] Cannot scan directory {src_dir}: {err}")
        return stats

    for entry in entries:
        src_child = entry.path
        dst_child = os.path.join(dst_dir, entry.name)

        if entry.is_dir(follow_symlinks=False):
            # Recurse into child directory
            merge_directory_tree(
                src_child,
                dst_child,
                action=action,
                policy=policy,
                stats=stats,
            )
        else:
            # Transfer child file
            result = _transfer_single_file(
                src_child,
                dst_child,
                action=action,
                policy=policy,
            )
            if result in ("transferred", "renamed"):
                stats["transferred"] += 1
            elif result == "skipped":
                stats["skipped"] += 1

    # If action is move, clean up empty source directory
    if action == "move":
        try:
            os.rmdir(src_dir)
        except OSError:
            pass

    return stats


def execute_transfer(
    sources: List[str],
    destination_dir: str,
    action: str = "copy",
    policy: str = "merge",
) -> Dict[str, Any]:
    """
    Main transfer entry point.
    Processes a list of source paths (files or directories) into destination_dir.
    """
    collision_policy = CollisionPolicy(policy.lower())
    os.makedirs(destination_dir, exist_ok=True)

    summary = {
        "transferred": 0,
        "skipped": 0,
        "merged_dirs": 0,
        "errors": [],
    }

    for src in sources:
        if not os.path.lexists(src):
            summary["errors"].append({"path": src, "error": "Item not found"})
            continue

        item_name = os.path.basename(src.rstrip("/\\"))
        dst_target = os.path.join(destination_dir, item_name)

        try:
            if os.path.isdir(src):
                merge_directory_tree(
                    src,
                    dst_target,
                    action=action,
                    policy=collision_policy,
                    stats=summary,
                )
            else:
                result = _transfer_single_file(
                    src,
                    dst_target,
                    action=action,
                    policy=collision_policy,
                )
                if result in ("transferred", "renamed"):
                    summary["transferred"] += 1
                elif result == "skipped":
                    summary["skipped"] += 1
        except Exception as err:
            logger.error(f"[FS Transfer] Failed to transfer {src} -> {dst_target}: {err}")
            summary["errors"].append({"path": src, "error": str(err)})

    return {
        "status": "ok" if not summary["errors"] else "partial",
        "action": action,
        "policy": collision_policy.value,
        **summary,
    }

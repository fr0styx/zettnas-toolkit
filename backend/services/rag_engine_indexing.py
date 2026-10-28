"""Indexing files and folders, forgetting and flushing for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

# pyright: reportAttributeAccessIssue=false

import bisect
import hashlib
import json
import os
import re
import threading
import time
from typing import (  # noqa: F401
    Any,
)

from backend.config import (  # noqa: F401
    logger,
)
from backend.db_crypto import (  # noqa: F401
    sqlite3,
)
from backend.fsutil import (  # noqa: F401
    atomic_write_json,
    is_protected,
    locked_json,
    read_json,
)
from backend.logging_config import (  # noqa: F401
    sanitize_string,
)
from backend.services import (  # noqa: F401
    rag_standby,
)
from backend.services.ai_activity import upgrade_window_open
from backend.services.rag_documents import (  # noqa: F401
    extract_document_text,
    generate_contextual_hierarchical_chunks,
)
from backend.services.rag_embeddings import (  # noqa: F401
    compute_384d_embedding,
    embedding_host,
    format_embeddinggemma_document,
)
from backend.services.rag_text import (  # noqa: F401
    AUDIO_EXTENSIONS,
    CODE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    EXCLUDED_DIRS,
    EXCLUDED_EXTENSIONS,
    EXCLUDED_FILENAMES,
    IMAGE_EXTENSIONS,
    MAX_INDEX_FILE_BYTES,
    VIDEO_EXTENSIONS,
    looks_like_binary,
    text_for_embedding,
)
from backend.state import (  # noqa: F401
    add_event,
)


def _core():
    """backend.services.rag_engine, read at call time: shared settings live there and tests patch them."""
    from backend.services import rag_engine

    return rag_engine


class RagIndexingMixin:
    """Indexing files and folders, forgetting and flushing for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

    def forget_folder(self, folder_path: str) -> dict[str, Any]:
        """Deletes everything the index learned from a folder and stops learning it again (AI-20).

        Removes its files, chunks, vectors, photo data, folder summaries and queued work, then
        adds the folder to excluded_paths. Reads nothing from the folder itself.
        """
        norm = os.path.normpath(str(folder_path or "").strip())
        if not norm or norm in (".", "/"):
            raise ValueError("Choose a folder to forget.")
        prefix = norm.rstrip("/") + "/"
        under = "(canonical_path = ? OR substr(canonical_path, 1, ?) = ?)"
        args = (norm, len(prefix), prefix)
        removed = {"files": 0, "vectors": 0, "manifests": 0, "queued": 0}
        with self._write_lock:
            self._ensure_schema()
            conn = self._get_conn(readonly=False)
            try:
                file_ids = [r[0] for r in conn.execute(f"SELECT file_id FROM indexed_files WHERE {under}", args)]
                if file_ids:
                    marks = ",".join("?" for _ in file_ids)
                    chunk_ids = [
                        r[0]
                        for r in conn.execute(
                            f"SELECT chunk_id FROM document_chunks WHERE file_id IN ({marks})", file_ids
                        )
                    ]
                    vec_tables = [
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE name LIKE 'vec_chunks_%' AND sql LIKE '%vec0%'"
                        )
                    ]
                    for table in vec_tables:
                        if not re.fullmatch(r"vec_chunks_\d+", table):
                            continue
                        for i in range(0, len(chunk_ids), 500):
                            part = chunk_ids[i : i + 500]
                            try:
                                cur = conn.execute(
                                    f"DELETE FROM {table} WHERE chunk_id IN ({','.join('?' for _ in part)})", part
                                )
                                removed["vectors"] += max(0, cur.rowcount or 0)
                            except sqlite3.Error as e:
                                logger.debug(f"[RAG] Forget: vector cleanup in {table} skipped: {e}")
                    # chunks and photo data go with their file (ON DELETE CASCADE)
                    removed["files"] = conn.execute(f"DELETE FROM indexed_files WHERE {under}", args).rowcount
                removed["manifests"] = conn.execute(
                    "DELETE FROM folder_manifests WHERE folder_path = ? OR substr(folder_path, 1, ?) = ?", args
                ).rowcount
                removed["queued"] = conn.execute(
                    "DELETE FROM rag_deferred_queue WHERE target_path = ? OR substr(target_path, 1, ?) = ?", args
                ).rowcount
                conn.commit()
            finally:
                conn.close()
        cfg = self.get_config()
        excluded = [p for p in (cfg.get("excluded_paths") or []) if p]
        if norm not in {os.path.normpath(p) for p in excluded}:
            excluded.append(norm)
        watched = [p for p in (cfg.get("watched_paths") or []) if os.path.normpath(p) != norm]
        self.update_config({"excluded_paths": excluded, "watched_paths": watched})
        logger.info(f"[RAG] Forgot folder {sanitize_string(norm)}: {removed}")
        return {"status": "ok", "folder": norm, "removed": removed}

    def flush_index(self) -> dict[str, Any]:
        """
        Stops active syncs and wipes all indexed files, document chunks, photo assets,
        folder manifests, and deferred items from rag_index.db, reclaims NVMe storage with VACUUM,
        and resets in-memory indexing progress counters so the user can start completely fresh.
        Spindown-Safe: Does not touch or wake any array disks.
        """
        logger.info("[RAG] Flushing index requested. Stopping sync if active...")
        if self._sync_state in ("running", "paused"):
            self.stop_sync()

        with self._write_lock:
            self._ensure_schema()
            conn = self._get_conn(readonly=False)
            try:
                # 1. Truncate indexed data tables
                if self._has_sqlite_vec and self._vec_table_active:
                    try:
                        conn.execute(f"DELETE FROM vec_chunks_{int(self._vec_table_dim)}")
                    except sqlite3.Error as e:
                        logger.debug(f"[RAG] vector table reset skipped: {e}")
                conn.execute("DELETE FROM document_chunks;")
                conn.execute("DELETE FROM photo_assets;")
                conn.execute("DELETE FROM folder_manifests;")
                conn.execute("DELETE FROM indexed_files;")
                conn.execute("DELETE FROM rag_deferred_queue;")
                conn.commit()

                # 2. Rebuild FTS virtual tables
                try:
                    conn.execute("INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild');")
                    conn.execute("INSERT INTO rag_manifests_fts(rag_manifests_fts) VALUES('rebuild');")
                    conn.execute("INSERT INTO rag_photos_fts(rag_photos_fts) VALUES('rebuild');")
                    conn.commit()
                except Exception as fts_err:
                    logger.debug(f"[RAG] FTS rebuild notice during flush: {fts_err}")

                # 3. Reclaim NVMe disk space
                try:
                    conn.execute("VACUUM;")
                except Exception as vac_err:
                    logger.debug(f"[RAG] VACUUM notice during flush: {vac_err}")
            finally:
                conn.close()

            # 4. Reset in-memory state
            self._is_indexing = False
            self._sync_state = "idle"
            self._last_sync_ts = None
            self._sync_progress = {
                "state": "idle",
                "current_path": "",
                "target_paths": [],
                "indexed_files": 0,
                "skipped_unchanged": 0,
                "deferred_standby": 0,
                "errors": 0,
                "respect_standby": True,
                "auto_triggered_by_spinup": False,
                "woken_disks": [],
                "started_at": None,
                "updated_at": None,
                "message": "RAG database flushed clean. Ready for fresh sync.",
            }
            logger.info("[RAG] Successfully flushed all indexed files, vectors, and chunks from rag_index.db")
            try:
                cfg = self.get_config()
                if cfg.get("active_sync_session"):
                    cfg["active_sync_session"] = None
                    atomic_write_json(_core().RAG_CONFIG_PATH, cfg)
            except Exception:
                logger.debug("backend.services.rag_engine.RagSearchEngine.flush_index: ignored error", exc_info=True)
            return {
                "status": "ok",
                "message": "RAG index and vector database successfully flushed clean.",
                "stats": self.get_index_stats(),
                "sync_progress": self.get_sync_progress(),
            }

    def start_background_sync(
        self,
        paths: list[str],
        respect_standby: bool = True,
        force_wake: bool = False,
        max_files: int = 100000,
        recursive: bool = True,
        auto_spinup_devs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Starts indexing one or more folders asynchronously in a background daemon thread."""
        if self._is_indexing and self._sync_state in ("running", "paused"):
            return {"status": "already_running", **self.get_sync_progress()}

        self._stop_requested = False
        self._pause_event.set()
        self._is_indexing = True
        self._sync_state = "running"
        now = time.time()
        is_spinup = bool(auto_spinup_devs)
        dev_label = ", ".join(f"/dev/{d}" for d in (auto_spinup_devs or []) if d) or "array disk"
        init_msg = (
            f"⚡ Auto-learning started ({dev_label} spun up): syncing {', '.join(paths)}..."
            if is_spinup
            else f"Syncing {len(paths)} folder(s)..."
        )
        self._sync_progress = {
            "state": "running",
            "current_path": paths[0] if paths else "",
            "target_paths": list(paths),
            "indexed_files": 0,
            "skipped_unchanged": 0,
            "deferred_standby": 0,
            "errors": 0,
            "respect_standby": respect_standby,
            "auto_triggered_by_spinup": is_spinup,
            "woken_disks": list(auto_spinup_devs or []),
            "started_at": now,
            "updated_at": now,
            "message": init_msg,
        }

        # Persist active sync session so container restart / server reboot can automatically resume
        try:
            cfg = self.get_config()
            cfg["active_sync_session"] = {
                "paths": list(paths),
                "started_at": now,
                "status": "running",
                "respect_standby": respect_standby,
                "force_wake": force_wake,
            }
            atomic_write_json(_core().RAG_CONFIG_PATH, cfg)
        except Exception:
            logger.debug(
                "backend.services.rag_engine.RagSearchEngine.start_background_sync: ignored error", exc_info=True
            )

        if is_spinup:
            try:
                add_event(
                    "info",
                    f"ZettAI Auto-Learning Started ({dev_label})",
                    f"Disk spin-up detected on {dev_label}. Syncing {len(paths)} watched folder(s)...",
                )
            except Exception:
                logger.debug(
                    "backend.services.rag_engine.RagSearchEngine.start_background_sync: ignored error", exc_info=True
                )

        def _worker() -> None:
            try:
                self.index_paths(
                    paths=paths,
                    respect_standby=respect_standby,
                    force_wake=force_wake,
                    max_files=max_files,
                    recursive=recursive,
                    _from_bg_worker=True,
                    auto_spinup_devs=auto_spinup_devs,
                )
            except Exception as e:
                logger.debug(f"[RAG] Background sync error: {e}")
                self._sync_state = "idle"
                self._sync_progress["state"] = "idle"
                self._sync_progress["message"] = f"Sync error: {e}"
            finally:
                self._is_indexing = False
                try:
                    cfg = self.get_config()
                    if self._sync_state in ("idle", "stopped", "completed"):
                        if cfg.get("active_sync_session"):
                            cfg["active_sync_session"] = None
                            atomic_write_json(_core().RAG_CONFIG_PATH, cfg)
                except Exception:
                    logger.debug(
                        "backend.services.rag_engine.RagSearchEngine.start_background_sync._worker: ignored error",
                        exc_info=True,
                    )

        t = threading.Thread(target=_worker, name="zettnas-rag-sync", daemon=True)
        self._sync_thread = t
        t.start()
        return {"status": "started", **self.get_sync_progress()}

    def index_paths(
        self,
        paths: list[str],
        respect_standby: bool = True,
        force_wake: bool = False,
        max_files: int = 100000,
        recursive: bool = True,
        _from_bg_worker: bool = False,
        auto_spinup_devs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Indexes multiple folders sequentially while respecting pause/resume/stop and disk standby."""
        clean_paths = [os.path.normpath(p.strip()) for p in (paths or []) if p and str(p).strip()]
        if not clean_paths:
            clean_paths = self.get_config().get("watched_paths") or ["/mnt/user"]

        is_spinup = bool(auto_spinup_devs)
        dev_label = ", ".join(f"/dev/{d}" for d in (auto_spinup_devs or []) if d) or "array disk"

        if not _from_bg_worker:
            self._stop_requested = False
            self._pause_event.set()
            self._sync_state = "running"
            now = time.time()
            self._sync_progress = {
                "state": "running",
                "current_path": clean_paths[0],
                "target_paths": clean_paths,
                "indexed_files": 0,
                "skipped_unchanged": 0,
                "deferred_standby": 0,
                "errors": 0,
                "respect_standby": respect_standby,
                "auto_triggered_by_spinup": is_spinup,
                "woken_disks": list(auto_spinup_devs or []),
                "started_at": now,
                "updated_at": now,
                "message": (
                    f"⚡ Auto-learning started ({dev_label} spun up): syncing {', '.join(clean_paths)}..."
                    if is_spinup
                    else f"Syncing {len(clean_paths)} folder(s)..."
                ),
            }

        total_indexed = 0
        total_skipped = 0
        total_deferred = 0
        total_errors = 0
        per_path_results: list[dict[str, Any]] = []
        was_stopped = False

        self._is_indexing = True
        try:
            for p in clean_paths:
                if self._stop_requested:
                    was_stopped = True
                    break
                remaining = max(1, max_files - (total_indexed + total_skipped))
                res = self.index_directory(
                    root_path=p,
                    respect_standby=respect_standby,
                    force_wake=force_wake,
                    max_files=remaining,
                    recursive=recursive,
                    _reset_control_flags=False,
                )
                per_path_results.append(res)
                total_indexed += int(res.get("indexed_files", 0))
                total_skipped += int(res.get("skipped_unchanged", 0))
                total_deferred += int(res.get("deferred_standby", 0))
                total_errors += int(res.get("errors", 0))
                if res.get("status") == "stopped" or self._stop_requested:
                    was_stopped = True
                    break

            final_status = (
                "stopped"
                if was_stopped
                else (
                    "deferred_standby"
                    if (total_deferred > 0 and total_indexed == 0 and total_skipped == 0)
                    else "completed"
                )
            )
            self._sync_state = "stopped" if was_stopped else "completed"
            self._sync_progress.update(
                {
                    "state": self._sync_state,
                    "current_path": "",
                    "indexed_files": total_indexed,
                    "skipped_unchanged": total_skipped,
                    "deferred_standby": total_deferred,
                    "errors": total_errors,
                    "auto_triggered_by_spinup": is_spinup,
                    "woken_disks": list(auto_spinup_devs or []),
                    "updated_at": time.time(),
                    "message": (
                        f"Sync stopped ({total_indexed} indexed, {total_skipped} unchanged)."
                        if was_stopped
                        else (
                            f"Deferred {total_deferred} folder(s) because backing HDD is in standby (auto-learns on spin-up)."
                            if final_status == "deferred_standby"
                            else (
                                f"⚡ Auto-learned on disk spin-up ({dev_label}): {total_indexed} indexed, {total_skipped} unchanged, {total_deferred} standby-deferred."
                                if is_spinup
                                else f"✓ Sync Complete: All {total_indexed + total_skipped} media & companion files up to date ({total_indexed} newly indexed, {total_skipped} unchanged, {total_deferred} deferred)."
                            )
                        )
                    ),
                }
            )

            if is_spinup:
                try:
                    add_event(
                        "info",
                        f"ZettAI Auto-Learning Completed ({dev_label})",
                        f"Indexed {total_indexed} files ({total_skipped} unchanged, {total_deferred} deferred) on {dev_label}.",
                    )
                except Exception:
                    logger.debug(
                        "backend.services.rag_engine.RagSearchEngine.index_paths: ignored error", exc_info=True
                    )
            return {
                "status": final_status,
                "path": ", ".join(clean_paths),
                "paths": clean_paths,
                "indexed_files": total_indexed,
                "skipped_unchanged": total_skipped,
                "deferred_standby": total_deferred,
                "errors": total_errors,
                "auto_triggered_by_spinup": is_spinup,
                "woken_disks": list(auto_spinup_devs or []),
                "results": per_path_results,
                "sync_progress": self.get_sync_progress(),
            }
        finally:
            self._is_indexing = False

    def index_directory(
        self,
        root_path: str,
        respect_standby: bool = True,
        force_wake: bool = False,
        max_files: int = 100000,
        recursive: bool = True,
        _reset_control_flags: bool = True,
    ) -> dict[str, Any]:
        """
        Incrementally indexes documents, recipes, code, and photos under `root_path`.
        Strictly obeys SpindownGuard: if a backing disk is in STANDBY and respect_standby=True
        (and force_wake=False), queues the path in `rag_deferred_queue` without touching the disk.
        Supports cooperative Pause / Resume / Stop at every directory and file boundary.
        """
        self._ensure_schema()
        norm_root = os.path.normpath(root_path)
        cfg = self.get_config()
        if cfg.get("enabled") is False:
            return {
                "status": "disabled",
                "path": norm_root,
                "indexed_files": 0,
                "skipped_unchanged": 0,
                "deferred_standby": 0,
                "errors": 0,
                "message": "ZettAI service is disabled — learning paused.",
            }

        if _reset_control_flags:
            self._stop_requested = False
            self._pause_event.set()
            self._sync_state = "running"
            now = time.time()
            self._sync_progress.update(
                {
                    "state": "running",
                    "current_path": norm_root,
                    "target_paths": [norm_root],
                    "indexed_files": 0,
                    "skipped_unchanged": 0,
                    "deferred_standby": 0,
                    "errors": 0,
                    "respect_standby": respect_standby,
                    "started_at": now,
                    "updated_at": now,
                    "message": f"Scanning {norm_root}...",
                }
            )

        # Layer 1 Spindown Guard: Check backing device BEFORE calling os.path.exists / touching root_path
        backing_dev = rag_standby.resolve_path_backing_dev(norm_root)
        if respect_standby and not force_wake and rag_standby.is_backing_disk_in_standby(backing_dev):
            with self._write_lock:
                conn = self._get_conn(readonly=False)
                try:
                    conn.execute(
                        """
                        INSERT INTO rag_deferred_queue(target_path, backing_dev, reason, queued_at, priority)
                        VALUES (?, ?, 'disk_standby', ?, 1)
                        ON CONFLICT(target_path) DO UPDATE SET queued_at = excluded.queued_at
                        """,
                        (norm_root, backing_dev, time.time()),
                    )
                    conn.commit()
                finally:
                    conn.close()
            if _reset_control_flags:
                self._sync_state = "completed"
                self._sync_progress["state"] = "completed"
                self._sync_progress["deferred_standby"] = 1
                self._sync_progress["message"] = (
                    f"Deferred {norm_root}: backing disk /dev/{backing_dev} is in standby (0 wakeups)."
                )
            return {
                "status": "deferred_standby",
                "path": norm_root,
                "backing_dev": backing_dev,
                "indexed_files": 0,
                "skipped_unchanged": 0,
                "deferred_standby": 1,
                "message": f"Deferred indexing on {norm_root} because backing drive {backing_dev} is in standby.",
            }

        if not os.path.exists(norm_root):
            self.remove_deferred_path(norm_root)
            if _reset_control_flags:
                self._sync_state = "idle"
                self._sync_progress["state"] = "idle"
            return {
                "status": "not_found",
                "path": norm_root,
                "indexed_files": 0,
                "skipped_unchanged": 0,
                "deferred_standby": 0,
            }

        self._is_indexing = True
        indexed_new_or_updated = 0
        skipped_unchanged = 0
        deferred_standby = 0
        errors_count = 0
        seen_file_ids: set[int] = set()
        any_subpath_deferred = False
        stopped_early = False

        try:
            # Preload existing file metadata for microsecond incremental fast-skip
            conn_ro = self._get_conn(readonly=True)
            try:
                prefix_slash = norm_root.rstrip("/") + "/"
                prefix_upper = norm_root.rstrip("/") + "0"
                rows = conn_ro.execute(
                    """
                    SELECT file_id, canonical_path, mtime_ns, size_bytes, sha256_hash, index_version, parse_status
                    FROM indexed_files
                    WHERE canonical_path = ? OR (canonical_path >= ? AND canonical_path < ?)
                    """,
                    (norm_root, prefix_slash, prefix_upper),
                ).fetchall()
                existing_map: dict[str, sqlite3.Row] = {r["canonical_path"]: r for r in rows}
            finally:
                conn_ro.close()
            by_dir: dict[str, list[sqlite3.Row]] = {}
            for r in rows:
                by_dir.setdefault(os.path.dirname(r["canonical_path"]), []).append(r)
            sorted_paths = sorted(existing_map)
            # AI-34: a run that reached the file limit left a cursor; this one starts there
            cursor = [self._read_cursor(norm_root).split("/") or None]
            if cursor[0] == [""]:
                cursor[0] = None
            limit_hit_at: list[str] = []
            stale_ids: set[int] = set()
            upgrade_waiting = [0]

            def _under(prefix: str) -> list[sqlite3.Row]:
                lo = bisect.bisect_left(sorted_paths, prefix)
                hi = bisect.bisect_left(sorted_paths, prefix[:-1] + "0")
                return [existing_map[p] for p in sorted_paths[lo:hi]]

            def _clean_dir(current_dir: str, kept_names: set[str]) -> None:
                """The index entries of a fully scanned folder that are gone: its files not seen
                this run, and everything under subfolders that no longer exist (AI-34)."""
                for r in by_dir.get(current_dir, []):
                    if int(r["file_id"]) not in seen_file_ids:
                        stale_ids.add(int(r["file_id"]))
                if not kept_names or os.path.normpath(current_dir) in ("/mnt/user", "/mnt/storage"):
                    return  # an empty listing may be an unmounted pool; a union root, a stopped array
                prefix = current_dir.rstrip("/") + "/"
                for r in _under(prefix):
                    first = r["canonical_path"][len(prefix) :].split("/", 1)[0]
                    if first not in kept_names and "/" in r["canonical_path"][len(prefix) :]:
                        stale_ids.add(int(r["file_id"]))

            def _wait_if_paused_or_stopped() -> bool:
                """Returns True if stop was requested, or blocks cooperatively while paused."""
                nonlocal stopped_early
                if self._stop_requested:
                    stopped_early = True
                    return True
                while not self._pause_event.is_set() and not self._stop_requested:
                    self._sync_state = "paused"
                    self._sync_progress["state"] = "paused"
                    time.sleep(0.1)
                if self._stop_requested:
                    stopped_early = True
                    return True
                if self._sync_state == "paused":
                    self._sync_state = "running"
                    self._sync_progress["state"] = "running"
                return False

            def _record_deferred_subpath(subpath: str, dev: str) -> None:
                nonlocal any_subpath_deferred, deferred_standby
                any_subpath_deferred = True
                deferred_standby += 1
                with self._write_lock:
                    c_def = self._get_conn(readonly=False)
                    try:
                        c_def.execute(
                            """
                            INSERT INTO rag_deferred_queue(target_path, backing_dev, reason, queued_at, priority)
                            VALUES (?, ?, 'disk_standby', ?, 0)
                            ON CONFLICT(target_path) DO UPDATE SET queued_at = excluded.queued_at
                            """,
                            (subpath, dev, time.time()),
                        )
                        c_def.commit()
                    finally:
                        c_def.close()

            def _walk_dir(current_dir: str) -> None:
                nonlocal \
                    indexed_new_or_updated, \
                    skipped_unchanged, \
                    deferred_standby, \
                    errors_count, \
                    any_subpath_deferred, \
                    stopped_early
                if _wait_if_paused_or_stopped():
                    return
                if max_files and max_files > 0 and (indexed_new_or_updated + skipped_unchanged) >= max_files:
                    return

                self._sync_progress["current_path"] = current_dir
                self._sync_progress["updated_at"] = time.time()

                dir_dev = rag_standby.resolve_path_backing_dev(current_dir)
                if respect_standby and not force_wake and rag_standby.is_backing_disk_in_standby(dir_dev):
                    _record_deferred_subpath(current_dir, dir_dev)
                    return

                try:
                    entries = sorted(os.scandir(current_dir), key=lambda e: e.name)  # one order, for the cursor
                except Exception:
                    return

                is_top_union_root = os.path.normpath(current_dir) in ("/mnt/user", "/mnt/storage")
                excl_set = {os.path.normpath(p) for p in (self.get_config().get("excluded_paths") or []) if p}
                complete = True  # every entry handled: the folder may be cleaned (AI-34)
                kept_names = {e.name for e in entries}

                for entry in entries:
                    if _wait_if_paused_or_stopped():
                        complete = False
                        break
                    if max_files and max_files > 0 and (indexed_new_or_updated + skipped_unchanged) >= max_files:
                        complete = False
                        if not limit_hit_at:
                            limit_hit_at.append(entry.path)
                        break
                    if cursor[0] is not None:
                        parts = entry.path.split("/")
                        on_the_way = cursor[0][: len(parts)] == parts
                        if parts == cursor[0]:
                            cursor[0] = None  # reached: everything after it is new to this run
                        elif not on_the_way and parts < cursor[0]:
                            complete = False  # done by the run before
                            continue
                    name = entry.name
                    if name.startswith(".") or name in EXCLUDED_DIRS or name.lower() in EXCLUDED_FILENAMES:
                        continue
                    # Skip noisy system/container shares when scanning /mnt/user root unless explicitly targeted
                    if is_top_union_root and name.lower() in _core().SYSTEM_SHARE_EXCLUSIONS:
                        continue

                    child_path = os.path.join(current_dir, name)
                    if os.path.normpath(child_path) in excl_set or is_protected(child_path):
                        kept_names.discard(name)  # excluded now: what was learned there goes
                        continue

                    # Before touching a child share/directory, check if its backing disk is in standby
                    if is_top_union_root and respect_standby and not force_wake:
                        child_dev = rag_standby.resolve_path_backing_dev(child_path)
                        if rag_standby.is_backing_disk_in_standby(child_dev):
                            _record_deferred_subpath(child_path, child_dev)
                            continue

                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            _walk_dir(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except Exception:
                        continue

                    ext = os.path.splitext(name)[1].lower()
                    if ext in EXCLUDED_EXTENSIONS:
                        continue
                    if (
                        ext not in DOCUMENT_EXTENSIONS
                        and ext not in CODE_EXTENSIONS
                        and ext not in IMAGE_EXTENSIONS
                        and ext not in AUDIO_EXTENSIONS
                        and ext not in VIDEO_EXTENSIONS
                    ):
                        continue

                    # Re-check disk standby before reading file if we resumed from pause or every 20 files
                    if (
                        respect_standby
                        and not force_wake
                        and ((indexed_new_or_updated + skipped_unchanged) % 20 == 0)
                        and rag_standby.is_backing_disk_in_standby(dir_dev)
                    ):
                        _record_deferred_subpath(current_dir, dir_dev)
                        return  # not complete: nothing here is cleaned

                    try:
                        st = entry.stat(follow_symlinks=False)
                    except Exception:
                        continue

                    if ext not in VIDEO_EXTENSIONS and ext not in AUDIO_EXTENSIONS:
                        if st.st_size <= 0 or st.st_size > MAX_INDEX_FILE_BYTES:
                            continue
                    else:
                        if st.st_size <= 0:
                            continue

                    c_path = os.path.realpath(entry.path)
                    cached_row = existing_map.get(c_path)
                    unchanged = (
                        cached_row is not None
                        and int(cached_row["mtime_ns"]) == int(st.st_mtime_ns)
                        and int(cached_row["size_bytes"]) == int(st.st_size)
                        and cached_row["parse_status"] == "ok"
                    )
                    old_version = (
                        unchanged
                        and cached_row is not None
                        and int(cached_row["index_version"]) != _core().CURRENT_INDEX_VERSION
                    )
                    if old_version and not upgrade_window_open():
                        upgrade_waiting[0] += 1  # made the old way: re-made overnight (AI-30)
                    if cached_row is not None and unchanged and (not old_version or not upgrade_window_open()):
                        seen_file_ids.add(int(cached_row["file_id"]))
                        skipped_unchanged += 1
                        if _reset_control_flags:
                            self._sync_progress["skipped_unchanged"] = skipped_unchanged
                        continue

                    # Index single file
                    self._sync_progress["current_path"] = c_path
                    fid = self._index_single_file(
                        c_path,
                        name,
                        ext,
                        st.st_size,
                        st.st_mtime_ns,
                        cached_row,
                        respect_standby=respect_standby,
                        force_wake=force_wake,
                    )
                    if fid is not None:
                        seen_file_ids.add(fid)
                        indexed_new_or_updated += 1
                        if _reset_control_flags:
                            self._sync_progress["indexed_files"] = indexed_new_or_updated
                    else:
                        errors_count += 1
                        if cached_row is not None:
                            seen_file_ids.add(int(cached_row["file_id"]))  # a failed re-read keeps the old entry

                    # Cooperative yield every 25 files
                    if indexed_new_or_updated % 25 == 0:
                        time.sleep(0.002)

                if complete and not stopped_early:
                    _clean_dir(current_dir, kept_names)

            if os.path.isfile(norm_root):
                if not _wait_if_paused_or_stopped():
                    st = os.stat(norm_root)
                    name = os.path.basename(norm_root)
                    ext = os.path.splitext(name)[1].lower()
                    c_path = os.path.realpath(norm_root)
                    fid = self._index_single_file(
                        c_path,
                        name,
                        ext,
                        st.st_size,
                        st.st_mtime_ns,
                        existing_map.get(c_path),
                        respect_standby=respect_standby,
                        force_wake=force_wake,
                    )
                    if fid is not None:
                        seen_file_ids.add(fid)
                        indexed_new_or_updated += 1
            else:
                _walk_dir(norm_root)

            # Spindown-safe and stop-safe cleanup, per folder (AI-34): what a fully scanned folder
            # no longer holds goes from the index, whether or not the run reached the file limit;
            # a folder on a sleeping disk, stopped or left for the next run is not cleaned
            stale_ids -= seen_file_ids  # moved here later in the same run (AI-35)
            if stale_ids:
                ids = sorted(stale_ids)
                with self._write_lock:
                    conn_del = self._get_conn(readonly=False)
                    try:
                        for i in range(0, len(ids), 900):
                            part = ids[i : i + 900]
                            placeholders = ",".join("?" for _ in part)
                            self._drop_file_vectors(conn_del, placeholders, part)
                            conn_del.execute(f"DELETE FROM indexed_files WHERE file_id IN ({placeholders})", part)
                        conn_del.commit()
                    finally:
                        conn_del.close()

            # AI-34: the file limit continues where it stopped next time
            if limit_hit_at:
                self._write_cursor(norm_root, limit_hit_at[0])
            elif not stopped_early:
                self._write_cursor(norm_root, "")

            # Clear any satisfied deferred queue item (and subpaths) for norm_root
            if not any_subpath_deferred and not stopped_early:
                self.remove_deferred_path(norm_root)

            # Roll up folder manifest for norm_root (zero disk I/O, pure SQLite)
            if not stopped_early and os.path.isdir(norm_root):
                try:
                    self.refresh_folder_manifest(norm_root)
                except Exception as e:
                    logger.debug(f"[RAG] Failed updating folder manifest for {norm_root}: {e}")

            self._last_sync_ts = time.time()
            final_status = "stopped" if stopped_early else "completed"
            if _reset_control_flags:
                self._sync_state = final_status
                self._sync_progress.update(
                    {
                        "state": final_status,
                        "current_path": "",
                        "indexed_files": indexed_new_or_updated,
                        "skipped_unchanged": skipped_unchanged,
                        "deferred_standby": deferred_standby,
                        "errors": errors_count,
                        "updated_at": self._last_sync_ts,
                        "message": (
                            f"Sync stopped on {norm_root} ({indexed_new_or_updated} indexed)."
                            if stopped_early
                            else f"Reached the limit of {max_files} files in {norm_root}: {indexed_new_or_updated} indexed, "
                            f"{skipped_unchanged} unchanged. The next run goes on from {limit_hit_at[0]}."
                            if limit_hit_at
                            else f"Completed {norm_root}: {indexed_new_or_updated} indexed, {skipped_unchanged} unchanged, {deferred_standby} deferred."
                            + (
                                f" {upgrade_waiting[0]} files wait for the overnight re-index."
                                if upgrade_waiting[0]
                                else ""
                            )
                        ),
                        "limit_reached": bool(limit_hit_at),
                    }
                )
            return {
                "status": final_status,
                "path": norm_root,
                "indexed_files": indexed_new_or_updated,
                "skipped_unchanged": skipped_unchanged,
                "deferred_standby": deferred_standby,
                "errors": errors_count,
                "removed": len(stale_ids),
                "limit_reached": bool(limit_hit_at),
                "resume_from": limit_hit_at[0] if limit_hit_at else None,
                "upgrade_waiting": upgrade_waiting[0],
            }
        finally:
            if _reset_control_flags:
                self._is_indexing = False

    def _reuse_same_content(
        self,
        canonical_path: str,
        file_name: str,
        size_bytes: int,
        mtime_ns: int,
        sha256_hex: str,
        backing_dev: str,
        vis_tier: str,
        owner_user: str,
        share_name: str,
        allowed_csv: str,
    ) -> int | None:
        """The index entry for this content, if one exists (AI-35). When its old path is gone the
        entry is moved here (a move or rename); otherwise it is cloned with its chunks, vectors,
        photo analysis and tags (a copy). None when there is nothing to reuse."""
        model = str(self.get_config().get("embedding_model") or "zett_lexical_384d")
        now = time.time()
        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                src = conn.execute(
                    """
                    SELECT * FROM indexed_files
                    WHERE sha256_hash = ? AND size_bytes = ? AND parse_status = 'ok' AND index_version = ?
                      AND canonical_path != ? AND embedding_model IN (?, ?)
                    ORDER BY last_verified_at DESC LIMIT 1
                    """,
                    (sha256_hex, size_bytes, _core().CURRENT_INDEX_VERSION, canonical_path, model, "zett_lexical_384d"),
                ).fetchone()
                if src is None:
                    return None
                old_path, old_name = str(src["canonical_path"]), str(src["file_name"])
                fields = {
                    "canonical_path": canonical_path,
                    "parent_dir": os.path.dirname(canonical_path),
                    "file_name": file_name,
                    "mtime_ns": mtime_ns,
                    "size_bytes": size_bytes,
                    "backing_dev": backing_dev,
                    "share_name": share_name,
                    "visibility_tier": vis_tier,
                    "owner_username": owner_user,
                    "allowed_users_csv": allowed_csv,
                    "last_verified_at": now,
                }
                if src["doc_title"] == os.path.splitext(old_name)[0]:
                    fields["doc_title"] = os.path.splitext(file_name)[0]
                rbac = (file_name, vis_tier, owner_user, share_name, allowed_csv)
                if self._path_gone(old_path, str(src["backing_dev"] or "")):
                    file_id = int(src["file_id"])
                    sets = ", ".join(f"{k} = ?" for k in fields)
                    conn.execute(f"UPDATE indexed_files SET {sets} WHERE file_id = ?", [*fields.values(), file_id])
                    how = "moved"
                else:
                    file_id = self._clone_entry(conn, src, {**fields, "indexed_at": now})
                    how = "copied"
                if how == "moved":
                    for table in ("document_chunks", "photo_assets"):
                        conn.execute(
                            f"UPDATE {table} SET file_name = ?, visibility_tier = ?, owner_username = ?, share_name = ?,"
                            " allowed_users_csv = ? WHERE file_id = ?",
                            (*rbac, file_id),
                        )
                conn.commit()
                logger.info(
                    f"[RAG] {sanitize_string(canonical_path)}: {how} from {sanitize_string(old_path)}, not read again"
                )
                return file_id
            except sqlite3.Error as e:
                conn.rollback()
                logger.debug(f"[RAG] Reuse of known content skipped: {e}")
                return None
            finally:
                conn.close()

    @staticmethod
    def _path_gone(path: str, backing_dev: str) -> bool:
        """The old path no longer exists; a sleeping disk counts as still there (no wake-up)."""
        if backing_dev and rag_standby.is_backing_disk_in_standby(backing_dev):
            return False
        return not os.path.lexists(path)

    def _clone_entry(self, conn: sqlite3.Connection, src: sqlite3.Row, fields: dict[str, Any]) -> int:
        """A new entry for a copy: the source's analysis under the copy's path and permissions."""
        cols = [k for k in src.keys() if k != "file_id"]
        vals = {**dict(src), **fields}
        cur = conn.execute(
            f"INSERT INTO indexed_files ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [vals[c] for c in cols],
        )
        new_id = int(cur.lastrowid or 0)
        rbac = {
            k: fields[k] for k in ("file_name", "visibility_tier", "owner_username", "share_name", "allowed_users_csv")
        }
        id_map: dict[int, int] = {}
        chunks = conn.execute(
            "SELECT * FROM document_chunks WHERE file_id = ? ORDER BY chunk_level != 'parent', chunk_id",
            (int(src["file_id"]),),
        ).fetchall()
        for ch in chunks:
            row = {**dict(ch), **rbac, "file_id": new_id}
            old_cid = row.pop("chunk_id")
            if row.get("parent_chunk_id") is not None:
                row["parent_chunk_id"] = id_map.get(int(row["parent_chunk_id"]))
            names = list(row)
            cur_c = conn.execute(
                f"INSERT INTO document_chunks ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                [row[n] for n in names],
            )
            id_map[int(old_cid)] = int(cur_c.lastrowid or 0)
            dim = int(row.get("embedding_dim") or 0)
            if (
                row.get("chunk_level") != "parent"
                and row.get("embedding_model") != "zett_lexical_384d"
                and dim == self._vec_table_dim
            ):
                self.sync_vector_chunk(
                    conn, id_map[int(old_cid)], row["embedding_f32"], new_id, rbac["visibility_tier"], dim=dim
                )
        photo = conn.execute("SELECT * FROM photo_assets WHERE file_id = ?", (int(src["file_id"]),)).fetchone()
        if photo is not None:
            prow = {**dict(photo), **rbac, "file_id": new_id}
            names = list(prow)
            conn.execute(
                f"INSERT INTO photo_assets ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                [prow[n] for n in names],
            )
        for table in ("doc_tags",):
            conn.execute(
                f"INSERT OR IGNORE INTO {table} (file_id, tag) SELECT ?, tag FROM {table} WHERE file_id = ?",
                (new_id, int(src["file_id"])),
            )
        conn.execute(
            "INSERT OR IGNORE INTO doc_tags_done (file_id) SELECT ? WHERE EXISTS "
            "(SELECT 1 FROM doc_tags_done WHERE file_id = ?)",
            (new_id, int(src["file_id"])),
        )
        return new_id

    def _cursor_file(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "rag_cursors.json")

    def _read_cursor(self, root: str) -> str:
        """Where the last run of `root` stopped at the file limit; "" for the start (AI-34)."""
        data = read_json(self._cursor_file(), {}) or {}
        return str(data.get(root) or "") if isinstance(data, dict) else ""

    def _write_cursor(self, root: str, path: str) -> None:
        with locked_json(self._cursor_file()):
            data = read_json(self._cursor_file(), {}) or {}
            data = data if isinstance(data, dict) else {}
            if (data.get(root) or "") == path:
                return
            if path:
                data[root] = path
            else:
                data.pop(root, None)
            try:
                atomic_write_json(self._cursor_file(), data)
            except OSError as e:
                logger.warning(f"[RAG] Could not save where indexing stopped: {e}")

    def _record_deferred_subpath(self, subpath: str, dev: str) -> None:
        """Queues a file or folder on a sleeping disk to be learned when the disk spins up."""
        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                conn.execute(
                    """
                    INSERT INTO rag_deferred_queue(target_path, backing_dev, reason, queued_at, priority)
                    VALUES (?, ?, 'disk_standby', ?, 0)
                    ON CONFLICT(target_path) DO UPDATE SET queued_at = excluded.queued_at
                    """,
                    (subpath, dev, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def _scanned_pdf_text(self, canonical_path: str, mtime_ns: int) -> str:
        """Text the vision queue read from a scanned PDF's page images (D3), if any."""
        try:
            conn = self._get_conn(readonly=True)
            try:
                row = conn.execute(
                    "SELECT text FROM pdf_ocr WHERE path = ? AND mtime_ns = ?", (canonical_path, int(mtime_ns))
                ).fetchone()
            finally:
                conn.close()
            return str(row[0]) if row and row[0] else ""
        except sqlite3.Error:
            return ""  # no OCR table yet

    def _index_single_file(
        self,
        canonical_path: str,
        file_name: str,
        file_ext: str,
        size_bytes: int,
        mtime_ns: int,
        cached_row: sqlite3.Row | None,
        respect_standby: bool | None = None,
        force_wake: bool = False,
    ) -> int | None:
        """Hashes, parses, embeds, and persists a single document, code file, or photo into rag_index.db."""
        now = time.time()
        parent_dir = os.path.dirname(canonical_path)
        backing_dev = rag_standby.resolve_path_backing_dev(canonical_path)
        vis_tier, owner_user, share_name, allowed_csv = _core().classify_path_rbac(canonical_path)

        cfg = self.get_config()
        effective_respect_standby = (
            bool(cfg.get("respect_standby", True)) if respect_standby is None else bool(respect_standby)
        )
        if effective_respect_standby and not force_wake:
            if rag_standby.is_backing_disk_in_standby(backing_dev):
                logger.debug(
                    f"[RAG Standby Guard] Aborting _index_single_file for sleeping disk {backing_dev}: {canonical_path}"
                )
                return None

        is_video = file_ext in VIDEO_EXTENSIONS

        # Compute streaming SHA-256 (for large video files > 10MB, use fast sparse header+footer fingerprint)
        h = hashlib.sha256()
        try:
            with open(canonical_path, "rb") as f:
                if is_video and size_bytes > 10 * 1024 * 1024:
                    h.update(f.read(65536))
                    if size_bytes > 131072:
                        f.seek(max(0, size_bytes - 65536))
                        h.update(f.read(65536))
                    h.update(f"{size_bytes}_{mtime_ns}".encode())
                else:
                    while True:
                        block = f.read(65536)
                        if not block:
                            break
                        h.update(block)
            sha256_hex = h.hexdigest()
        except Exception as e:
            logger.debug(f"[RAG] Failed reading {canonical_path}: {e}")
            return None

        # Touch immunity: if SHA-256 matches existing row at same path, just update mtime_ns
        if (
            cached_row is not None
            and cached_row["sha256_hash"] == sha256_hex
            and int(cached_row["index_version"]) == _core().CURRENT_INDEX_VERSION
            and cached_row["parse_status"] == "ok"
        ):
            with self._write_lock:
                conn = self._get_conn(readonly=False)
                try:
                    conn.execute(
                        """
                        UPDATE indexed_files
                        SET mtime_ns = ?, size_bytes = ?, last_verified_at = ?,
                            visibility_tier = ?, owner_username = ?, share_name = ?, allowed_users_csv = ?
                        WHERE file_id = ?
                        """,
                        (
                            mtime_ns,
                            size_bytes,
                            now,
                            vis_tier,
                            owner_user,
                            share_name,
                            allowed_csv,
                            int(cached_row["file_id"]),
                        ),
                    )
                    conn.commit()
                    return int(cached_row["file_id"])
                finally:
                    conn.close()

        # AI-35: a file whose content is already indexed (moved, renamed or copied) is not read and
        # embedded again: the entry moves with it, or a copy gets the same analysis
        if cached_row is None:
            reused = self._reuse_same_content(
                canonical_path,
                file_name,
                size_bytes,
                mtime_ns,
                sha256_hex,
                backing_dev,
                vis_tier,
                owner_user,
                share_name,
                allowed_csv,
            )
            if reused is not None:
                return reused

        is_image = file_ext in IMAGE_EXTENSIONS
        is_video = file_ext in VIDEO_EXTENSIONS
        is_audio = file_ext in AUDIO_EXTENSIONS
        modality = (
            "image"
            if is_image
            else (
                "video"
                if is_video
                else ("audio" if is_audio else ("code" if file_ext in CODE_EXTENSIONS else "document"))
            )
        )

        if is_image:
            photo_data = None
            # Check backing disk standby status (AGENTS.md §1.2 Spindown Invariant)
            if rag_standby.is_backing_disk_in_standby(backing_dev):
                cached_thumb = None
                with self._write_lock:
                    conn = self._get_conn(readonly=True)
                    try:
                        t_row = conn.execute(
                            "SELECT p.thumb_webp FROM photo_assets p JOIN indexed_files f ON f.file_id = p.file_id WHERE f.canonical_path = ?",
                            (canonical_path,),
                        ).fetchone()
                        if t_row and t_row["thumb_webp"]:
                            cached_thumb = t_row["thumb_webp"]
                    finally:
                        conn.close()
                if cached_thumb:
                    try:
                        photo_data = _core().analyze_photo_asset(cached_thumb, file_name)
                    except Exception as e:
                        logger.debug(f"[RAG] Failed thumbnail analysis {sanitize_string(canonical_path)}: {e}")
                else:
                    self._record_deferred_subpath(canonical_path, backing_dev)
                    return None

            if photo_data is None:
                try:
                    photo_data = _core().analyze_photo_asset(canonical_path, file_name)
                except Exception as e:
                    logger.debug(f"[RAG] Corrupt image {sanitize_string(canonical_path)}: {e}")
                    return self._record_parse_error(
                        canonical_path,
                        parent_dir,
                        file_name,
                        file_ext,
                        modality,
                        size_bytes,
                        mtime_ns,
                        sha256_hex,
                        backing_dev,
                        vis_tier,
                        owner_user,
                        share_name,
                        allowed_csv,
                    )

            ocr_text = photo_data.get("ocr_text", "")
            doc_type = "photo"
            doc_title = os.path.splitext(file_name)[0]
            doc_meta: dict[str, Any] = {
                "width": photo_data["width"],
                "height": photo_data["height"],
                "dominant_hex": photo_data["dominant_hex"],
                "scene_tags": photo_data["scene_tags"],
                "object_colors": photo_data["object_colors"],
            }
            ocr_chunks: list[dict[str, Any]] = []
            ocr_parent_chunks: list[dict[str, Any]] = []
            if ocr_text:
                parsed_type, parsed_title, parsed_meta, ocr_chunks, ocr_parent_chunks = (
                    generate_contextual_hierarchical_chunks(file_name, ".txt", ocr_text, canonical_path)
                )
                if parsed_type in ("recipe", "invoice"):
                    doc_type = parsed_type
                    doc_title = parsed_title
                    doc_meta.update(parsed_meta)
                    doc_meta["is_photo_ocr"] = True

            doc_meta_json = json.dumps(doc_meta)

            # Text read from the photo gets the same neural vectors as documents, so search
            # finds it by meaning; keyword vectors only when the embedding model is unavailable.
            cfg = self.get_config()
            ocr_model = cfg.get("embedding_model") or "embeddinggemma"
            ocr_texts = [
                format_embeddinggemma_document(
                    file_name, text_for_embedding(".txt", f"{ch['heading_context']} {ch['chunk_text']}".strip())
                )
                for ch in ocr_chunks
            ]
            ocr_blobs = None
            if ocr_texts and ocr_model != "zett_lexical_384d":
                ocr_blobs = _core().compute_neural_embeddings_batch(
                    ocr_texts, ocr_model, target_dim=cfg.get("embedding_dim"), host=embedding_host(cfg)
                )
            ocr_file_model = ocr_model if ocr_blobs is not None else "zett_lexical_384d"

            with self._write_lock:
                conn = self._get_conn(readonly=False)
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO indexed_files (
                            canonical_path, parent_dir, file_name, file_ext, modality,
                            doc_type, doc_title, doc_metadata_json, size_bytes, mtime_ns,
                            sha256_hash, backing_dev, share_name, visibility_tier,
                            owner_username, allowed_users_csv, parse_status, index_version,
                            chunk_count, indexed_at, last_verified_at, embedding_model
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?)
                        ON CONFLICT(canonical_path) DO UPDATE SET
                            parent_dir = excluded.parent_dir,
                            file_name = excluded.file_name,
                            file_ext = excluded.file_ext,
                            modality = excluded.modality,
                            doc_type = excluded.doc_type,
                            doc_title = excluded.doc_title,
                            doc_metadata_json = excluded.doc_metadata_json,
                            size_bytes = excluded.size_bytes,
                            mtime_ns = excluded.mtime_ns,
                            sha256_hash = excluded.sha256_hash,
                            backing_dev = excluded.backing_dev,
                            share_name = excluded.share_name,
                            visibility_tier = excluded.visibility_tier,
                            owner_username = excluded.owner_username,
                            allowed_users_csv = excluded.allowed_users_csv,
                            parse_status = 'ok',
                            index_version = excluded.index_version,
                            chunk_count = excluded.chunk_count,
                            indexed_at = excluded.indexed_at,
                            last_verified_at = excluded.last_verified_at,
                            embedding_model = excluded.embedding_model
                        """,
                        (
                            canonical_path,
                            parent_dir,
                            file_name,
                            file_ext,
                            modality,
                            doc_type,
                            doc_title,
                            doc_meta_json,
                            size_bytes,
                            mtime_ns,
                            sha256_hex,
                            backing_dev,
                            share_name,
                            vis_tier,
                            owner_user,
                            allowed_csv,
                            _core().CURRENT_INDEX_VERSION,
                            len(ocr_chunks),
                            now,
                            now,
                            ocr_file_model,
                        ),
                    )
                    row_id = conn.execute(
                        "SELECT file_id FROM indexed_files WHERE canonical_path = ?", (canonical_path,)
                    ).fetchone()
                    file_id = int(row_id["file_id"]) if row_id else int(cur.lastrowid or 0)

                    conn.execute("DELETE FROM photo_assets WHERE file_id = ?", (file_id,))
                    conn.execute(
                        """
                        INSERT INTO photo_assets (
                            file_id, file_name, width, height, aspect_ratio, format,
                            taken_at, camera_make, camera_model, gps_lat, gps_lon,
                            phash_hex, dominant_hex, palette_json, object_colors_json,
                            frame_colors_json, object_colors_text, color_hist_f32,
                            center_color_hist_f32, scene_tags_json, auto_tags_text,
                            caption_text, ocr_text, vision_embedding_f32, thumb_webp,
                            visibility_tier, owner_username, share_name, allowed_users_csv
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file_id,
                            file_name,
                            photo_data["width"],
                            photo_data["height"],
                            photo_data["aspect_ratio"],
                            photo_data["format"],
                            photo_data["taken_at"],
                            photo_data["camera_make"],
                            photo_data["camera_model"],
                            photo_data["gps_lat"],
                            photo_data["gps_lon"],
                            photo_data["phash_hex"],
                            photo_data["dominant_hex"],
                            photo_data["palette_json"],
                            photo_data["object_colors_json"],
                            photo_data["frame_colors_json"],
                            photo_data["object_colors_text"],
                            photo_data["color_hist_f32"],
                            photo_data["center_color_hist_f32"],
                            photo_data["scene_tags_json"],
                            photo_data["auto_tags_text"],
                            photo_data["caption_text"],
                            ocr_text,
                            photo_data["vision_embedding_f32"],
                            photo_data["thumb_webp"],
                            vis_tier,
                            owner_user,
                            share_name,
                            allowed_csv,
                        ),
                    )

                    self._drop_file_vectors(conn, "?", (file_id,))
                    conn.execute("DELETE FROM document_chunks WHERE file_id = ?", (file_id,))
                    ocr_parent_id_map: dict[int, int] = {}
                    for p in ocr_parent_chunks:
                        # parents only give context, like document parents: no vector
                        cur_p = conn.execute(
                            """
                            INSERT INTO document_chunks (
                                file_id, chunk_index, parent_chunk_id, chunk_level, source_modality, file_name, doc_type,
                                heading_context, structural_context, chunk_text, raw_chunk_text, doc_metadata_json,
                                line_start, line_end, token_count, embedding_f32, embedding_model, embedding_dim,
                                visibility_tier, owner_username, share_name, allowed_users_csv
                            ) VALUES (?, ?, NULL, 'parent', 'photo_ocr', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                            """,
                            (
                                file_id,
                                -(p["parent_index"] + 1),
                                file_name,
                                doc_type,
                                p["heading_context"],
                                "",
                                p["chunk_text"],
                                p.get("raw_chunk_text", p["chunk_text"]),
                                doc_meta_json,
                                p["line_start"],
                                p["line_end"],
                                p["token_count"],
                                b"",
                                ocr_file_model,
                                vis_tier,
                                owner_user,
                                share_name,
                                allowed_csv,
                            ),
                        )
                        ocr_parent_id_map[p["parent_index"]] = int(cur_p.lastrowid)

                    for i, ch in enumerate(ocr_chunks):
                        if ocr_blobs is not None:
                            ch_blob = ocr_blobs[i]
                        else:
                            ch_blob, _ = compute_384d_embedding(text=ocr_texts[i], scene_tags=photo_data["scene_tags"])
                        ch_dim = len(ch_blob) // 4
                        _pi = ch.get("parent_index")
                        p_id = ocr_parent_id_map.get(_pi) if _pi is not None else None
                        cur_c = conn.execute(
                            """
                            INSERT INTO document_chunks (
                                file_id, chunk_index, parent_chunk_id, chunk_level, source_modality, file_name, doc_type,
                                heading_context, structural_context, chunk_text, raw_chunk_text, doc_metadata_json,
                                line_start, line_end, token_count, embedding_f32, embedding_model, embedding_dim,
                                visibility_tier, owner_username, share_name, allowed_users_csv
                            ) VALUES (?, ?, ?, 'child', 'photo_ocr', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                file_id,
                                ch["chunk_index"],
                                p_id,
                                file_name,
                                doc_type,
                                ch["heading_context"],
                                ch.get("structural_context", ""),
                                ch["chunk_text"],
                                ch.get("raw_chunk_text", ch["chunk_text"]),
                                doc_meta_json,
                                ch["line_start"],
                                ch["line_end"],
                                ch["token_count"],
                                ch_blob,
                                ocr_file_model,
                                ch_dim,
                                vis_tier,
                                owner_user,
                                share_name,
                                allowed_csv,
                            ),
                        )
                        if ocr_blobs is not None and ch_dim == self._vec_table_dim:
                            self.sync_vector_chunk(
                                conn, int(cur_c.lastrowid or 0), ch_blob, file_id, vis_tier, dim=ch_dim
                            )

                    conn.commit()
                    return file_id
                finally:
                    conn.close()

        # Document or Code modality
        raw_text = extract_document_text(canonical_path, file_ext)
        if looks_like_binary(raw_text):  # never index or embed binary data as text
            raw_text = ""
        if file_ext.lower() == ".pdf" and len(raw_text.strip()) < 80:
            raw_text = (raw_text + "\n" + self._scanned_pdf_text(canonical_path, mtime_ns)).strip()  # D3
        if not raw_text.strip():
            base_clean = re.sub(r"[._\-]+", " ", os.path.splitext(file_name)[0]).strip()
            parent_clean = os.path.basename(parent_dir)
            raw_text = f"Document: {base_clean}\nFile Name: {file_name}\nFormat: {file_ext}\nFolder: {parent_clean}"

        doc_type, doc_title, doc_meta, child_chunks, parent_chunks = generate_contextual_hierarchical_chunks(
            file_name, file_ext, raw_text, canonical_path
        )
        doc_meta_json = json.dumps(doc_meta)

        cfg = self.get_config()
        configured_emb_model = cfg.get("embedding_model") or "embeddinggemma"
        target_dim = cfg.get("embedding_dim")
        effective_file_emb_model = "zett_lexical_384d"

        effective_title = doc_title or file_name
        lexical_tags = (
            ["recipe", "food"]
            if doc_type == "recipe"
            else (["receipt", "document"] if doc_type == "invoice" else ["document"])
        )
        child_texts = [
            format_embeddinggemma_document(
                effective_title, text_for_embedding(file_ext, f"{ch['heading_context']} {ch['chunk_text']}".strip())
            )
            for ch in child_chunks
        ]
        # One batched call per file; every vector of a file comes from the same model (AI-15).
        neural_blobs = None
        if configured_emb_model != "zett_lexical_384d":
            neural_blobs = _core().compute_neural_embeddings_batch(
                child_texts, configured_emb_model, target_dim=target_dim, host=embedding_host(cfg)
            )
        if neural_blobs is not None:
            effective_file_emb_model = configured_emb_model
            all_blobs = neural_blobs
        else:
            all_blobs = [compute_384d_embedding(text=t, scene_tags=lexical_tags)[0] for t in child_texts]
        prepared_child_chunks: list[tuple[dict[str, Any], bytes]] = list(zip(child_chunks, all_blobs, strict=False))
        # Parents only give their children context in answers; search never ranks them, so they get
        # no vector (they are the longest chunks, and they took nearest-neighbour slots)
        prepared_parent_chunks: list[tuple[dict[str, Any], bytes]] = [(p, b"") for p in parent_chunks]

        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                cur = conn.execute(
                    """
                    INSERT INTO indexed_files (
                        canonical_path, parent_dir, file_name, file_ext, modality,
                        doc_type, doc_title, doc_metadata_json, size_bytes, mtime_ns,
                        sha256_hash, backing_dev, share_name, visibility_tier,
                        owner_username, allowed_users_csv, parse_status, index_version,
                        chunk_count, indexed_at, last_verified_at, embedding_model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_path) DO UPDATE SET
                        parent_dir = excluded.parent_dir,
                        file_name = excluded.file_name,
                        file_ext = excluded.file_ext,
                        modality = excluded.modality,
                        doc_type = excluded.doc_type,
                        doc_title = excluded.doc_title,
                        doc_metadata_json = excluded.doc_metadata_json,
                        size_bytes = excluded.size_bytes,
                        mtime_ns = excluded.mtime_ns,
                        sha256_hash = excluded.sha256_hash,
                        backing_dev = excluded.backing_dev,
                        share_name = excluded.share_name,
                        visibility_tier = excluded.visibility_tier,
                        owner_username = excluded.owner_username,
                        allowed_users_csv = excluded.allowed_users_csv,
                        parse_status = 'ok',
                        index_version = excluded.index_version,
                        chunk_count = excluded.chunk_count,
                        indexed_at = excluded.indexed_at,
                        last_verified_at = excluded.last_verified_at,
                        embedding_model = excluded.embedding_model
                    """,
                    (
                        canonical_path,
                        parent_dir,
                        file_name,
                        file_ext,
                        modality,
                        doc_type,
                        doc_title,
                        doc_meta_json,
                        size_bytes,
                        mtime_ns,
                        sha256_hex,
                        backing_dev,
                        share_name,
                        vis_tier,
                        owner_user,
                        allowed_csv,
                        _core().CURRENT_INDEX_VERSION,
                        len(prepared_child_chunks),
                        now,
                        now,
                        effective_file_emb_model,
                    ),
                )
                row_id = conn.execute(
                    "SELECT file_id FROM indexed_files WHERE canonical_path = ?", (canonical_path,)
                ).fetchone()
                file_id = int(row_id["file_id"]) if row_id else int(cur.lastrowid or 0)

                self._drop_file_vectors(conn, "?", (file_id,))
                conn.execute("DELETE FROM document_chunks WHERE file_id = ?", (file_id,))
                # auto-tags for the document filters (B8), from the text just read
                from backend.services import rag_tags

                rag_tags.store(
                    conn,
                    file_id,
                    rag_tags.tags_for(
                        file_name, doc_title, doc_type, " ".join(ch["chunk_text"] for ch, _ in prepared_child_chunks)
                    ),
                )
                parent_id_map: dict[int, int] = {}
                for p, p_emb in prepared_parent_chunks:
                    p_dim = len(p_emb) // 4
                    cur_p = conn.execute(
                        """
                        INSERT INTO document_chunks (
                            file_id, chunk_index, parent_chunk_id, chunk_level, source_modality, file_name, doc_type,
                            heading_context, structural_context, chunk_text, raw_chunk_text, doc_metadata_json,
                            line_start, line_end, token_count, embedding_f32, embedding_model, embedding_dim,
                            visibility_tier, owner_username, share_name, allowed_users_csv
                        ) VALUES (?, ?, NULL, 'parent', ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file_id,
                            -(p["parent_index"] + 1),
                            modality,
                            file_name,
                            doc_type,
                            p["heading_context"],
                            p["chunk_text"],
                            p.get("raw_chunk_text", p["chunk_text"]),
                            doc_meta_json,
                            p["line_start"],
                            p["line_end"],
                            p["token_count"],
                            p_emb,
                            effective_file_emb_model,
                            p_dim,
                            vis_tier,
                            owner_user,
                            share_name,
                            allowed_csv,
                        ),
                    )
                    parent_id_map[p["parent_index"]] = int(cur_p.lastrowid)

                for ch, emb_blob in prepared_child_chunks:
                    _pi = ch.get("parent_index")
                    p_id = parent_id_map.get(_pi) if _pi is not None else None
                    ch_dim = len(emb_blob) // 4
                    cur_c = conn.execute(
                        """
                        INSERT INTO document_chunks (
                            file_id, chunk_index, parent_chunk_id, chunk_level, source_modality, file_name, doc_type,
                            heading_context, structural_context, chunk_text, raw_chunk_text, doc_metadata_json,
                            line_start, line_end, token_count, embedding_f32, embedding_model, embedding_dim,
                            visibility_tier, owner_username, share_name, allowed_users_csv
                        ) VALUES (?, ?, ?, 'child', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file_id,
                            ch["chunk_index"],
                            p_id,
                            modality,
                            file_name,
                            doc_type,
                            ch["heading_context"],
                            ch.get("structural_context", ""),
                            ch["chunk_text"],
                            ch.get("raw_chunk_text", ch["chunk_text"]),
                            doc_meta_json,
                            ch["line_start"],
                            ch["line_end"],
                            ch["token_count"],
                            emb_blob,
                            effective_file_emb_model,
                            ch_dim,
                            vis_tier,
                            owner_user,
                            share_name,
                            allowed_csv,
                        ),
                    )
                    if effective_file_emb_model != "zett_lexical_384d" and ch_dim == self._vec_table_dim:
                        self.sync_vector_chunk(conn, int(cur_c.lastrowid or 0), emb_blob, file_id, vis_tier, dim=ch_dim)
                conn.commit()
                return file_id
            finally:
                conn.close()

    def _record_parse_error(
        self,
        canonical_path: str,
        parent_dir: str,
        file_name: str,
        file_ext: str,
        modality: str,
        size_bytes: int,
        mtime_ns: int,
        sha256_hex: str,
        backing_dev: str,
        vis_tier: str,
        owner_user: str,
        share_name: str,
        allowed_csv: str,
    ) -> int | None:
        """Records a poison-pill tombstone so corrupt files are skipped on future incremental scans."""
        now = time.time()
        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                conn.execute(
                    """
                    INSERT INTO indexed_files (
                        canonical_path, parent_dir, file_name, file_ext, modality,
                        doc_type, doc_title, doc_metadata_json, size_bytes, mtime_ns,
                        sha256_hash, backing_dev, share_name, visibility_tier,
                        owner_username, allowed_users_csv, parse_status, index_version,
                        chunk_count, indexed_at, last_verified_at
                    ) VALUES (?, ?, ?, ?, ?, 'generic', ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, 'parse_error', ?, 0, ?, ?)
                    ON CONFLICT(canonical_path) DO UPDATE SET
                        mtime_ns = excluded.mtime_ns,
                        size_bytes = excluded.size_bytes,
                        sha256_hash = excluded.sha256_hash,
                        parse_status = 'parse_error',
                        index_version = excluded.index_version,
                        last_verified_at = excluded.last_verified_at
                    """,
                    (
                        canonical_path,
                        parent_dir,
                        file_name,
                        file_ext,
                        modality,
                        file_name,
                        size_bytes,
                        mtime_ns,
                        sha256_hex,
                        backing_dev,
                        share_name,
                        vis_tier,
                        owner_user,
                        allowed_csv,
                        _core().CURRENT_INDEX_VERSION,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return None
            finally:
                conn.close()

    def sync_vector_chunk(
        self,
        conn: sqlite3.Connection,
        chunk_id: int,
        embedding_blob: bytes,
        file_id: int,
        visibility_tier: str = "public_share",
        dim: int | None = None,
    ) -> None:
        """
        Synchronizes a chunk's vector into the decoupled vec_chunks_{dim} virtual table.
        Decoupled Python code avoids SQLite trigger crashes when extensions or dimensions differ.
        """
        target_dim = dim or self._vec_table_dim
        if not self._has_sqlite_vec or not self._vec_table_active or self._vec_table_dim != target_dim:
            return
        if not embedding_blob or len(embedding_blob) != target_dim * 4:
            return
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO vec_chunks_{target_dim}(chunk_id, embedding, file_id, visibility_tier) VALUES (?, ?, ?, ?)",
                (chunk_id, embedding_blob, file_id, visibility_tier),
            )
        except Exception as e:
            logger.debug("Vector table sync deferred for chunk %d: %s", chunk_id, e)

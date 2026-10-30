"""Standby-safe learning, the deferred queue, sync control and re-embedding for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

# pyright: reportAttributeAccessIssue=false

import asyncio
import os
import sqlite3
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
)
from backend.ignored_errors import ignored
from backend.logging_config import (  # noqa: F401
    sanitize_string,
)
from backend.services import (  # noqa: F401
    rag_standby,
)
from backend.services.ai_activity import upgrade_window_open
from backend.services.rag_embeddings import (  # noqa: F401
    chunk_embedding_text,
    embedding_host,
    format_embeddinggemma_document,
)
from backend.services.rag_text import (  # noqa: F401
    text_for_embedding,
)
from backend.settings import test_mode


def _core():
    """backend.services.rag_engine, read at call time: shared settings live there and tests patch them."""
    from backend.services import rag_engine

    return rag_engine


FRESH_RESCAN_SSD_SECS = 3600  # SSD and NVMe pools: hourly
FRESH_RESCAN_HDD_SECS = 12 * 3600  # spinning disks that happen to be awake: twice a day


# How often the watcher looks for disks that woke up and for deferred work (PERF-5)
SPINUP_WATCH_SECS = 30.0
WATCH_FULL_EVERY_SECS = 300.0  # the queue checks run at least this often even when nothing changed


def _is_solid_state(dev: str | None) -> bool:
    """True for NVMe/SSD devices (sysfs rotational = 0); unknown counts as spinning."""
    if not dev:
        return False
    import backend.config as config

    base = str(getattr(config, "HOST_SYS", "/sys") or "/sys")
    name = os.path.basename(str(dev))
    for candidate in (name, name.rstrip("0123456789") if not name.startswith("nvme") else name.split("p")[0]):
        try:
            with open(os.path.join(base, "block", candidate, "queue", "rotational"), encoding="ascii") as f:
                return f.read().strip() == "0"
        except OSError:
            continue
    return name.startswith("nvme")


def upgrade_pass_paths(engine: Any, cfg: dict[str, Any], excluded: set[str], already: list[str]) -> list[str]:
    """The watched folders on awake disks to pass over tonight for the re-index (AI-30): once a
    night, inside the upgrade hours, while entries made the old way remain."""
    from backend.services import ai_activity

    get_conn = getattr(engine, "_get_conn", None)
    tonight = time.strftime("%Y-%m-%d", time.localtime(time.time()))
    if (
        get_conn is None
        or not ai_activity.upgrade_window_open(time.time())
        or getattr(engine, "_upgrade_pass_on", "") == tonight
    ):
        return []
    conn = get_conn(readonly=True)
    try:
        pending = conn.execute(
            "SELECT 1 FROM indexed_files WHERE index_version != ? AND parse_status = 'ok' LIMIT 1",
            (_core().CURRENT_INDEX_VERSION,),
        ).fetchone()
    finally:
        conn.close()
    if not pending:
        return []
    engine._upgrade_pass_on = tonight
    out = []
    for wp in cfg.get("watched_paths") or []:
        norm_wp = os.path.normpath(wp)
        if norm_wp in already or any(norm_wp == ex or norm_wp.startswith(ex.rstrip("/") + "/") for ex in excluded):
            continue
        dev = rag_standby.resolve_path_backing_dev(norm_wp)
        if rag_standby.is_backing_disk_in_standby(dev or norm_wp):
            continue  # never woken for it: its files are re-made a night it is awake
        out.append(norm_wp)
    return out


def _one_reembed_at_a_time(fn: Any) -> Any:
    """One re-embed at a time (AI-41): the nightly text upgrade and one started from the AI
    settings would otherwise share the staging table. A second one answers "busy"."""
    import functools

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not self._reembed_lock.acquire(blocking=False):
            if getattr(self, "_reembed_keep", None) is not None:
                self._text_upgrade_stop = True  # the nightly one makes way for this one (NAI-7)
                return {"status": "busy", "message": "The nightly re-embed is stopping. Start this again in a minute."}
            return {"status": "busy", "message": "A re-embed is already running."}
        try:
            return await fn(self, *args, **kwargs)
        finally:
            self._reembed_lock.release()

    return wrapper


class RagLearningMixin:
    """Standby-safe learning, the deferred queue, sync control and re-embedding for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

    # set by the nightly text upgrade: it re-embeds only while this says so (NAI-7)
    _reembed_keep: Any = None
    _reembed_why = ""

    def _reembed_go(self) -> bool:
        keep = self._reembed_keep
        if keep is None or keep():
            return True
        self._reembed_why = "Paused: it goes on tonight, in the hours set for it."
        return False

    @_one_reembed_at_a_time
    async def in_place_reembed_collection(
        self,
        target_model: str,
        target_dim: int,
        batch_size: int = 16,
        progress_callback: Any | None = None,
        target_host: str | None = None,
        retry_wait_s: float = 65.0,
        all_chunks: bool = False,
    ) -> dict[str, Any]:
        """Re-embeds every chunk with another model, from the index on SSD (no disk wake-ups).

        New vectors go to a staging table first; search keeps using the old ones until every
        chunk is done, then the index switches over in one transaction, together with the
        config (model, dimension, embedding host). Stopping half way (a restart, the model going
        away) loses nothing: the next run picks up the staged vectors. Chunks added while it
        runs are caught by the final passes. If the model stays unreachable, the run pauses
        instead of storing fallback vectors under the new model's name.
        """
        import time

        cfg = self.get_config()
        host = (target_host or "").strip() or None
        current = (cfg.get("embedding_model"), int(cfg.get("embedding_dim") or 0), (cfg.get("embedding_host") or None))
        same_target = current == (target_model, int(target_dim), host) and not all_chunks

        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS reembed_staging (
                        chunk_id INTEGER PRIMARY KEY, embedding BLOB NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL
                    )"""
                )
                # staged vectors for another target are useless now
                conn.execute("DELETE FROM reembed_staging WHERE model != ? OR dim != ?", (target_model, target_dim))
                conn.commit()
                total = conn.execute("SELECT COUNT(*) FROM document_chunks WHERE chunk_level != 'parent'").fetchone()[0]
            finally:
                conn.close()
        if total == 0:
            return {"status": "ok", "total": 0, "completed": 0, "message": "No chunks to re-embed"}

        def pending_ids() -> list[int]:
            # same model as now: only chunks that lack it; a new model: every chunk
            done_clause = "" if not same_target else "AND NOT (c.embedding_model = ? AND c.embedding_dim = ?)"
            params: tuple = () if not same_target else (target_model, target_dim)
            c = self._get_conn(readonly=True)
            try:
                rows = c.execute(
                    f"""SELECT c.chunk_id FROM document_chunks c
                        LEFT JOIN reembed_staging s ON s.chunk_id = c.chunk_id
                        WHERE s.chunk_id IS NULL AND c.chunk_level != 'parent' {done_clause} ORDER BY c.chunk_id""",
                    params,
                ).fetchall()
                return [int(r[0]) for r in rows]
            finally:
                c.close()

        def texts_for(ids: list[int]) -> list[tuple[int, str]]:
            c = self._get_conn(readonly=True)
            try:
                marks = ",".join("?" * len(ids))
                rows = c.execute(
                    f"""SELECT c.chunk_id, COALESCE(NULLIF(c.file_name, ''), f.file_name) AS file_name,
                               c.heading_context, c.chunk_text, c.raw_chunk_text, f.doc_title, f.file_ext
                        FROM document_chunks c LEFT JOIN indexed_files f ON f.file_id = c.file_id
                        WHERE c.chunk_id IN ({marks})""",
                    ids,
                ).fetchall()
            finally:
                c.close()
            mk = chunk_embedding_text
            return [
                (int(r["chunk_id"]), mk(r["doc_title"], r["file_name"] or "", dict(r), r["file_ext"] or ""))
                for r in rows
            ]

        def staged_count() -> int:
            c = self._get_conn(readonly=True)
            try:
                return int(
                    c.execute(
                        """SELECT COUNT(*) FROM reembed_staging s JOIN document_chunks c ON c.chunk_id = s.chunk_id
                           WHERE c.chunk_level != 'parent'"""
                    ).fetchone()[0]
                )
            finally:
                c.close()

        start_time = time.time()
        session_done = 0
        speed = 0.0

        def report(status: str, **extra: Any) -> dict[str, Any]:
            done = min(total, staged_count())
            data = {
                "type": "progress" if status == "running" else status,
                "status": status,
                "completed": done,
                "total": total,
                "speed": speed,
                "eta_sec": round((total - done) / speed, 1) if speed > 0 else 0.0,
                "percentage": round(100.0 * done / total, 1),
                "model": target_model,
                "updated_at": time.time(),
                **extra,
            }
            self._write_reindex_progress(data)
            if progress_callback:
                try:
                    progress_callback(data)
                except Exception:
                    logger.debug("[RAG] re-embed progress callback failed", exc_info=True)
            return data

        async def embed_and_stage(ids: list[int]) -> bool:
            nonlocal session_done, speed
            failures = 0
            for i in range(0, len(ids), 256):
                rows = texts_for(ids[i : i + 256])
                for j in range(0, len(rows), batch_size):
                    part = rows[j : j + batch_size]
                    if not self._reembed_go():
                        return False  # the nightly upgrade outside its hours, or asked to stop (NAI-7)
                    while True:
                        blobs = await asyncio.to_thread(
                            _core().compute_neural_embeddings_batch,
                            [t for _, t in part],
                            target_model,
                            target_dim,
                            host,
                            batch_size,
                        )
                        if blobs is not None:
                            failures = 0
                            break
                        failures += 1
                        if failures >= 5:
                            return False
                        report("running", message="The embedding model is not answering; retrying")
                        await asyncio.sleep(retry_wait_s)
                    with self._write_lock:
                        w = self._get_conn(readonly=False)
                        try:
                            w.executemany(
                                "INSERT OR REPLACE INTO reembed_staging(chunk_id, embedding, model, dim) VALUES (?, ?, ?, ?)",
                                [(cid, b, target_model, target_dim) for (cid, _), b in zip(part, blobs, strict=True)],
                            )
                            w.commit()
                        finally:
                            w.close()
                    session_done += len(part)
                    speed = round(session_done / max(0.001, time.time() - start_time), 2)
                    report("running")
                    await asyncio.sleep(0.02)  # let searches and the indexer in

            return True

        report("running")
        for _ in range(5):  # later passes pick up chunks indexed meanwhile
            ids = pending_ids()
            if not ids:
                break
            if not await embed_and_stage(ids):
                msg = self._reembed_why or f"Paused: '{target_model}' stopped answering. Start it again to continue."
                report("paused", message=msg)
                return {"status": "paused", "total": total, "completed": staged_count(), "message": msg}

        # Switch over: copy staged vectors in, rebuild the vector table, then the config
        with self._write_lock:
            late = pending_ids()
            if late and not await embed_and_stage(late):
                msg = self._reembed_why or f"Paused: '{target_model}' stopped answering. Start it again to continue."
                report("paused", message=msg)
                return {"status": "paused", "total": total, "completed": staged_count(), "message": msg}
            w = self._get_conn(readonly=False)
            try:
                w.execute(
                    """UPDATE document_chunks SET embedding_f32 = s.embedding, embedding_model = s.model, embedding_dim = s.dim
                       FROM reembed_staging s WHERE document_chunks.chunk_id = s.chunk_id"""
                )
                w.execute(
                    "UPDATE document_chunks SET embedding_f32 = X'', embedding_model = ?, embedding_dim = 0 WHERE chunk_level = 'parent'",
                    (target_model,),
                )
                w.execute("UPDATE indexed_files SET embedding_model = ?", (target_model,))
                if self._has_sqlite_vec and self._init_vec_table(w, target_dim, background=False):
                    table = _core().vec_table(target_dim)
                    w.execute(f"DROP TABLE IF EXISTS vec_chunks_{int(target_dim)}")  # filled anew below
                    self._vec_legacy = None
                    w.execute(f"DELETE FROM {table}")
                    w.execute(
                        f"""INSERT INTO {table}(chunk_id, embedding, file_id, visibility_tier)
                            SELECT chunk_id, vec_quantize_int8(embedding_f32, 'unit'), file_id, visibility_tier
                            FROM document_chunks WHERE embedding_model = ? AND embedding_dim = ?""",
                        (target_model, target_dim),
                    )
                w.execute("DELETE FROM reembed_staging")
                if not same_target:  # every chunk was embedded now, as chunks are embedded today
                    _core().set_embed_text_version(w, _core().EMBED_TEXT_VERSION)
                w.commit()
            finally:
                w.close()
            self.update_config(
                {"embedding_model": target_model, "embedding_dim": target_dim, "embedding_host": host or ""}
            )
            self._vec_table_dim = target_dim
            self._vec_table_active = bool(self._has_sqlite_vec)

        res_complete = {
            "status": "ok",
            "type": "complete",
            "total": total,
            "completed": total,
            "speed": speed,
            "eta_sec": 0.0,
            "percentage": 100.0,
            "duration_sec": round(time.time() - start_time, 2),
            "model": target_model,
            "dimension": target_dim,
            "updated_at": time.time(),
        }
        self._write_reindex_progress(dict(res_complete, status="complete"))
        if progress_callback:
            try:
                progress_callback(res_complete)
            except Exception:
                logger.debug("[RAG] re-embed progress callback failed", exc_info=True)
        return res_complete

    def _write_reindex_progress(self, data: dict[str, Any]) -> None:
        from backend import config as _cfg

        prog_path = os.path.join(_cfg.DATA_DIR, "reindex_progress.json")
        try:
            atomic_write_json(prog_path, data)
        except OSError:
            logger.debug("[RAG] could not write re-embed progress", exc_info=True)

    def _start_spinup_watcher(self) -> None:
        """
        Starts a lightweight background daemon thread that monitors disk spin-up transitions
        (without ever touching or waking sleeping drives) and automatically triggers learning
        when a sleeping disk spins up.
        """
        if test_mode():
            return
        if self.db_path != _core().RAG_DB_PATH:
            return
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return

        def _watch_loop() -> None:
            # Give host 3.0s to initialize devices, mount points, and PAL storage drivers
            time.sleep(3.0)

            # Auto-recovery on startup: Check for interrupted sync session from previous run
            try:
                cfg = self.get_config()
                if cfg.get("enabled", True):
                    active_session = cfg.get("active_sync_session")
                    if active_session and active_session.get("status") == "running" and not self._is_indexing:
                        session_paths = [os.path.normpath(p) for p in (active_session.get("paths") or []) if p]
                        if session_paths:
                            can_run = True
                            for sp in session_paths:
                                dev = rag_standby.resolve_path_backing_dev(sp)
                                if bool(
                                    active_session.get("respect_standby", True)
                                ) and rag_standby.is_backing_disk_in_standby(dev or sp):
                                    can_run = False
                                    self.enqueue_deferred_path(sp, reason="disk_standby", priority=2)
                            if can_run:
                                logger.info(
                                    f"[RAG] Automatically resuming interrupted sync session for: {session_paths}"
                                )
                                self.start_background_sync(
                                    paths=session_paths,
                                    respect_standby=bool(active_session.get("respect_standby", True)),
                                    force_wake=bool(active_session.get("force_wake", False)),
                                )
            except Exception as init_err:
                logger.debug(f"[RAG] Startup auto-resume error: {init_err}")

            last: dict[str, Any] = {}
            while True:
                try:
                    time.sleep(SPINUP_WATCH_SECS)  # PERF-5: was 5 s
                    self._watch_tick(last)
                except Exception as e:
                    logger.debug(f"[RAG] Spin-up auto-learn watcher error: {e}")

        t = threading.Thread(target=_watch_loop, name="zettnas-rag-spinup-watcher", daemon=True)
        self._watcher_thread = t
        t.start()

    def _watch_signature(self) -> tuple:
        """What the spin-up checks depend on. Cheap: no database, one stat of the config file."""
        try:
            st = os.stat(_core().RAG_CONFIG_PATH)
            config_key: tuple | None = (st.st_mtime_ns, st.st_size)
        except OSError:
            config_key = None
        return (
            tuple(rag_standby.get_sleeping_disks_list()),
            config_key,
            bool(self._is_indexing),
            str(self._sync_state),
        )

    def _watch_tick(self, last: dict[str, Any]) -> bool:
        """One pass of the spin-up watcher. The queue checks open the index database, which on
        a FUSE data folder costs hundreds of blocking calls, so they run only when a disk went
        to sleep or woke, the settings changed, indexing started or stopped, or every five
        minutes (the learning schedule window). Returns whether the checks ran."""
        now = time.monotonic()
        signature = self._watch_signature()
        ran = signature != last.get("signature") or now - last.get("at", float("-inf")) >= WATCH_FULL_EVERY_SECS
        if ran:
            if signature[1] is not None:
                self.sync_watched_deferred_queue()
            self.check_and_trigger_spinup_auto_learn(background=True)
            last["signature"] = self._watch_signature()  # the checks may have changed the state
            last["at"] = now
        self._maybe_reembed_fallback_files()
        return ran

    def enqueue_deferred_path(self, path: str, reason: str = "disk_standby", priority: int = 1) -> dict[str, Any]:
        """Queues a folder path in rag_deferred_queue without touching the disk platter."""
        self._ensure_schema()
        norm_p = os.path.normpath(str(path or "").strip())
        if not norm_p:
            return {"queued": False}
        dev = rag_standby.resolve_path_backing_dev(norm_p)
        if dev:
            self._known_sleeping_devs.add(dev)
        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                conn.execute(
                    """
                    INSERT INTO rag_deferred_queue(target_path, backing_dev, reason, queued_at, priority)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(target_path) DO UPDATE SET
                        backing_dev = excluded.backing_dev,
                        reason = excluded.reason,
                        queued_at = excluded.queued_at,
                        priority = MAX(rag_deferred_queue.priority, excluded.priority)
                    """,
                    (norm_p, dev, reason, time.time(), int(priority)),
                )
                conn.commit()
            finally:
                conn.close()
        return {"queued": True, "path": norm_p, "backing_dev": dev}

    def remove_deferred_path(self, path: str) -> int:
        """Removes a path and any child subpaths from rag_deferred_queue."""
        self._ensure_schema()
        norm_p = os.path.normpath(str(path or "").strip())
        if not norm_p:
            return 0
        prefix = norm_p.rstrip("/") + "/%"
        with self._write_lock:
            conn = self._get_conn(readonly=False)
            try:
                cur = conn.execute(
                    "DELETE FROM rag_deferred_queue WHERE target_path = ? OR target_path LIKE ?",
                    (norm_p, prefix),
                )
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()

    def get_deferred_queue(self) -> list[dict[str, Any]]:
        """Returns all paths currently waiting in rag_deferred_queue along with live standby status."""
        self._ensure_schema()
        conn = self._get_conn(readonly=True)
        try:
            rows = conn.execute(
                """
                SELECT target_path, backing_dev, reason, queued_at, priority
                FROM rag_deferred_queue
                ORDER BY priority DESC, queued_at ASC
                """
            ).fetchall()
        except Exception:
            return []
        finally:
            conn.close()

        items: list[dict[str, Any]] = []
        for r in rows:
            tp = r["target_path"]
            dev = r["backing_dev"] or rag_standby.resolve_path_backing_dev(tp)
            standby = rag_standby.is_backing_disk_in_standby(dev or tp)
            items.append(
                {
                    "path": tp,
                    "backing_dev": dev,
                    "in_standby": standby,
                    "disk_state": "standby" if standby else "active",
                    "reason": r["reason"] or "disk_standby",
                    "queued_at": float(r["queued_at"] or 0.0),
                    "priority": int(r["priority"] or 0),
                }
            )
        return items

    def sync_watched_deferred_queue(self) -> dict[str, Any]:
        """
        Reconciles `rag_deferred_queue` against the active `watched_paths` and `excluded_paths`:
          1. Prunes stale deferred entries that are no longer inside any watched folder (or were excluded).
          2. Ensures watched folders on currently-sleeping disks that have not yet been indexed
             are queued in `rag_deferred_queue` so they auto-learn the moment the disk spins up.
        """
        self._ensure_schema()
        cfg = self.get_config()
        scope_mode = cfg.get("scope_mode", "include")
        watched = [os.path.normpath(p) for p in (cfg.get("watched_paths") or []) if p]
        excluded = {os.path.normpath(p) for p in (cfg.get("excluded_paths") or []) if p}

        current_items = self.get_deferred_queue()
        existing_deferred_paths = {os.path.normpath(it["path"]) for it in current_items}
        pruned = 0
        enqueued = 0

        for it in current_items:
            tp = os.path.normpath(it["path"])
            is_excl = any(tp == ex or tp.startswith(ex.rstrip("/") + "/") for ex in excluded)
            in_watched = True
            if scope_mode == "include" and watched:
                in_watched = any(tp == wp or tp.startswith(wp.rstrip("/") + "/") for wp in watched)
            if is_excl or not in_watched:
                pruned += self.remove_deferred_path(tp)
                existing_deferred_paths.discard(tp)

        if cfg.get("respect_standby", True) and cfg.get("auto_learn_on_spinup", True):
            conn_ro = self._get_conn(readonly=True)
            try:
                for wp in watched:
                    if any(wp == ex or wp.startswith(ex.rstrip("/") + "/") for ex in excluded):
                        continue
                    dev = rag_standby.resolve_path_backing_dev(wp)
                    if rag_standby.is_backing_disk_in_standby(dev or wp):
                        if dev:
                            self._known_sleeping_devs.add(dev)
                        if wp not in existing_deferred_paths:
                            # Check if this watched path has any indexed files yet
                            prefix_slash = wp.rstrip("/") + "/"
                            prefix_upper = wp.rstrip("/") + "0"
                            cnt = conn_ro.execute(
                                """
                                SELECT COUNT(*) FROM indexed_files
                                WHERE canonical_path = ? OR (canonical_path >= ? AND canonical_path < ?)
                                """,
                                (wp, prefix_slash, prefix_upper),
                            ).fetchone()[0]
                            if cnt == 0:
                                self.enqueue_deferred_path(wp, reason="disk_standby", priority=1)
                                existing_deferred_paths.add(wp)
                                enqueued += 1
            except Exception:
                ignored("backend.services.rag_engine.RagSearchEngine.sync_watched_deferred_queue")
            finally:
                conn_ro.close()

        # If sync progress message still mentions a pruned/removed path, refresh the status message
        if pruned > 0 and not self._is_indexing:
            remaining_q = self.get_deferred_queue()
            if remaining_q:
                first_q = remaining_q[0]
                dev_s = f"/dev/{first_q['backing_dev']}" if first_q.get("backing_dev") else "standby disk"
                self._sync_progress["deferred_standby"] = len(remaining_q)
                self._sync_progress["message"] = (
                    f"Deferred {first_q['path']}: backing disk {dev_s} is in standby "
                    f"(auto-learns on spin-up, 0 wakeups)."
                )
            else:
                self._sync_progress["deferred_standby"] = 0

        return {"pruned": pruned, "enqueued": enqueued}

    def check_and_trigger_spinup_auto_learn(self, background: bool = True) -> dict[str, Any]:
        """
        Detects when a sleeping/standby disk has spun up (transitioned to active/running)
        or when paths in `rag_deferred_queue` now reside on a running disk, and automatically
        starts learning/indexing those folders without ever waking sleeping drives.
        """
        self._ensure_schema()
        cfg = self.get_config()
        current_sleeping = set(rag_standby.get_sleeping_disks_list())
        woken_devs = self._known_sleeping_devs - current_sleeping
        self._known_sleeping_devs = set(current_sleeping)

        if not cfg.get("enabled", True):
            return {"triggered": False, "reason": "disabled", "woken_disks": sorted(woken_devs)}
        if not cfg.get("auto_learn_on_spinup", True):
            return {"triggered": False, "reason": "auto_learn_disabled", "woken_disks": sorted(woken_devs)}

        in_sched, resume_time = self.is_within_learning_schedule()
        if not in_sched:
            return {
                "triggered": False,
                "reason": f"outside_schedule (resumes at {resume_time})",
                "woken_disks": sorted(woken_devs),
            }

        if self._is_indexing or self._sync_state in ("running", "paused", "stopping"):
            return {"triggered": False, "reason": "already_indexing", "woken_disks": sorted(woken_devs)}

        excluded_set = {os.path.normpath(p) for p in (cfg.get("excluded_paths") or []) if p}
        ready_paths: list[str] = []
        ready_devs: set[str] = set(woken_devs)

        # 1. Check all queued paths in rag_deferred_queue whose backing disk is now running
        deferred_items = self.get_deferred_queue()
        for item in deferred_items:
            tp = os.path.normpath(item["path"])
            if any(tp == ex or tp.startswith(ex.rstrip("/") + "/") for ex in excluded_set):
                self.remove_deferred_path(tp)
                continue
            dev = item.get("backing_dev") or rag_standby.resolve_path_backing_dev(tp)
            if not rag_standby.is_backing_disk_in_standby(dev or tp):
                if tp not in ready_paths:
                    ready_paths.append(tp)
                if dev:
                    ready_devs.add(dev)

        # 2. Watched folders whose disk just spun up. A full rescan keeps the disk busy, so it runs
        # at most every SPINUP_RESCAN_COOLDOWN_SECS per disk; queued folders (step 1) don't wait (PERF-7).
        now_ts = time.time()
        rescanned: set[str] = set()
        for wp in cfg.get("watched_paths") or []:
            norm_wp = os.path.normpath(wp)
            if any(norm_wp == ex or norm_wp.startswith(ex.rstrip("/") + "/") for ex in excluded_set):
                continue
            dev = rag_standby.resolve_path_backing_dev(norm_wp)
            if dev and dev in woken_devs and not rag_standby.is_backing_disk_in_standby(dev):
                if now_ts - self._last_spinup_rescan.get(dev, 0.0) < _core().SPINUP_RESCAN_COOLDOWN_SECS:
                    continue
                if norm_wp not in ready_paths:
                    ready_paths.append(norm_wp)
                ready_devs.add(dev)
                rescanned.add(dev)
        for dev in rescanned:
            self._last_spinup_rescan[dev] = now_ts

        # 3. Freshness: watched folders on disks that are awake anyway are re-read on a schedule,
        # so SSD pools and disks that never sleep don't keep a stale index (AI-3). Unchanged files
        # are skipped by their size and time, so a pass mostly reads folder listings.
        fresh = getattr(self, "_last_fresh_rescan", None)
        if fresh is None:
            fresh = self._last_fresh_rescan = {"_started": now_ts}
        for wp in cfg.get("watched_paths") or []:
            norm_wp = os.path.normpath(wp)
            if norm_wp in ready_paths or any(
                norm_wp == ex or norm_wp.startswith(ex.rstrip("/") + "/") for ex in excluded_set
            ):
                continue
            dev = rag_standby.resolve_path_backing_dev(norm_wp)
            if rag_standby.is_backing_disk_in_standby(dev or norm_wp):
                continue
            interval = FRESH_RESCAN_SSD_SECS if _is_solid_state(dev) else FRESH_RESCAN_HDD_SECS
            if now_ts - fresh.get(norm_wp, fresh["_started"]) >= interval:
                ready_paths.append(norm_wp)
                fresh[norm_wp] = now_ts

        # 4. The overnight re-index (AI-30): once a night, while entries made the old way remain,
        # the watched folders on disks that are awake anyway get a pass
        for wp in upgrade_pass_paths(self, cfg, excluded_set, ready_paths):
            ready_paths.append(wp)

        if not ready_paths:
            return {
                "triggered": False,
                "reason": "no_awake_deferred_paths",
                "woken_disks": sorted(woken_devs),
                "sleeping_disks": sorted(current_sleeping),
            }

        for rp in ready_paths:
            self.remove_deferred_path(rp)

        dev_label = ", ".join(f"/dev/{d}" for d in sorted(ready_devs) if d) or "array disk"
        auto_msg = f"⚡ Auto-learning started ({dev_label} spun up): syncing {', '.join(ready_paths)}..."
        self._last_auto_learn_event = {
            "timestamp": time.time(),
            "paths": list(ready_paths),
            "woken_disks": sorted(ready_devs),
            "message": auto_msg,
        }
        logger.info(f"[RAG] {auto_msg}")

        if background:
            sync_res = self.start_background_sync(
                paths=ready_paths,
                respect_standby=bool(cfg.get("respect_standby", True)),
                force_wake=False,
                auto_spinup_devs=sorted(ready_devs),
            )
            return {
                "triggered": True,
                "mode": "background",
                "paths": ready_paths,
                "woken_disks": sorted(ready_devs),
                "message": auto_msg,
                "sync": sync_res,
            }
        else:
            sync_res = self.index_paths(
                paths=ready_paths,
                respect_standby=bool(cfg.get("respect_standby", True)),
                force_wake=False,
                auto_spinup_devs=sorted(ready_devs),
            )
            return {
                "triggered": True,
                "mode": "synchronous",
                "paths": ready_paths,
                "woken_disks": sorted(ready_devs),
                "message": self._sync_progress.get("message", auto_msg),
                "sync": sync_res,
            }

    def is_within_learning_schedule(self) -> tuple[bool, str]:
        """Checks whether current local time is within the configured ZettAI learning window."""
        cfg = self.get_config()
        if not cfg.get("schedule_enabled"):
            return (True, "")
        start_s = str(cfg.get("schedule_start") or "01:00").strip()
        end_s = str(cfg.get("schedule_end") or "06:00").strip()
        try:
            now_lt = time.localtime()
            cur_mins = now_lt.tm_hour * 60 + now_lt.tm_min
            sh, sm = [int(x) for x in start_s.split(":")[:2]]
            eh, em = [int(x) for x in end_s.split(":")[:2]]
            start_mins = sh * 60 + sm
            end_mins = eh * 60 + em
            if start_mins <= end_mins:
                in_win = start_mins <= cur_mins < end_mins
            else:
                in_win = cur_mins >= start_mins or cur_mins < end_mins
            return (in_win, start_s if not in_win else "")
        except Exception:
            return (True, "")

    def get_learning_results(self, principal: Any = None) -> dict[str, Any]:
        """
        Returns ZettAI 6-state status (Initializing | Learning | Idle | Paused | Disabled | Error),
        succeeded/failed file counts, and failed file paths for the Learning Results dialog.
        """
        self._ensure_schema()
        cfg = self.get_config()
        in_sched, resume_time = self.is_within_learning_schedule()

        conn = self._get_conn(readonly=True)
        try:
            rbac_sql, rbac_params = self._build_rbac_clause(principal, "f")
            succeeded_count = conn.execute(
                f"SELECT COUNT(*) FROM indexed_files f WHERE f.parse_status = 'ok' AND {rbac_sql}",
                rbac_params,
            ).fetchone()[0]
            failed_rows = conn.execute(
                f"""
                SELECT f.file_id, f.canonical_path, f.file_name, f.parse_status, f.indexed_at
                FROM indexed_files f
                WHERE f.parse_status != 'ok' AND {rbac_sql}
                ORDER BY f.indexed_at DESC
                LIMIT 100
                """,
                rbac_params,
            ).fetchall()
            failed_count = conn.execute(
                f"SELECT COUNT(*) FROM indexed_files f WHERE f.parse_status != 'ok' AND {rbac_sql}",
                rbac_params,
            ).fetchone()[0]
            deferred_count = conn.execute("SELECT COUNT(*) FROM rag_deferred_queue").fetchone()[0]

            failed_files = [
                {
                    "file_id": int(r["file_id"]),
                    "path": r["canonical_path"],
                    "name": r["file_name"],
                    "reason": r["parse_status"] or "Unsupported or unreadable format",
                    "indexed_at": float(r["indexed_at"] or 0.0),
                }
                for r in failed_rows
                if self._check_post_rbac(r["canonical_path"], principal)
            ]
        except Exception as e:
            return {
                "zettai_status": "Error",
                "status_reason": str(e),
                "succeeded_count": 0,
                "failed_count": 0,
                "deferred_count": 0,
                "failed_files": [],
            }
        finally:
            conn.close()

        if not cfg.get("enabled", True):
            z_status = "Disabled"
            reason = "ZettAI service is turned off in Settings."
        elif self._is_indexing and self._sync_state == "running":
            z_status = "Learning"
            reason = self._sync_progress.get("message") or "Analyzing and indexing files..."
        elif self._sync_state == "paused":
            z_status = "Paused"
            reason = "Learning paused by user."
        elif not in_sched:
            z_status = "Paused"
            reason = f"Outside scheduled learning window (resumes at {resume_time})."
        else:
            z_status = "Idle"
            reason = "No pending learning tasks."

        return {
            "zettai_status": z_status,
            "status_reason": reason,
            "resume_time": resume_time or None,
            "succeeded_count": int(succeeded_count),
            "failed_count": int(failed_count),
            "deferred_count": int(deferred_count),
            "failed_files": failed_files,
        }

    def relearn_failed_files(self) -> dict[str, Any]:
        """Retries indexing any files that previously failed parsing (without waking sleeping drives)."""
        res_info = self.get_learning_results()
        failed_list = res_info.get("failed_files") or []
        retried = 0
        recovered = 0
        for item in failed_list:
            f_path = item.get("path") or ""
            if not f_path:
                continue
            dev = rag_standby.resolve_path_backing_dev(f_path)
            if rag_standby.is_backing_disk_in_standby(dev):
                continue
            retried += 1
            if os.path.isfile(f_path):
                try:
                    st = os.stat(f_path)
                    f_name = os.path.basename(f_path)
                    f_ext = os.path.splitext(f_name)[1]
                    fid = self._index_single_file(f_path, f_name, f_ext, st.st_size, st.st_mtime_ns, None)
                    if fid is not None:
                        recovered += 1
                except Exception as e:
                    logger.debug(f"[RAG] Relearn failed on {sanitize_string(f_path)}: {e}")
            else:
                with self._write_lock:
                    conn = self._get_conn(readonly=False)
                    try:
                        self._drop_file_vectors(
                            conn, "SELECT file_id FROM indexed_files WHERE canonical_path = ?", (f_path,)
                        )
                        conn.execute("DELETE FROM indexed_files WHERE canonical_path = ?", (f_path,))
                        conn.commit()
                    finally:
                        conn.close()
        updated = self.get_learning_results()
        updated["retried"] = retried
        updated["recovered"] = recovered
        return updated

    def toggle_favorite(self, path: str) -> dict[str, Any]:
        """Adds or removes a file path from ZettAI favorites."""
        norm_p = os.path.normpath(str(path or "").strip())
        cfg = self.get_config()
        favs: list[str] = list(cfg.get("favorites") or [])
        if norm_p in favs:
            favs.remove(norm_p)
            is_fav = False
        else:
            favs.append(norm_p)
            is_fav = True
        self.update_config({"favorites": favs})
        return {"status": "ok", "path": norm_p, "is_favorite": is_fav, "favorites": favs}

    def get_sync_progress(self) -> dict[str, Any]:
        """Returns live sync state, progress counters, and pause/resume/stop capabilities."""
        state = self._sync_state
        is_active = self._is_indexing or state in ("running", "paused", "stopping")
        prog = dict(self._sync_progress)
        prog["state"] = state
        prog["sync_state"] = state
        prog["is_scanning"] = is_active
        prog["is_paused"] = state == "paused"
        prog["can_pause"] = state == "running" and self._is_indexing
        prog["can_resume"] = state == "paused" and self._is_indexing
        prog["can_stop"] = state in ("running", "paused") and self._is_indexing
        prog["last_message"] = prog.get("message", "")
        prog["sleeping_disks"] = rag_standby.get_sleeping_disks_list()
        prog["running_disks"] = rag_standby.get_running_disks_list()
        prog["deferred_queue"] = self.get_deferred_queue()
        prog["last_auto_learn_event"] = self._last_auto_learn_event
        return prog

    def pause_sync(self) -> dict[str, Any]:
        """Pauses an active indexing job at the current file boundary."""
        self._pause_event.clear()
        self._sync_state = "paused"
        self._sync_progress["state"] = "paused"
        self._sync_progress["updated_at"] = time.time()
        self._sync_progress["message"] = "Sync paused by user."
        return self.get_sync_progress()

    def resume_sync(self) -> dict[str, Any]:
        """Resumes a paused indexing job (re-verifying disk standby before touching files)."""
        self._pause_event.set()
        self._sync_state = "running" if self._is_indexing else "idle"
        self._sync_progress["state"] = self._sync_state
        self._sync_progress["updated_at"] = time.time()
        self._sync_progress["message"] = "Sync resumed."
        return self.get_sync_progress()

    def stop_sync(self) -> dict[str, Any]:
        """Stops an active or paused indexing job immediately and cleanly."""
        self._stop_requested = True
        self._pause_event.set()
        if self._is_indexing:
            self._sync_state = "stopping"
            self._sync_progress["state"] = "stopping"
            self._sync_progress["message"] = "Stopping sync..."
        else:
            self._sync_state = "stopped"
            self._sync_progress["state"] = "stopped"
            self._sync_progress["message"] = "Sync stopped."
        self._sync_progress["updated_at"] = time.time()
        try:
            cfg = self.get_config()
            if cfg.get("active_sync_session"):
                cfg["active_sync_session"] = None
                atomic_write_json(_core().RAG_CONFIG_PATH, cfg)
        except Exception:
            ignored("backend.services.rag_engine.RagSearchEngine.stop_sync")
        return self.get_sync_progress()

    def reembed_fallback_files(self, max_files: int = 20) -> dict[str, Any]:
        """Files stored with the built-in lexical vectors because the embedding model was down
        get neural vectors from the chunk text already in the index (no disk reads) (AI-10).

        Stops at the first file the model can't embed; a full re-embed in progress goes first.
        """
        cfg = self.get_config()
        model = cfg.get("embedding_model") or "embeddinggemma"
        if model == "zett_lexical_384d":
            return {"status": "lexical_model", "files": 0}
        if self._is_indexing:
            return {"status": "busy", "files": 0}
        target_dim = cfg.get("embedding_dim")
        conn = self._get_conn(readonly=True)
        try:
            try:
                if conn.execute("SELECT 1 FROM reembed_staging LIMIT 1").fetchone():
                    return {"status": "full_reembed_pending", "files": 0}
            except sqlite3.Error:
                logger.debug("[RAG] no re-embed staging table: no full re-embed has run")
            files = conn.execute(
                """SELECT file_id, file_name, file_ext, doc_title FROM indexed_files
                   WHERE parse_status = 'ok' AND embedding_model = 'zett_lexical_384d' ORDER BY file_id LIMIT ?""",
                (int(max_files),),
            ).fetchall()
        finally:
            conn.close()
        done = 0
        for f in files:
            fid = int(f["file_id"])
            conn = self._get_conn(readonly=True)
            try:
                chunks = conn.execute(
                    """SELECT chunk_id, heading_context, chunk_text, raw_chunk_text, visibility_tier
                       FROM document_chunks WHERE file_id = ? AND chunk_level != 'parent' ORDER BY chunk_id""",
                    (fid,),
                ).fetchall()
            finally:
                conn.close()
            texts = [chunk_embedding_text(f["doc_title"], f["file_name"], dict(c), f["file_ext"] or "") for c in chunks]
            blobs = _core().compute_neural_embeddings_batch(
                texts, model, target_dim=target_dim, host=embedding_host(cfg)
            )
            if blobs is None:
                return {"status": "embedder_unavailable", "files": done}
            with self._write_lock:
                w = self._get_conn(readonly=False)
                try:
                    for c, blob in zip(chunks, blobs, strict=True):
                        dim = len(blob) // 4
                        w.execute(
                            "UPDATE document_chunks SET embedding_f32 = ?, embedding_model = ?, embedding_dim = ? WHERE chunk_id = ?",
                            (blob, model, dim, int(c["chunk_id"])),
                        )
                        self.sync_vector_chunk(
                            w, int(c["chunk_id"]), blob, fid, c["visibility_tier"] or "public_share", dim=dim
                        )
                    w.execute("UPDATE indexed_files SET embedding_model = ? WHERE file_id = ?", (model, fid))
                    w.commit()
                finally:
                    w.close()
            done += 1
        if done:
            logger.info(f"[RAG] Re-embedded {done} file(s) that had fallback vectors with '{model}'")
        return {"status": "ok", "files": done}

    def _maybe_backfill_tags(self) -> None:
        """Tags documents indexed before auto-tags existed, a batch per round, from the text the
        index holds (no disk access), until none are left (B8)."""
        if getattr(self, "_tags_backfilled", False):
            return
        from backend.services import rag_tags

        try:
            with self._write_lock:
                conn = self._get_conn(readonly=False)
                try:
                    n = rag_tags.backfill(conn)
                    conn.commit()
                finally:
                    conn.close()
        except sqlite3.Error:
            logger.warning("[RAG] Tagging older documents failed; trying again next round", exc_info=True)
            return
        if n:
            logger.info(f"[RAG] Tagged {n} older document(s) for the search filters")
        else:
            self._tags_backfilled = True

    def _maybe_backfill_photo_dates(self) -> None:
        """Reads the date and position of photos indexed before AI-24: at night, while nobody
        chats, a batch per round, only on disks that are awake; stops once none are left."""
        from backend.services import ai_activity, photo_place

        if getattr(self, "_photo_dates_done", False) or not ai_activity.upgrade_window_open(time.time()):
            return
        try:
            conn = self._get_conn(readonly=True)
            try:
                rows = photo_place.pending(conn)
            finally:
                conn.close()
            if not rows:
                self._photo_dates_done = True
                return

            def awake(dev: str, path: str) -> bool:
                return not rag_standby.is_backing_disk_in_standby(
                    dev or rag_standby.resolve_path_backing_dev(path) or path
                )

            updates = photo_place.read_pending(rows, awake)  # reads files outside the write lock
            if updates:
                with self._write_lock:
                    w = self._get_conn(readonly=False)
                    try:
                        photo_place.apply(w, updates)
                        w.commit()
                    finally:
                        w.close()
                logger.info(f"[RAG] Read the date and place of {len(updates)} older photo(s)")
        except sqlite3.Error:
            logger.warning("[RAG] Reading older photos' dates failed; trying again next round", exc_info=True)

    def _maybe_name_photo_places(self) -> None:
        """Gives photos with a position but no place their town's name, from the index alone, a
        batch per round; once per place list (AI-24)."""
        from backend.services import photo_place

        sig = photo_place.places_signature()
        if not sig or getattr(self, "_places_named_for", "") == sig:
            return
        try:
            with self._write_lock:
                conn = self._get_conn(readonly=False)
                try:
                    conn.execute("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)")
                    row = conn.execute("SELECT value FROM rag_meta WHERE key = 'photo_places'").fetchone()
                    if row and row[0] == sig:
                        self._places_named_for = sig
                        return
                    named, last = photo_place.name_unnamed(conn, getattr(self, "_places_cursor", 0))
                    if last:
                        self._places_cursor = last
                    else:
                        conn.execute("INSERT OR REPLACE INTO rag_meta (key, value) VALUES ('photo_places', ?)", (sig,))
                        self._places_named_for = sig
                        self._places_cursor = 0
                    conn.commit()
                finally:
                    conn.close()
            if named:
                logger.info(f"[RAG] Named the place of {named} photo(s)")
        except sqlite3.Error:
            logger.warning("[RAG] Naming photo places failed; trying again next round", exc_info=True)

    def _maybe_maintain_index(self) -> None:
        """Once a night, while nobody chats: SQLite's own statistics (PRAGMA optimize), each
        keyword index merged into one segment (FTS optimize) and the WAL folded back (PERF-23)."""
        from backend.services import ai_activity

        tonight = time.strftime("%Y-%m-%d", time.localtime())
        if getattr(self, "_maintained_on", "") == tonight or not ai_activity.upgrade_window_open(time.time()):
            return
        self._maintained_on = tonight
        t0 = time.time()
        try:
            with self._write_lock:
                conn = self._get_conn(readonly=False)
                try:
                    tables = {
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE '%USING fts5%'"
                        )
                    }
                    for table in sorted(tables):
                        if table == "rag_chunks_cjk":
                            continue  # contentless_delete tables have no optimize of their own worth it
                        conn.execute(f"INSERT INTO {table}({table}) VALUES ('optimize')")
                    conn.commit()
                    conn.execute("PRAGMA optimize")
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    conn.close()
            logger.info(
                f"[RAG] Nightly index maintenance done in {time.time() - t0:.1f}s ({len(tables)} keyword indexes)"
            )
        except sqlite3.Error:
            logger.warning("[RAG] Nightly index maintenance failed; trying again tomorrow", exc_info=True)

    def _maybe_upgrade_embedding_text(self) -> bool:
        """Re-embeds the index at night when its chunks were embedded as an older text (AI-41):
        the in-place re-embed, from the index on SSD, with the model already in use; search keeps
        the old vectors until the new ones are all in. Returns whether it started."""
        running = getattr(self, "_text_upgrade_thread", None)
        if running is not None and running.is_alive():
            return False
        cfg = self.get_config()
        model = str(cfg.get("embedding_model") or "")
        if not model or model == "zett_lexical_384d" or not upgrade_window_open():
            return False
        if self.embed_text_version() >= _core().EMBED_TEXT_VERSION:
            return False
        dim = int(cfg.get("embedding_dim") or 768)
        progress: dict[str, Any] = {"status": "running", "reason": "embedding_text", "completed": 0, "total": 0}
        self.text_upgrade_progress = progress

        self._text_upgrade_stop = False
        self._reembed_why = ""
        self._reembed_keep = lambda: upgrade_window_open() and not self._text_upgrade_stop

        def run() -> None:
            try:
                res = asyncio.run(
                    self.in_place_reembed_collection(
                        model,
                        dim,
                        progress_callback=progress.update,
                        target_host=cfg.get("embedding_host") or None,
                        all_chunks=True,
                    )
                )
                progress.update(res)
                progress["status"] = {"paused": "paused", "busy": "idle"}.get(str(res.get("status")), "complete")
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as e:
                logger.warning("[RAG] The nightly re-embed stopped: %s", e)
                progress["status"] = "error"
            finally:
                self._reembed_keep = None

        logger.info("[RAG] Re-embedding the index as clean chunk text (AI-41), from the index, no disk reads")
        self._text_upgrade_thread = threading.Thread(target=run, daemon=True, name="RagTextUpgrade")
        self._text_upgrade_thread.start()
        return True

    def embed_text_version(self) -> int:
        """The version of the text this index's chunks were embedded as (1 before AI-41). An index
        without neural vectors has nothing to upgrade."""
        conn = self._get_conn(readonly=True)
        try:
            return _core().read_embed_text_version(conn)
        finally:
            conn.close()

    def _maybe_reembed_fallback_files(self) -> None:
        now = time.time()
        if now - self._last_fallback_reembed < _core().FALLBACK_REEMBED_EVERY_SECS:
            return
        self._last_fallback_reembed = now
        self.reembed_fallback_files()
        self._maybe_upgrade_embedding_text()  # nights only, once per index (AI-41)
        self._maybe_backfill_tags()  # same five-minute cadence; stops once every older file is tagged
        self._maybe_backfill_photo_dates()  # at night only (AI-24)
        self._maybe_name_photo_places()  # from the index alone, any time (AI-24)
        self._maybe_maintain_index()  # once a night (PERF-23)

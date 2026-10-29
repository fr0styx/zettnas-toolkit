"""Folder discovery, folder manifests and folder-wide context for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

# pyright: reportAttributeAccessIssue=false

import json
import os
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
from backend.ignored_errors import ignored
from backend.services import (  # noqa: F401
    rag_standby,
)
from backend.services.rag_embeddings import (  # noqa: F401
    classify_query_task_intent,
    compute_multimodal_query_embedding,
    cosine_similarity_vec,
    embedding_host,
    unpack_embedding,
)
from backend.services.rag_grounding import (  # noqa: F401
    apply_primacy_recency_inversion,
)


def _core():
    """backend.services.rag_engine, read at call time: shared settings live there and tests patch them."""
    from backend.services import rag_engine

    return rag_engine


class RagManifestMixin:
    """Folder discovery, folder manifests and folder-wide context for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

    def discover_available_folders(self) -> list[dict[str, Any]]:
        """
        Discovers available NAS shares and folders under /mnt/user (or /mnt/storage) without waking
        sleeping HDDs. Uses /var/local/emhttp/shares.ini when on Unraid.
        """
        cfg = self.get_config()
        watched_set = {os.path.normpath(p) for p in (cfg.get("watched_paths") or [])}
        excluded_set = {os.path.normpath(p) for p in (cfg.get("excluded_paths") or [])}
        folders: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        _, unraid_shares = rag_standby._get_unraid_disks_and_shares()
        if unraid_shares:
            for s_name, s_info in sorted(unraid_shares.items()):
                if s_name.startswith("."):
                    continue
                full_path = f"/mnt/user/{s_name}"
                norm_p = os.path.normpath(full_path)
                seen_paths.add(norm_p)
                dev = rag_standby.resolve_path_backing_dev(norm_p)
                in_standby = rag_standby.is_backing_disk_in_standby(dev)
                use_cache = (s_info.get("useCache") or "").lower()
                is_sys = s_name.lower() in _core().SYSTEM_SHARE_EXCLUSIONS
                folders.append(
                    {
                        "name": s_name,
                        "path": norm_p,
                        "backing_dev": dev or ("nvme0n1" if use_cache == "only" else "array"),
                        "disk_state": "standby" if in_standby else "active",
                        "in_standby": in_standby,
                        "use_cache": use_cache or "auto",
                        "comment": s_info.get("comment") or "",
                        "is_system": is_sys,
                        "is_watched": norm_p in watched_set,
                        "is_excluded": norm_p in excluded_set,
                    }
                )
        else:
            # Generic Linux / non-Unraid: only scan /mnt/user if backing disk is not in standby
            for base_root in ("/mnt/user", "/mnt/storage"):
                if not os.path.isdir(base_root):
                    continue
                base_dev = rag_standby.resolve_path_backing_dev(base_root)
                if rag_standby.is_backing_disk_in_standby(base_dev):
                    continue
                try:
                    for entry in sorted(os.scandir(base_root), key=lambda e: e.name.lower()):
                        if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                            continue
                        norm_p = os.path.normpath(entry.path)
                        if norm_p in seen_paths:
                            continue
                        seen_paths.add(norm_p)
                        dev = rag_standby.resolve_path_backing_dev(norm_p)
                        in_standby = rag_standby.is_backing_disk_in_standby(dev)
                        is_sys = entry.name.lower() in _core().SYSTEM_SHARE_EXCLUSIONS
                        folders.append(
                            {
                                "name": entry.name,
                                "path": norm_p,
                                "backing_dev": dev or "pool",
                                "disk_state": "standby" if in_standby else "active",
                                "in_standby": in_standby,
                                "use_cache": "auto",
                                "comment": "",
                                "is_system": is_sys,
                                "is_watched": norm_p in watched_set,
                                "is_excluded": norm_p in excluded_set,
                            }
                        )
                except Exception:
                    ignored("backend.services.rag_engine.RagSearchEngine.discover_available_folders")

        # Also include any custom watched_paths that weren't in top-level shares
        for wp in cfg.get("watched_paths") or []:
            norm_wp = os.path.normpath(wp)
            if norm_wp not in seen_paths:
                seen_paths.add(norm_wp)
                dev = rag_standby.resolve_path_backing_dev(norm_wp)
                in_standby = rag_standby.is_backing_disk_in_standby(dev)
                folders.append(
                    {
                        "name": os.path.basename(norm_wp) or norm_wp,
                        "path": norm_wp,
                        "backing_dev": dev or "pool",
                        "disk_state": "standby" if in_standby else "active",
                        "in_standby": in_standby,
                        "use_cache": "custom",
                        "comment": "Custom folder",
                        "is_system": False,
                        "is_watched": True,
                        "is_excluded": norm_wp in excluded_set,
                    }
                )

        return folders

    def refresh_folder_manifest(self, folder_path: str) -> dict[str, Any] | None:
        """
        Calculates and persists a deterministic structural manifest rollup for folder_path
        into the `folder_manifests` table and `rag_manifests_fts` virtual table.
        Operates 100% against `/app/data/rag_index.db` without waking sleeping array disks!
        """
        self._ensure_schema()
        norm_path = os.path.normpath(folder_path)
        conn = self._get_conn(readonly=False)
        try:
            prefix_slash = norm_path.rstrip("/") + "/"
            prefix_upper = norm_path.rstrip("/") + "0"
            rows = conn.execute(
                """
                SELECT file_id, file_name, file_ext, doc_type, doc_title, doc_metadata_json,
                       size_bytes, mtime_ns, backing_dev, visibility_tier, owner_username,
                       share_name, allowed_users_csv
                FROM indexed_files
                WHERE (parent_dir = ? OR (canonical_path >= ? AND canonical_path < ?))
                  AND parse_status = 'ok'
                ORDER BY size_bytes DESC
                """,
                (norm_path, prefix_slash, prefix_upper),
            ).fetchall()
            if not rows:
                return None

            total_files = len(rows)
            total_size = sum(int(r["size_bytes"] or 0) for r in rows)
            file_types: dict[str, int] = {}
            doc_titles: list[str] = []
            backing_dev = rows[0]["backing_dev"] or ""
            vis_tier = rows[0]["visibility_tier"] or "public_share"
            owner_user = rows[0]["owner_username"] or ""
            share_name = rows[0]["share_name"] or ""
            allowed_csv = rows[0]["allowed_users_csv"] or "*"

            for r in rows:
                ext = (r["file_ext"] or "").lower().lstrip(".")
                if ext:
                    file_types[ext] = file_types.get(ext, 0) + 1
                t = r["doc_title"] or r["file_name"]
                if t and t not in doc_titles and len(doc_titles) < 30:
                    doc_titles.append(t)

            folder_name = os.path.basename(norm_path) or norm_path
            type_summary = ", ".join(
                f"{cnt} {ext.upper()}" for ext, cnt in sorted(file_types.items(), key=lambda x: -x[1])[:6]
            )
            titles_summary = "\n".join(f"- {t}" for t in doc_titles[:15])
            size_mb = total_size / (1024 * 1024)
            size_str = f"{size_mb:.2f} MB" if size_mb >= 0.01 else f"{total_size} bytes"
            structural_summary = (
                f"Folder: {folder_name} ({norm_path})\n"
                f"Total Files: {total_files} ({size_str})\n"
                f"Formats: {type_summary or 'Various'}\n"
                f"Key Documents:\n{titles_summary}"
            )
            topics_json = json.dumps(doc_titles[:25])
            file_types_json = json.dumps(file_types)
            now = time.time()
            parent_path = os.path.dirname(norm_path)

            conn.execute(
                """
                INSERT INTO folder_manifests (
                    folder_path, parent_path, folder_name, total_files, total_size_bytes,
                    file_types_json, structural_summary, topics_json, backing_dev,
                    visibility_tier, owner_username, share_name, allowed_users_csv,
                    indexed_at, last_verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(folder_path) DO UPDATE SET
                    parent_path = excluded.parent_path,
                    folder_name = excluded.folder_name,
                    total_files = excluded.total_files,
                    total_size_bytes = excluded.total_size_bytes,
                    file_types_json = excluded.file_types_json,
                    structural_summary = excluded.structural_summary,
                    topics_json = excluded.topics_json,
                    backing_dev = excluded.backing_dev,
                    visibility_tier = excluded.visibility_tier,
                    owner_username = excluded.owner_username,
                    share_name = excluded.share_name,
                    allowed_users_csv = excluded.allowed_users_csv,
                    last_verified_at = excluded.last_verified_at
                """,
                (
                    norm_path,
                    parent_path,
                    folder_name,
                    total_files,
                    total_size,
                    file_types_json,
                    structural_summary,
                    topics_json,
                    backing_dev,
                    vis_tier,
                    owner_user,
                    share_name,
                    allowed_csv,
                    now,
                    now,
                ),
            )
            conn.commit()

            chunk_count_row = conn.execute(
                """
                SELECT count(*) as total_chunks FROM document_chunks c
                JOIN indexed_files f ON f.file_id = c.file_id
                WHERE (f.parent_dir = ? OR (f.canonical_path >= ? AND f.canonical_path < ?))
                  AND f.parse_status = 'ok'
                """,
                (norm_path, prefix_slash, prefix_upper),
            ).fetchone()
            total_chunks = int(chunk_count_row["total_chunks"] or 0) if chunk_count_row else len(rows)
            files_list = [r["file_name"] for r in rows]

            return {
                "folder_path": norm_path,
                "folder_name": folder_name,
                "total_files": total_files,
                "total_size_bytes": total_size,
                "total_chunks": total_chunks,
                "files": files_list,
                "outline": structural_summary,
                "file_types": file_types,
                "structural_summary": structural_summary,
                "topics": doc_titles[:25],
                "backing_dev": backing_dev,
            }
        finally:
            conn.close()

    def _readable_paths(self, canonical_paths: Any, principal: Any) -> set[str]:
        """The index paths a principal may read (no disk access)."""
        paths = list(canonical_paths)
        if principal is None:
            return set(paths)
        readable = self._post_rbac_checker(principal)
        return {p for p in paths if readable(p)}

    def _limit_manifest(self, manifest: dict[str, Any] | None, norm_path: str, principal: Any) -> dict[str, Any] | None:
        """A folder manifest with only what the principal may read.

        The stored rollup (titles, topics, outline) covers every file in the folder, so
        when some files are not readable it is rebuilt from the readable files alone.
        """
        if not manifest or principal is None:
            return manifest
        prefix_slash = norm_path.rstrip("/") + "/"
        prefix_upper = norm_path.rstrip("/") + "0"
        conn = self._get_conn(readonly=True)
        try:
            rows = conn.execute(
                """
                SELECT f.file_id, f.file_name, f.canonical_path, f.size_bytes, f.file_ext FROM indexed_files f
                WHERE (f.parent_dir = ? OR (f.canonical_path >= ? AND f.canonical_path < ?))
                  AND f.parse_status = 'ok'
                """,
                (norm_path, prefix_slash, prefix_upper),
            ).fetchall()
            readable = self._readable_paths([r["canonical_path"] for r in rows], principal)
            if len(readable) == len(rows):
                return manifest
            visible = [r for r in rows if r["canonical_path"] in readable]
            file_types: dict[str, int] = {}
            for r in visible:
                ext = (r["file_ext"] or "").lower() or "other"
                file_types[ext] = file_types.get(ext, 0) + 1
            total_chunks = 0
            ids = [r["file_id"] for r in visible]
            for i in range(0, len(ids), 500):
                part = ids[i : i + 500]
                q = f"SELECT count(*) AS n FROM document_chunks WHERE file_id IN ({','.join('?' * len(part))})"
                total_chunks += int(conn.execute(q, part).fetchone()["n"] or 0)
        finally:
            conn.close()
        return {
            **manifest,
            "total_files": len(visible),
            "total_size_bytes": sum(int(r["size_bytes"] or 0) for r in visible),
            "total_chunks": total_chunks,
            "files": [r["file_name"] for r in visible],
            "file_types": file_types,
            "outline": "",
            "structural_summary": "",
            "topics": [],
        }

    def get_folder_manifest(self, folder_path: str, principal: Any = None) -> dict[str, Any] | None:
        """Folder manifest rollup, limited to what the principal may read."""
        norm_path = os.path.normpath(folder_path)
        return self._limit_manifest(self._get_folder_manifest(norm_path, principal), norm_path, principal)

    def _get_folder_manifest(self, folder_path: str, principal: Any = None) -> dict[str, Any] | None:
        """Retrieves folder manifest rollup with RBAC enforcement, or auto-generates from indexed_files."""
        self._ensure_schema()
        norm_path = os.path.normpath(folder_path)
        conn = self._get_conn(readonly=True)
        try:
            rbac_sql, rbac_params = self._build_rbac_clause(principal, "m")
            row = conn.execute(
                f"""
                SELECT * FROM folder_manifests m
                WHERE m.folder_path = ? AND {rbac_sql}
                """,
                [norm_path] + rbac_params,
            ).fetchone()
            if not row:
                conn.close()
                return self.refresh_folder_manifest(norm_path)

            prefix_slash = norm_path.rstrip("/") + "/"
            prefix_upper = norm_path.rstrip("/") + "0"
            chunk_count_row = conn.execute(
                """
                SELECT count(*) as total_chunks FROM document_chunks c
                JOIN indexed_files f ON f.file_id = c.file_id
                WHERE (f.parent_dir = ? OR (f.canonical_path >= ? AND f.canonical_path < ?))
                  AND f.parse_status = 'ok'
                """,
                (norm_path, prefix_slash, prefix_upper),
            ).fetchone()
            file_rows = conn.execute(
                """
                SELECT file_name FROM indexed_files
                WHERE (parent_dir = ? OR (canonical_path >= ? AND canonical_path < ?))
                  AND parse_status = 'ok'
                """,
                (norm_path, prefix_slash, prefix_upper),
            ).fetchall()
            files_list = [fr["file_name"] for fr in file_rows]
            total_chunks = int(chunk_count_row["total_chunks"] or 0) if chunk_count_row else int(row["total_files"])

            return {
                "folder_path": row["folder_path"],
                "folder_name": row["folder_name"],
                "total_files": int(row["total_files"]),
                "total_size_bytes": int(row["total_size_bytes"]),
                "total_chunks": total_chunks,
                "files": files_list,
                "outline": row["structural_summary"],
                "file_types": json.loads(row["file_types_json"] or "{}"),
                "structural_summary": row["structural_summary"],
                "topics": json.loads(row["topics_json"] or "[]"),
                "backing_dev": row["backing_dev"],
                "indexed_at": float(row["indexed_at"]),
            }
        finally:
            try:
                conn.close()
            except Exception:
                ignored("backend.services.rag_engine.RagSearchEngine.get_folder_manifest")

    def list_folder_manifests(
        self, path_prefix: str | None = None, principal: Any = None, limit: int = 100, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Lists all known folder manifests with zero disk wakeups."""
        self._ensure_schema()
        conn = self._get_conn(readonly=True)
        try:
            rbac_sql, rbac_params = self._build_rbac_clause(principal, "m")
            sub_sql, sub_params = self._build_subtree_clause(path_prefix, "m")
            eff_limit = max(1, min(500, int(limit or 100)))
            rows = conn.execute(
                f"""
                SELECT * FROM folder_manifests m
                WHERE {rbac_sql} AND {sub_sql}
                ORDER BY total_files DESC, folder_path ASC
                LIMIT ?
                """,
                rbac_params + sub_params + [eff_limit],
            ).fetchall()
            manifests = []
            for r in rows:
                manifests.append(
                    {
                        "folder_path": r["folder_path"],
                        "folder_name": r["folder_name"],
                        "total_files": int(r["total_files"]),
                        "total_size_bytes": int(r["total_size_bytes"]),
                        "outline": r["structural_summary"],
                        "file_types": json.loads(r["file_types_json"] or "{}"),
                        "structural_summary": r["structural_summary"],
                        "topics": json.loads(r["topics_json"] or "[]"),
                        "backing_dev": r["backing_dev"],
                        "indexed_at": float(r["indexed_at"]),
                    }
                )
            return manifests
        finally:
            conn.close()

    def aggregate_folder_context(
        self,
        folder_path: str,
        query: str = "",
        max_tokens: int = 4000,
        principal: Any = None,
        diversity_lambda: float = 0.60,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """
        RAG v3 Folder Context Engine:
          - Spindown-Safe: 100% Zero Array Disk I/O against /app/data/rag_index.db
          - Mode A (Targeted Fact Retrieval): query-specific chunks mapped to deduplicated parent context
          - Mode B (Comprehensive Folder Audit): Maximal Marginal Relevance (MMR) diverse sampling
            across all files in the folder so no single document crowds out the rest.
        """
        self._ensure_schema()
        norm_path = os.path.normpath(folder_path)
        backing_dev = rag_standby.resolve_path_backing_dev(norm_path)
        is_standby = rag_standby.is_backing_disk_in_standby(backing_dev)
        try:
            eff_max_tokens = max(100, int(max_tokens or 4000))
        except (ValueError, TypeError):
            eff_max_tokens = 4000

        manifest = self.get_folder_manifest(norm_path, principal=principal)
        if not manifest or manifest.get("total_files", 0) == 0:
            return {
                "status": "empty",
                "mode": "comprehensive"
                if mode and mode.lower() in ("comprehensive", "mode_b", "audit")
                else "targeted",
                "folder_path": norm_path,
                "message": f"No indexed files found in folder {norm_path}.",
                "manifest": manifest,
                "selected_chunks": [],
                "chunks": [],
                "context_text": "",
                "summary": "",
                "files_included": 0,
                "total_tokens": 0,
                "evidence_count": 0,
                "grounding_confidence_score": 0,
                "crag_grade": "low",
                "standby_guard": {
                    "served_from_nvme_cache": True,
                    "zero_disk_wakeups": True,
                    "disk_state": "standby" if is_standby else "active",
                    "backing_dev": backing_dev,
                },
            }

        q_clean = (query or "").strip().lower()
        audit_intent_words = {
            "summarize",
            "summary",
            "audit",
            "overview",
            "all",
            "what's in",
            "whats in",
            "compare",
            "list",
            "status",
        }
        if mode:
            is_mode_b = mode.lower() in ("comprehensive", "mode_b", "audit")
        else:
            is_mode_b = (not q_clean) or any(w in q_clean for w in audit_intent_words)

        conn = self._get_conn(readonly=True)
        try:
            rbac_sql, rbac_params = self._build_rbac_clause(principal, "f")
            sub_sql, sub_params = self._build_subtree_clause(norm_path, "f")

            rows = conn.execute(
                f"""
                SELECT
                    c.chunk_id, c.file_id, c.chunk_index, c.parent_chunk_id, c.chunk_level,
                    c.heading_context, c.structural_context, c.chunk_text, c.raw_chunk_text,
                    c.line_start, c.line_end, c.token_count, c.embedding_f32,
                    f.canonical_path, f.file_name, f.doc_title, f.doc_type, f.size_bytes
                FROM document_chunks c
                JOIN indexed_files f ON f.file_id = c.file_id
                WHERE f.parse_status = 'ok' AND c.chunk_level = 'child'
                  AND {rbac_sql} AND {sub_sql}
                LIMIT 500
                """,
                rbac_params + sub_params,
            ).fetchall()
            # The SQL tier check treats every share as public; drop what this principal can't read.
            readable = self._readable_paths({r["canonical_path"] for r in rows}, principal)
            rows = [r for r in rows if r["canonical_path"] in readable]

            if not rows:
                return {
                    "status": "ok",
                    "mode": "comprehensive" if is_mode_b else "targeted",
                    "folder_path": norm_path,
                    "manifest": manifest,
                    "selected_chunks": [],
                    "chunks": [],
                    "context_text": "",
                    "summary": manifest.get("structural_summary", "") if manifest else "",
                    "files_included": 0,
                    "total_tokens": 0,
                    "evidence_count": 0,
                    "grounding_confidence_score": 0,
                    "crag_grade": "low",
                    "standby_guard": {
                        "served_from_nvme_cache": True,
                        "zero_disk_wakeups": True,
                        "disk_state": "standby" if is_standby else "active",
                        "backing_dev": backing_dev,
                    },
                }

            parent_ids = {int(r["parent_chunk_id"]) for r in rows if r["parent_chunk_id"] is not None}
            parent_chunk_map: dict[int, sqlite3.Row] = {}
            if parent_ids:
                p_placeholders = ",".join("?" for _ in parent_ids)
                p_rows = conn.execute(
                    f"SELECT chunk_id, heading_context, chunk_text, raw_chunk_text, line_start, line_end FROM document_chunks WHERE chunk_id IN ({p_placeholders})",
                    list(parent_ids),
                ).fetchall()
                parent_chunk_map = {int(pr["chunk_id"]): pr for pr in p_rows}

            cfg = self.get_config()
            chosen_emb_model = cfg.get("embedding_model") or "embeddinggemma"
            target_dim = cfg.get("embedding_dim")
            ollama_host = embedding_host(cfg)
            intent_type, task_prefix = classify_query_task_intent(query or norm_path)
            _, query_vec = compute_multimodal_query_embedding(
                query=query or norm_path,
                model=chosen_emb_model,
                ollama_host=ollama_host,
                target_dim=target_dim,
                task_prompt=task_prefix,
            )

            candidate_pool = []
            for r in rows:
                emb = unpack_embedding(r["embedding_f32"])
                sim = cosine_similarity_vec(query_vec, emb)
                candidate_pool.append(
                    {
                        "row": r,
                        "emb": emb,
                        "sim": sim,
                        "file_id": int(r["file_id"]),
                        "chunk_id": int(r["chunk_id"]),
                        "parent_chunk_id": int(r["parent_chunk_id"]) if r["parent_chunk_id"] is not None else None,
                    }
                )

            selected_items = []
            used_parent_ids: set[int] = set()
            used_file_counts: dict[int, int] = {}
            current_tokens = 0

            if is_mode_b:
                selected_embs: list[list[float]] = []
                pool_left = list(candidate_pool)

                while pool_left and current_tokens < eff_max_tokens:
                    best_item = None
                    best_score = -999.0
                    best_idx = -1

                    for idx, cand in enumerate(pool_left):
                        file_cnt = used_file_counts.get(cand["file_id"], 0)
                        file_penalty = 0.25 * file_cnt

                        if not selected_embs:
                            mmr_score = cand["sim"] - file_penalty
                        else:
                            max_sim_to_selected = max(
                                cosine_similarity_vec(cand["emb"], s_emb) for s_emb in selected_embs
                            )
                            mmr_score = (
                                diversity_lambda * cand["sim"]
                                - (1.0 - diversity_lambda) * max_sim_to_selected
                                - file_penalty
                            )

                        if mmr_score > best_score:
                            best_score = mmr_score
                            best_item = cand
                            best_idx = idx

                    if not best_item or best_idx < 0:
                        break

                    pool_left.pop(best_idx)
                    r = best_item["row"]
                    p_id = best_item["parent_chunk_id"]

                    gen_text = ""
                    p_row = parent_chunk_map.get(p_id) if p_id else None
                    if p_row and p_id not in used_parent_ids:
                        gen_text = p_row["raw_chunk_text"] or p_row["chunk_text"]
                        used_parent_ids.add(p_id)
                    elif not p_row:
                        gen_text = r["raw_chunk_text"] or r["chunk_text"]

                    if gen_text:
                        item_tokens = max(1, len(gen_text.split()))
                        if current_tokens + item_tokens <= eff_max_tokens or not selected_items:
                            selected_items.append(
                                {
                                    "file_name": r["file_name"],
                                    "doc_title": r["doc_title"],
                                    "file_path": r["canonical_path"],
                                    "heading": r["heading_context"],
                                    "chunk_text": gen_text,
                                    "line_start": r["line_start"],
                                    "line_end": r["line_end"],
                                    "token_count": item_tokens,
                                    "mmr_score": round(best_score, 4),
                                }
                            )
                            current_tokens += item_tokens
                            used_file_counts[best_item["file_id"]] = used_file_counts.get(best_item["file_id"], 0) + 1
                            if best_item["emb"]:
                                selected_embs.append(best_item["emb"])
            else:
                candidate_pool.sort(key=lambda x: x["sim"], reverse=True)
                for cand in candidate_pool:
                    if current_tokens >= eff_max_tokens:
                        break
                    r = cand["row"]
                    p_id = cand["parent_chunk_id"]
                    p_row = parent_chunk_map.get(p_id) if p_id else None
                    if p_row and p_id in used_parent_ids:
                        continue
                    if p_row:
                        gen_text = p_row["raw_chunk_text"] or p_row["chunk_text"]
                        if p_id:
                            used_parent_ids.add(p_id)
                    else:
                        gen_text = r["raw_chunk_text"] or r["chunk_text"]

                    item_tokens = max(1, len(gen_text.split()))
                    if current_tokens + item_tokens <= max_tokens or not selected_items:
                        selected_items.append(
                            {
                                "file_name": r["file_name"],
                                "doc_title": r["doc_title"],
                                "file_path": r["canonical_path"],
                                "heading": r["heading_context"],
                                "chunk_text": gen_text,
                                "line_start": r["line_start"],
                                "line_end": r["line_end"],
                                "token_count": item_tokens,
                                "score": round(cand["sim"], 4),
                            }
                        )
                        current_tokens += item_tokens

            reordered_items = apply_primacy_recency_inversion(selected_items)
            context_text = "\n\n".join(
                f"### {item.get('doc_title') or item.get('file_name')} ({item.get('file_name')})\n{item.get('chunk_text', '')}"
                for item in reordered_items
            )
            summary = manifest.get("structural_summary", "") if manifest else ""
            files_included = len(set(it.get("file_name") for it in reordered_items if it.get("file_name")))

            return {
                "status": "ok",
                "mode": "comprehensive" if is_mode_b else "targeted",
                "folder_path": norm_path,
                "manifest": manifest,
                "selected_chunks": reordered_items,
                "chunks": reordered_items,
                "context_text": context_text,
                "summary": summary,
                "files_included": files_included or (manifest.get("total_files", 0) if manifest else 0),
                "total_tokens": current_tokens,
                "evidence_count": len(reordered_items),
                # Folder context is gathered, not answered: there is no answer to check yet.
                "grounding_confidence_score": None,
                "crag_grade": "unrated",
                "standby_guard": {
                    "served_from_nvme_cache": True,
                    "zero_disk_wakeups": True,
                    "disk_state": "standby" if is_standby else "active",
                    "backing_dev": backing_dev,
                },
            }
        finally:
            conn.close()

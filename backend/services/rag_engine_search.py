"""Search, ask and thumbnails for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

# pyright: reportAttributeAccessIssue=false

import json
import os
import re
import struct
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
from backend.services import (  # noqa: F401
    rag_standby,
)
from backend.services.rag_documents import (  # noqa: F401
    late_interaction_rerank,
)
from backend.services.rag_embeddings import (  # noqa: F401
    classify_query_task_intent,
    compute_384d_embedding,
    compute_multimodal_query_embedding,
    cosine_similarity_vec,
    embedding_host,
    unpack_embedding,
)
from backend.services.rag_grounding import (  # noqa: F401
    apply_primacy_recency_inversion,
    compute_grounding_confidence_score,
    grade_rag_retrieval,
)
from backend.services.rag_text import (  # noqa: F401
    _STOPWORDS,
    CANONICAL_COLORS,
    COLOR_SYNONYMS,
    _has_cjk,
    _normalize_pdf_broken_words,
    _token_matches_word,
    bhattacharyya_similarity,
    build_safe_fts5_query,
    build_target_color_histogram,
    parse_multimodal_query,
    text_tokens,
)

DIRECT_SCOPE_CHUNKS = 4000  # a scope this small is scored whole, exactly (AI-23)


def _core():
    """backend.services.rag_engine, read at call time: shared settings live there and tests patch them."""
    from backend.services import rag_engine

    return rag_engine


PHOTO_RECENT_CANDIDATES = 3000  # newest photos scored besides every keyword hit (AI-2)


def _readable_share_names(username: str) -> set[str] | None:
    """Lower-case names of the shared folders `username` may read; None when no shares are known
    here (then the per-file check alone decides, as before)."""
    try:
        from backend.services.share_access import grants_for, known_shares

        if not username or not known_shares():
            return None
        names = set()
        for root, level in grants_for(username):
            if level in ("read", "write") and "/homes/" not in root.rstrip("/") + "/":
                names.add(os.path.basename(root.rstrip("/")).lower())
        return names
    except Exception:
        logger.debug("rag search: share grants unavailable", exc_info=True)
        return None


class RagSearchMixin:
    """Search, ask and thumbnails for RagSearchEngine (split out of rag_engine.py, ARCH-1)."""

    @staticmethod
    def _build_rbac_clause(principal: Any, table_alias: str = "f") -> tuple[str, list[Any]]:
        """Builds parameterized SQLite WHERE predicate for multi-user RBAC path isolation."""
        if principal is None:
            return ("1=1", [])
        role_id = str(getattr(principal, "role_id", "") or "").lower()
        has_any = getattr(principal, "has_any_scope", None)
        is_admin = role_id in ("superadmin", "storage_admin") or (
            callable(has_any) and has_any("storage:admin", "shares:manage", "*")
        )
        if is_admin:
            return ("1=1", [])

        username = str(getattr(principal, "username", "") or "").lower().strip()
        pfx = f"{table_alias}." if table_alias else ""
        # Shared folders this person may read, filtered here rather than after the search, so a
        # person with a few shares gets a full result list (AI-10). The per-file check afterwards
        # stays as the final word.
        share_names = _readable_share_names(username)
        if share_names is None:
            public_sql, public_params = f"{pfx}visibility_tier = 'public_share'", []
        elif share_names:
            public_sql = (
                f"({pfx}visibility_tier = 'public_share' AND {pfx}share_name IN ({','.join('?' * len(share_names))}))"
            )
            public_params = sorted(share_names)
        else:
            public_sql, public_params = "0", []
        sql = (
            f"({public_sql} "
            f"OR ({pfx}visibility_tier = 'user_home' AND {pfx}owner_username = ?) "
            f"OR ({pfx}visibility_tier = 'restricted_share' AND instr(',' || {pfx}allowed_users_csv || ',', ',' || ? || ',') > 0))"
        )
        return (sql, [*public_params, username, username])

    def tag_counts(self, principal: Any = None) -> dict[str, int]:
        """How many documents this person may see carry each auto-tag (the search filter chips)."""
        from backend.services import rag_tags

        self._ensure_schema()
        rbac_sql, rbac_params = self._build_rbac_clause(principal, "f")
        conn = self._get_conn(readonly=True)
        try:
            return rag_tags.counts(conn, rbac_sql, rbac_params)
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    @staticmethod
    def _build_subtree_clause(path_prefix: str | None, table_alias: str = "f") -> tuple[str, list[Any]]:
        """Exact B-tree directory boundary predicate immune to prefix sibling traversal (/homes/alice vs /homes/alice_bob)."""
        if not path_prefix or not str(path_prefix).strip():
            return ("1=1", [])
        clean_dir = os.path.normpath(str(path_prefix).strip())
        if clean_dir in ("/", "."):
            return ("1=1", [])
        pfx = f"{table_alias}." if table_alias else ""
        dir_slash = clean_dir.rstrip("/") + "/"
        dir_upper = clean_dir.rstrip("/") + "0"
        return (
            f"({pfx}canonical_path = ? OR ({pfx}canonical_path >= ? AND {pfx}canonical_path < ?))",
            [clean_dir, dir_slash, dir_upper],
        )

    @staticmethod
    def _post_rbac_checker(principal: Any) -> Any:
        """_check_post_rbac for many index paths in one request: no disk access, grants loaded once."""
        checker = None
        if principal is not None:
            try:
                from backend.services.path_access import indexed_path_checker

                checker = indexed_path_checker(principal)
            except Exception:  # an unusable principal reads nothing, as with _check_post_rbac
                logger.debug("backend.services.rag_engine._post_rbac_checker: refused", exc_info=True)
                checker = lambda _path: False  # noqa: E731

        def ok(canonical_path: str) -> bool:
            if "/.RecycleBin/" in canonical_path or canonical_path.endswith("/.RecycleBin"):
                return False
            if checker is None:
                return True
            try:
                return checker(canonical_path)
            except Exception:
                logger.debug("backend.services.rag_engine._post_rbac_checker: refused", exc_info=True)
                return False

        return ok

    @staticmethod
    def _check_post_rbac(canonical_path: str, principal: Any) -> bool:
        """Defense-in-depth post-retrieval path verification."""
        if "/.RecycleBin/" in canonical_path or canonical_path.endswith("/.RecycleBin"):
            return False
        if principal is None:
            return True
        try:
            from backend.services.path_access import check_user_path_access

            check_user_path_access(canonical_path, principal)
            return True
        except Exception:
            return False

    def search(
        self,
        query: str = "",
        mode: str = "all",
        colors: list[str] | None = None,
        scenes: list[str] | None = None,
        path_prefix: str | None = None,
        limit: int = 24,
        principal: Any = None,
        match_tab: str = "semantic",
        sort_by: str = "relevance",
        embedding_model: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        100% Zero-Disk-Touch Cross-Modal Search over `/app/data/rag_index.db` (mode=ro).
        Never calls os.stat(), os.path.exists(), or open() on array paths!
        Supports ZettAI match tabs (semantic | keyword | audio), file types (all | images | videos | audio | documents | folders),
        sort orders (relevance | keyword | mtime), and grouped category summary cards.
        """
        self._ensure_schema()
        limit = max(1, min(100, int(limit or 24)))
        from backend.services import rag_tags

        want_tags = rag_tags.valid(tags)
        intent = parse_multimodal_query(query)
        cfg = self.get_config()
        fav_set = {os.path.normpath(p) for p in (cfg.get("favorites") or [])}

        # Merge explicit filter chips with auto-extracted query intent
        req_colors: list[str] = []
        for c in (colors or []) + intent["auto_colors"]:
            cn = COLOR_SYNONYMS.get(str(c).lower().strip(), str(c).lower().strip())
            if cn in CANONICAL_COLORS and cn not in req_colors:
                req_colors.append(cn)

        req_scenes: list[str] = []
        for s in (scenes or []) + intent["auto_scenes"]:
            sn = str(s).lower().strip()
            if sn and sn not in req_scenes:
                req_scenes.append(sn)

        raw_mode = (mode or "all").lower().strip()
        if raw_mode in ("photo", "images", "image"):
            effective_mode = "photos"
        elif raw_mode in ("document", "docs"):
            effective_mode = "documents"
        elif raw_mode in ("all", "photos", "visual", "documents", "recipes", "videos", "audio", "folders"):
            effective_mode = raw_mode
        else:
            effective_mode = "all"

        eff_tab = (match_tab or "semantic").lower().strip()
        if eff_tab not in ("semantic", "keyword", "audio"):
            eff_tab = "semantic"

        eff_sort = (sort_by or "relevance").lower().strip()
        if eff_sort not in ("relevance", "keyword", "mtime"):
            eff_sort = "relevance"

        chosen_emb_model = embedding_model or cfg.get("embedding_model") or "embeddinggemma"
        target_dim = cfg.get("embedding_dim")
        intent_type, task_prefix = classify_query_task_intent(query, modality_hint=effective_mode)
        effective_emb_model, query_vec = compute_multimodal_query_embedding(
            query=query,
            model=chosen_emb_model,
            ollama_host=embedding_host(cfg),
            target_dim=target_dim,
            req_scenes=req_scenes,
            req_colors=req_colors,
            task_prompt=task_prefix,
        )
        if effective_emb_model != "zett_lexical_384d":
            # the first search with a model measures its similarity cut-off, in the background (AI-17)
            from backend.services import rag_calibration

            rag_calibration.ensure_measured(effective_emb_model, target_dim, embedding_host(cfg))
        fts_query = build_safe_fts5_query(query)
        target_hist = build_target_color_histogram(req_colors) if req_colors else []
        # The embedder didn't answer: results come from keywords only, and the person is told (AI-4)
        search_degraded = chosen_emb_model != "zett_lexical_384d" and effective_emb_model == "zett_lexical_384d"

        conn = self._get_conn(readonly=True)
        try:
            photo_items: list[dict[str, Any]] = []
            doc_items: list[dict[str, Any]] = []

            # 1. Visual / Photo Search Branch (always run when query/filters exist so category_groups counts are complete)
            if not want_tags and (
                effective_mode in ("all", "photos", "visual", "videos", "folders")
                or (effective_mode == "recipes" and "recipe" in req_scenes)
                or bool(query.strip() or req_colors or req_scenes)
            ):
                photo_vec = query_vec
                if effective_emb_model != "zett_lexical_384d" or len(query_vec) != 384:
                    _, photo_vec = compute_384d_embedding(
                        text=query or " ".join(req_scenes + req_colors),
                        scene_tags=req_scenes,
                        object_colors={c: 1.0 for c in req_colors},
                        frame_colors={c: 0.8 for c in req_colors},
                        color_hist_64=target_hist if req_colors else None,
                    )
                photo_items = self._search_photos_ro(
                    conn=conn,
                    raw_query=query,
                    fts_query=fts_query,
                    query_vec=photo_vec,
                    req_colors=req_colors,
                    req_scenes=req_scenes,
                    target_hist=target_hist,
                    path_prefix=path_prefix,
                    limit=max(limit * 2, 48),
                    principal=principal,
                )

            # 2. Document / Recipe / Code / Audio Transcript Search Branch
            if effective_mode in ("all", "documents", "recipes", "audio", "videos", "folders") or bool(
                query.strip() or want_tags
            ):
                doc_items = self._search_documents_ro(
                    conn=conn,
                    raw_query=query,
                    fts_query=fts_query,
                    query_vec=query_vec,
                    req_scenes=req_scenes,
                    only_recipes=(effective_mode == "recipes"),
                    path_prefix=path_prefix,
                    limit=max(limit * 2, 48),
                    principal=principal,
                    modality_hint=intent.get("modality_hint", "all"),
                    only_docs=(effective_mode == "documents"),
                    query_embedding_model=effective_emb_model,
                    query_embedding_dim=target_dim,
                    intent_type=intent_type,
                    tags=want_tags,
                )
                # Optional cross-encoder reranking of the top documents (AI-13)
                if doc_items and query.strip():
                    from backend.services.rag_rerank import rerank_items

                    doc_items = rerank_items(query, doc_items, self.get_config())

            all_candidates = photo_items + doc_items
            q_lower = (query or "").strip().lower()
            q_terms = [t for t in text_tokens(q_lower) if len(t) >= 2]

            video_exts = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
            audio_exts = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}

            for it in all_candidates:
                p_norm = os.path.normpath(it.get("path") or "")
                it["is_favorite"] = p_norm in fav_set
                it["parent_dir"] = os.path.dirname(p_norm)
                ext = os.path.splitext(it.get("name") or "")[1].lower()
                if ext in video_exts:
                    it["category_type"] = "videos"
                elif ext in audio_exts or it.get("doc_type") == "audio":
                    it["category_type"] = "audio"
                elif it.get("media_type") == "photo" or it.get("modality") == "image":
                    it["category_type"] = "images"
                else:
                    it["category_type"] = "documents"

                # Compute explicit keyword match score for Keyword tab / sort using whole-word boundaries
                haystack = f"{it.get('name', '')} {it.get('title', '')} {it.get('excerpt', '')} {it.get('ocr_snippet', '')} {' '.join(it.get('scene_tags') or [])}".lower()
                name_lower = (it.get("name") or "").lower()
                if q_lower and _token_matches_word(q_lower, haystack):
                    kw_score = 0.95 if _token_matches_word(q_lower, name_lower) else 0.82
                elif q_terms:
                    matched_cnt = sum(1 for t in q_terms if _token_matches_word(t, haystack))
                    kw_score = round(0.85 * (matched_cnt / len(q_terms)), 4)
                else:
                    kw_score = it.get("score", 0.5)
                it["keyword_score"] = kw_score

            # Filter by match_tab if 'keyword' or 'audio'
            if eff_tab == "keyword" and q_terms:
                filtered_candidates = [it for it in all_candidates if it.get("keyword_score", 0.0) > 0.0]
                if filtered_candidates:
                    all_candidates = filtered_candidates
            elif eff_tab == "audio":
                audio_only = [
                    it
                    for it in all_candidates
                    if it.get("category_type") in ("audio", "videos")
                    or "audio" in (it.get("name") or "").lower()
                    or "transcript" in (it.get("excerpt") or "").lower()
                ]
                if audio_only:
                    all_candidates = audio_only

            # Build ZettAI Category Summary Groups (Images, Videos, Audio, Documents, Folders)
            cat_images = [it for it in all_candidates if it.get("category_type") == "images"]
            cat_videos = [it for it in all_candidates if it.get("category_type") == "videos"]
            cat_audio = [it for it in all_candidates if it.get("category_type") == "audio"]
            cat_docs = [it for it in all_candidates if it.get("category_type") == "documents"]

            folder_map: dict[str, dict[str, Any]] = {}
            for it in all_candidates:
                pdir = it.get("parent_dir") or ""
                if not pdir:
                    continue
                if pdir not in folder_map:
                    folder_map[pdir] = {
                        "id": f"folder:{pdir}",
                        "name": os.path.basename(pdir) or pdir,
                        "path": pdir,
                        "file_path": pdir,
                        "media_type": "folder",
                        "category_type": "folders",
                        "item_count": 0,
                        "score": it.get("score", 0.5),
                        "mtime": it.get("mtime", 0),
                        "disk_state": it.get("disk_state", "active"),
                    }
                folder_map[pdir]["item_count"] += 1
                if it.get("score", 0) > folder_map[pdir]["score"]:
                    folder_map[pdir]["score"] = it.get("score", 0)

            cat_folders = sorted(folder_map.values(), key=lambda x: (x["score"], x["item_count"]), reverse=True)

            # Filter by explicit file_type mode if requested
            if effective_mode == "videos":
                combined = list(cat_videos)
            elif effective_mode == "audio":
                combined = list(cat_audio)
            elif effective_mode == "folders":
                combined = list(cat_folders)
            elif effective_mode in ("photos", "visual"):
                combined = list(cat_images)
            elif effective_mode in ("documents", "recipes"):
                combined = list(cat_docs)
            else:
                combined = list(all_candidates)

            # Apply requested sort order
            if eff_sort == "mtime":
                combined.sort(key=lambda x: (int(x.get("mtime") or 0), float(x.get("score") or 0.0)), reverse=True)
            elif eff_sort == "keyword" or eff_tab == "keyword":
                combined.sort(
                    key=lambda x: (float(x.get("keyword_score") or 0.0), float(x.get("score") or 0.0)),
                    reverse=True,
                )
            else:
                combined.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
                combined = late_interaction_rerank(query, combined, top_k=limit)

            combined = combined[:limit]

            # Build top structured_card if top hit is a recipe or invoice (or recipe intent requested)
            structured_card = None
            candidate_cards = combined if ("recipe" in req_scenes or effective_mode == "recipes") else combined[:1]
            for item in candidate_cards:
                if item.get("structured_card"):
                    sc = dict(item["structured_card"])
                    clean_sc_title = _normalize_pdf_broken_words(sc.get("title") or "")
                    sc["title"] = clean_sc_title or item.get("title") or item.get("name") or "Document"
                    structured_card = sc
                    break

            deferred_cnt = conn.execute("SELECT COUNT(*) FROM rag_deferred_queue").fetchone()[0]

            return {
                "status": "ok",
                "query": query,
                "degraded": search_degraded,
                "degraded_reason": "The AI search model didn't answer; these results match words only."
                if search_degraded
                else "",
                "mode": effective_mode,
                "match_tab": eff_tab,
                "sort_by": eff_sort,
                "parsed_intent": {
                    "tokens": intent["tokens"],
                    "auto_colors": req_colors,
                    "auto_scenes": req_scenes,
                    "semantic_query": intent["semantic_query"],
                    "modality_hint": intent["modality_hint"],
                },
                "structured_card": structured_card,
                "category_groups": {
                    "images": {"count": len(cat_images), "items": cat_images[:8]},
                    "videos": {"count": len(cat_videos), "items": cat_videos[:8]},
                    "audio": {"count": len(cat_audio), "items": cat_audio[:8]},
                    "documents": {"count": len(cat_docs), "items": cat_docs[:8]},
                    "folders": {"count": len(cat_folders), "items": cat_folders[:8]},
                },
                "standby_guard": {
                    "served_from_nvme_cache": True,
                    "zero_disk_wakeups": True,
                    "sleeping_disks": rag_standby.get_sleeping_disks_list(),
                    "deferred_queue_count": deferred_cnt,
                },
                "items": combined,
                "results": photo_items[:limit] if effective_mode in ("photos", "visual") else combined,
                "photo_results": photo_items[:limit],
                "document_results": doc_items[:limit],
            }
        finally:
            conn.close()

    def _search_photos_ro(
        self,
        conn: sqlite3.Connection,
        raw_query: str,
        fts_query: str,
        query_vec: list[float],
        req_colors: list[str],
        req_scenes: list[str],
        target_hist: list[float],
        path_prefix: str | None,
        limit: int,
        principal: Any,
    ) -> list[dict[str, Any]]:
        rbac_sql, rbac_params = self._build_rbac_clause(principal, "f")
        sub_sql, sub_params = self._build_subtree_clause(path_prefix, "f")

        # FTS5 BM25 lexical lookup on rag_photos_fts, among the photos this person may see in the
        # chosen folder (AI-23)
        bm25_map: dict[int, float] = {}
        if fts_query:
            try:
                fts_rows = conn.execute(
                    f"""
                    SELECT rag_photos_fts.rowid AS file_id,
                           -bm25(rag_photos_fts, 3.0, 5.0, 5.0, 4.0, 2.0, 4.0) AS raw_bm25
                    FROM rag_photos_fts
                    JOIN indexed_files f ON f.file_id = rag_photos_fts.rowid
                    WHERE rag_photos_fts MATCH ? AND f.parse_status = 'ok' AND {rbac_sql} AND {sub_sql}
                    ORDER BY raw_bm25 DESC
                    LIMIT 250
                    """,
                    [fts_query, *rbac_params, *sub_params],
                ).fetchall()
                for r in fts_rows:
                    raw_val = max(0.0, float(r["raw_bm25"] or 0.0))
                    bm25_map[int(r["file_id"])] = raw_val / (raw_val + 4.0)
            except sqlite3.OperationalError:
                pass

        photo_cols = """
                p.file_id, p.file_name, p.width, p.height, p.aspect_ratio, p.format,
                p.taken_at, p.camera_make, p.camera_model, p.dominant_hex, p.palette_json,
                p.object_colors_json, p.frame_colors_json, p.color_hist_f32, p.center_color_hist_f32,
                p.scene_tags_json, p.auto_tags_text, p.caption_text, p.ocr_text, p.vision_embedding_f32,
                f.canonical_path, f.size_bytes, f.mtime_ns, f.backing_dev, f.doc_type, f.doc_metadata_json"""
        # Candidates: every keyword hit (captions, OCR, tags), then the newest photos for the
        # colour and scene scoring; before, 2,000 photos in no particular order (AI-2)
        rows = []
        if bm25_map:
            hit_ids = list(bm25_map)
            rows = conn.execute(
                f"""
                SELECT {photo_cols}
                FROM photo_assets p
                JOIN indexed_files f ON f.file_id = p.file_id
                WHERE p.file_id IN ({",".join("?" * len(hit_ids))}) AND f.parse_status = 'ok' AND {rbac_sql} AND {sub_sql}
                """,
                hit_ids + rbac_params + sub_params,
            ).fetchall()
        seen_photo_ids = [int(r["file_id"]) for r in rows]
        exclude_sql = f"AND p.file_id NOT IN ({','.join('?' * len(seen_photo_ids))})" if seen_photo_ids else ""
        rows += conn.execute(
            f"""
            SELECT {photo_cols}
            FROM photo_assets p
            JOIN indexed_files f ON f.file_id = p.file_id
            WHERE f.parse_status = 'ok' AND {rbac_sql} AND {sub_sql} {exclude_sql}
            ORDER BY f.mtime_ns DESC
            LIMIT {PHOTO_RECENT_CANDIDATES}
            """,
            rbac_params + sub_params + seen_photo_ids,
        ).fetchall()

        photo_query_vec = query_vec
        if not photo_query_vec or len(photo_query_vec) != 384:
            _, photo_query_vec = compute_384d_embedding(
                text=raw_query or " ".join(req_scenes + req_colors),
                scene_tags=req_scenes,
                object_colors={c: 1.0 for c in req_colors},
                frame_colors={c: 0.8 for c in req_colors},
                color_hist_64=target_hist if req_colors else None,
            )

        results: list[dict[str, Any]] = []
        q_lower = (raw_query or "").lower()
        readable = self._post_rbac_checker(principal)

        for r in rows:
            c_path = r["canonical_path"]
            if not readable(c_path):
                continue

            fid = int(r["file_id"])
            obj_colors: dict[str, float] = json.loads(r["object_colors_json"] or "{}")
            frm_colors: dict[str, float] = json.loads(r["frame_colors_json"] or "{}")
            scene_tags: list[str] = json.loads(r["scene_tags_json"] or "[]")
            palette_swatches: list[str] = json.loads(r["palette_json"] or "[]")

            emb_vec = unpack_embedding(r["vision_embedding_f32"])
            s_vec = cosine_similarity_vec(photo_query_vec, emb_vec)
            s_bm25 = bm25_map.get(fid, 0.0)

            # Color similarity (center-weighted Bhattacharyya + explicit 12-color fraction)
            s_color = 0.0
            max_target_color_weight = 0.0
            if req_colors:
                s_hist_center = bhattacharyya_similarity(target_hist, r["center_color_hist_f32"])
                s_hist_frame = bhattacharyya_similarity(target_hist, r["color_hist_f32"])
                for c in req_colors:
                    cw = max(float(obj_colors.get(c, 0.0)), 0.65 * float(frm_colors.get(c, 0.0)))
                    if cw > max_target_color_weight:
                        max_target_color_weight = cw
                s_color = 0.50 * max_target_color_weight + 0.35 * s_hist_center + 0.15 * s_hist_frame

            # Scene match confidence
            matched_scenes = [
                s for s in req_scenes if s in scene_tags or _token_matches_word(s, r["auto_tags_text"].lower())
            ]
            w_scene = 1.0 if matched_scenes else 0.0

            # Confidence-Weighted Compositional Match Boost (+0.45 max) & Negative Color Mismatch Penalty (0.35x)
            compositional_match = False
            b_comp = 0.0
            color_penalty_mult = 1.0

            if req_colors and req_scenes:
                if max_target_color_weight >= 0.08 and w_scene > 0.0:
                    compositional_match = True
                    b_comp = 0.45 * min(1.0, max_target_color_weight / 0.18) * w_scene
                elif max_target_color_weight < 0.03:
                    # Dampen photos of the wrong color (e.g. blue car when searching for red car)
                    color_penalty_mult = 0.35
                elif w_scene == 0.0:
                    color_penalty_mult = 0.55
            elif req_colors:
                if max_target_color_weight >= 0.10:
                    b_comp = 0.30 * min(1.0, max_target_color_weight / 0.20)
                elif max_target_color_weight < 0.03:
                    color_penalty_mult = 0.30
            elif req_scenes:
                if w_scene > 0.0:
                    b_comp = 0.35
                else:
                    color_penalty_mult = 0.45

            # Base hybrid combination
            if req_colors:
                base_score = 0.38 * s_vec + 0.27 * s_bm25 + 0.35 * s_color
            else:
                base_score = 0.55 * s_vec + 0.45 * s_bm25

            if q_lower and _token_matches_word(q_lower, r["file_name"].lower()):
                base_score += 0.15

            final_score = min(1.0, (base_score + b_comp) * color_penalty_mult)

            # Filter out weak non-matches when a specific query/filter was provided
            if raw_query.strip() and not req_colors and not req_scenes and s_bm25 <= 0.0:
                photo_haystack = f"{r['file_name']} {r['auto_tags_text']} {r['caption_text']} {r['ocr_text']}".lower()
                q_words = [w for w in text_tokens(q_lower) if w not in _STOPWORDS and (len(w) >= 3 or _has_cjk(w))]
                if q_words and not any(_token_matches_word(w, photo_haystack) for w in q_words) and s_vec < 0.48:
                    continue
            if (raw_query.strip() or req_colors or req_scenes) and final_score < 0.12:
                continue

            backing_dev = r["backing_dev"] or rag_standby.resolve_path_backing_dev(c_path)
            disk_state = "standby" if rag_standby.is_backing_disk_in_standby(backing_dev) else "active"

            doc_meta = json.loads(r["doc_metadata_json"] or "{}")
            structured_card = None
            if r["doc_type"] in ("recipe", "invoice") and doc_meta.get("card_type"):
                structured_card = dict(doc_meta)
                structured_card["type"] = structured_card.get("card_type")
                structured_card["source_file_id"] = fid
                structured_card["source_path"] = c_path
                structured_card["thumbnail_url"] = f"/api/media/thumbnail/{fid}"

            results.append(
                {
                    "id": fid,
                    "file_id": fid,
                    "path": c_path,
                    "file_path": c_path,
                    "name": r["file_name"],
                    "file_name": r["file_name"],
                    "media_type": "photo",
                    "modality": "image",
                    "doc_type": r["doc_type"],
                    "score": round(final_score, 4),
                    "compositional_match": compositional_match,
                    "thumbnail_url": f"/api/media/thumbnail/{fid}",
                    "dominant_hex": r["dominant_hex"],
                    "color_swatches": palette_swatches or [r["dominant_hex"]],
                    "object_colors": list(obj_colors.keys()),
                    "dominant_colors": list(frm_colors.keys()),
                    "frame_colors": list(frm_colors.keys()),
                    "scene_tags": scene_tags,
                    "ocr_snippet": (r["ocr_text"] or "")[:240] or None,
                    "excerpt": (r["ocr_text"] or r["caption_text"] or "")[:240],
                    "structured_card": structured_card,
                    "width": r["width"],
                    "height": r["height"],
                    "camera_model": r["camera_model"] or None,
                    "disk_id": backing_dev or "nvme0n1",
                    "disk_state": disk_state,
                    "size_bytes": int(r["size_bytes"]),
                    "mtime": int(int(r["mtime_ns"]) // 1_000_000_000),
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def _search_documents_ro(
        self,
        conn: sqlite3.Connection,
        raw_query: str,
        fts_query: str,
        query_vec: list[float],
        req_scenes: list[str],
        only_recipes: bool,
        path_prefix: str | None,
        limit: int,
        principal: Any,
        modality_hint: str = "all",
        only_docs: bool = False,
        query_embedding_model: str = "zett_lexical_384d",
        query_embedding_dim: int | None = None,
        intent_type: str = "search",
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rbac_sql, rbac_params = self._build_rbac_clause(principal, "f")
        sub_sql, sub_params = self._build_subtree_clause(path_prefix, "f")
        if tags:
            from backend.services import rag_tags

            tag_sql, tag_params = rag_tags.filter_sql(tags, "f")
            sub_sql, sub_params = f"({sub_sql}{tag_sql})", [*sub_params, *tag_params]
        recipe_sql = "AND f.doc_type = 'recipe'" if only_recipes else ""
        scope_sql = f"f.parse_status = 'ok' AND c.chunk_level != 'parent' {recipe_sql} AND {rbac_sql} AND {sub_sql}"
        scope_params = rbac_params + sub_params

        # The keyword top 250 is taken among the chunks this person may read in the chosen folder
        # and tags, not among all of them and filtered after: in a small scope the best matches
        # are often far below a global top 250 (AI-23)
        bm25_map: dict[int, float] = {}
        bm25_rank: dict[int, int] = {}
        if fts_query:
            try:
                fts_rows = conn.execute(
                    f"""
                    SELECT rag_chunks_fts.rowid AS chunk_id, -bm25(rag_chunks_fts, 5.0, 3.0, 1.0, 2.0) AS raw_bm25
                    FROM rag_chunks_fts
                    JOIN document_chunks c ON c.chunk_id = rag_chunks_fts.rowid
                    JOIN indexed_files f ON f.file_id = c.file_id
                    WHERE rag_chunks_fts MATCH ? AND {scope_sql}
                    ORDER BY raw_bm25 DESC
                    LIMIT 250
                    """,
                    [fts_query, *scope_params],
                ).fetchall()
                for rank_idx, r in enumerate(fts_rows, start=1):
                    cid = int(r["chunk_id"])
                    raw_val = max(0.0, float(r["raw_bm25"] or 0.0))
                    bm25_map[cid] = raw_val / (raw_val + 5.0)
                    bm25_rank[cid] = rank_idx
            except sqlite3.OperationalError:
                pass

        fts_chunk_ids = list(bm25_map.keys())
        vec_ids: set[int] | None = None
        # A small scope (a folder, a few shares, a tag) is scored whole: every chunk in it, exactly,
        # instead of nearest neighbours fetched from the whole index (AI-23)
        scoped = bool(scope_params) or bool(recipe_sql)
        in_scope = (
            conn.execute(
                f"SELECT c.chunk_id FROM document_chunks c JOIN indexed_files f ON f.file_id = c.file_id "
                f"WHERE {scope_sql} LIMIT {DIRECT_SCOPE_CHUNKS + 1}",
                scope_params,
            ).fetchall()
            if scoped
            else []
        )
        if scoped and len(in_scope) <= DIRECT_SCOPE_CHUNKS:
            vec_ids = {int(r[0]) for r in in_scope}
            fts_chunk_ids += [cid for cid in vec_ids if cid not in bm25_map]
        elif self._has_sqlite_vec and self._vec_table_active and query_vec and len(query_vec) == self._vec_table_dim:
            try:
                target_dim = self._vec_table_dim
                query_blob = struct.pack(f"<{target_dim}f", *query_vec)
                vec_table = f"vec_chunks_{target_dim}"
                # Filters apply while fetching: ask for more neighbours until enough of them are
                # files this person may read under the chosen folder, instead of filtering a
                # global top 60 afterwards (AI-4).
                want = max(limit * 4, 100)
                k = max(want, 200)
                filtered = bool(rbac_params or sub_params)
                while True:
                    vec_hits = conn.execute(
                        f"SELECT chunk_id FROM {vec_table} WHERE embedding MATCH ? AND k = ?",
                        (query_blob, k),
                    ).fetchall()
                    ids = [int(vh["chunk_id"]) for vh in vec_hits]
                    if filtered and ids:
                        ph = ",".join("?" * len(ids))
                        ok = {
                            int(r[0])
                            for r in conn.execute(
                                f"SELECT c.chunk_id FROM document_chunks c JOIN indexed_files f ON f.file_id = c.file_id "
                                f"WHERE c.chunk_id IN ({ph}) AND {rbac_sql} AND {sub_sql}",
                                ids + rbac_params + sub_params,
                            ).fetchall()
                        }
                        ids = [i for i in ids if i in ok]
                    if len(ids) >= want or len(vec_hits) < k or k >= 4000:
                        break
                    k *= 2
                vec_ids = set(ids)
                for cid_v in ids:
                    if cid_v not in fts_chunk_ids:
                        fts_chunk_ids.append(cid_v)
            except Exception as e:
                logger.debug("sqlite-vec candidate lookup skipped: %s", e)

        fts_rows: list[sqlite3.Row] = []
        if fts_chunk_ids:
            placeholders = ",".join("?" * len(fts_chunk_ids))
            fts_rows = conn.execute(
                f"""
                SELECT
                    c.chunk_id, c.file_id, c.chunk_index, c.parent_chunk_id, c.chunk_level, c.source_modality,
                    c.heading_context, c.structural_context, c.chunk_text, c.raw_chunk_text,
                    c.line_start, c.line_end, c.embedding_f32,
                    f.canonical_path, f.file_name, f.file_ext, f.modality, f.doc_type,
                    f.doc_title, f.doc_metadata_json, f.backing_dev, f.mtime_ns, f.size_bytes, f.embedding_model,
                    p.dominant_hex, (p.thumb_webp IS NOT NULL) AS has_thumb
                FROM document_chunks c
                JOIN indexed_files f ON f.file_id = c.file_id
                LEFT JOIN photo_assets p ON p.file_id = c.file_id
                WHERE c.chunk_id IN ({placeholders}) AND f.parse_status = 'ok' AND c.chunk_level != 'parent' {recipe_sql} AND {rbac_sql} AND {sub_sql}
                """,
                fts_chunk_ids + rbac_params + sub_params,
            ).fetchall()

        seen_chunk_ids = {int(r["chunk_id"]) for r in fts_rows}
        # Without a vector index the newest chunks stand in for a vector search; with one, the
        # nearest neighbours already are the candidates and age plays no part (AI-4).
        remaining_slots = 0 if vec_ids is not None else max(500, 3000 - len(seen_chunk_ids))

        # The newest chunks: sort only ids (served by idx_chunks_file_level, without reading the
        # chunk rows), then load just those rows, in the same order.
        recent_ids = (
            []
            if not remaining_slots
            else [
                int(r[0])
                for r in conn.execute(
                    f"""
                SELECT c.chunk_id
                FROM document_chunks c
                JOIN indexed_files f ON f.file_id = c.file_id
                WHERE f.parse_status = 'ok' AND c.chunk_level != 'parent' {recipe_sql} AND {rbac_sql} AND {sub_sql}
                ORDER BY f.mtime_ns DESC, c.chunk_id DESC
                LIMIT {remaining_slots}
                """,
                    rbac_params + sub_params,
                ).fetchall()
            ]
        )
        wanted = [cid for cid in recent_ids if cid not in seen_chunk_ids]
        by_id: dict[int, sqlite3.Row] = {}
        for i in range(0, len(wanted), 900):
            part = wanted[i : i + 900]
            for row in conn.execute(
                f"""
                SELECT
                    c.chunk_id, c.file_id, c.chunk_index, c.parent_chunk_id, c.chunk_level, c.source_modality,
                    c.heading_context, c.structural_context, c.chunk_text, c.raw_chunk_text,
                    c.line_start, c.line_end, c.embedding_f32,
                    f.canonical_path, f.file_name, f.file_ext, f.modality, f.doc_type,
                    f.doc_title, f.doc_metadata_json, f.backing_dev, f.mtime_ns, f.size_bytes, f.embedding_model,
                    p.dominant_hex, (p.thumb_webp IS NOT NULL) AS has_thumb
                FROM document_chunks c
                JOIN indexed_files f ON f.file_id = c.file_id
                LEFT JOIN photo_assets p ON p.file_id = c.file_id
                WHERE c.chunk_id IN ({",".join("?" * len(part))})
                """,
                part,
            ).fetchall():
                by_id[int(row["chunk_id"])] = row
        recent_rows = [by_id[cid] for cid in wanted if cid in by_id]

        rows = list(fts_rows)
        for r in recent_rows:
            if int(r["chunk_id"]) not in seen_chunk_ids:
                seen_chunk_ids.add(int(r["chunk_id"]))
                rows.append(r)

        # Score all candidate chunks
        scored_chunks: list[tuple[float, sqlite3.Row, float]] = []
        mismatched_chunks: set[int] = set()
        for r in rows:
            emb = unpack_embedding(r["embedding_f32"])
            file_emb_model = r["embedding_model"] if "embedding_model" in r.keys() else "zett_lexical_384d"
            # the exact model: EmbeddingGemma 1 and 2 vectors live in different spaces (AI-17)
            q_norm = (query_embedding_model or "").lower().removesuffix(":latest")
            f_norm = (file_emb_model or "").lower().removesuffix(":latest")
            is_match = q_norm == f_norm
            if query_embedding_model and not is_match:
                s_vec = 0.0
                mismatched_chunks.add(int(r["chunk_id"]))
            else:
                s_vec = cosine_similarity_vec(query_vec, emb)
            scored_chunks.append((s_vec, r, bm25_map.get(int(r["chunk_id"]), 0.0)))

        # Sort by vector score to assign vector ranks for RRF
        scored_chunks.sort(key=lambda tup: tup[0], reverse=True)
        vec_rank: dict[int, int] = {int(tup[1]["chunk_id"]): idx for idx, tup in enumerate(scored_chunks, start=1)}

        q_tokens = [t for t in text_tokens((raw_query or "").lower()) if t not in _STOPWORDS]
        prof = _core().similarity_profile(query_embedding_model, query_embedding_dim)
        per_file_best: dict[int, dict[str, Any]] = {}
        readable = self._post_rbac_checker(principal)  # one check per file, no disk access

        for s_vec, r, s_bm25 in scored_chunks:
            c_path = r["canonical_path"]
            if not readable(c_path):
                continue

            cid = int(r["chunk_id"])
            fid = int(r["file_id"])
            r_v = vec_rank.get(cid, 1000)
            r_b = bm25_rank.get(cid, 1000)

            clean_chunk_preview = _normalize_pdf_broken_words(r["chunk_text"] or "")
            clean_heading = _normalize_pdf_broken_words(r["heading_context"] or "") or r["file_name"]

            # Title / filename / ingredient match boost using whole-word boundaries on normalized text
            title_lower = f"{r['file_name']} {r['doc_title']} {clean_heading}".lower()
            chunk_lower = clean_chunk_preview.lower()
            lex_boost = 0.0
            matched_title = 0
            matched_chunk = 0
            if q_tokens:
                matched_title = sum(1 for t in q_tokens if _token_matches_word(t, title_lower))
                matched_chunk = sum(1 for t in q_tokens if _token_matches_word(t, chunk_lower))
                lex_boost += 0.14 * (matched_title / len(q_tokens)) + 0.12 * (matched_chunk / len(q_tokens))
            if "recipe" in req_scenes and r["doc_type"] == "recipe":
                lex_boost += 0.15

            if q_tokens:
                has_lexical_hit = (matched_title > 0) or (matched_chunk > 0)
                if not has_lexical_hit:
                    # Reject FTS5 false-positives caused by mid-word PDF line breaks (e.g. 'car\nrot' or 'Health Car\ne')
                    s_bm25 = 0.0
            else:
                has_lexical_hit = cid in bm25_rank and s_bm25 > 0.01

            s_rrf = (61.0 / 2.0) * (
                (1.0 / (60.0 + r_v)) + (1.0 / (60.0 + r_b) if (cid in bm25_rank and has_lexical_hit) else 0.0)
            )
            effective_rrf = s_rrf if (has_lexical_hit or s_vec >= prof["vec_min"]) else 0.0
            # Dynamic Token-Density-Aware Hybrid RRF Scoring (Batch 2 Item 2.3)
            if intent_type == "code":
                w_vec, w_bm25, w_rrf = 0.25, 0.55, 0.20
            elif intent_type == "qa":
                w_vec, w_bm25, w_rrf = 0.60, 0.20, 0.20
            elif len(q_tokens) <= 2:
                w_vec, w_bm25, w_rrf = 0.35, 0.45, 0.20
            else:
                w_vec, w_bm25, w_rrf = 0.50, 0.30, 0.20

            if prof["ranker"] == "vector":
                score = min(1.0, prof["w_vec"] * s_vec + prof["w_bm25"] * s_bm25)
            else:
                score = min(1.0, w_vec * s_vec + w_bm25 * s_bm25 + w_rrf * effective_rrf + lex_boost)
            if cid in mismatched_chunks and has_lexical_hit:
                # Embedded with another model (a fallback while the embedder was away): its vector
                # can't be compared, so its keyword match decides, ranked below good vector hits (AI-5)
                score = max(score, min(0.6, 0.18 + 0.45 * s_bm25 + lex_boost))
            if raw_query.strip():
                if (
                    not has_lexical_hit
                    and s_vec < prof["vec_min"]
                    and not ("recipe" in req_scenes and r["doc_type"] == "recipe")
                ):
                    continue
                # Lexical vectors: reject weak single-word body coincidences on 3+ word queries
                # (e.g. "states" in a book when asking "president of the united states")
                if (
                    prof["strict_terms"]
                    and len(q_tokens) >= 3
                    and matched_title == 0
                    and matched_chunk <= 1
                    and not req_scenes
                ):
                    continue
                # When the query is a visual subject (e.g. "car", "beach", "pool") and user has not
                # explicitly filtered to Documents, only include documents whose title/filename matches
                # (lexical vectors only: a neural model already tells a document about a car from
                # a photo of one)
                if (
                    prof["strict_terms"]
                    and modality_hint == "photos"
                    and not only_docs
                    and not only_recipes
                    and matched_title == 0
                ):
                    continue
                if score < 0.16:
                    continue

            if fid in per_file_best and per_file_best[fid]["score"] >= score:
                continue

            backing_dev = r["backing_dev"] or rag_standby.resolve_path_backing_dev(c_path)
            disk_state = "standby" if rag_standby.is_backing_disk_in_standby(backing_dev) else "active"
            doc_meta = json.loads(r["doc_metadata_json"] or "{}")

            structured_card = None
            if r["doc_type"] in ("recipe", "invoice") and doc_meta.get("card_type"):
                structured_card = dict(doc_meta)
                structured_card["type"] = structured_card.get("card_type")
                structured_card["source_file_id"] = fid
                structured_card["source_path"] = c_path
                if r["has_thumb"]:
                    structured_card["thumbnail_url"] = f"/api/media/thumbnail/{fid}"

            per_file_best[fid] = {
                "id": fid,
                "file_id": fid,
                "chunk_id": cid,
                "parent_chunk_id": r["parent_chunk_id"],
                "path": c_path,
                "file_path": c_path,
                "canonical_path": c_path,
                "name": r["file_name"],
                "file_name": r["file_name"],
                "title": r["doc_title"] or r["file_name"],
                "media_type": "photo" if r["source_modality"] == "photo_ocr" else "document",
                "category_type": "documents",
                "modality": r["modality"],
                "source_modality": r["source_modality"],
                "doc_type": r["doc_type"],
                "score": round(score, 4),
                "compositional_match": False,
                "thumbnail_url": f"/api/media/thumbnail/{fid}" if r["has_thumb"] else None,
                "dominant_hex": r["dominant_hex"] or "#0ea5e9",
                "color_swatches": [],
                "object_colors": [],
                "dominant_colors": [],
                "scene_tags": [r["doc_type"]],
                "breadcrumb": clean_heading,
                "section_title": clean_heading,
                "structural_context": r["structural_context"] or "",
                "raw_chunk_text": r["raw_chunk_text"] or r["chunk_text"],
                "excerpt": clean_chunk_preview[:420],
                "line_start": int(r["line_start"]),
                "line_end": int(r["line_end"]),
                "recipe_meta": doc_meta if r["doc_type"] == "recipe" else None,
                "structured_card": structured_card,
                "disk_id": backing_dev or "nvme0n1",
                "disk_state": disk_state,
                "size_bytes": int(r["size_bytes"]),
                "mtime": int(int(r["mtime_ns"]) // 1_000_000_000),
            }

        results = sorted(per_file_best.values(), key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def ask(
        self,
        query: str,
        scope: str = "all",
        path_prefix: str | None = None,
        top_k: int = 5,
        principal: Any = None,
    ) -> dict[str, Any]:
        """
        RAG v3 Grounded Conversational RAG & Structured Synthesis:
          - Resolves clean parent chunks for high-fidelity generation without fragmenting paragraphs
          - Primacy-Recency Alternating Inversion (mitigating Lost-in-the-Middle)
          - Corrective RAG (CRAG) retrieval evaluation (high, ambiguous, low)
          - Fast Python Lexical Entailment (<2ms) Grounding Confidence Score (0-100%)
          - 100% Spindown-Safe Zero Array Disk I/O against /app/data/rag_index.db
        """
        t0 = time.perf_counter()
        self._ensure_schema()
        top_k = max(1, min(12, int(top_k or 5)))
        mode = "recipes" if scope == "recipes" else ("documents" if scope in ("docs", "documents") else "all")

        search_res = self.search(
            query=query,
            mode=mode,
            path_prefix=path_prefix,
            limit=max(top_k * 2, 10),
            principal=principal,
        )

        doc_hits = search_res.get("document_results", [])
        photo_hits = search_res.get("photo_results", [])

        # Pre-load parent chunks for clean unfragmented generation context
        p_ids = {int(hit["parent_chunk_id"]) for hit in doc_hits[:top_k] if hit.get("parent_chunk_id") is not None}
        p_map: dict[int, sqlite3.Row] = {}
        if p_ids:
            conn_p = self._get_conn(readonly=True)
            try:
                p_placeholders = ",".join("?" for _ in p_ids)
                p_rows = conn_p.execute(
                    f"SELECT chunk_id, heading_context, chunk_text, raw_chunk_text, line_start, line_end FROM document_chunks WHERE chunk_id IN ({p_placeholders})",
                    list(p_ids),
                ).fetchall()
                p_map = {int(r["chunk_id"]): r for r in p_rows}
            finally:
                conn_p.close()

        raw_citations: list[dict[str, Any]] = []
        for idx, hit in enumerate(doc_hits[:top_k], start=1):
            breadcrumb = hit.get("breadcrumb") or hit.get("title") or hit["name"]
            p_id = hit.get("parent_chunk_id")
            p_row = p_map.get(int(p_id)) if p_id is not None else None
            if p_row:
                raw_excerpt = p_row["raw_chunk_text"] or p_row["chunk_text"] or ""
                line_start = p_row["line_start"]
                line_end = p_row["line_end"]
            else:
                raw_excerpt = hit.get("raw_chunk_text") or hit.get("excerpt") or hit.get("ocr_snippet") or ""
                line_start = hit.get("line_start", 1)
                line_end = hit.get("line_end", 1)

            collapsed_excerpt = re.sub(r"\s+", " ", raw_excerpt).strip()
            raw_citations.append(
                {
                    "index": idx,
                    "citation_index": idx,
                    "file_id": hit["file_id"],
                    "path": hit["path"],
                    "file_path": hit["path"],
                    "name": hit["name"],
                    "file_name": hit["name"],
                    "doc_title": hit.get("doc_title") or hit.get("title") or hit.get("name") or "",
                    "doc_type": hit.get("doc_type", "generic"),
                    "source_modality": hit.get("source_modality", hit.get("modality", "document")),
                    "breadcrumb": breadcrumb,
                    "section_title": breadcrumb,
                    "excerpt": collapsed_excerpt[:320],
                    "full_parent_context": collapsed_excerpt,
                    "line_start": line_start,
                    "line_end": line_end,
                    "score": hit["score"],
                    "thumbnail_url": hit.get("thumbnail_url"),
                    "disk_state": hit.get("disk_state", "active"),
                }
            )

        # Apply Primacy-Recency Alternating Inversion to preserve top context at prompt attention peaks
        # Best first: the prompt says the answer is usually in document 1, and trimming cuts from
        # the end. Reordering only pays off for long lists (AI-8).
        citations = raw_citations if len(raw_citations) <= 8 else apply_primacy_recency_inversion(raw_citations)
        for i, c in enumerate(citations, start=1):
            c["citation_index"] = i
            c["index"] = i

        structured_card = search_res.get("structured_card")
        if structured_card and not structured_card.get("type"):
            structured_card["type"] = structured_card.get("card_type", "summary")
        if not structured_card and citations:
            top_c = citations[0]
            structured_card = {
                "type": "summary",
                "card_type": "summary",
                "title": top_c["name"],
                "source_file_id": top_c["file_id"],
                "source_path": top_c["path"],
                "sources_count": len(citations),
                "key_points": [c["excerpt"][:180] for c in citations[:3] if c.get("excerpt")],
            }

        # Corrective RAG (CRAG) retrieval confidence evaluation
        crag_eval = grade_rag_retrieval(query, citations)

        # Synthesize Grounded Answer Markdown with [1], [2] inline citations
        if not citations and not photo_hits:
            answer_md = (
                "No matching indexed documents or photos were found for your query. "
                "Try indexing your active shares or broadening your search terms."
            )
        elif crag_eval["grade"] == "low" and not photo_hits:
            answer_md = (
                f'I searched your indexed knowledge base for **"{query}"**, but found insufficient evidence '
                f"(confidence: {int(crag_eval['confidence'] * 100)}%). To prevent inaccurate answers, please "
                f"specify a folder or verify that the relevant documents are indexed."
            )
        elif structured_card and structured_card.get("card_type") == "recipe":
            r_title = structured_card.get("title", "Recipe")
            ings = structured_card.get("ingredients", [])
            steps = structured_card.get("steps") or structured_card.get("steps_summary") or []
            prep = structured_card.get("prep_time", "15 mins")
            cook = structured_card.get("cook_time", "25 mins")
            serv = structured_card.get("servings", "4")
            cite_name = citations[0]["name"] if citations else "recipe"
            ing_preview = ", ".join(ings[:5]) if ings else "see full ingredients list below"
            step_preview = steps[0] if steps else (citations[0]["excerpt"] if citations else "")
            answer_md = (
                f"Found **{r_title}** in **[1] {cite_name}** "
                f"(Prep: `{prep}`, Cook: `{cook}`, Serves: `{serv}`).\n\n"
                f"**Key Ingredients:** {ing_preview}.\n\n"
                f"**Preparation Highlight:** {step_preview}"
            )
        elif citations:
            parts: list[str] = []
            for c in citations[:3]:
                clean_excerpt = re.sub(r"^\[.*?\]\s*", "", c["excerpt"] or "")
                clean_excerpt = re.sub(r"\s+", " ", clean_excerpt).strip()
                parts.append(f"• [{c['citation_index']}] **{c['name']}**: {clean_excerpt[:220]}")
            folder_banner = f"📁 *Context Scope: {path_prefix}*\n\n" if path_prefix else ""
            answer_md = (
                folder_banner
                + f'Found **{len(citations)}** grounded document match(es) for **"{query}"**:\n'
                + "\n".join(parts)
            )
        else:
            top_p = photo_hits[0]
            answer_md = (
                f"Found **{len(photo_hits)}** matching visual asset(s), led by **[1] {top_p['name']}** "
                f"(Colors: `{', '.join(top_p.get('object_colors') or top_p.get('dominant_colors') or [])}`, "
                f"Scene: `{', '.join(top_p.get('scene_tags') or [])}`)."
            )

        # Fast Python Lexical Entailment Verification (<2ms)
        evidence_snippets = [c.get("full_parent_context", c["excerpt"]) for c in citations]
        grounding = compute_grounding_confidence_score(answer_md, evidence_snippets)

        # Folder manifest rollup if scoped to a folder
        manifest = self.get_folder_manifest(path_prefix, principal=principal) if path_prefix else None

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "status": "ok",
            "query": query,
            "answer": answer_md,
            "answer_markdown": answer_md,
            "elapsed_ms": elapsed_ms,
            "synthesis_engine": "zettnas_rag_v3_hierarchical",
            "crag_grade": crag_eval["grade"],
            "crag_confidence": crag_eval["confidence"],
            "grounding_confidence_score": grounding["grounding_confidence_score"],
            "grounded_sentences": grounding["grounded_sentences"],
            "total_sentences": grounding["total_sentences"],
            "unsupported_claims": grounding["unsupported_claims"],
            "folder_path": path_prefix,
            "manifest": manifest,
            "parsed_intent": search_res["parsed_intent"],
            "structured_card": structured_card,
            "structured_cards": [structured_card] if structured_card else [],
            "citations": citations,
            "visual_matches": photo_hits[:6],
            "photos": photo_hits[:6],
            "standby_guard": search_res["standby_guard"],
        }

    def get_thumbnail(self, file_id: int, principal: Any = None) -> tuple[bytes, str]:
        """
        Fetches the cached WebP micro-thumbnail BLOB from `photo_assets` in `/app/data/rag_index.db`
        with 100% zero array disk I/O. Returns an SVG placeholder if no BLOB is present.
        """
        self._ensure_schema()
        conn = self._get_conn(readonly=True)
        try:
            row = conn.execute(
                """
                SELECT p.thumb_webp, p.dominant_hex, p.file_name, f.canonical_path
                FROM photo_assets p
                JOIN indexed_files f ON f.file_id = p.file_id
                WHERE p.file_id = ?
                """,
                (int(file_id),),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            raise KeyError(f"Asset {file_id} not found")

        if not self._check_post_rbac(row["canonical_path"], principal):
            raise PermissionError("Access denied to this file path")

        blob = row["thumb_webp"]
        if blob:
            media_type = "image/webp" if blob[:4] == b"RIFF" else "image/jpeg"
            return (bytes(blob), media_type)

        dom_hex = row["dominant_hex"] or "#1e293b"
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
            f'<rect width="224" height="224" fill="{dom_hex}"/>'
            f'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '
            f'fill="#ffffff" font-family="sans-serif" font-size="13">Standby Cache</text></svg>'
        )
        return (svg.encode("utf-8"), "image/svg+xml")

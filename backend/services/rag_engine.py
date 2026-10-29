"""
ZettNAS Toolkit - Multi-Modal Local RAG & Visual Search Engine (ZettAI)
Provides hardware-accelerated (NPU -> GPU -> CPU) document/recipe RAG,
12-color perceptual + spatial scene photo search, spindown-safe incremental indexing,
and multi-user RBAC path isolation backed by SQLite WAL (/app/data/rag_index.db).
"""

import ast
import asyncio
import colorsys
import hashlib
import html.parser
import io
import json
import math
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any, Optional, Union

from PIL import Image, ImageFile

from backend import db_crypto
from backend.config import ALLOWED_BROWSE_ROOTS, DATA_DIR, HOST_DEV, HOST_PROC, HOST_SYS, logger
from backend.db_crypto import sqlite3  # SQLCipher module: the index can be encrypted at rest (AI-20)
from backend.fsutil import atomic_write_json, read_json, resolve_within
from backend.ignored_errors import ignored
from backend.logging_config import sanitize_string
from backend.state import Z_STATE, add_event

# Guard against decompression bombs and truncated camera uploads
Image.MAX_IMAGE_PIXELS = 64_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Split into modules (AI-21); names stay importable from here.
from backend.services import rag_standby  # noqa: E402
from backend.services.rag_documents import (  # noqa: E402, F401
    _chunk_python_ast,
    _HTMLTextExtractor,
    extract_document_text,
    generate_contextual_hierarchical_chunks,
    late_interaction_rerank,
    parse_document_structure_and_chunks,
)
from backend.services.rag_embeddings import (  # noqa: E402, F401
    _EMBED_BREAKER,
    _EMBED_MODEL_SEEN,
    CLASS_INDICATORS_RE,
    CLI_COMMAND_INDICATORS,
    CODE_EXTENSIONS_RE,
    CODE_SYNTAX_INDICATORS,
    EMBED_BATCH_SIZE,
    QA_INDICATORS_RE,
    TASK_PREFIX_CLASSIFICATION,
    TASK_PREFIX_CODE,
    TASK_PREFIX_QA,
    TASK_PREFIX_SEARCH,
    _detected_host_ip,
    _embedding_model_candidates,
    _pack_embedding,
    _resolve_ollama_host,
    classify_query_task_intent,
    compute_384d_embedding,
    compute_multimodal_query_embedding,
    compute_neural_embedding_via_ollama,
    compute_neural_embeddings_batch,
    cosine_similarity_vec,
    embedding_host,
    format_embeddinggemma_document,
    load_sqlite_vec_extension,
    truncate_and_normalize_mrl,
    unpack_embedding,
)
from backend.services.rag_grounding import (  # noqa: E402, F401
    CRAGGrade,
    GroundingScoreResult,
    apply_primacy_recency_inversion,
    compute_grounding_confidence_score,
    grade_rag_retrieval,
)
from backend.services.rag_standby import (  # noqa: E402, F401
    _SMARTCTL_STANDBY_CACHE,
    _UNRAID_INI_CACHE,
    UNKNOWN_BACKING_DEV,
    _disk_reports_standby,
    _get_unraid_disks_and_shares,
    _parse_ini_sections,
    get_running_disks_list,
    get_sleeping_disks_list,
    is_backing_disk_in_standby,
    resolve_path_backing_dev,
)
from backend.services.rag_text import (  # noqa: E402, F401
    _CJK_CHARS,
    _CJK_RUN_RE,
    _FTS5_RESERVED,
    _STOPWORDS,
    _TOKEN_RE,
    AUDIO_EXTENSIONS,
    CANONICAL_COLORS,
    CODE_EXTENSIONS,
    COLOR_HEX_MAP,
    COLOR_SYNONYMS,
    COLOR_TARGET_BINS,
    DOCUMENT_EXTENSIONS,
    EMBEDDING_DIM,
    EXCLUDED_DIRS,
    EXCLUDED_EXTENSIONS,
    EXCLUDED_FILENAMES,
    IMAGE_EXTENSIONS,
    MAX_INDEX_FILE_BYTES,
    SCENE_ONTOLOGY,
    VIDEO_EXTENSIONS,
    _has_cjk,
    _normalize_pdf_broken_words,
    _token_matches_word,
    bhattacharyya_similarity,
    build_safe_fts5_query,
    build_target_color_histogram,
    classify_rgb_pixel,
    looks_like_binary,
    parse_multimodal_query,
    text_for_embedding,
    text_tokens,
)

RAG_DB_PATH = os.path.join(DATA_DIR, "rag_index.db")
RAG_CONFIG_PATH = os.path.join(DATA_DIR, "rag_config.json")
CURRENT_INDEX_VERSION = 4  # 4: sentence-aware, token-sized chunks (AI-30)


def analyze_photo_asset(file_path: str | bytes, file_name: str) -> dict[str, Any]:
    """
    Single-pass Pillow + EXIF visual analyzer:
      1. Decodes image safely and generates a 224px max-edge WebP micro-thumbnail (thumb_webp BLOB)
      2. Computes 64-bit perceptual hash (phash_hex)
      3. Extracts Dual-Zone 12-Color Perceptual Breakdown:
         - Center Subject ROI (50% x 50% focal box) -> object_colors
         - Full Frame -> frame_colors & dominant_hex
      4. Computes 64-bin L1-normalized HSV histograms (full-frame & center ROI)
      5. Detects Scene & Object tags (pool, beach, car, food/recipe, document, sunset, snow, outdoor)
         using both spatial pixel layout AND path/EXIF context
      6. Runs two-stage fast OCR / embedded text extraction for text-bearing photos
    """
    from backend.services import photo_place

    photo_place.ensure_heif()  # iPhone photos (AI-24)
    img_target = io.BytesIO(file_path) if isinstance(file_path, bytes) else file_path
    with Image.open(img_target) as img:
        orig_w, orig_h = img.size
        img_format = str(img.format or "JPEG").upper()
        info_dict = dict(img.info or {})

        # Convert to RGB once
        rgb_img = img.convert("RGB")

        # 1. Generate 224px WebP thumbnail for zero-disk-touch UI grids
        thumb_img = rgb_img.copy()
        thumb_img.thumbnail((224, 224), Image.Resampling.BILINEAR)
        thumb_buf = io.BytesIO()
        try:
            thumb_img.save(thumb_buf, format="WEBP", quality=70, method=0)
            thumb_webp = thumb_buf.getvalue()
        except Exception:
            thumb_img.save(thumb_buf, format="JPEG", quality=72)
            thumb_webp = thumb_buf.getvalue()

        # 2. Compute 8x8 luminance perceptual hash (64-bit hex)
        small_gray = rgb_img.resize((8, 8), Image.Resampling.BILINEAR).convert("L")
        gray_pixels = list(getattr(small_gray, "get_flattened_data", small_gray.getdata)())  # pyright: ignore[reportArgumentType]
        avg_lum = sum(gray_pixels) / 64.0
        bits = 0
        for px in gray_pixels:
            bits = (bits << 1) | (1 if px >= avg_lum else 0)
        phash_hex = f"{bits:016x}"

        # 3. Resize to 64x64 working grid for fast spatial color & scene analysis
        grid_size = 64
        work_img = rgb_img.resize((grid_size, grid_size), Image.Resampling.BILINEAR)
        pixels = list(getattr(work_img, "get_flattened_data", work_img.getdata)())  # pyright: ignore[reportArgumentType]

    frame_counts: dict[str, int] = {c: 0 for c in CANONICAL_COLORS}
    center_counts: dict[str, int] = {c: 0 for c in CANONICAL_COLORS}
    border_counts: dict[str, int] = {c: 0 for c in CANONICAL_COLORS}
    top_counts: dict[str, int] = {c: 0 for c in CANONICAL_COLORS}
    bottom_counts: dict[str, int] = {c: 0 for c in CANONICAL_COLORS}

    frame_hist = [0.0] * 64
    center_hist = [0.0] * 64

    r_sum, g_sum, b_sum = 0, 0, 0
    center_total = 0
    border_total = 0
    top_total = 0
    bottom_total = 0
    lower_center_dark = 0
    lower_center_total = 0
    high_contrast_transitions = 0
    prev_lum = -1.0

    # Analyze 64x64 grid
    c_min = int(grid_size * 0.25)
    c_max = int(grid_size * 0.75)

    for idx, (r, g, b) in enumerate(pixels):
        y = idx // grid_size
        x = idx % grid_size

        cname = classify_rgb_pixel(r, g, b)
        frame_counts[cname] += 1
        r_sum += r
        g_sum += g
        b_sum += b

        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        bh = min(7, int(h * 8.0))
        bs = min(3, int(s * 4.0))
        bv = min(1, int(v * 2.0))
        h_idx = bh * 8 + bs * 2 + bv
        frame_hist[h_idx] += 1.0

        # Track horizontal luminance transitions for document/OCR striation detection
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if x > 0 and abs(lum - prev_lum) > 95.0:
            high_contrast_transitions += 1
        prev_lum = lum

        # Spatial zones
        if y < grid_size // 2:
            top_counts[cname] += 1
            top_total += 1
        else:
            bottom_counts[cname] += 1
            bottom_total += 1

        in_center = (c_min <= x < c_max) and (c_min <= y < c_max)
        if in_center:
            center_counts[cname] += 1
            center_total += 1
            center_hist[h_idx] += 1.0
            if y >= grid_size // 2:
                lower_center_total += 1
                if v < 0.28:
                    lower_center_dark += 1
        else:
            border_counts[cname] += 1
            border_total += 1

    total_px = float(len(pixels)) or 1.0
    center_total_f = float(center_total) or 1.0
    border_total_f = float(border_total) or 1.0
    top_total_f = float(top_total) or 1.0
    bottom_total_f = float(bottom_total) or 1.0

    frame_colors = {
        c: round(cnt / total_px, 4)
        for c, cnt in sorted(frame_counts.items(), key=lambda kv: kv[1], reverse=True)
        if cnt / total_px >= 0.04
    }
    object_colors = {
        c: round(cnt / center_total_f, 4)
        for c, cnt in sorted(center_counts.items(), key=lambda kv: kv[1], reverse=True)
        if cnt / center_total_f >= 0.04
    }

    # Normalize 64-bin histograms
    frame_hist_norm = [x / total_px for x in frame_hist]
    center_hist_norm = [x / center_total_f for x in center_hist]
    color_hist_blob = struct.pack("<64f", *frame_hist_norm)
    center_color_hist_blob = struct.pack("<64f", *center_hist_norm)

    # Primary dominant color hex
    top_color_name = next(iter(object_colors.keys()), next(iter(frame_colors.keys()), "silver"))
    dominant_hex = COLOR_HEX_MAP.get(top_color_name, "#64748b")
    palette_hex = [
        COLOR_HEX_MAP[c] for c in list(dict.fromkeys(list(object_colors.keys()) + list(frame_colors.keys())))[:5]
    ]

    # 4. Spatial Scene & Object Classification (Works even on generic IMG_0042.JPG!)
    scene_tags: list[str] = []

    def _add_tag(t: str) -> None:
        if t not in scene_tags:
            scene_tags.append(t)

    cyan_pct = frame_counts["cyan"] / total_px
    blue_pct = frame_counts["blue"] / total_px
    green_pct = frame_counts["green"] / total_px
    white_pct = frame_counts["white"] / total_px
    yellow_pct = frame_counts["yellow"] / total_px
    orange_pct = frame_counts["orange"] / total_px
    red_pct = frame_counts["red"] / total_px
    brown_pct = frame_counts["brown"] / total_px

    top_water_sky = (top_counts["blue"] + top_counts["cyan"]) / top_total_f
    bot_water = (bottom_counts["cyan"] + bottom_counts["blue"]) / bottom_total_f
    bot_sand = (
        bottom_counts["yellow"] + bottom_counts["orange"] + bottom_counts["brown"] + bottom_counts["white"]
    ) / bottom_total_f

    # Pool detection: strong cyan/aqua or water-dominated lower/full frame
    if cyan_pct >= 0.14 or (cyan_pct >= 0.06 and (cyan_pct + blue_pct) >= 0.38) or bot_water >= 0.35:
        _add_tag("pool")
        _add_tag("outdoor")

    # Beach detection: sky/ocean in upper/mid + warm sand tones in lower/mid
    if (top_water_sky >= 0.18 and bot_sand >= 0.18 and (yellow_pct + orange_pct + brown_pct) >= 0.08) or (
        (cyan_pct + blue_pct) >= 0.20 and (yellow_pct + orange_pct + brown_pct) >= 0.15
    ):
        _add_tag("beach")
        _add_tag("outdoor")

    # Car / Vehicle detection: distinct center subject mass contrasting with perimeter border
    # or chromatic/metallic center subject with lower shadow/wheel dark band
    top_center_color, top_center_frac = next(iter(object_colors.items()), ("silver", 0.0))
    border_same_frac = border_counts.get(top_center_color, 0) / border_total_f
    center_border_contrast = top_center_frac - border_same_frac
    has_wheel_shadow = (lower_center_dark / float(max(1, lower_center_total))) >= 0.08

    if (top_center_frac >= 0.22 and center_border_contrast >= 0.14) or (top_center_frac >= 0.18 and has_wheel_shadow):
        _add_tag("car")

    # Sunset / Sunrise detection
    if (orange_pct + red_pct + yellow_pct) >= 0.35 and (top_counts["orange"] + top_counts["red"]) / top_total_f >= 0.20:
        _add_tag("sunset")
        _add_tag("outdoor")

    # Nature / Forest / Outdoor
    if green_pct >= 0.28:
        _add_tag("outdoor")

    # Snow / Winter
    if white_pct >= 0.55 and (white_pct + frame_counts["silver"] / total_px) >= 0.72:
        _add_tag("snow")
        _add_tag("outdoor")

    # Document / Screenshot / Receipt photo detection
    striation_ratio = high_contrast_transitions / total_px
    if (
        white_pct >= 0.45
        and (frame_counts["black"] + frame_counts["silver"]) / total_px >= 0.08
        and striation_ratio >= 0.06
    ):
        _add_tag("document")

    # 5. Enrich with filename / parent folder semantic cues
    parent_dir = os.path.basename(os.path.dirname(file_path)) if isinstance(file_path, str) else ""
    path_context = f"{parent_dir} {file_name}".lower()
    path_words = re.findall(r"[a-z0-9]+", path_context)
    from backend.services import rag_lang

    for slug in rag_lang.scenes_in(text_tokens(path_context), path_context):  # "Strand", "海边" (AI-13)
        _add_tag(slug)
    for cname in rag_lang.colors_in(text_tokens(path_context), path_context):
        object_colors[cname] = max(object_colors.get(cname, 0.0), 0.55)
        frame_colors[cname] = max(frame_colors.get(cname, 0.0), 0.35)
    for w in path_words:
        if w in COLOR_SYNONYMS:
            cname = COLOR_SYNONYMS[w]
            object_colors[cname] = max(object_colors.get(cname, 0.0), 0.55)
            frame_colors[cname] = max(frame_colors.get(cname, 0.0), 0.35)
        for scene_slug, (_, syn_set) in SCENE_ONTOLOGY.items():
            if w in syn_set or (w.endswith("s") and w[:-1] in syn_set):
                _add_tag(scene_slug)

    # 6. EXIF & Embedded OCR / Caption Extraction
    camera_make = ""
    camera_model = ""
    taken_at: float | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    ocr_text_parts: list[str] = []

    # Check PNG/WebP info text chunks (e.g. Title, Description, Comment, OCR, Recipe)
    for k, v in info_dict.items():
        if (
            isinstance(k, str)
            and isinstance(v, str)
            and len(v.strip()) >= 3
            and k.lower()
            in (
                "description",
                "comment",
                "title",
                "ocr",
                "text",
                "parameters",
                "usercomment",
                "xml:com.adobe.xmp",
            )
        ):
            ocr_text_parts.append(v.strip()[:2000])

    # Check adjacent .txt / .ocr sidecar if present in same directory
    if isinstance(file_path, str):
        for sidecar_ext in (".ocr.txt", ".caption.txt"):
            sidecar_path = file_path + sidecar_ext
            if os.path.isfile(sidecar_path):
                try:
                    with open(sidecar_path, encoding="utf-8", errors="replace") as sf:
                        ocr_text_parts.append(sf.read(4096).strip())
                except Exception:
                    ignored("backend.services.rag_engine.analyze_photo_asset")

    check_ext = file_path if isinstance(file_path, str) else file_name
    if check_ext.lower().endswith(photo_place.EXIF_EXTENSIONS):
        try:
            import exifread  # type: ignore

            if isinstance(file_path, str):
                with open(file_path, "rb") as ef:
                    tags = exifread.process_file(ef, details=False)
            else:
                tags = exifread.process_file(io.BytesIO(file_path), details=False)

            if "Image Make" in tags:
                camera_make = str(tags["Image Make"]).strip()
            if "Image Model" in tags:
                camera_model = str(tags["Image Model"]).strip()
            if "Image ImageDescription" in tags:
                desc = str(tags["Image ImageDescription"]).strip()
                if desc:
                    ocr_text_parts.append(desc)
            if "EXIF UserComment" in tags:
                ucomm = str(tags["EXIF UserComment"]).strip()
                if ucomm and not ucomm.startswith("ASCII\x00"):
                    ocr_text_parts.append(ucomm)
        except Exception:
            ignored("backend.services.rag_engine.analyze_photo_asset")

    # when and where (AI-24): the capture date and GPS position, and the town for it, offline
    taken_at, gps_lat, gps_lon = photo_place.when_where(file_path, file_name)
    location_label = photo_place.place_for(gps_lat, gps_lon)

    ocr_text = sanitize_string("\n".join(p for p in ocr_text_parts if p)).strip()
    if ocr_text:
        for slug in rag_lang.scenes_in(text_tokens(ocr_text.lower()), ocr_text.lower()):
            _add_tag(slug)
        for w in re.findall(r"[a-z0-9]+", ocr_text.lower()):
            for scene_slug, (_, syn_set) in SCENE_ONTOLOGY.items():
                if w in syn_set:
                    _add_tag(scene_slug)

    object_colors_list = list(object_colors.keys())
    frame_colors_list = list(frame_colors.keys())
    object_colors_text = " ".join(object_colors_list)
    auto_tags_text = " ".join(scene_tags + object_colors_list + frame_colors_list + path_words)
    caption_text = (
        f"Photo ({orig_w}x{orig_h}) featuring {', '.join(scene_tags or ['scene'])} "
        f"with {', '.join(object_colors_list[:3] or frame_colors_list[:3] or ['neutral'])} colors"
    )
    when_where_text = photo_place.caption_suffix(taken_at, location_label)
    if when_where_text:
        caption_text = f"{caption_text}, {when_where_text}"
    if ocr_text:
        caption_text = f"{caption_text}. Text: {ocr_text[:300]}"

    emb_blob, _ = compute_384d_embedding(
        text=f"{file_name} {auto_tags_text} {caption_text} {ocr_text}",
        scene_tags=scene_tags,
        object_colors=object_colors,
        frame_colors=frame_colors,
        color_hist_64=center_hist_norm,
    )

    return {
        "width": orig_w,
        "height": orig_h,
        "aspect_ratio": round(orig_w / float(max(1, orig_h)), 3),
        "format": img_format,
        "taken_at": taken_at,
        "camera_make": camera_make,
        "camera_model": camera_model,
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "location_label": location_label,
        "phash_hex": phash_hex,
        "dominant_hex": dominant_hex,
        "palette_json": json.dumps(palette_hex),
        "object_colors": object_colors,
        "frame_colors": frame_colors,
        "object_colors_json": json.dumps(object_colors),
        "frame_colors_json": json.dumps(frame_colors),
        "object_colors_text": object_colors_text,
        "color_hist_f32": color_hist_blob,
        "center_color_hist_f32": center_color_hist_blob,
        "scene_tags": scene_tags,
        "scene_tags_json": json.dumps(scene_tags),
        "auto_tags_text": auto_tags_text,
        "caption_text": caption_text,
        "ocr_text": ocr_text,
        "vision_embedding_f32": emb_blob,
        "thumb_webp": thumb_webp,
    }


# Similarity profiles per embedding model (AI-2). Neural models give high, tightly packed cosines
# (EmbeddingGemma: right file ~0.72, best wrong file ~0.63 on the eval set) and match across
# languages; the built-in lexical vectors give low, wide ones and only match shared words. One
# fixed cut-off tuned on English lexical vectors threw away most cross-language matches.
#
# Measured with tests/rag_eval (290 queries; EmbeddingGemma): the old blend scored recall@5 0.28
# cross-language, 0.65 paraphrase, 0.88 same-language. Ranking by vector similarity with a small
# keyword tie-break, and without the lexical-only gates, scores 0.98, 0.975 and 1.0. Plain RRF
# of the two rankings and the title/word boosts both scored lower, so neither is used for
# neural models (AI-5).
SIMILARITY_PROFILES: dict[str, dict[str, Any]] = {
    # strict_terms: drop 3+ word queries that match at most one word of the text, and documents
    # without a title match when the query reads like a photo search
    "lexical": {"vec_min": 0.45, "strict_terms": True, "ranker": "blend"},
    "neural": {"vec_min": 0.50, "strict_terms": False, "ranker": "vector", "w_vec": 1.0, "w_bm25": 0.05},
}


def similarity_profile(model: str | None, dim: int | None = None) -> dict[str, Any]:
    """The profile for this embedding model; a neural model's vec_min is the one measured for that
    exact model on this install, once it has been (AI-17, rag_calibration)."""
    m = (model or "").lower()
    if not m or "lexical" in m:
        return SIMILARITY_PROFILES["lexical"]
    from backend.services import rag_calibration

    got = rag_calibration.measured(model or "", dim)
    if got and isinstance(got.get("vec_min"), (int, float)):
        return {**SIMILARITY_PROFILES["neural"], "vec_min": float(got["vec_min"]), "vec_min_measured": True}
    return SIMILARITY_PROFILES["neural"]


def classify_path_rbac(canonical_path: str) -> tuple[str, str, str, str]:
    """
    Classifies a file's canonical path into RBAC visibility tiers:
      Returns (visibility_tier, owner_username, share_name, allowed_users_csv)
      visibility_tier in {'admin_boot', 'user_home', 'restricted_share', 'public_share'}
    """
    norm = os.path.normpath(canonical_path).replace("\\", "/")
    parts = [p for p in norm.split("/") if p]

    if parts and parts[0] == "boot":
        return ("admin_boot", "", "boot", "")

    share_name = ""
    if (
        len(parts) >= 3
        and parts[0] == "mnt"
        and parts[1] in ("user", "storage", "cache", "fast", "ssd", "disk1", "disk2", "disk3", "disk4")
    ):
        share_name = parts[2].lower()
    elif len(parts) >= 4 and parts[0] == "zettos" and parts[1] == "pool":
        share_name = parts[3].lower()

    if "homes" in parts:
        idx_homes = parts.index("homes")
        if idx_homes + 1 < len(parts):
            owner_user = parts[idx_homes + 1].lower()
            return ("user_home", owner_user, "homes", owner_user)
        return ("admin_boot", "", "homes", "")

    return ("public_share", "", share_name, "*")


SYSTEM_SHARE_EXCLUSIONS: set[str] = {
    "appdata",
    "system",
    "domains",
    "isos",
    "docker",
    "libvirt",
    "lost+found",
    ".RecycleBin",
    ".thumbnails",
}


# Rescan a disk's watched folders on spin-up at most this often (queued folders don't wait)
SPINUP_RESCAN_COOLDOWN_SECS = 6 * 3600
# How often to retry giving files with fallback (lexical) vectors their neural vectors (AI-10)
FALLBACK_REEMBED_EVERY_SECS = 300


from backend.services.rag_engine_indexing import RagIndexingMixin  # noqa: E402
from backend.services.rag_engine_learning import RagLearningMixin  # noqa: E402
from backend.services.rag_engine_manifests import RagManifestMixin  # noqa: E402
from backend.services.rag_engine_search import RagSearchMixin  # noqa: E402


class RagSearchEngine(RagSearchMixin, RagManifestMixin, RagLearningMixin, RagIndexingMixin):
    """
    Spindown-Safe Multi-Modal Local RAG & Visual Search Engine backed by SQLite WAL.
    Supports interactive Stop / Pause / Resume controls, multi-folder watched_paths,
    and automatic opportunistic learning when a sleeping disk spins up.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or RAG_DB_PATH
        self._write_lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._is_indexing = False
        self._sync_state: str = "idle"  # "idle" | "running" | "paused" | "stopping" | "completed" | "stopped"
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_requested: bool = False
        self._sync_thread: threading.Thread | None = None
        self._watcher_thread: threading.Thread | None = None
        self._known_sleeping_devs: set[str] = set(rag_standby.get_sleeping_disks_list())
        self._last_spinup_rescan: dict[str, float] = {}  # disk -> when its watched folders were last rescanned
        self._last_fallback_reembed = 0.0
        self._last_auto_learn_event: dict[str, Any] | None = None
        self._sync_progress: dict[str, Any] = {
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
            "message": "",
        }
        self._last_sync_ts: float | None = None
        self._schema_initialized = False
        self._has_sqlite_vec: bool = False
        self._vec_table_active: bool = False
        self._vec_legacy: str | None = None  # the float index searched until the int8 one is filled (AI-18)
        self._vec_converting = False
        self._vec_table_dim: int = 768
        self._ensure_schema()
        if os.path.exists(self.db_path):
            try:
                conn_init = self._get_conn(readonly=True)
                try:
                    c_row = conn_init.execute("SELECT COUNT(*) FROM indexed_files WHERE parse_status = 'ok'").fetchone()
                    total_ready = int(c_row[0]) if c_row and c_row[0] else 0
                    if total_ready > 0:
                        self._sync_state = "completed"
                        self._sync_progress.update(
                            {
                                "state": "completed",
                                "skipped_unchanged": total_ready,
                                "last_message": f"✓ All {total_ready} media & document files up to date.",
                                "message": f"✓ All {total_ready} media & document files up to date.",
                            }
                        )
                finally:
                    conn_init.close()
            except Exception:
                ignored("backend.services.rag_engine.RagSearchEngine.__init__")
        self._start_spinup_watcher()

    def _open_ro(self) -> sqlite3.Connection:
        from backend.sqlite_conn import connect

        conn = connect("rag_index", self.db_path, readonly=True)
        conn.execute("PRAGMA query_only=ON;")
        conn.execute(f"PRAGMA cache_size=-{READ_CACHE_KIB};")
        load_sqlite_vec_extension(conn)
        return conn

    def _get_conn(self, readonly: bool = False) -> sqlite3.Connection:
        db_crypto.wait_ready(self.db_path)  # raises while the index is being encrypted
        if readonly and os.path.exists(self.db_path):
            try:
                return self._open_ro()
            except Exception:
                ignored("backend.services.rag_engine.RagSearchEngine._get_conn")

        from backend.sqlite_conn import connect

        conn = connect("rag_index", self.db_path)
        conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES};")  # the WAL shrinks back (PERF-23)
        load_sqlite_vec_extension(conn)
        return conn

    def _get_ro_conn(self) -> sqlite3.Connection:
        """Returns a read-only SQLite connection configured for WAL mode."""
        return self._get_conn(readonly=True)

    def close(self) -> None:
        """Signals background threads to stop and releases resources."""
        self._stop_requested = True

    def _ensure_schema(self) -> None:
        with self._write_lock:
            if self._schema_initialized and os.path.exists(self.db_path):
                return
            conn = self._get_conn(readonly=False)
            try:
                # columns added after these tables first shipped (before the CREATE INDEX
                # statements below use them): see db_schema (ARC-8)
                from backend.db_schema import ensure_columns

                ensure_columns(conn, "rag_index.db")

                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS indexed_files (
                        file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        canonical_path TEXT UNIQUE NOT NULL,
                        parent_dir TEXT NOT NULL,
                        file_name TEXT NOT NULL,
                        file_ext TEXT NOT NULL,
                        modality TEXT NOT NULL,
                        doc_type TEXT NOT NULL DEFAULT 'generic',
                        doc_title TEXT NOT NULL DEFAULT '',
                        doc_metadata_json TEXT NOT NULL DEFAULT '{}',
                        size_bytes INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        sha256_hash TEXT NOT NULL,
                        backing_dev TEXT NOT NULL DEFAULT '',
                        pool_id TEXT NOT NULL DEFAULT '',
                        share_name TEXT NOT NULL DEFAULT '',
                        visibility_tier TEXT NOT NULL DEFAULT 'public_share',
                        owner_username TEXT NOT NULL DEFAULT '',
                        allowed_users_csv TEXT NOT NULL DEFAULT '*',
                        parse_status TEXT NOT NULL DEFAULT 'ok',
                        index_version INTEGER NOT NULL DEFAULT 3,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        indexed_at REAL NOT NULL,
                        last_verified_at REAL NOT NULL,
                        embedding_model TEXT NOT NULL DEFAULT 'zett_lexical_384d'
                    );

                    CREATE INDEX IF NOT EXISTS idx_files_lookup ON indexed_files(canonical_path, mtime_ns, size_bytes);
                    CREATE INDEX IF NOT EXISTS idx_files_sha256 ON indexed_files(sha256_hash, size_bytes);
                    CREATE INDEX IF NOT EXISTS idx_files_rbac ON indexed_files(visibility_tier, owner_username, share_name);
                    CREATE INDEX IF NOT EXISTS idx_files_modality_type ON indexed_files(modality, doc_type);
                    CREATE INDEX IF NOT EXISTS idx_files_parent ON indexed_files(parent_dir);
                    CREATE INDEX IF NOT EXISTS idx_files_ext ON indexed_files(file_ext);
                    -- the newest readable files first without sorting the whole index (PERF-24); partial,
                    -- so it doesn't take the plan from narrower indexes like idx_files_fallback_vectors
                    CREATE INDEX IF NOT EXISTS idx_files_ok_mtime ON indexed_files(mtime_ns DESC) WHERE parse_status = 'ok';
                    -- auto-tags for the document filters (B8, rag_tags.SCHEMA)
                    CREATE TABLE IF NOT EXISTS doc_tags (file_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (file_id, tag));
                    CREATE INDEX IF NOT EXISTS idx_doc_tags_tag ON doc_tags(tag, file_id);
                    CREATE TABLE IF NOT EXISTS doc_tags_done (file_id INTEGER PRIMARY KEY);
                    -- the fallback re-embed check runs every 5 minutes; without this it scanned every file (PERF-5)
                    CREATE INDEX IF NOT EXISTS idx_files_fallback_vectors ON indexed_files(file_id)
                        WHERE parse_status = 'ok' AND embedding_model = 'zett_lexical_384d';

                    CREATE TABLE IF NOT EXISTS document_chunks (
                        chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_id INTEGER NOT NULL REFERENCES indexed_files(file_id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        parent_chunk_id INTEGER DEFAULT NULL,
                        chunk_level TEXT NOT NULL DEFAULT 'child',
                        source_modality TEXT NOT NULL DEFAULT 'document',
                        file_name TEXT NOT NULL DEFAULT '',
                        doc_type TEXT NOT NULL DEFAULT 'generic',
                        heading_context TEXT NOT NULL DEFAULT '',
                        structural_context TEXT NOT NULL DEFAULT '',
                        chunk_text TEXT NOT NULL,
                        raw_chunk_text TEXT NOT NULL DEFAULT '',
                        doc_metadata_json TEXT NOT NULL DEFAULT '{}',
                        char_start INTEGER NOT NULL DEFAULT 0,
                        char_end INTEGER NOT NULL DEFAULT 0,
                        line_start INTEGER NOT NULL DEFAULT 1,
                        line_end INTEGER NOT NULL DEFAULT 1,
                        token_count INTEGER NOT NULL DEFAULT 0,
                        embedding_model TEXT NOT NULL DEFAULT 'zettnas-unified-384-v2',
                        embedding_dim INTEGER NOT NULL DEFAULT 384,
                        embedding_f32 BLOB NOT NULL,
                        visibility_tier TEXT NOT NULL DEFAULT 'public_share',
                        owner_username TEXT NOT NULL DEFAULT '',
                        share_name TEXT NOT NULL DEFAULT '',
                        allowed_users_csv TEXT NOT NULL DEFAULT '*',
                        UNIQUE(file_id, chunk_index)
                    );

                    CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON document_chunks(file_id);
                    -- Lets search pick its newest chunks without reading every chunk row
                    CREATE INDEX IF NOT EXISTS idx_chunks_file_level ON document_chunks(file_id, chunk_level);
                    CREATE INDEX IF NOT EXISTS idx_chunks_parent ON document_chunks(file_id, parent_chunk_id);
                    CREATE INDEX IF NOT EXISTS idx_chunks_level ON document_chunks(chunk_level);
                    CREATE INDEX IF NOT EXISTS idx_chunks_rbac ON document_chunks(visibility_tier, owner_username, share_name);

                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
                        file_name,
                        heading_context,
                        chunk_text,
                        doc_metadata_json,
                        content='document_chunks',
                        content_rowid='chunk_id',
                        tokenize='porter unicode61 remove_diacritics 2'
                    );

                    CREATE TRIGGER IF NOT EXISTS trg_chunks_ai AFTER INSERT ON document_chunks BEGIN
                        INSERT INTO rag_chunks_fts(rowid, file_name, heading_context, chunk_text, doc_metadata_json)
                        VALUES (new.chunk_id, new.file_name, new.heading_context, new.chunk_text, new.doc_metadata_json);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_chunks_ad AFTER DELETE ON document_chunks BEGIN
                        INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, file_name, heading_context, chunk_text, doc_metadata_json)
                        VALUES ('delete', old.chunk_id, old.file_name, old.heading_context, old.chunk_text, old.doc_metadata_json);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_chunks_au AFTER UPDATE ON document_chunks BEGIN
                        INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, file_name, heading_context, chunk_text, doc_metadata_json)
                        VALUES ('delete', old.chunk_id, old.file_name, old.heading_context, old.chunk_text, old.doc_metadata_json);
                        INSERT INTO rag_chunks_fts(rowid, file_name, heading_context, chunk_text, doc_metadata_json)
                        VALUES (new.chunk_id, new.file_name, new.heading_context, new.chunk_text, new.doc_metadata_json);
                    END;

                    CREATE TABLE IF NOT EXISTS folder_manifests (
                        manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        folder_path TEXT UNIQUE NOT NULL,
                        parent_path TEXT NOT NULL DEFAULT '',
                        folder_name TEXT NOT NULL DEFAULT '',
                        total_files INTEGER NOT NULL DEFAULT 0,
                        total_size_bytes INTEGER NOT NULL DEFAULT 0,
                        file_types_json TEXT NOT NULL DEFAULT '{}',
                        structural_summary TEXT NOT NULL DEFAULT '',
                        topics_json TEXT NOT NULL DEFAULT '[]',
                        backing_dev TEXT NOT NULL DEFAULT '',
                        visibility_tier TEXT NOT NULL DEFAULT 'public_share',
                        owner_username TEXT NOT NULL DEFAULT '',
                        share_name TEXT NOT NULL DEFAULT '',
                        allowed_users_csv TEXT NOT NULL DEFAULT '*',
                        indexed_at REAL NOT NULL,
                        last_verified_at REAL NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_manifest_parent ON folder_manifests(parent_path);
                    CREATE INDEX IF NOT EXISTS idx_manifest_rbac ON folder_manifests(visibility_tier, owner_username, share_name);

                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_manifests_fts USING fts5(
                        folder_name,
                        folder_path,
                        structural_summary,
                        topics_json,
                        content='folder_manifests',
                        content_rowid='manifest_id',
                        tokenize='porter unicode61 remove_diacritics 2'
                    );

                    CREATE TRIGGER IF NOT EXISTS trg_manifests_ai AFTER INSERT ON folder_manifests BEGIN
                        INSERT INTO rag_manifests_fts(rowid, folder_name, folder_path, structural_summary, topics_json)
                        VALUES (new.manifest_id, new.folder_name, new.folder_path, new.structural_summary, new.topics_json);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_manifests_ad AFTER DELETE ON folder_manifests BEGIN
                        INSERT INTO rag_manifests_fts(rag_manifests_fts, rowid, folder_name, folder_path, structural_summary, topics_json)
                        VALUES ('delete', old.manifest_id, old.folder_name, old.folder_path, old.structural_summary, old.topics_json);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_manifests_au AFTER UPDATE ON folder_manifests BEGIN
                        INSERT INTO rag_manifests_fts(rag_manifests_fts, rowid, folder_name, folder_path, structural_summary, topics_json)
                        VALUES ('delete', old.manifest_id, old.folder_name, old.folder_path, old.structural_summary, old.topics_json);
                        INSERT INTO rag_manifests_fts(rowid, folder_name, folder_path, structural_summary, topics_json)
                        VALUES (new.manifest_id, new.folder_name, new.folder_path, new.structural_summary, new.topics_json);
                    END;

                    CREATE TABLE IF NOT EXISTS photo_assets (
                        file_id INTEGER PRIMARY KEY REFERENCES indexed_files(file_id) ON DELETE CASCADE,
                        file_name TEXT NOT NULL DEFAULT '',
                        width INTEGER NOT NULL DEFAULT 0,
                        height INTEGER NOT NULL DEFAULT 0,
                        aspect_ratio REAL NOT NULL DEFAULT 1.0,
                        format TEXT NOT NULL DEFAULT 'JPEG',
                        taken_at REAL,
                        camera_make TEXT NOT NULL DEFAULT '',
                        camera_model TEXT NOT NULL DEFAULT '',
                        lens_model TEXT NOT NULL DEFAULT '',
                        iso INTEGER,
                        focal_length_mm REAL,
                        aperture_f REAL,
                        gps_lat REAL,
                        gps_lon REAL,
                        location_label TEXT NOT NULL DEFAULT '',
                        when_where_done INTEGER NOT NULL DEFAULT 0,
                        phash_hex TEXT NOT NULL DEFAULT '',
                        dominant_hex TEXT NOT NULL DEFAULT '#1e293b',
                        palette_json TEXT NOT NULL DEFAULT '[]',
                        object_colors_json TEXT NOT NULL DEFAULT '{}',
                        frame_colors_json TEXT NOT NULL DEFAULT '{}',
                        object_colors_text TEXT NOT NULL DEFAULT '',
                        color_hist_f32 BLOB,
                        center_color_hist_f32 BLOB,
                        scene_tags_json TEXT NOT NULL DEFAULT '[]',
                        auto_tags_text TEXT NOT NULL DEFAULT '',
                        caption_text TEXT NOT NULL DEFAULT '',
                        ocr_text TEXT NOT NULL DEFAULT '',
                        vision_embedding_f32 BLOB NOT NULL,
                        thumb_webp BLOB,
                        visibility_tier TEXT NOT NULL DEFAULT 'public_share',
                        owner_username TEXT NOT NULL DEFAULT '',
                        share_name TEXT NOT NULL DEFAULT '',
                        allowed_users_csv TEXT NOT NULL DEFAULT '*'
                    );

                    CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photo_assets(taken_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_photos_rbac ON photo_assets(visibility_tier, owner_username, share_name);
                    CREATE INDEX IF NOT EXISTS idx_photos_phash ON photo_assets(phash_hex);

                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_photos_fts USING fts5(
                        file_name,
                        object_colors_text,
                        auto_tags_text,
                        caption_text,
                        camera_model,
                        location_label,
                        content='photo_assets',
                        content_rowid='file_id',
                        tokenize='porter unicode61 remove_diacritics 2'
                    );

                    CREATE TRIGGER IF NOT EXISTS trg_photos_ai AFTER INSERT ON photo_assets BEGIN
                        INSERT INTO rag_photos_fts(rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
                        VALUES (new.file_id, new.file_name, new.object_colors_text, new.auto_tags_text, new.caption_text, new.camera_model, new.location_label);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_photos_ad AFTER DELETE ON photo_assets BEGIN
                        INSERT INTO rag_photos_fts(rag_photos_fts, rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
                        VALUES ('delete', old.file_id, old.file_name, old.object_colors_text, old.auto_tags_text, old.caption_text, old.camera_model, old.location_label);
                    END;
                    CREATE TRIGGER IF NOT EXISTS trg_photos_au AFTER UPDATE ON photo_assets BEGIN
                        INSERT INTO rag_photos_fts(rag_photos_fts, rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
                        VALUES ('delete', old.file_id, old.file_name, old.object_colors_text, old.auto_tags_text, old.caption_text, old.camera_model, old.location_label);
                        INSERT INTO rag_photos_fts(rowid, file_name, object_colors_text, auto_tags_text, caption_text, camera_model, location_label)
                        VALUES (new.file_id, new.file_name, new.object_colors_text, new.auto_tags_text, new.caption_text, new.camera_model, new.location_label);
                    END;

                    CREATE TABLE IF NOT EXISTS rag_deferred_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_path TEXT UNIQUE NOT NULL,
                        backing_dev TEXT NOT NULL,
                        reason TEXT NOT NULL DEFAULT 'disk_standby',
                        queued_at REAL NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_deferred_dev ON rag_deferred_queue(backing_dev, priority DESC);
                    """
                )
                conn.commit()

                try:
                    cfg = self.get_config()
                    self._vec_table_dim = int(cfg.get("embedding_dim") or 768)
                    self._has_sqlite_vec = load_sqlite_vec_extension(conn)
                    if self._has_sqlite_vec:
                        self._init_vec_table(conn, self._vec_table_dim)
                        self._vec_table_active = True
                except Exception as e:
                    logger.debug("sqlite-vec table init skipped: %s", e)

                try:
                    self._migrate_unicode_tokens(conn)
                except sqlite3.Error as e:
                    logger.warning(f"[RAG] Unicode token migration skipped: {e}")
                try:
                    from backend.services import rag_cjk

                    if rag_cjk.ensure_schema(conn):
                        added = rag_cjk.backfill(conn)  # once per index (AI-13)
                        if added:
                            logger.info(f"[RAG] {added} chunk(s) with CJK text added to the keyword index")
                    conn.commit()
                except sqlite3.Error as e:
                    logger.warning(f"[RAG] CJK keyword index skipped: {e}")

                self._schema_initialized = True
            finally:
                conn.close()

    def _init_vec_table(self, conn: sqlite3.Connection, dim: int, background: bool = True) -> bool:
        """The vec0 index for one dimension, with int8 vectors (AI-18). An index made before with
        float vectors stays in use until the int8 one is filled, in the background and in
        batches, from the float vectors in document_chunks; then it is dropped. Converting a
        big index takes minutes, and doing it at start kept the app from answering its health
        check, so the update was rolled back."""
        dim = int(dim)
        try:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table(dim)} USING vec0(
                    chunk_id INTEGER PRIMARY KEY,
                    embedding int8[{dim}],
                    file_id INTEGER,
                    visibility_tier TEXT
                );
                """
            )
        except Exception as e:
            logger.debug("vec0 table creation failed: %s", e)
            return False
        old = f"vec_chunks_{dim}"
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (old,)).fetchone():
            self._vec_legacy = old
            if background and not self._vec_converting:
                self._vec_converting = True
                threading.Thread(target=self.convert_vectors, args=(dim,), daemon=True, name="rag-vec-int8").start()
        else:
            self._vec_legacy = None
        return True

    def vec_search_table(self) -> tuple[str, str]:
        """The index search reads now and how a query vector is put to it: the float index while
        the int8 one is being filled, then the int8 one."""
        if self._vec_legacy:
            return self._vec_legacy, "?"
        return vec_table(self._vec_table_dim), VEC_QUANTIZE

    def convert_vectors(self, dim: int, batch: int = 500, pause: float = 0.05) -> int:
        """Fills the int8 index from the float vectors in document_chunks (no file is read), a
        batch at a time, each under the write lock, so search and indexing go on meanwhile; the
        float index is dropped at the end. Safe to stop: the next start carries on."""
        dim = int(dim)
        old, new = f"vec_chunks_{dim}", vec_table(dim)
        model = self.get_config().get("embedding_model") or ""
        last, done, t0 = 0, 0, time.time()
        try:
            while True:
                with self._write_lock:
                    conn = self._get_conn(readonly=False)
                    try:
                        rows = conn.execute(
                            "SELECT chunk_id, embedding_f32, file_id, visibility_tier FROM document_chunks "
                            "WHERE chunk_id > ? AND embedding_dim = ? AND embedding_model = ? AND chunk_level != 'parent' "
                            "AND length(embedding_f32) = ? ORDER BY chunk_id LIMIT ?",
                            (last, dim, model, dim * 4, batch),
                        ).fetchall()
                        if not rows:
                            conn.execute(f"DROP TABLE IF EXISTS {old}")
                            conn.commit()
                            self._vec_legacy = None
                            break
                        conn.executemany(
                            f"INSERT OR REPLACE INTO {new}(chunk_id, embedding, file_id, visibility_tier) "
                            f"VALUES (?, {VEC_QUANTIZE}, ?, ?)",
                            [tuple(r) for r in rows],
                        )
                        conn.commit()
                    finally:
                        conn.close()
                last = int(rows[-1][0])
                done += len(rows)
                if pause:
                    time.sleep(pause)
            logger.info(f"[RAG] Vector index converted to int8: {done} vectors in {time.time() - t0:.1f}s")
        except Exception:
            logger.warning(
                "[RAG] Vector index conversion to int8 stopped; it carries on at the next start", exc_info=True
            )
        finally:
            self._vec_converting = False
        return done

    def file_chunks(self, path: str, max_chars: int = 16000) -> dict[str, Any]:
        """One indexed file's text in reading order, from the index (no disk access, AI-22).
        Returns {"found": False} when the path is not an indexed file (a folder, say)."""
        conn = self._get_conn(readonly=True)
        try:
            row = (
                conn.execute(
                    "SELECT file_id, file_name, doc_title, doc_type FROM indexed_files WHERE canonical_path = ?",
                    (os.path.realpath(path),),
                ).fetchone()
                or conn.execute(
                    "SELECT file_id, file_name, doc_title, doc_type FROM indexed_files WHERE canonical_path = ?",
                    (path,),
                ).fetchone()
            )
            if not row:
                return {"found": False}
            fid, name, title, doc_type = row
            rows = conn.execute(
                "SELECT chunk_id, chunk_text, heading_context, line_start, line_end FROM document_chunks "
                "WHERE file_id = ? AND chunk_level != 'parent' ORDER BY chunk_index",
                (fid,),
            ).fetchall()
        finally:
            conn.close()
        chunks, used, total = [], 0, 0
        for chunk_id, text, heading, l0, l1 in rows:
            total += len(text or "")
            if used + len(text or "") > max_chars:
                continue
            used += len(text or "")
            chunks.append(
                {"chunk_id": chunk_id, "text": text or "", "heading": heading or "", "line_start": l0, "line_end": l1}
            )
        return {
            "found": True,
            "file_id": fid,
            "name": name or os.path.basename(path),
            "title": title or "",
            "doc_type": doc_type or "document",
            "chunks": chunks,
            "complete": used >= total,
        }

    def _drop_file_vectors(self, conn: sqlite3.Connection, file_ids_sql: str, params: Any) -> None:
        """Removes the vector-table rows of these files' chunks; call it before the chunks go.

        `file_ids_sql` is a list of placeholders or a subquery giving file ids."""
        if not (self._has_sqlite_vec and self._vec_table_active):
            return
        try:
            for table in (vec_table(self._vec_table_dim), self._vec_legacy):
                if table:
                    conn.execute(
                        f"""DELETE FROM {table} WHERE chunk_id IN (
                            SELECT chunk_id FROM document_chunks WHERE file_id IN ({file_ids_sql}))""",
                        params,
                    )
        except sqlite3.Error as e:
            logger.debug(f"[RAG] vector cleanup skipped: {e}")

    def _default_watched_paths(self) -> list[str]:
        """Determines sensible non-system default watched folders without waking sleeping drives."""
        _, unraid_shares = rag_standby._get_unraid_disks_and_shares()
        if unraid_shares:
            user_shares: list[str] = []
            for s_name in sorted(unraid_shares.keys()):
                if s_name.lower() not in SYSTEM_SHARE_EXCLUSIONS and not s_name.startswith("."):
                    user_shares.append(f"/mnt/user/{s_name}")
            if user_shares:
                return user_shares
        return ["/mnt/user"]

    def get_config(self) -> dict[str, Any]:
        default_cfg: dict[str, Any] = {
            "enabled": True,
            "scope_mode": "include",  # "all" (Learn All Files), "exclude" (Exclude Folders), "include" (Specified Watched Folders)
            "respect_standby": True,
            "auto_learn_on_spinup": True,
            "compute_preference": "auto",  # "auto" (NPU -> GPU -> CPU), "npu", "gpu", "cpu_eco"
            "watched_paths": self._default_watched_paths(),
            "excluded_paths": [],
            "schedule_enabled": False,
            "schedule_start": "01:00",
            "schedule_end": "06:00",
            "active_model": "qwen2.5:3b",
            "embedding_model": "embeddinggemma",
            "embedding_dim": 768,
            "embedding_provider": "ollama",
            "llm_endpoint": "",
            "llm_model": "qwen2.5:3b",
            "idle_unload_minutes": 15,  # chat models unload after this many idle minutes (decision 4)
            "favorites": [],
            "search_history": [],
            "custom_hf_models": [],
            "removed_models": [],
            "vision_captions": "auto",  # AI-14: "auto" (when a vision model is installed) or "off"
            "caption_language": "auto",  # AI-13: "auto" (the documents' language) or en, de, fr, es, zh
            "vision_model": "",
            "embedding_host": "",  # Ollama-compatible server for embeddings only; empty = the Ollama host
            "rerank_endpoint": "",  # AI-13: Cohere/OVMS/TEI-style /rerank URL, empty = off
            "transcribe_endpoint": "",  # COMP-03: OpenAI-style speech server (Whisper), empty = off
            "transcribe_model": "",
            "transcribe_video": False,  # videos too, not only voice memos and other audio
            "transcribe_max_minutes": 30,
            "photo_vector_host": "",  # B14: contrib/openvino-clip (SigLIP 2), empty = off
            "photo_vector_model": "",
            "rerank_model": "",
            "rerank_top_n": 30,
            "ai_role_access": {"kid": False, "guest": False},  # who may ask Zetty (B8, ai_access)
            "ai_search_role_access": {"kid": False, "guest": False},  # who may use AI search (B11, AI-26)
        }
        saved = read_json(RAG_CONFIG_PATH, {})
        if isinstance(saved, dict):
            default_cfg.update(saved)
        # Clean up empty or duplicate watched_paths
        raw_paths = default_cfg.get("watched_paths") or []
        cleaned_paths: list[str] = []
        for p in raw_paths:
            cp = os.path.normpath(str(p or "").strip())
            if cp and cp not in cleaned_paths:
                cleaned_paths.append(cp)
        default_cfg["watched_paths"] = cleaned_paths or self._default_watched_paths()

        raw_excl = default_cfg.get("excluded_paths") or []
        cleaned_excl: list[str] = []
        for p in raw_excl:
            cp = os.path.normpath(str(p or "").strip())
            if cp and cp not in cleaned_excl:
                cleaned_excl.append(cp)
        default_cfg["excluded_paths"] = cleaned_excl

        if not default_cfg.get("active_model"):
            default_cfg["active_model"] = default_cfg.get("llm_model") or "qwen2.5:3b"
        if not default_cfg.get("embedding_model"):
            default_cfg["embedding_model"] = "embeddinggemma"
        return default_cfg

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        cfg = self.get_config()
        if (
            "embedding_model" in updates
            and updates["embedding_model"] != cfg.get("embedding_model")
            and "embedding_host" not in updates
        ):
            updates = dict(updates, embedding_host="")  # a host serves one model: it doesn't follow a switch
        for k in (
            "enabled",
            "scope_mode",
            "respect_standby",
            "auto_learn_on_spinup",
            "compute_preference",
            "watched_paths",
            "excluded_paths",
            "schedule_enabled",
            "schedule_start",
            "schedule_end",
            "active_model",
            "embedding_model",
            "embedding_dim",
            "embedding_provider",
            "embedding_host",
            "llm_endpoint",
            "llm_model",
            "llm_fallback_model",
            "idle_unload_minutes",
            "favorites",
            "search_history",
            "custom_hf_models",
            "removed_models",
            "conversation_retention_days",
            "vision_captions",
            "caption_language",
            "vision_model",
            "rerank_endpoint",
            "rerank_model",
            "rerank_top_n",
            "transcribe_endpoint",
            "transcribe_model",
            "transcribe_video",
            "transcribe_max_minutes",
            "photo_vector_host",
            "photo_vector_model",
        ):
            if k in updates and updates[k] is not None:
                cfg[k] = updates[k]
        for key in ("ai_role_access", "ai_search_role_access"):
            if isinstance(updates.get(key), dict):
                # who may ask Zetty / use AI search; the API checks the values first (ai_access.clean_switches)
                switches = {str(k): bool(v) for k, v in updates[key].items()}
                cfg[key] = {**(cfg.get(key) or {}), **switches}
        if str(cfg.get("vision_captions", "auto")).lower() not in ("auto", "off"):
            cfg["vision_captions"] = "auto"
        if str(cfg.get("caption_language", "auto")).lower() not in ("auto", "en", "de", "fr", "es", "zh"):
            cfg["caption_language"] = "auto"
        if "conversation_retention_days" in cfg:
            try:
                cfg["conversation_retention_days"] = max(0, min(3650, int(cfg["conversation_retention_days"])))
            except (TypeError, ValueError):
                cfg["conversation_retention_days"] = 0

        if "respect_standby" in updates and "auto_learn_on_spinup" not in updates:
            cfg["auto_learn_on_spinup"] = bool(cfg["respect_standby"])
        elif "auto_learn_on_spinup" in updates and "respect_standby" not in updates:
            cfg["respect_standby"] = bool(cfg["auto_learn_on_spinup"])

        if "active_model" in updates and updates["active_model"]:
            cfg["llm_model"] = updates["active_model"]
        elif "llm_model" in updates and updates["llm_model"]:
            cfg["active_model"] = updates["llm_model"]

        # Validate schedule window (start and end cannot be identical per ZettAI Wiki)
        if cfg.get("schedule_enabled") and cfg.get("schedule_start") == cfg.get("schedule_end"):
            cfg["schedule_end"] = "06:00" if cfg.get("schedule_start") != "06:00" else "07:00"

        for list_key in ("watched_paths", "excluded_paths"):
            if isinstance(cfg.get(list_key), list):
                dedup: list[str] = []
                for p in cfg[list_key]:
                    cp = os.path.normpath(str(p or "").strip())
                    if cp and cp not in dedup:
                        dedup.append(cp)
                cfg[list_key] = dedup

        # When ZettAI is disabled, pause any unfinished learning task so it can resume when re-enabled
        if updates.get("enabled") is False and self._is_indexing:
            self.pause_sync()
        elif updates.get("enabled") is True and self._is_indexing and self._sync_state == "paused":
            self.resume_sync()

        atomic_write_json(RAG_CONFIG_PATH, cfg)
        if any(
            k in updates
            for k in ("watched_paths", "excluded_paths", "scope_mode", "respect_standby", "auto_learn_on_spinup")
        ):
            self.sync_watched_deferred_queue()
        return cfg

    def get_index_stats(self) -> dict[str, Any]:
        self._ensure_schema()
        cfg = self.get_config()
        conn = self._get_conn(readonly=True)
        try:
            total_files = conn.execute("SELECT COUNT(*) FROM indexed_files WHERE parse_status = 'ok'").fetchone()[0]
            total_photos = conn.execute("SELECT COUNT(*) FROM photo_assets").fetchone()[0]
            total_videos = conn.execute(
                "SELECT COUNT(*) FROM indexed_files WHERE modality = 'video' AND parse_status = 'ok'"
            ).fetchone()[0]
            total_docs = conn.execute(
                "SELECT COUNT(*) FROM indexed_files WHERE modality IN ('document', 'code') AND parse_status = 'ok'"
            ).fetchone()[0]
            total_recipes = conn.execute(
                "SELECT COUNT(*) FROM indexed_files WHERE doc_type = 'recipe' AND parse_status = 'ok'"
            ).fetchone()[0]
            total_chunks = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
            deferred_count = conn.execute("SELECT COUNT(*) FROM rag_deferred_queue").fetchone()[0]
            last_row = conn.execute("SELECT MAX(indexed_at) FROM indexed_files").fetchone()
            last_ts = float(last_row[0]) if last_row and last_row[0] is not None else self._last_sync_ts
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

            # Determine actual embedding model and dimension stored in indexed chunks
            chunk_dim_row = conn.execute(
                "SELECT embedding_model, embedding_dim FROM document_chunks WHERE embedding_dim > 0 ORDER BY chunk_id DESC LIMIT 1"
            ).fetchone()
            actual_dim = (
                int(chunk_dim_row["embedding_dim"])
                if chunk_dim_row and chunk_dim_row["embedding_dim"]
                else int(cfg.get("embedding_dim") or 768)
            )
            actual_model = (
                str(chunk_dim_row["embedding_model"])
                if chunk_dim_row and chunk_dim_row["embedding_model"]
                else str(cfg.get("embedding_model") or "embeddinggemma")
            )

            return {
                "indexed_count": total_files,
                "total_files": total_files,
                "total_photos": total_photos,
                "total_videos": total_videos,
                "total_docs": total_docs,
                "total_documents": total_docs,
                "total_recipes": total_recipes,
                "total_chunks": total_chunks,
                "deferred_queue_count": deferred_count,
                "last_scan_timestamp": last_ts,
                "is_scanning": self._is_indexing,
                "is_paused": self._sync_state == "paused",
                "sync_state": self._sync_state,
                "db_path": self.db_path,
                "db_size_bytes": db_size,
                "embedding_model": cfg.get("embedding_model") or "embeddinggemma",
                "embedding_dim": int(cfg.get("embedding_dim") or 768),
                "actual_embedding_model": actual_model,
                "actual_embedding_dim": actual_dim,
            }
        except Exception as e:
            logger.debug(f"[RAG] Error reading index stats: {e}")
            return {
                "indexed_count": 0,
                "total_files": 0,
                "total_photos": 0,
                "total_docs": 0,
                "total_documents": 0,
                "total_recipes": 0,
                "total_chunks": 0,
                "deferred_queue_count": 0,
                "last_scan_timestamp": self._last_sync_ts,
                "is_scanning": self._is_indexing,
                "is_paused": self._sync_state == "paused",
                "sync_state": self._sync_state,
                "db_path": self.db_path,
                "db_size_bytes": 0,
            }
        finally:
            conn.close()

    def _migrate_unicode_tokens(self, conn: sqlite3.Connection) -> int:
        """Once per index: marks files with CJK or Cyrillic text to be learned again, because
        their stored lexical vectors predate Unicode tokenisation (AI-13)."""
        conn.execute("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)")
        if conn.execute("SELECT 1 FROM rag_meta WHERE key = 'unicode_tokens_v1'").fetchone():
            return 0
        pattern = re.compile(rf"[{_CJK_CHARS}\u0400-\u04ff]")
        stale: set[int] = set()
        for row in conn.execute("SELECT file_id, chunk_text FROM document_chunks"):
            if row[0] not in stale and pattern.search(row[1] or ""):
                stale.add(int(row[0]))
        for fid in stale:
            conn.execute("UPDATE indexed_files SET index_version = 0 WHERE file_id = ?", (fid,))
        conn.execute(
            "INSERT OR REPLACE INTO rag_meta (key, value) VALUES ('unicode_tokens_v1', ?)", (str(time.time()),)
        )
        conn.commit()
        if stale:
            logger.info(f"[RAG] {len(stale)} file(s) with CJK/Cyrillic text will be learned again (Unicode tokens)")
        return len(stale)


# Read connections get a bigger page cache; the WAL is capped and shrinks back (PERF-23). A pool
# of open read connections was tried and left out: a cursor not read to the end keeps its read
# snapshot, so a lent-out connection would read stale data and hold back checkpoints.
READ_CACHE_KIB = 16384
WAL_SIZE_LIMIT_BYTES = 64 * 1024 * 1024


def vec_table(dim: int) -> str:
    """The vector index for one dimension: int8 vectors (AI-18). The float vectors are kept once,
    in document_chunks.embedding_f32, and score the nearest neighbours this index finds."""
    return f"vec_chunks_{int(dim)}_i8"


# how a float32 vector blob goes into the index: each value of a unit vector as an int8
VEC_QUANTIZE = "vec_quantize_int8(?, 'unit')"


_RAG_ENGINE: RagSearchEngine | None = None
_RAG_ENGINE_LOCK = threading.Lock()


def get_rag_engine() -> RagSearchEngine:
    global _RAG_ENGINE
    if _RAG_ENGINE is None:
        with _RAG_ENGINE_LOCK:
            if _RAG_ENGINE is None:
                _RAG_ENGINE = RagSearchEngine()
    return _RAG_ENGINE

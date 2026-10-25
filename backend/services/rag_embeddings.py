"""
Embeddings for the AI index: the built-in 384-d lexical vectors, Ollama neural
embeddings, sqlite-vec loading and vector maths.

Split out of rag_engine.py (AI-21), which re-exports these names.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time
import urllib.error
import urllib.request

from backend.config import logger
from backend.services.rag_text import (
    _STOPWORDS,
    CANONICAL_COLORS,
    COLOR_SYNONYMS,
    EMBEDDING_DIM,
    SCENE_ONTOLOGY,
    build_target_color_histogram,
    text_tokens,
)


def compute_384d_embedding(
    text: str,
    scene_tags: list[str] | None = None,
    object_colors: dict[str, float] | None = None,
    frame_colors: dict[str, float] | None = None,
    color_hist_64: list[float] | None = None,
) -> tuple[bytes, list[float]]:
    """
    Projects text, scene ontology tags, and perceptual color features into a unified
    384-dimensional L2-normalized cross-modal vector space:
      - Dims 0..255   (256-d): Signed Murmur/SHA feature-hashed lexical + stem + char-trigram projection
      - Dims 256..319 (64-d) : Semantic Concept & Scene Ontology latents
      - Dims 320..383 (64-d) : Perceptual Color (12 bins x 2 zones) + Chromaticity signature
    """
    vec = [0.0] * EMBEDDING_DIM
    lowered = (text or "").lower()
    words = text_tokens(lowered)

    # 1. Lexical & character n-gram hashing into dims 0..255
    for w in words:
        if w in _STOPWORDS and len(w) <= 3:
            continue
        # Normalize simple plural stems so "cars" <-> "car", "recipes" <-> "recipe", "pools" <-> "pool"
        stems = {w}
        if len(w) > 4 and w.endswith("es"):
            stems.add(w[:-2])
        if len(w) > 3 and w.endswith("s"):
            stems.add(w[:-1])
        if len(w) > 5 and w.endswith("ing"):
            stems.add(w[:-3])

        for term in stems:
            digest = hashlib.md5(term.encode("utf-8")).digest()
            idx1 = digest[0]  # 0..255
            sign1 = 1.0 if (digest[1] & 1) == 0 else -1.0
            idx2 = digest[2]
            sign2 = 1.0 if (digest[3] & 1) == 0 else -1.0
            weight = 1.35 if term == w else 0.95
            vec[idx1] += sign1 * weight
            vec[idx2] += sign2 * (weight * 0.6)

        # Character trigrams for typo/substring resilience
        if len(w) >= 4:
            padded = f"^{w}$"
            for i in range(len(padded) - 2):
                tri = padded[i : i + 3]
                td = hashlib.md5(tri.encode("utf-8")).digest()
                t_idx = td[0]
                t_sign = 1.0 if (td[1] & 1) == 0 else -1.0
                vec[t_idx] += t_sign * 0.22

    # 2. Semantic Concept & Scene Ontology Latents (Dims 256..319)
    active_scenes: set[str] = set(scene_tags or [])
    for w in words:
        for scene_slug, (_, syn_set) in SCENE_ONTOLOGY.items():
            if w in syn_set or (w.endswith("s") and w[:-1] in syn_set):
                active_scenes.add(scene_slug)

    for scene_slug in active_scenes:
        if scene_slug in SCENE_ONTOLOGY:
            slot, _ = SCENE_ONTOLOGY[scene_slug]
            base_dim = 256 + (slot * 3) % 64
            vec[base_dim] += 2.4
            vec[256 + ((slot * 3 + 1) % 64)] += 1.6
            vec[256 + ((slot * 3 + 2) % 64)] += 1.2

    # 3. Perceptual Color & Spatial Chromaticity Signature (Dims 320..383)
    # Extract colors mentioned in text as well as visual object_colors / frame_colors
    merged_obj_colors: dict[str, float] = dict(object_colors or {})
    merged_frm_colors: dict[str, float] = dict(frame_colors or {})
    for w in words:
        if w in COLOR_SYNONYMS:
            cname = COLOR_SYNONYMS[w]
            merged_obj_colors[cname] = max(merged_obj_colors.get(cname, 0.0), 0.85)
            merged_frm_colors[cname] = max(merged_frm_colors.get(cname, 0.0), 0.65)

    for idx_c, cname in enumerate(CANONICAL_COLORS):
        obj_w = float(merged_obj_colors.get(cname, 0.0))
        frm_w = float(merged_frm_colors.get(cname, 0.0))
        if obj_w > 0 or frm_w > 0:
            # Subject color slot (weighted 2.5x) + frame color slot
            dim_obj = 320 + idx_c * 2
            dim_frm = 320 + idx_c * 2 + 1
            vec[dim_obj] += obj_w * 2.6 + frm_w * 0.8
            vec[dim_frm] += frm_w * 1.8 + obj_w * 1.0

    # Fold compact 64-bin HSV energy into dims 344..383 (40 dims)
    if color_hist_64:
        for i, val in enumerate(color_hist_64[:64]):
            vec[344 + (i % 40)] += float(val) * 0.9

    # L2 Normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-9:
        vec = [x / norm for x in vec]
    else:
        vec[0] = 1.0

    blob = struct.pack(f"<{EMBEDDING_DIM}f", *vec)
    return blob, vec


def unpack_embedding(blob: bytes | None) -> list[float] | None:
    """Unpacks binary float32 buffer into float vector, supporting arbitrary vector dimensions."""
    if not blob or len(blob) % 4 != 0:
        return None
    dim = len(blob) // 4
    return list(struct.unpack(f"<{dim}f", blob))


def load_sqlite_vec_extension(conn: sqlite3.Connection) -> bool:
    """
    Authorizes and loads sqlite-vec extension into the SQLite connection.
    Must be called on both read-write and read-only connections.
    """
    if hasattr(conn, "enable_load_extension"):
        try:
            conn.enable_load_extension(True)
        except Exception as e:
            logger.debug("Failed enabling SQLite extension loading: %s", e)
            return False

    try:
        import sqlite_vec

        sqlite_vec.load(conn)
        return True
    except Exception as e:
        logger.debug("sqlite_vec package load skipped/failed: %s", e)

    candidate_paths = [
        os.environ.get("SQLITE_VEC_PATH", ""),
        "/app/lib/vec0.so",
        "/usr/local/lib/vec0.so",
        "/usr/lib/vec0.so",
        "vec0",
    ]
    for path in candidate_paths:
        if not path:
            continue
        try:
            conn.load_extension(path)
            return True
        except Exception:
            continue
    return False


TASK_PREFIX_CODE = "task: code retrieval | query: "  # the model card's prompt (v1 and v2)
TASK_PREFIX_QA = "task: question answering | query: "
TASK_PREFIX_CLASSIFICATION = "task: classification | query: "
TASK_PREFIX_SEARCH = "task: search result | query: "

CODE_SYNTAX_INDICATORS = {
    "def ",
    "class ",
    "import ",
    "function ",
    "func ",
    "return ",
    "select ",
    "from ",
    "where ",
    "const ",
    "let ",
    "var ",
    "=>",
    "async ",
    "await ",
    "public ",
    "private ",
    "interface ",
    "struct ",
    "impl ",
    "fn ",
}

CLI_COMMAND_INDICATORS = {
    "docker compose",
    "docker run",
    "systemctl ",
    "smartctl ",
    "btrfs subvol",
    "btrfs scrub",
    "zpool status",
    "zfs create",
    "mdadm --",
    "chmod ",
    "chown ",
}

CODE_EXTENSIONS_RE = re.compile(
    r"\b\w+\.(py|js|ts|sh|json|ya?ml|rs|go|c|cpp|h|css|html)\b",
    re.IGNORECASE,
)

QA_INDICATORS_RE = re.compile(
    r"^(how\s+(to|do|can|does)|why\s+(is|does|do)|what\s+(is|are)|where\s+(is|can)|when\s+should|can\s+i|is\s+it\s+(safe|possible)|explain)\b",
    re.IGNORECASE,
)

CLASS_INDICATORS_RE = re.compile(
    r"\b(list\s+all|find\s+all|classify|categorize|audit|duplicates?|group\s+by)\b",
    re.IGNORECASE,
)


def classify_query_task_intent(query: str, modality_hint: str = "all") -> tuple[str, str]:
    """
    Deterministic intent classifier for Google DeepMind asymmetric task prefixing.
    Evaluates interrogative QA structures BEFORE code keywords to prevent
    domain noun collisions (e.g. 'How do I fix a raid array?').
    Returns (intent_type, task_prefix) where intent_type is 'code', 'qa', 'classification', or 'search'.
    """
    q_strip = (query or "").strip()
    low = q_strip.lower()

    if modality_hint == "code":
        return "code", TASK_PREFIX_CODE

    # Rule 1: Evaluate conversational / interrogative QA FIRST
    if QA_INDICATORS_RE.search(low) or low.endswith("?"):
        return "qa", TASK_PREFIX_QA

    # Rule 2: Evaluate classification / listing requests
    if CLASS_INDICATORS_RE.search(low):
        return "classification", TASK_PREFIX_CLASSIFICATION

    # Rule 3: Evaluate unambiguous code syntax, CLI commands, or source file extensions
    if (
        any(ind in low for ind in CODE_SYNTAX_INDICATORS)
        or any(ind in low for ind in CLI_COMMAND_INDICATORS)
        or bool(CODE_EXTENSIONS_RE.search(low))
    ):
        return "code", TASK_PREFIX_CODE

    # Rule 4: Default to semantic search
    return "search", TASK_PREFIX_SEARCH


def format_embeddinggemma_document(title: str | None, text: str) -> str:
    """
    Google DeepMind EmbeddingGemma-2 canonical document/passage formatting:
    f"title: {title.strip()} | text: {text.strip()}" if title is provided,
    else f"title: none | text: {text.strip()}".
    """
    clean_title = (title or "").strip()
    clean_text = (text or "").strip()
    if clean_title:
        return f"title: {clean_title} | text: {clean_text}"
    return f"title: none | text: {clean_text}"


def truncate_and_normalize_mrl(vec: list[float], target_dim: int | None) -> list[float]:
    """
    Slices leading dimensions of MRL vector and re-normalizes to unit L2 sphere.
    Strictly guarantees that math.isclose(sum(x*x for x in sliced_vec), 1.0, rel_tol=1e-5)
    for any non-zero input vector. Handles subnormal floats, large numbers near float64
    overflow limit (via max-abs scaling), full dimension, and oversized target_dim.
    """
    if not vec or not target_dim or target_dim <= 0:
        return vec
    sliced = [float(x) for x in vec[:target_dim]]
    if not sliced:
        return []

    if any(math.isnan(x) for x in sliced):
        return sliced

    max_abs = max(abs(x) for x in sliced)
    if max_abs <= 0.0 or math.isinf(max_abs):
        return sliced

    # Scale by max_abs to prevent intermediate float overflow/underflow
    scaled = [x / max_abs for x in sliced]
    scaled_norm = math.sqrt(sum(s * s for s in scaled))
    if scaled_norm <= 0.0:
        return sliced

    return [s / scaled_norm for s in scaled]


_CACHED_OLLAMA_HOST: str | None = None
_CACHED_OLLAMA_UNTIL = 0.0
OLLAMA_HOST_RECHECK_SECS = 300.0  # a found runtime is looked for again after this (it may have moved)
OLLAMA_HOST_MISS_SECS = 30.0  # nothing found: look again soon


def _detected_host_ip() -> str | None:
    """Returns this machine's LAN IP (HOST_IP env or auto-detected), or None."""
    try:
        from backend.hardware.network import read_ip

        ip = (read_ip() or "").strip()
    except Exception:
        return None
    if not ip or ip.startswith("127.") or ip == "0.0.0.0":
        return None
    return ip


def embedding_host(cfg: dict) -> str | None:
    """Where embeddings come from: the AI config's embedding host, else its Ollama host (None = discover)."""
    return (str(cfg.get("embedding_host") or "").strip() or str(cfg.get("ollama_host") or "").strip()) or None


def _resolve_ollama_host(explicit_host: str | None = None) -> str:
    """Discovers reachable Ollama host inside Docker bridge network or bare metal."""
    global _CACHED_OLLAMA_HOST, _CACHED_OLLAMA_UNTIL
    if explicit_host:
        h = explicit_host
        if not h.startswith("http://") and not h.startswith("https://"):
            h = f"http://{h}"
        return h.rstrip("/")
    if _CACHED_OLLAMA_HOST and (not _CACHED_OLLAMA_UNTIL or time.time() < _CACHED_OLLAMA_UNTIL):
        return _CACHED_OLLAMA_HOST

    env_h = os.environ.get("OLLAMA_HOST")
    if env_h:
        if not env_h.startswith("http://") and not env_h.startswith("https://"):
            env_h = f"http://{env_h}"
        _CACHED_OLLAMA_HOST = env_h.rstrip("/")
        return _CACHED_OLLAMA_HOST

    from backend.services.ai_endpoints import candidate_hosts

    candidates = candidate_hosts(_detected_host_ip())  # never a LAN router (AI-05)

    for cand in candidates:
        try:
            req = urllib.request.Request(f"http://{cand}:11434/api/tags", headers={"User-Agent": "ZettNAS/1.0"})
            with urllib.request.urlopen(req, timeout=0.35) as resp:
                if resp.status == 200:
                    _CACHED_OLLAMA_HOST = f"http://{cand}:11434"
                    _CACHED_OLLAMA_UNTIL = time.time() + OLLAMA_HOST_RECHECK_SECS
                    return _CACHED_OLLAMA_HOST
        except Exception:
            continue
    _CACHED_OLLAMA_HOST = "http://127.0.0.1:11434"
    _CACHED_OLLAMA_UNTIL = time.time() + OLLAMA_HOST_MISS_SECS
    return _CACHED_OLLAMA_HOST


def compute_neural_embedding_via_ollama(
    text: str,
    model: str = "embeddinggemma",
    host: str | None = None,
    timeout: float = 1.8,
    target_dim: int | None = None,
    is_query: bool = False,
    task_prompt: str | None = None,
) -> tuple[bytes, list[float]] | None:
    """
    Computes dense neural vector embeddings via Ollama or local inference endpoint.
    Supports Google DeepMind's EmbeddingGemma 2, Nomic-Embed-Text, and standard embedders.
    Features:
      - Asymmetric retrieval task prefixing (e.g. 'task: search result | query: ...')
      - Matryoshka Representation Learning (MRL) dimension truncation (768 -> 512, 256, 128)
      - Dual API compatibility: tries modern Ollama /api/embed then falls back to /api/embeddings
      - Extended 8K context token handling (up to 16,000 characters)
      - Accelerated by host NPU/GPU drivers when available.
    Returns (packed_f32_blob, normalized_float_vector) on success, or None on failure/timeout.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return None

    target_host = _resolve_ollama_host(host)

    # Asymmetric instruction prefix for EmbeddingGemma models (Google DeepMind spec)
    is_eg = "embeddinggemma" in model.lower()
    if is_eg:
        if is_query:
            if not clean_text.lower().startswith("task:"):
                instruction = task_prompt or "task: search result | query: "
                prompt_text = f"{instruction}{clean_text}"
            else:
                prompt_text = clean_text
        else:
            prompt_text = clean_text

        # True 8K token context budgeting: 32K chars for Latin/code, 12K chars for CJK
        cjk_chars = sum(1 for c in prompt_text if "\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff")
        is_cjk_dominant = (cjk_chars / max(1, len(prompt_text))) > 0.3
        # EmbeddingGemma reads 2,048 tokens; more text is silently cut by the runtime (AI-11)
        max_chars = 2500 if is_cjk_dominant else 6000
        prompt_text = prompt_text[:max_chars]
    else:
        prompt_text = clean_text[:4000]

    # Only the configured model (and its ":latest" tag): never another model under its name,
    # or queries and the index end up embedded by different models
    candidates = _embedding_model_candidates(model)

    for target_model in candidates:
        raw_emb = None
        # 1. Try modern Ollama /api/embed endpoint first
        try:
            embed_url = f"{target_host}/api/embed"
            payload_embed = json.dumps({"model": target_model, "input": prompt_text}).encode("utf-8")
            req_embed = urllib.request.Request(
                embed_url,
                data=payload_embed,
                headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-RAG-Engine/2.0"},
                method="POST",
            )
            with urllib.request.urlopen(req_embed, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    embs = data.get("embeddings")
                    if embs and isinstance(embs, list) and len(embs) > 0 and isinstance(embs[0], list):
                        raw_emb = embs[0]
        except Exception:
            logger.debug(
                "backend.services.rag_engine.compute_neural_embedding_via_ollama: ignored error", exc_info=True
            )

        # 2. Fall back to legacy /api/embeddings endpoint if /api/embed was unavailable
        if raw_emb is None:
            try:
                emb_url = f"{target_host}/api/embeddings"
                payload_legacy = json.dumps({"model": target_model, "prompt": prompt_text}).encode("utf-8")
                req_legacy = urllib.request.Request(
                    emb_url,
                    data=payload_legacy,
                    headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-RAG-Engine/2.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req_legacy, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        cand_emb = data.get("embedding")
                        if cand_emb and isinstance(cand_emb, list):
                            raw_emb = cand_emb
            except Exception:
                logger.debug(
                    "backend.services.rag_engine.compute_neural_embedding_via_ollama: ignored error", exc_info=True
                )

        if raw_emb:
            # L2 normalization
            norm = math.sqrt(sum(float(x) * float(x) for x in raw_emb))
            if norm > 0.0:
                norm_emb = [float(x) / norm for x in raw_emb]
            else:
                norm_emb = [float(x) for x in raw_emb]

            # Matryoshka Representation Learning (MRL) dimension truncation
            # EmbeddingGemma 2 supports dynamic truncation: 768 -> 512, 256, 128
            if target_dim and 0 < target_dim < len(norm_emb):
                norm_emb = truncate_and_normalize_mrl(norm_emb, target_dim)

            dim = len(norm_emb)
            blob = struct.pack(f"<{dim}f", *norm_emb)
            return blob, norm_emb

    return None


_EMBED_BREAKER = {"until": 0.0}  # after a failure, skip the embedder for a while (AI-15)
_EMBED_MODEL_SEEN: dict[str, str] = {}  # configured name -> name the runtime accepted
EMBED_BATCH_SIZE = 32


def _embedding_model_candidates(model: str) -> list[str]:
    """The configured model and, without a tag, its ":latest" tag. Nothing else: falling back
    to another model (EmbeddingGemma 1 for 2, say) silently mixes embedding spaces."""
    cands = [model]
    if ":" not in model.rsplit("/", 1)[-1]:
        cands.append(f"{model}:latest")
    return cands


def _pack_embedding(raw: list[float], target_dim: int | None) -> bytes:
    norm = math.sqrt(sum(float(x) * float(x) for x in raw))
    vec = [float(x) / norm for x in raw] if norm > 0.0 else [float(x) for x in raw]
    if target_dim and 0 < target_dim < len(vec):
        vec = truncate_and_normalize_mrl(vec, target_dim)
    return struct.pack(f"<{len(vec)}f", *vec)


def compute_neural_embeddings_batch(
    texts: list[str],
    model: str,
    target_dim: int | None = None,
    host: str | None = None,
    batch_size: int = EMBED_BATCH_SIZE,
) -> list[bytes] | None:
    """Embeds document texts with Ollama's /api/embed in batches (AI-15).

    All or nothing: returns one packed vector per text, or None if any batch failed, so a
    file is never stored with a mix of neural and lexical vectors. After a failure the
    embedder is skipped for 60 seconds instead of timing out on every file.
    """
    if not texts:
        return []
    if time.time() < _EMBED_BREAKER["until"]:
        return None
    target_host = _resolve_ollama_host(host)
    limit = 6000 if "embeddinggemma" in model.lower() else 4000
    clean = [(t or " ").strip()[:limit] or " " for t in texts]
    out: list[bytes] = []
    for start in range(0, len(clean), max(1, batch_size)):
        batch = clean[start : start + batch_size]
        embs = None
        for cand in _embedding_model_candidates(model):
            try:
                req = urllib.request.Request(
                    f"{target_host}/api/embed",
                    data=json.dumps({"model": cand, "input": batch}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-RAG-Engine/2.0"},
                    method="POST",
                )
                with urllib.request.urlopen(
                    req, timeout=15.0 + 4.0 * len(batch)
                ) as resp:  # a 2,048-token text takes ~3 s on an iGPU
                    data = json.loads(resp.read().decode("utf-8"))
                got = data.get("embeddings")
                if isinstance(got, list) and len(got) == len(batch) and all(isinstance(e, list) and e for e in got):
                    embs = got
                    _EMBED_MODEL_SEEN[model] = cand
                    break
            except urllib.error.HTTPError as e:
                if e.code == 404:  # unknown model name: try the next alias
                    continue
                break
            except Exception:
                break
        if embs is None:
            _EMBED_BREAKER["until"] = time.time() + 60.0
            logger.warning(
                f"[RAG] Embedding model '{model}' unavailable at {target_host}; using lexical vectors for now. "
                "Re-embed the index from AI settings once the model is back."
            )
            return None
        out.extend(_pack_embedding(e, target_dim) for e in embs)
    return out


QUERY_EMBED_TIMEOUT = 6.0
QUERY_VEC_CACHE_SIZE = 256
_QUERY_VEC_CACHE: dict[tuple, list[float]] = {}  # the same question twice costs one embedding


def compute_multimodal_query_embedding(
    query: str,
    model: str = "embeddinggemma",
    req_scenes: list[str] | None = None,
    req_colors: list[str] | None = None,
    ollama_host: str | None = None,
    target_dim: int | None = None,
    task_prompt: str | None = None,
) -> tuple[str, list[float]]:
    """
    Generates query vector embedding based on requested embedding_model.
    If a neural model (e.g. 'google/embeddinggemma-2', 'embeddinggemma', 'nomic-embed-text') is requested, queries Ollama,
    falling back to deterministic 384d lexical vector if Ollama is unreachable.
    Returns (effective_model_name, vector_list).
    """
    if model and model != "zett_lexical_384d":
        key = (model, target_dim, task_prompt or "", query)
        cached = _QUERY_VEC_CACHE.get(key)
        if cached is not None:
            return model, cached
        # A busy iGPU (chat or captioning running) can take seconds: wait longer and try once
        # more before falling back to keyword vectors (AI-4)
        res = None
        for timeout in (QUERY_EMBED_TIMEOUT, QUERY_EMBED_TIMEOUT):
            res = compute_neural_embedding_via_ollama(
                text=query,
                model=model,
                host=ollama_host,
                target_dim=target_dim,
                is_query=True,
                task_prompt=task_prompt,
                timeout=timeout,
            )
            if res is not None:
                break
        if res is not None:
            _, vec = res
            if len(_QUERY_VEC_CACHE) >= QUERY_VEC_CACHE_SIZE:
                _QUERY_VEC_CACHE.pop(next(iter(_QUERY_VEC_CACHE)))
            _QUERY_VEC_CACHE[key] = vec
            return model, vec

    req_scenes = req_scenes or []
    req_colors = req_colors or []
    _, vec = compute_384d_embedding(
        text=query or " ".join(req_scenes + req_colors),
        scene_tags=req_scenes,
        object_colors={c: 1.0 for c in req_colors},
        frame_colors={c: 0.8 for c in req_colors},
        color_hist_64=build_target_color_histogram(req_colors) if req_colors else None,
    )
    return "zett_lexical_384d", vec


_sumprod = getattr(math, "sumprod", None)  # Python 3.12+: dot product in C, extended precision
_TINY_NORM_SQ = 1e-280  # below this the squares may have underflowed; use the scaled path


def cosine_similarity_vec(v1: list[float], v2: list[float] | None) -> float:
    """
    Computes cosine similarity between two vectors with Matryoshka prefix truncation
    and robust scale handling against float overflow/underflow and NaN poisoning.

    Ordinary vectors take a C fast path; vectors with NaN/Inf, huge or tiny values fall
    back to the scaled computation, so every case returns what it always did.
    """
    if not v1 or not v2:
        return 0.0
    if _sumprod is not None:
        # Sums of squares over the whole vectors: NaN/Inf anywhere makes them non-finite.
        ss1 = _sumprod(v1, v1)
        ss2 = _sumprod(v2, v2)
        if math.isfinite(ss1) and math.isfinite(ss2):
            min_dim = min(len(v1), len(v2))
            a = v1 if len(v1) == min_dim else v1[:min_dim]
            b = v2 if len(v2) == min_dim else v2[:min_dim]
            n1 = ss1 if a is v1 else _sumprod(a, a)
            n2 = ss2 if b is v2 else _sumprod(b, b)
            if n1 > _TINY_NORM_SQ and n2 > _TINY_NORM_SQ:
                dot = _sumprod(a, b) / (math.sqrt(n1) * math.sqrt(n2))
                if math.isnan(dot):
                    return 0.0
                return max(0.0, min(1.0, dot))
    return _cosine_similarity_scaled(v1, v2)


def _cosine_similarity_scaled(v1: list[float], v2: list[float]) -> float:
    """Max-abs scaled cosine for vectors the fast path can't take (overflow, underflow, NaN)."""

    # Guard against NaN / Inf poisoning
    if any(math.isnan(x) or math.isinf(x) for x in v1) or any(math.isnan(x) or math.isinf(x) for x in v2):
        return 0.0

    min_dim = min(len(v1), len(v2))
    if min_dim <= 0:
        return 0.0

    sub_v1 = v1[:min_dim]
    sub_v2 = v2[:min_dim]

    max1 = max(abs(x) for x in sub_v1)
    max2 = max(abs(x) for x in sub_v2)
    if max1 <= 0.0 or max2 <= 0.0:
        return 0.0

    # Max-abs scaling prevents intermediate overflow (e.g. 1e160) and subnormal underflow
    scaled_v1 = [x / max1 for x in sub_v1]
    scaled_v2 = [x / max2 for x in sub_v2]

    norm1 = math.sqrt(sum(x * x for x in scaled_v1))
    norm2 = math.sqrt(sum(x * x for x in scaled_v2))
    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0

    dot = sum((a / norm1) * (b / norm2) for a, b in zip(scaled_v1, scaled_v2, strict=False))
    if math.isnan(dot):
        return 0.0

    return max(0.0, min(1.0, dot))

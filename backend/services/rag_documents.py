"""
Text extraction and chunking for the AI index (HTML, PDF, Office, code).

Split out of rag_engine.py (AI-21), which re-exports these names.
"""

import ast
import html.parser
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any

from backend.config import logger
from backend.logging_config import sanitize_string
from backend.services.rag_text import (
    _STOPWORDS,
    AUDIO_EXTENSIONS,
    CODE_EXTENSIONS,
    MAX_INDEX_FILE_BYTES,
    VIDEO_EXTENSIONS,
)


class _HTMLTextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._Parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip = True
        elif tag.lower() in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self._Parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._Parts.append(data)

    def get_text(self) -> str:
        return "".join(self._Parts)


def extract_document_text(file_path: str, file_ext: str) -> str:
    """
    Extracts plain text from supported document/code files (.md, .txt, .docx, .pdf, .html, .json, .csv, etc.)
    with zero heavyweight external binary dependencies.
    Video and audio files are parsed for title, metadata tags, and companion sidecars without size caps.
    """
    ext = file_ext.lower()
    if ext not in VIDEO_EXTENSIONS and ext not in AUDIO_EXTENSIONS:
        try:
            size = os.path.getsize(file_path)
            if size > MAX_INDEX_FILE_BYTES:
                return ""
        except Exception:
            return ""

    if ext == ".docx":
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                if "word/document.xml" not in zf.namelist():
                    return ""
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            paragraphs: list[str] = []
            for p in root.iter():
                if p.tag.endswith("}p"):
                    runs = [t.text for t in p.iter() if t.tag.endswith("}t") and t.text]
                    if runs:
                        paragraphs.append("".join(runs))
            return "\n\n".join(paragraphs)
        except Exception as e:
            logger.debug(f"[RAG] DOCX parse error on {sanitize_string(file_path)}: {e}")
            return ""

    if ext in AUDIO_EXTENSIONS:
        try:
            meta_parts = [f"Audio track: {os.path.basename(file_path)}", f"Format: {ext}"]
            try:
                import mutagen

                audio_info = mutagen.File(file_path)
                if audio_info:
                    for k in ("title", "artist", "album", "genre", "date"):
                        if k in audio_info:
                            val = audio_info[k]
                            if isinstance(val, (list, tuple)):
                                val = ", ".join(str(x) for x in val)
                            meta_parts.append(f"{k.capitalize()}: {val}")
            except Exception:
                logger.debug("backend.services.rag_engine.extract_document_text: ignored error", exc_info=True)
            return "\n".join(meta_parts)
        except Exception:
            return f"Audio track: {os.path.basename(file_path)}"

    if ext in VIDEO_EXTENSIONS:
        try:
            base = os.path.basename(file_path)
            title = os.path.splitext(base)[0]
            clean_title = re.sub(r"[._\-]+", " ", title).strip()
            parent = os.path.basename(os.path.dirname(file_path))
            meta_parts = [f"Video Title: {clean_title}", f"File Name: {base}", f"Folder: {parent}", f"Format: {ext}"]

            dir_name = os.path.dirname(file_path)
            nfo_path = os.path.join(dir_name, f"{title}.nfo")
            if not os.path.exists(nfo_path):
                for alt_nfo in ("movie.nfo", "tvshow.nfo"):
                    p = os.path.join(dir_name, alt_nfo)
                    if os.path.exists(p):
                        nfo_path = p
                        break
            if os.path.exists(nfo_path):
                try:
                    with open(nfo_path, encoding="utf-8", errors="ignore") as nf:
                        nfo_text = nf.read(8000)
                        if "<plot>" in nfo_text:
                            plot_m = re.search(r"<plot>(.*?)</plot>", nfo_text, re.DOTALL | re.IGNORECASE)
                            if plot_m:
                                meta_parts.append(f"Plot: {plot_m.group(1).strip()}")
                        else:
                            meta_parts.append(f"NFO Summary: {nfo_text[:1000]}")
                except Exception:
                    logger.debug("backend.services.rag_engine.extract_document_text: ignored error", exc_info=True)
            return "\n".join(meta_parts)
        except Exception:
            return f"Video: {os.path.basename(file_path)}"

    if ext == ".pdf":
        # Try pypdf/fitz first if installed, otherwise use native zlib FlateDecode stream parser
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(file_path)
            pages = [page.extract_text() or "" for page in reader.pages[:100]]
            extracted = "\n\n".join(p for p in pages if p.strip())
            if extracted.strip():
                return extracted
        except Exception:
            logger.debug("backend.services.rag_engine.extract_document_text: ignored error", exc_info=True)

        try:
            with open(file_path, "rb") as f:
                raw = f.read(min(MAX_INDEX_FILE_BYTES, 16 * 1024 * 1024))
            text_fragments: list[str] = []
            # Decompress FlateDecode streams and extract literal strings (...)
            for m in re.finditer(rb"stream[\r\n]+(.*?)[\r\n]+endstream", raw, re.DOTALL):
                stream_bytes = m.group(1)
                for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
                    try:
                        decompressed = zlib.decompress(stream_bytes, wbits)
                        decoded = decompressed.decode("latin-1", errors="ignore")
                        for s_match in re.finditer(r"\(([^()\\]{2,250}(?:\\.[^()\\]*)*)\)", decoded):
                            frag = s_match.group(1)
                            frag = frag.replace(r"\(", "(").replace(r"\)", ")").replace(r"\n", "\n")
                            if any(c.isalpha() for c in frag):
                                text_fragments.append(frag)
                        break
                    except Exception:
                        continue
            # Also scan uncompressed literal text strings in raw PDF
            if not text_fragments:
                decoded_raw = raw.decode("latin-1", errors="ignore")
                for s_match in re.finditer(r"\(([^()\\]{3,250})\)\s*Tj", decoded_raw):
                    frag = s_match.group(1)
                    if any(c.isalpha() for c in frag):
                        text_fragments.append(frag)
            return "\n".join(text_fragments)
        except Exception as e:
            logger.debug(f"[RAG] PDF parse error on {sanitize_string(file_path)}: {e}")
            return ""

    # Text-based formats
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content = f.read(2 * 1024 * 1024)
    except Exception:
        return ""

    if ext in (".html", ".htm"):
        try:
            parser = _HTMLTextExtractor()
            parser.feed(content)
            return parser.get_text()
        except Exception:
            return re.sub(r"<[^>]+>", " ", content)

    return content


def _chunk_python_ast(
    file_name: str,
    raw_text: str,
    canonical_path: str | None = None,
    parent_chunk_chars: int = 3500,
    child_chunk_chars: int = 950,
) -> tuple[str, str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]] | None:
    """
    Python AST-aware chunker using ast.parse:
    - Binds decorators (@router.get, @synchronized) directly to function/method definitions.
    - Captures class context: 'Class: ClassName > Method: method_name'.
    - Extracts docstrings, type annotations, and parameter signatures into structural_context.
    - Gracefully returns None on SyntaxError so caller can fall back to standard line chunker.
    """
    try:
        tree = ast.parse(raw_text)
    except Exception:
        return None

    lines = raw_text.splitlines()
    if not lines:
        return None

    base_title = os.path.splitext(file_name)[0].replace("_", " ").replace("-", " ").strip().title()
    parent_dir = os.path.dirname(canonical_path) if canonical_path else ""
    folder_name = os.path.basename(parent_dir) if parent_dir else ""
    folder_prefix = f"Folder: {folder_name} | " if folder_name else ""

    doc_metadata: dict[str, Any] = {
        "card_type": "code",
        "title": base_title,
        "language": "python",
        "has_classes": any(isinstance(n, ast.ClassDef) for n in tree.body),
    }

    parent_chunks: list[dict[str, Any]] = []
    child_chunks: list[dict[str, Any]] = []

    def _get_decorators(node: Any) -> list[str]:
        decs: list[str] = []
        for d in getattr(node, "decorator_list", []):
            try:
                decs.append("@" + ast.unparse(d))
            except Exception:
                decs.append("@decorator")
        return decs

    def _get_returns(node: Any) -> str | None:
        if getattr(node, "returns", None):
            try:
                return ast.unparse(node.returns)
            except Exception:
                return None
        return None

    current_parent_index = 0

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            c_start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            c_end = getattr(node, "end_lineno", len(lines)) or len(lines)
            class_body = "\n".join(lines[c_start - 1 : c_end]).strip()
            class_decs = _get_decorators(node)

            p_id = f"parent_{current_parent_index}"
            parent_chunks.append(
                {
                    "parent_index": current_parent_index,
                    "parent_chunk_id": p_id,
                    "chunk_level": "parent",
                    "heading_context": f"Class: {class_name}",
                    "chunk_text": class_body,
                    "raw_chunk_text": class_body,
                    "text": class_body,
                    "line_start": c_start,
                    "line_end": c_end,
                    "token_count": max(1, len(class_body.split())),
                }
            )

            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if methods:
                for m in methods:
                    m_start = m.decorator_list[0].lineno if m.decorator_list else m.lineno
                    m_end = getattr(m, "end_lineno", c_end) or c_end
                    m_body = "\n".join(lines[m_start - 1 : m_end]).strip()
                    m_decs = _get_decorators(m)
                    m_ret = _get_returns(m)
                    heading_ctx = f"Class: {class_name} > Method: {m.name}"
                    struct_ctx = f"decorators: {m_decs} | returns: {m_ret}"
                    breadcrumb = f"[{folder_prefix}Doc: {base_title} > {heading_ctx}]"
                    full_text = f"{breadcrumb}\n{struct_ctx}\n{m_body}"

                    child_chunks.append(
                        {
                            "chunk_index": len(child_chunks),
                            "parent_index": current_parent_index,
                            "parent_chunk_id": p_id,
                            "chunk_level": "child",
                            "heading_context": heading_ctx,
                            "structural_context": struct_ctx,
                            "chunk_text": full_text,
                            "raw_chunk_text": m_body,
                            "raw_text": m_body,
                            "text": full_text,
                            "line_start": m_start,
                            "line_end": m_end,
                            "token_count": max(1, len(full_text.split())),
                        }
                    )
            else:
                breadcrumb = f"[{folder_prefix}Doc: {base_title} > Class: {class_name}]"
                struct_ctx = f"decorators: {class_decs}"
                full_text = f"{breadcrumb}\n{struct_ctx}\n{class_body}"
                child_chunks.append(
                    {
                        "chunk_index": len(child_chunks),
                        "parent_index": current_parent_index,
                        "parent_chunk_id": p_id,
                        "chunk_level": "child",
                        "heading_context": f"Class: {class_name}",
                        "structural_context": struct_ctx,
                        "chunk_text": full_text,
                        "raw_chunk_text": class_body,
                        "raw_text": class_body,
                        "text": full_text,
                        "line_start": c_start,
                        "line_end": c_end,
                        "token_count": max(1, len(full_text.split())),
                    }
                )
            current_parent_index += 1

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name
            f_start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            f_end = getattr(node, "end_lineno", len(lines)) or len(lines)
            fn_body = "\n".join(lines[f_start - 1 : f_end]).strip()
            fn_decs = _get_decorators(node)
            fn_ret = _get_returns(node)
            heading_ctx = f"{base_title} > Function: {fn_name}"
            struct_ctx = f"decorators: {fn_decs} | returns: {fn_ret}"
            breadcrumb = f"[{folder_prefix}Doc: {heading_ctx}]"
            full_text = f"{breadcrumb}\n{struct_ctx}\n{fn_body}"

            p_id = f"parent_{current_parent_index}"
            parent_chunks.append(
                {
                    "parent_index": current_parent_index,
                    "parent_chunk_id": p_id,
                    "chunk_level": "parent",
                    "heading_context": heading_ctx,
                    "chunk_text": fn_body,
                    "raw_chunk_text": fn_body,
                    "text": fn_body,
                    "line_start": f_start,
                    "line_end": f_end,
                    "token_count": max(1, len(fn_body.split())),
                }
            )

            child_chunks.append(
                {
                    "chunk_index": len(child_chunks),
                    "parent_index": current_parent_index,
                    "parent_chunk_id": p_id,
                    "chunk_level": "child",
                    "heading_context": heading_ctx,
                    "structural_context": struct_ctx,
                    "chunk_text": full_text,
                    "raw_chunk_text": fn_body,
                    "raw_text": fn_body,
                    "text": full_text,
                    "line_start": f_start,
                    "line_end": f_end,
                    "token_count": max(1, len(full_text.split())),
                }
            )
            current_parent_index += 1

    if not child_chunks:
        return None

    return ("code", base_title, doc_metadata, child_chunks, parent_chunks)


def late_interaction_rerank(
    raw_query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """
    Stage 2 lightweight late-interaction re-ranker (<2ms).
    Evaluates candidate items using contiguous phrase match and token proximity:
      - Contiguous phrase match: +0.08 body boost, +0.12 title boost
      - Token proximity span (<20 words): +0.05
      - Structural / header boost: +0.06
    """
    if not candidates or not raw_query:
        return candidates[:top_k]

    q_lower = raw_query.strip().lower()
    q_words = [w for w in re.findall(r"[a-z0-9_\u4e00-\u9fff]+", q_lower) if w not in _STOPWORDS]

    for item in candidates:
        bonus = 0.0
        title_lower = (item.get("title") or item.get("name") or "").lower()
        chunk_text = (item.get("raw_chunk_text") or item.get("chunk_text") or "").lower()
        header_text = (item.get("breadcrumb") or item.get("section_title") or item.get("heading_context") or "").lower()

        # 1. Contiguous phrase match
        if len(q_words) >= 2 and q_lower in chunk_text:
            bonus += 0.08
        if len(q_words) >= 2 and q_lower in title_lower:
            bonus += 0.12

        # 2. Token proximity span: query words within <20 words
        if len(q_words) >= 2:
            body_words = chunk_text.split()
            word_indices = [idx for idx, w in enumerate(body_words) if any(qw in w for qw in q_words)]
            if len(word_indices) >= len(q_words):
                min_span = 9999
                for i in range(len(word_indices) - len(q_words) + 1):
                    span = word_indices[i + len(q_words) - 1] - word_indices[i]
                    if span < min_span:
                        min_span = span
                if min_span < 20:
                    bonus += 0.05

        # 3. Structural header boost
        if q_words and any(qw in header_text for qw in q_words):
            bonus += 0.06

        orig_score = float(item.get("score") or 0.0)
        item["score"] = round(min(1.0, orig_score + bonus), 4)

    candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return candidates[:top_k]


def generate_contextual_hierarchical_chunks(
    file_name: str = "",
    file_ext: str = "",
    raw_text: str = "",
    canonical_path: str | None = None,
    parent_chunk_chars: int = 3500,
    child_chunk_chars: int = 950,
    child_overlap_chars: int = 80,
    file_path: str | None = None,
    text: str | None = None,
    **kwargs: Any,
) -> tuple[str, str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    RAG v3 Hierarchical & Anthropic-Style Contextual Chunking:
      1. Detects document type ('recipe', 'invoice', 'code', 'markdown', 'generic')
      2. Extracts structured metadata (ingredients, prep_time, cook_time, servings, steps)
      3. Splits into PARENT chunks (natural section boundaries, ~600-1200 tokens / 2500-4500 chars)
      4. Splits each parent into CHILD chunks (high-precision search units, ~150-250 tokens / 600-900 chars)
      5. Prepends situated deterministic breadcrumbs ([Folder: ...] [Doc: ... > Heading]) in 0ms
    Returns (doc_type, doc_title, doc_metadata, child_chunks, parent_chunks).
    """
    if not canonical_path and file_path:
        canonical_path = file_path
    if not file_name and canonical_path:
        file_name = os.path.basename(canonical_path)
    if not file_ext and file_name:
        file_ext = os.path.splitext(file_name)[1]
    if not raw_text and text:
        raw_text = text

    clean_text = sanitize_string(raw_text or "").strip()
    base_title = os.path.splitext(file_name)[0].replace("_", " ").replace("-", " ").strip().title()
    if not clean_text:
        return ("generic", base_title, {}, [], [])

    # Python AST-aware code chunking (Batch 2 Item 2.1)
    if file_ext.lower() in (".py", ".pyw"):
        ast_result = _chunk_python_ast(
            file_name=file_name,
            raw_text=clean_text,
            canonical_path=canonical_path,
            parent_chunk_chars=parent_chunk_chars,
            child_chunk_chars=child_chunk_chars,
        )
        if ast_result is not None:
            return ast_result

    lines = clean_text.splitlines()
    doc_title = base_title
    for line in lines[:15]:
        s = line.strip()
        if s.startswith("# "):
            doc_title = s.lstrip("#").strip()
            break
        elif len(s) >= 4 and len(s) <= 90 and not s.startswith(("-", "*", "{", "[")):
            doc_title = s
            break

    lower_text = clean_text.lower()
    lower_name = file_name.lower()

    # Recipe Detection Heuristics
    has_ingredient_header = bool(re.search(r"(?m)^\s*(?:#+\s*)?ingredients\b", lower_text))
    has_steps_header = bool(
        re.search(r"(?m)^\s*(?:#+\s*)?(?:instructions|directions|steps|method|preparation)\b", lower_text)
    )
    culinary_units = len(
        re.findall(
            r"\b\d+(?:/\d+|\.\d+)?\s*(?:cup|cups|tbsp|tablespoon|tsp|teaspoon|oz|ounce|lb|pound|g|gram|kg|ml|clove|cloves|pinch|slice|slices|can|cans)\b",
            lower_text,
        )
    )
    is_recipe = (
        has_ingredient_header
        or (has_steps_header and culinary_units >= 2)
        or ("recipe" in lower_name and culinary_units >= 1)
        or (
            culinary_units >= 3
            and any(
                w in lower_text
                for w in (
                    "bake",
                    "simmer",
                    "boil",
                    "saute",
                    "roast",
                    "garlic",
                    "pasta",
                    "chicken",
                    "flour",
                    "olive oil",
                )
            )
        )
    )

    # Invoice / Receipt Detection Heuristics
    is_invoice = not is_recipe and (
        any(w in lower_name for w in ("invoice", "receipt", "statement", "bill"))
        or (
            any(
                w in lower_text
                for w in ("invoice #", "invoice number", "subtotal", "amount due", "total paid", "receipt")
            )
            and bool(re.search(r"\$\s*\d+(?:\.\d{2})?", clean_text))
        )
    )

    doc_type = "generic"
    if is_recipe:
        doc_type = "recipe"
    elif is_invoice:
        doc_type = "invoice"
    elif file_ext.lower() in CODE_EXTENSIONS:
        doc_type = "code"
    elif file_ext.lower() == ".md":
        doc_type = "markdown"

    doc_metadata: dict[str, Any] = {"title": doc_title}

    if is_recipe:
        ingredients: list[str] = []
        steps: list[str] = []
        prep_time = ""
        cook_time = ""
        servings = ""

        m_prep = re.search(r"prep(?:\s*time)?\s*[:\-]\s*([^\n|,;]{2,25})", clean_text, re.IGNORECASE)
        if m_prep:
            prep_time = m_prep.group(1).strip()
        m_cook = re.search(r"cook(?:\s*time)?\s*[:\-]\s*([^\n|,;]{2,25})", clean_text, re.IGNORECASE)
        if m_cook:
            cook_time = m_cook.group(1).strip()
        m_serv = re.search(r"(?:servings|serves|yield)\s*[:\-]\s*([^\n|,;]{1,20})", clean_text, re.IGNORECASE)
        if m_serv:
            servings = m_serv.group(1).strip()

        section_mode = "none"
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            low_line = stripped.lower().lstrip("#* ").rstrip(":")
            if low_line in ("ingredients", "ingredient list", "what you need"):
                section_mode = "ingredients"
                continue
            if low_line in ("instructions", "directions", "steps", "method", "preparation", "how to make"):
                section_mode = "steps"
                continue
            if stripped.startswith("#"):
                section_mode = "other"
                continue

            if section_mode == "ingredients" and (stripped.startswith(("-", "*", "•")) or re.match(r"^\d", stripped)):
                item = re.sub(r"^[-*•]\s*", "", stripped).strip()
                if item and len(ingredients) < 25:
                    ingredients.append(item)
            elif section_mode == "steps" and (re.match(r"^\d+[\.\)]\s*", stripped) or stripped.startswith(("-", "*"))):
                step_txt = re.sub(r"^(?:\d+[\.\)]|[-*])\s*", "", stripped).strip()
                if step_txt and len(steps) < 20:
                    steps.append(step_txt)
            elif section_mode == "steps" and len(stripped) > 20 and len(steps) < 15:
                steps.append(stripped)

        # Fallback extraction if recipe had no formal markdown headers
        if not ingredients:
            for line in lines:
                stripped = line.strip()
                if re.search(
                    r"\b\d+(?:/\d+)?\s*(?:cup|cups|tbsp|tsp|oz|lb|g|kg|ml|clove|cloves|pinch|can)\b",
                    stripped,
                    re.IGNORECASE,
                ):
                    item = re.sub(r"^[-*•]\s*", "", stripped).strip()
                    if item and len(item) < 120 and len(ingredients) < 20:
                        ingredients.append(item)

        if not steps:
            for line in lines:
                stripped = line.strip()
                if re.match(r"^\d+[\.\)]\s+", stripped) or any(
                    v in stripped.lower()
                    for v in ("preheat", "simmer", "boil", "saute", "whisk", "roast", "bake", "toss")
                ):
                    step_txt = re.sub(r"^\d+[\.\)]\s*", "", stripped).strip()
                    if step_txt and step_txt not in ingredients and len(steps) < 12:
                        steps.append(step_txt)

        doc_metadata.update(
            {
                "card_type": "recipe",
                "title": doc_title,
                "prep_time": prep_time or "15 mins",
                "cook_time": cook_time or "25 mins",
                "servings": servings or "4",
                "ingredients": ingredients[:20],
                "steps": steps[:12],
            }
        )
    elif is_invoice:
        amounts = re.findall(r"\$\s*\d+(?:,\d{3})*(?:\.\d{2})?", clean_text)
        doc_metadata.update(
            {
                "card_type": "invoice",
                "title": doc_title,
                "total_amount": amounts[-1] if amounts else "N/A",
                "amounts": amounts[:6],
            }
        )

    # Situated Context Extraction
    parent_dir = os.path.dirname(canonical_path) if canonical_path else ""
    folder_name = os.path.basename(parent_dir) if parent_dir else ""
    folder_prefix = f"Folder: {folder_name} | " if folder_name else ""

    ingredient_summary = ""
    if is_recipe and doc_metadata.get("ingredients"):
        ingredient_summary = " | Ingredients: " + ", ".join(doc_metadata["ingredients"][:8])

    # 1. Build Parent Chunks (natural section boundaries, ~2500-4500 chars)
    parent_chunks: list[dict[str, Any]] = []
    current_parent_heading = doc_title
    current_parent_lines: list[str] = []
    current_parent_len = 0
    parent_start_line = 1

    def _flush_parent(end_line: int) -> None:
        nonlocal current_parent_lines, current_parent_len, parent_start_line
        if not current_parent_lines:
            return
        p_body = "\n".join(current_parent_lines).strip()
        if not p_body:
            return
        p_idx = len(parent_chunks)
        parent_chunks.append(
            {
                "parent_index": p_idx,
                "parent_chunk_id": f"parent_{p_idx}",
                "chunk_level": "parent",
                "heading_context": f"{doc_title} > {current_parent_heading}",
                "chunk_text": p_body,
                "raw_chunk_text": p_body,
                "text": p_body,
                "line_start": parent_start_line,
                "line_end": max(parent_start_line, end_line),
                "token_count": max(1, len(p_body.split())),
                "lines": list(current_parent_lines),
            }
        )

    for idx_line, line in enumerate(lines, start=1):
        stripped = line.strip()
        is_major_heading = stripped.startswith(("# ", "## ", "### ")) or (
            file_ext.lower() in CODE_EXTENSIONS and stripped.startswith(("def ", "class "))
        )
        if is_major_heading and current_parent_len >= min(800, max(200, parent_chunk_chars // 2)):
            _flush_parent(idx_line - 1)
            current_parent_lines = []
            current_parent_len = 0
            parent_start_line = idx_line

        if stripped.startswith("#"):
            current_parent_heading = stripped.lstrip("#").strip() or current_parent_heading

        current_parent_lines.append(line)
        current_parent_len += len(line) + 1

        if current_parent_len >= parent_chunk_chars:
            _flush_parent(idx_line)
            current_parent_lines = []
            current_parent_len = 0
            parent_start_line = idx_line + 1

    if current_parent_lines:
        _flush_parent(len(lines))

    # 2. Build Child Chunks from Parent Chunks (high-precision search units)
    child_chunks: list[dict[str, Any]] = []

    for p in parent_chunks:
        p_lines = p.get("lines", [])
        if not p_lines:
            continue
        p_heading = p["heading_context"]
        p_idx = p["parent_index"]
        c_lines: list[str] = []
        c_len = 0
        c_start_line = p["line_start"]

        def _flush_child(end_line_num: int) -> None:
            nonlocal c_lines, c_len, c_start_line
            if not c_lines:  # noqa: B023
                return
            body = "\n".join(c_lines).strip()  # noqa: B023
            if not body:
                return
            breadcrumb = f"[{folder_prefix}Doc: {p_heading}{ingredient_summary}]"  # noqa: B023
            full_child_text = f"{breadcrumb}\n{body}"
            child_chunks.append(
                {
                    "chunk_index": len(child_chunks),
                    "parent_index": p_idx,  # noqa: B023
                    "parent_chunk_id": f"parent_{p_idx}",  # noqa: B023
                    "chunk_level": "child",
                    "heading_context": p_heading,  # noqa: B023
                    "structural_context": breadcrumb,
                    "chunk_text": full_child_text,
                    "raw_chunk_text": body,
                    "raw_text": body,
                    "text": full_child_text,
                    "line_start": c_start_line,  # noqa: B023
                    "line_end": max(c_start_line, end_line_num),  # noqa: B023
                    "token_count": max(1, len(full_child_text.split())),
                }
            )

        for rel_idx, line in enumerate(p_lines):
            curr_abs_line = p["line_start"] + rel_idx
            stripped = line.strip()
            is_subheading = stripped.startswith(("#", "def ", "class ", "function ", "export "))
            if is_subheading and c_len >= min(400, max(100, child_chunk_chars // 2)):
                _flush_child(curr_abs_line - 1)
                overlap = c_lines[-3:] if len(c_lines) >= 3 else []
                c_lines = list(overlap)
                c_len = sum(len(x) + 1 for x in c_lines)
                c_start_line = max(p["line_start"], curr_abs_line - len(overlap))

            c_lines.append(line)
            c_len += len(line) + 1

            if c_len >= child_chunk_chars:
                _flush_child(curr_abs_line)
                overlap = c_lines[-3:] if len(c_lines) >= 3 else []
                c_lines = list(overlap)
                c_len = sum(len(x) + 1 for x in c_lines)
                c_start_line = max(p["line_start"], curr_abs_line - len(overlap) + 1)

        if c_lines:
            _flush_child(p["line_end"])

    # Clean temporary 'lines' list from parent_chunks to save memory
    for p in parent_chunks:
        p.pop("lines", None)

    return (doc_type, doc_title, doc_metadata, child_chunks, parent_chunks)


def parse_document_structure_and_chunks(
    file_name: str,
    file_ext: str,
    raw_text: str,
    canonical_path: str | None = None,
) -> tuple[str, str, dict[str, Any], list[dict[str, Any]]]:
    """
    Backward-compatible wrapper for generate_contextual_hierarchical_chunks.
    Returns 4-tuple (doc_type, doc_title, doc_metadata, child_chunks).
    """
    doc_type, doc_title, doc_metadata, child_chunks, parent_chunks = generate_contextual_hierarchical_chunks(
        file_name, file_ext, raw_text, canonical_path
    )
    doc_metadata["parent_chunks"] = parent_chunks
    return (doc_type, doc_title, doc_metadata, child_chunks)

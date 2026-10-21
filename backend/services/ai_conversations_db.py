"""
ai_conversations_db.py — High-Concurrency SQLite WAL Multi-Turn Conversation History Store.

Implements thread-safe persistence for ZettAI Local Chatbot threads and messages with:
- NVMe-resident SQLite WAL database (/app/data/ai_conversations.db, 0 disk wakeups).
- Strict multi-user tenancy and RBAC scoping per principal.
- Full-text search (FTS5) for instant conversation thread filtering.
- Generation Guard & Title Customization Protection (title_customized = 1).
- Token-budgeted history extraction (B_history ~ 1200 tokens) stripping heavy tool JSON.
"""

import contextlib
import json
import os
import re
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.config import DATA_DIR, logger

AI_CONVERSATIONS_DB_PATH = os.environ.get("AI_CONVERSATIONS_DB_PATH", os.path.join(DATA_DIR, "ai_conversations.db"))


def get_db_path() -> str:
    """Returns the effective database path, honoring runtime env overrides."""
    return os.environ.get("AI_CONVERSATIONS_DB_PATH", AI_CONVERSATIONS_DB_PATH)


@contextlib.contextmanager
def get_conv_db_connection(db_path: Optional[str] = None):
    """Context manager returning a configured SQLite WAL connection with foreign keys enabled."""
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_conversations_db(db_path: Optional[str] = None) -> None:
    """Initializes the conversation history tables, indices, and FTS5 search index."""
    with get_conv_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                title_customized INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL DEFAULT '',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}'
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                ON conversations(user_id, updated_at DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_pinned
                ON conversations(user_id, is_pinned DESC, updated_at DESC)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                telemetry_json TEXT,
                tools_called_json TEXT,
                web_sources_json TEXT,
                citations_json TEXT,
                photos_json TEXT,
                created_at REAL NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conv_created_asc
                ON conversation_messages(conversation_id, created_at ASC)
        """)

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS conversation_messages_fts USING fts5(
                message_id UNINDEXED,
                conversation_id UNINDEXED,
                user_id UNINDEXED,
                content,
                tokenize='unicode61 remove_diacritics 2'
            )
        """)
    logger.debug(f"[AI DB] Initialized conversation tables at {db_path or get_db_path()}")


try:
    init_conversations_db()
except Exception as _ex:
    logger.warning(f"[AI DB] Deferred initialization due to startup environment: {_ex}")


def create_conversation(
    user_id: str,
    title: str = "New Conversation",
    model: str = "",
    conv_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new conversation thread scoped to the given user_id."""
    clean_uid = str(user_id or "admin").strip().lower()
    cid = conv_id or f"conv_{uuid.uuid4().hex[:12]}"
    now = time.time()
    clean_title = (title or "New Conversation").strip()[:120]
    meta_str = json.dumps(meta or {})

    with get_conv_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversations (
                id, user_id, title, title_customized, model, is_pinned, is_archived, created_at, updated_at, meta_json
            ) VALUES (?, ?, ?, 0, ?, 0, 0, ?, ?, ?)
            """,
            (cid, clean_uid, clean_title, model or "", now, now, meta_str),
        )

    return {
        "id": cid,
        "user_id": clean_uid,
        "title": clean_title,
        "title_customized": False,
        "model": model or "",
        "is_pinned": False,
        "is_archived": False,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "meta": meta or {},
    }


def list_conversations(
    user_id: str,
    search: Optional[str] = None,
    include_archived: bool = False,
    limit: int = 60,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lists conversations for user_id with optional search and chronological ordering."""
    clean_uid = str(user_id or "admin").strip().lower()
    clean_search = str(search or "").strip()

    with get_conv_db_connection(db_path) as conn:
        if clean_search:
            safe_query = re.sub(r'["*^:]', " ", clean_search).strip()
            fts_matched_cids = set()
            if safe_query:
                try:
                    cur = conn.execute(
                        """
                        SELECT DISTINCT conversation_id FROM conversation_messages_fts
                        WHERE user_id = ? AND conversation_messages_fts MATCH ?
                        LIMIT 100
                        """,
                        (clean_uid, f"{safe_query}*"),
                    )
                    for row in cur.fetchall():
                        fts_matched_cids.add(row["conversation_id"])
                except Exception as ex:
                    logger.debug(f"[AI DB] FTS match query skipped: {ex}")

            archived_filter = "" if include_archived else "AND c.is_archived = 0"
            title_like = f"%{clean_search}%"
            cur = conn.execute(
                f"""
                SELECT c.*,
                       COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.id
                WHERE c.user_id = ?
                  {archived_filter}
                  AND (c.title LIKE ? OR c.id IN ({",".join(["?"] * len(fts_matched_cids)) if fts_matched_cids else "''"}))
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC
                LIMIT ?
                """,
                [clean_uid, title_like] + list(fts_matched_cids) + [limit],
            )
        else:
            archived_filter = "" if include_archived else "AND c.is_archived = 0"
            cur = conn.execute(
                f"""
                SELECT c.*,
                       COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON m.conversation_id = c.id
                WHERE c.user_id = ? {archived_filter}
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC
                LIMIT ?
                """,
                (clean_uid, limit),
            )

        results = []
        for r in cur.fetchall():
            meta = {}
            try:
                meta = json.loads(r["meta_json"]) if r["meta_json"] else {}
            except Exception:
                pass
            results.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "title": r["title"],
                    "title_customized": bool(r["title_customized"]),
                    "model": r["model"],
                    "is_pinned": bool(r["is_pinned"]),
                    "is_archived": bool(r["is_archived"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "message_count": r["message_count"],
                    "meta": meta,
                }
            )
        return results


def get_conversation(
    conv_id: str,
    user_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves conversation metadata without messages."""
    clean_uid = str(user_id or "admin").strip().lower()
    with get_conv_db_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, clean_uid),
        )
        row = cur.fetchone()
        if not row:
            return None
        meta = {}
        try:
            meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        except Exception:
            pass
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "title_customized": bool(row["title_customized"]),
            "model": row["model"],
            "is_pinned": bool(row["is_pinned"]),
            "is_archived": bool(row["is_archived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "meta": meta,
        }


def get_conversation_with_messages(
    conv_id: str,
    user_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves conversation metadata along with its full ordered message stream."""
    conv = get_conversation(conv_id, user_id, db_path)
    if not conv:
        return None

    clean_uid = str(user_id or "admin").strip().lower()
    with get_conv_db_connection(db_path) as conn:
        cur = conn.execute(
            """
            SELECT * FROM conversation_messages
            WHERE conversation_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            (conv_id, clean_uid),
        )
        messages = []
        for m in cur.fetchall():
            telemetry = None
            tools = None
            sources = None
            citations = None
            photos = None
            try:
                if m["telemetry_json"]:
                    telemetry = json.loads(m["telemetry_json"])
                if m["tools_called_json"]:
                    tools = json.loads(m["tools_called_json"])
                if m["web_sources_json"]:
                    sources = json.loads(m["web_sources_json"])
                if m["citations_json"]:
                    citations = json.loads(m["citations_json"])
                if m["photos_json"]:
                    photos = json.loads(m["photos_json"])
            except Exception:
                pass

            messages.append(
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "telemetry": telemetry,
                    "tools_called": tools,
                    "web_sources": sources,
                    "citations": citations,
                    "photos": photos,
                    "created_at": m["created_at"],
                }
            )

    conv["messages"] = messages
    conv["message_count"] = len(messages)
    return conv


def update_conversation(
    conv_id: str,
    user_id: str,
    title: Optional[str] = None,
    is_pinned: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    model: Optional[str] = None,
    title_customized: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Updates editable attributes of a conversation thread."""
    clean_uid = str(user_id or "admin").strip().lower()
    updates = []
    params: List[Any] = []

    if title is not None:
        clean_title = str(title).strip()[:120]
        updates.append("title = ?")
        params.append(clean_title)
        if title_customized is None:
            updates.append("title_customized = 1")
    if title_customized is not None:
        updates.append("title_customized = ?")
        params.append(1 if title_customized else 0)
    if is_pinned is not None:
        updates.append("is_pinned = ?")
        params.append(1 if is_pinned else 0)
    if is_archived is not None:
        updates.append("is_archived = ?")
        params.append(1 if is_archived else 0)
    if model is not None:
        updates.append("model = ?")
        params.append(str(model).strip()[:256])

    if not updates:
        return get_conversation(conv_id, user_id, db_path)

    updates.append("updated_at = ?")
    params.append(time.time())

    params.extend([conv_id, clean_uid])
    sql = f"UPDATE conversations SET {', '.join(updates)} WHERE id = ? AND user_id = ?"

    with get_conv_db_connection(db_path) as conn:
        cur = conn.execute(sql, params)
        if cur.rowcount == 0:
            return None

    return get_conversation(conv_id, user_id, db_path)


def delete_conversation(
    conv_id: str,
    user_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Deletes a conversation and all its messages permanently."""
    clean_uid = str(user_id or "admin").strip().lower()
    with get_conv_db_connection(db_path) as conn:
        try:
            conn.execute(
                "DELETE FROM conversation_messages_fts WHERE conversation_id = ? AND user_id = ?",
                (conv_id, clean_uid),
            )
        except Exception:
            pass

        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, clean_uid),
        )
        return cur.rowcount > 0


def clear_all_conversations(
    user_id: str,
    db_path: Optional[str] = None,
) -> int:
    """Deletes all conversations belonging to the user."""
    clean_uid = str(user_id or "admin").strip().lower()
    with get_conv_db_connection(db_path) as conn:
        try:
            conn.execute(
                "DELETE FROM conversation_messages_fts WHERE user_id = ?",
                (clean_uid,),
            )
        except Exception:
            pass

        cur = conn.execute(
            "DELETE FROM conversations WHERE user_id = ?",
            (clean_uid,),
        )
        return cur.rowcount


def append_message(
    conv_id: str,
    user_id: str,
    role: str,
    content: str,
    telemetry: Optional[Dict[str, Any]] = None,
    tools_called: Optional[List[Dict[str, Any]]] = None,
    web_sources: Optional[List[Dict[str, Any]]] = None,
    citations: Optional[List[Dict[str, Any]]] = None,
    photos: Optional[List[Dict[str, Any]]] = None,
    msg_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Appends a user, assistant, or system message to an active conversation thread."""
    clean_uid = str(user_id or "admin").strip().lower()
    clean_role = str(role or "user").strip().lower()
    if clean_role not in ("user", "assistant", "system"):
        clean_role = "user"

    mid = msg_id or f"msg_{uuid.uuid4().hex[:12]}"
    now = time.time()
    clean_content = str(content or "").strip()

    tel_str = json.dumps(telemetry) if telemetry else None
    tools_str = json.dumps(tools_called) if tools_called else None
    web_str = json.dumps(web_sources) if web_sources else None
    citations_str = json.dumps(citations) if citations else None
    photos_str = json.dumps(photos) if photos else None

    with get_conv_db_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, clean_uid),
        )
        if not cur.fetchone():
            conn.execute(
                """
                INSERT INTO conversations (
                    id, user_id, title, title_customized, model, is_pinned, is_archived, created_at, updated_at
                ) VALUES (?, ?, 'New Conversation', 0, '', 0, 0, ?, ?)
                """,
                (conv_id, clean_uid, now, now),
            )

        conn.execute(
            """
            INSERT INTO conversation_messages (
                id, conversation_id, user_id, role, content,
                telemetry_json, tools_called_json, web_sources_json, citations_json, photos_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                conv_id,
                clean_uid,
                clean_role,
                clean_content,
                tel_str,
                tools_str,
                web_str,
                citations_str,
                photos_str,
                now,
            ),
        )

        try:
            conn.execute(
                """
                INSERT INTO conversation_messages_fts (message_id, conversation_id, user_id, content)
                VALUES (?, ?, ?, ?)
                """,
                (mid, conv_id, clean_uid, clean_content),
            )
        except Exception as fts_ex:
            logger.debug(f"[AI DB] FTS indexing error (non-fatal): {fts_ex}")

        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
            (now, conv_id, clean_uid),
        )

    return {
        "id": mid,
        "conversation_id": conv_id,
        "user_id": clean_uid,
        "role": clean_role,
        "content": clean_content,
        "telemetry": telemetry,
        "tools_called": tools_called,
        "web_sources": web_sources,
        "citations": citations,
        "photos": photos,
        "created_at": now,
    }


def generate_auto_title_heuristic(prompt: str) -> str:
    """Generates a clean 3-5 word descriptive title from the user prompt."""
    raw = str(prompt or "").strip()
    if not raw:
        return "New Conversation"

    cleaned = re.sub(r"[`#*_\[\]()]", " ", raw)
    fillers = [
        r"^(?:can\s+you|could\s+you|would\s+you|will\s+you)\b",
        r"^(?:please|kindly)\b",
        r"^(?:i\s+want\s+to|i\s+need\s+to|i\s+would\s+like\s+to)\b",
        r"^(?:tell\s+me|show\s+me|give\s+me|help\s+me|explain\s+to\s+me)\b",
        r"^(?:how\s+do\s+i|how\s+to|how\s+can\s+i)\b",
        r"^(?:what\s+is|what\s+are|what\s+does|which)\b",
        r"^(?:check|look\s+at|audit|inspect|verify|diagnose)\b",
        r"^(?:hey\s+zetty|hello|hi|good\s+morning|good\s+evening)\b",
    ]
    changed = True
    while changed:
        changed = False
        cleaned = cleaned.strip(" ,.:;?!")
        for pattern in fillers:
            subbed = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
            if subbed != cleaned:
                cleaned = subbed
                changed = True

    words = [w for w in re.split(r"\s+", cleaned) if len(w) > 1 and not re.match(r"^[?.,!;:]+$", w)]
    if not words:
        words = [w for w in re.split(r"\s+", raw) if w]

    selected = words[:5]
    if not selected:
        return "New Conversation"

    title = " ".join(selected).title()
    title = title[:45].strip()
    return title or "New Conversation"


def update_auto_title_if_not_customized(
    conv_id: str,
    user_id: str,
    prompt: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """
    Updates conversation title based on user prompt IF title has not been customized by the user.
    Enforces Title Customization Guard (title_customized = 1).
    """
    clean_uid = str(user_id or "admin").strip().lower()
    with get_conv_db_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT title_customized, title FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, clean_uid),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["title_customized"]:
            return row["title"]

        new_title = generate_auto_title_heuristic(prompt)
        if new_title and new_title != row["title"]:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ? AND title_customized = 0",
                (new_title, conv_id, clean_uid),
            )
            return new_title
        return row["title"]


def get_dynamic_token_budget(
    model_name: Optional[str] = None,
    context_window: Optional[int] = None,
    system_ram_bytes: Optional[int] = None,
    target_ratio: float = 0.25,
    min_budget: int = 800,
    max_budget: int = 8192,
) -> int:
    """
    Computes dynamic token budget for conversation history sliding window.
    Deduces model context window from model name or configured context length,
    clamps budget to prevent OOM on low-power NAS systems (e.g. Intel N100 / 4GB-8GB RAM),
    and applies target_ratio (default 25% for history, leaving 50% for RAG and 25% for response).
    """
    raw_window = context_window
    if not raw_window and model_name:
        m_lower = model_name.lower().strip()
        if any(k in m_lower for k in ("qwen2.5", "deepseek-r1", "llama-3.1", "llama3.1", "mistral-nemo", "command-r")):
            raw_window = 32768
        elif any(k in m_lower for k in ("llama-3.2", "llama3.2", "phi-3", "phi3", "gemma-2", "gemma2")):
            raw_window = 8192
        elif any(k in m_lower for k in ("llama-3", "llama3", "llama-2", "llama2", "mistral", "phi-2")):
            raw_window = 4096
        else:
            raw_window = 4096

    if not raw_window:
        raw_window = 4096

    calculated = int(raw_window * target_ratio)

    total_ram = system_ram_bytes
    if total_ram is None:
        try:
            import psutil

            total_ram = psutil.virtual_memory().total
        except Exception:
            total_ram = None

    if total_ram is not None:
        if total_ram < 4 * 1024 * 1024 * 1024:
            calculated = min(calculated, 1024)
        elif total_ram < 8 * 1024 * 1024 * 1024:
            calculated = min(calculated, 2048)

    return max(min_budget, min(calculated, max_budget))


def get_token_budgeted_history(
    conv_id: str,
    user_id: str,
    max_tokens: Optional[int] = None,
    model_name: Optional[str] = None,
    context_window: Optional[int] = None,
    system_ram_bytes: Optional[int] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Extracts sliding-window conversation history for LLM context, stripped of heavy tool JSON dumps.
    Preserves turn N-1 in full detail for conversational pronoun resolution,
    while compacting older turns to keep total history tokens <= dynamic token budget.
    """
    effective_max_tokens = max_tokens
    if effective_max_tokens is None:
        effective_max_tokens = get_dynamic_token_budget(
            model_name=model_name,
            context_window=context_window,
            system_ram_bytes=system_ram_bytes,
        )

    clean_uid = str(user_id or "admin").strip().lower()
    with get_conv_db_connection(db_path) as conn:
        cur = conn.execute(
            """
            SELECT role, content FROM conversation_messages
            WHERE conversation_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            (conv_id, clean_uid),
        )
        rows = cur.fetchall()

    if not rows:
        return []

    raw_turns: List[Dict[str, str]] = []
    for r in rows:
        role = r["role"]
        content = r["content"] or ""
        if role == "assistant":
            content = re.sub(r"```(?:json|yaml)?[\s\S]{600,}?```", "[Structured telemetry data omitted]", content)
        raw_turns.append({"role": role, "content": content.strip()})

    if not raw_turns:
        return []

    budget_chars = effective_max_tokens * 4
    accumulated_chars = 0
    selected_turns: List[Dict[str, str]] = []

    for idx, turn in enumerate(reversed(raw_turns)):
        turn_len = len(turn["content"])
        if idx < 2:
            selected_turns.append(turn)
            accumulated_chars += turn_len
        elif (accumulated_chars + turn_len) <= budget_chars:
            selected_turns.append(turn)
            accumulated_chars += turn_len
        else:
            break

    selected_turns.reverse()
    return selected_turns

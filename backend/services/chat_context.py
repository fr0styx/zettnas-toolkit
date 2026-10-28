"""Conversation context for ZettAI: follow-ups, history and token budgets, citations and grounding labels (split out of ai_chat_agent.py, ARCH-1)."""

import json
import os
import re
import threading
import time
from typing import (  # noqa: F401
    Any,
)


def _core():
    """backend.services.ai_chat_agent, read at call time: it holds the shared state, and tests patch names there."""
    from backend.services import ai_chat_agent

    return ai_chat_agent


class DiscourseEntityStack:
    """Bounded LRU stack of recently referenced NAS entities and recommended actions."""

    def __init__(self, max_size: int = 5):
        self.max_size = max_size
        self._items: list[dict[str, Any]] = []

    def push(self, entity_type: str, name: str, details: dict[str, Any] | None = None):
        self._items = [i for i in self._items if not (i["type"] == entity_type and i["name"] == name)]
        self._items.insert(
            0,
            {
                "type": entity_type,
                "name": name,
                "details": details or {},
                "timestamp": time.time(),
            },
        )
        if len(self._items) > self.max_size:
            self._items = self._items[: self.max_size]

    def get_most_recent(self, entity_type: str | None = None) -> dict[str, Any] | None:
        for i in self._items:
            if entity_type is None or i["type"] == entity_type:
                return i
        return None

    def all_items(self) -> list[dict[str, Any]]:
        return list(self._items)


class ContextualQueryRewriter:
    """
    Resolves conversational follow-up utterances ('Do that', 'Restart it', 'Stop it', 'Why?')
    against conversational history and recently referenced entities to eliminate accidental web search detours.
    """

    AFFIRMATION_PATTERN = re.compile(
        r"^(?:do\s+(?:that|it|this)|yes(?: please)?|sure(?: thing)?|run\s+it|go\s+ahead|proceed|ok|okay|yep|yeah|restart\s+it|start\s+it|stop\s+it|check\s+(?:that|it|again)|rescan|why(?:\s+(?:is\s+that|so))?)$",
        re.IGNORECASE,
    )

    @classmethod
    def is_affirmation(cls, text: str) -> bool:
        clean = str(text or "").strip().lower().rstrip("!.?,")
        return bool(cls.AFFIRMATION_PATTERN.match(clean))

    @classmethod
    def resolve_followup(
        cls,
        current_msg: str,
        history: list[dict[str, Any]] | None,
        stack: DiscourseEntityStack | None = None,
    ) -> tuple[str, str | None, dict[str, Any] | None]:
        """
        Returns (rewritten_query, inferred_tool, inferred_args).
        If the utterance is an affirmation or pronoun reference, resolves to the target tool and arguments.
        """
        clean = str(current_msg or "").strip()
        clean_norm = clean.lower().rstrip("!.?,")

        if not cls.is_affirmation(clean_norm):
            return clean, None, None

        # Build context from previous assistant and user messages
        combined_prev = ""
        last_asst = ""
        last_user = ""
        if history:
            for h in reversed(history):
                if isinstance(h, dict):
                    role = h.get("role")
                    if role == "assistant" and not last_asst:
                        last_asst = str(h.get("content") or "")
                    elif role == "user" and not last_user:
                        last_user = str(h.get("content") or "")
                    if last_asst and last_user:
                        break
            combined_prev = (last_asst + " " + last_user).lower()

        # 1. Check stack first if available
        if stack:
            rec_act = stack.get_most_recent("recommended_action")
            if rec_act:
                return (
                    rec_act["name"],
                    rec_act.get("details", {}).get("tool"),
                    rec_act.get("details", {}).get("args"),
                )
            rec_c = stack.get_most_recent("container")
            if rec_c:
                act = "restart" if "restart" in clean_norm else ("stop" if "stop" in clean_norm else "start")
                return (
                    f"{act} container {rec_c['name']}",
                    "control_docker_container",
                    {"container": rec_c["name"], "action": act},
                )

        # 2. Check previous messages for container mentions
        ctrl_match = re.search(
            r"\b(restart|start|stop)\s+(?:the\s+)?(?:docker\s+)?(?:container\s+)?([a-z0-9_.-]+)\b",
            combined_prev,
        )
        if ctrl_match and ctrl_match.group(2) not in ("container", "docker", "it", "that", "this", "them"):
            act = ctrl_match.group(1)
            c_name = ctrl_match.group(2)
            return f"{act} container {c_name}", "control_docker_container", {"container": c_name, "action": act}

        if any(w in combined_prev for w in ("immich", "docker", "dockers", "container", "containers")):
            return "list docker containers", "list_docker_containers", {"limit": 40}

        # 3. Check for fan profile mentions
        if any(w in combined_prev for w in ("fan", "fans", "cooling", "thermal", "quiet", "performance")):
            fan_match = re.search(r"\b(auto|quiet|silent|eco|balanced|normal|performance|turbo|full)\b", combined_prev)
            if fan_match and any(w in clean_norm for w in ("do that", "yes", "sure", "run it", "proceed", "go ahead")):
                return f"set fan profile to {fan_match.group(1)}", "set_fan_profile", {"profile": fan_match.group(1)}
            return "check fan and thermal status", "get_fan_and_thermal_status", {}

        # 4. Check for disk standby mentions
        if any(w in combined_prev for w in ("disk", "disks", "drive", "drives", "standby", "sleeping")):
            return "check disks standby status", "get_disks_and_standby_status", {}

        # 5. Check for AI sync
        if any(w in combined_prev for w in ("ai sync", "indexing", "sync shares", "learning")):
            return "trigger ai sync start", "trigger_ai_sync", {"action": "start"}

        return clean, None, None


_FOLLOWUP_START = re.compile(
    r"^(?:and|also|what about|how about|and what about|same for|und|und was ist mit|was ist mit|auch|et|et pour|"
    r"quid de|y|y qué hay de|también|还有|那|那么|另外)\b",
    re.I,
)


_FOLLOWUP_REF = re.compile(
    r"\b(?:it|its|that|this|those|them|there|the same|the second|the first|the other|es|das|dort|dafür|"
    r"ça|cela|celui|celle|là|eso|ese|esa|allí)\b|[它这那]",
    re.I,
)


def rewrite_followup_for_search(message: str, history: list[dict[str, Any]] | None) -> str:
    """The query to search the files with for a follow-up such as "and the warranty?" or
    "und wann läuft der TÜV ab?": the previous question's words plus this one (AI-13). The model
    still sees the conversation; only the search needs the topic spelled out."""
    msg = str(message or "").strip()
    if not history or not msg:
        return msg
    prev = next(
        (
            str(h.get("content") or "").strip()
            for h in reversed(history)
            if isinstance(h, dict) and h.get("role") == "user"
        ),
        "",
    )
    if not prev or prev == msg:
        return msg
    words = re.findall(r"\w+", msg)
    short = len(words) <= 6 or (len(msg) <= 20 and any("\u4e00" <= ch <= "\u9fff" for ch in msg))
    if short and (_FOLLOWUP_START.search(msg) or _FOLLOWUP_REF.search(msg) or len(words) <= 3):
        return f"{prev} {msg}"[:500]
    return msg


class EdgeTokenBudgeter:
    """
    Mathematical context window budgeting across hardware tiers:
      - 8K SLM (RAM <= 6GB, e.g. 1.5B/3B models on budget homelab)
      - 16K Mid (RAM <= 12GB, 7B/8B models)
      - 32K Max (RAM > 12GB, 14B+ models)
    """

    @staticmethod
    def get_budget(ram_bytes: int, model_name: str) -> dict[str, int]:
        ram_gb = round(ram_bytes / (1024**3), 1)
        m_low = str(model_name or "").lower()

        if ram_gb > 12 and not any(k in m_low for k in ("1b", "1.5b", "3b", "4b")):
            return {
                "context_window": 32768,
                "system_schema": 2000,
                "history": 8000,
                "working_context": 10000,
                "headroom": 4096,
                "max_history_turns": 16,
            }
        elif ram_gb > 6:
            return {
                "context_window": 16384,
                "system_schema": 1500,
                "history": 4000,
                "working_context": 5000,
                "headroom": 2048,
                "max_history_turns": 10,
            }
        else:
            return {
                "context_window": 8192,
                "system_schema": 1200,
                "history": 2000,
                "working_context": 2500,
                "headroom": 1024,
                "max_history_turns": 6,
            }

    @staticmethod
    def compact_history(
        history: list[dict[str, Any]] | None, max_turns: int = 10, char_limit: int = 800
    ) -> list[dict[str, str]]:
        if not history:
            return []
        cleaned: list[dict[str, str]] = []
        for h in history[-max_turns:]:
            if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                cleaned.append(
                    {
                        "role": str(h["role"]),
                        "content": str(h["content"])[:char_limit],
                    }
                )
        return cleaned


class EndpointRegistry:
    """
    Manages reachable local inference daemons with health caching and a 30s circuit breaker
    to eliminate connection stalls and event loop blocking.
    """

    def __init__(self):
        self._endpoints: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def is_tripped(self, ep_url: str) -> bool:
        with self._lock:
            rec = self._endpoints.get(ep_url)
            if not rec:
                return False
            now = time.time()
            if rec.get("tripped") and now < rec.get("trip_until", 0.0):
                return True
            if rec.get("tripped") and now >= rec.get("trip_until", 0.0):
                # Reset half-open
                rec["tripped"] = False
                rec["fail_count"] = 0
            return False

    def record_failure(self, ep_url: str):
        with self._lock:
            rec = self._endpoints.setdefault(ep_url, {"fail_count": 0, "tripped": False, "trip_until": 0.0})
            rec["fail_count"] += 1
            if rec["fail_count"] >= 2:
                rec["tripped"] = True
                rec["trip_until"] = time.time() + 30.0

    def record_success(self, ep_url: str):
        with self._lock:
            rec = self._endpoints.setdefault(ep_url, {"fail_count": 0, "tripped": False, "trip_until": 0.0})
            rec["fail_count"] = 0
            rec["tripped"] = False


def _grounding_or_none(value: Any) -> int | None:
    """A measured grounding score, or None when nothing was measured (never a made-up default)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _grounding_label(value: Any) -> str:
    score = _grounding_or_none(value)
    return f"{score}% grounded" if score is not None else "grounding unverified"


def tidy_citations(text: str | None, source_count: int) -> str | None:
    """One citation style: [Doc 2] becomes [2], and numbers with no matching source are dropped.
    Code blocks are left alone. With no sources, numbers are kept (they may not be citations)."""
    if not text:
        return text
    parts = text.split("```")
    for i in range(0, len(parts), 2):  # even parts are outside code blocks
        seg = _core()._DOC_MARKER.sub(r"[\1]", parts[i])
        if source_count > 0:
            seg = _core()._NUM_MARKER.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= source_count else "", seg)
        parts[i] = seg
    return "```".join(parts)


DEFAULT_NUM_CTX = 8192


REPLY_TOKENS = 1024


def _context_window_for(messages: list[dict[str, Any]] | None = None, tools: list[dict[str, Any]] | None = None) -> int:
    """One fixed num_ctx (AI-7). Ollama reloads the model whenever num_ctx changes, and a window
    sized to each prompt grew to 16384 and a 1.8 GiB KV cache on an iGPU; the prompt is fitted to
    the window instead (see _fit_to_window). ZETTNAS_AI_NUM_CTX overrides it."""
    override = os.environ.get("ZETTNAS_AI_NUM_CTX", "").strip()
    if override.isdigit() and int(override) >= 2048:
        return int(override)
    return DEFAULT_NUM_CTX


_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_CYRILLIC_GREEK_RE = re.compile(r"[\u0370-\u03ff\u0400-\u04ff]")


def estimate_tokens(text: str) -> int:
    """Rough token count without a tokenizer, by script (AI-33): one per CJK character, about
    2.5 characters per token for Cyrillic and Greek, 3.2 for Latin text with accents (German,
    French, Spanish: tokenizers split those words more), 4 for plain English."""
    t = str(text or "")
    cjk = len(_CJK_RE.findall(t))
    rest = len(t) - cjk
    if not rest:
        return cjk
    other = len(_CYRILLIC_GREEK_RE.findall(t))
    accented = sum(1 for c in t if 127 < ord(c) < 0x370 and c.isalpha())
    if other / rest > 0.3:
        per = 2.5
    elif accented / rest > 0.005:
        per = 3.2
    else:
        per = 4.0
    return cjk + int(-(-rest // per))


def _fit_to_window(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, num_ctx: int
) -> list[dict[str, Any]]:
    """Drops the oldest history, then shortens the evidence, so the prompt and a reply fit in
    num_ctx (AI-7). The question is shortened only when the evidence alone can't make room
    (AI-33): the evidence is cut from its end, where the weakest sources are (AI-8)."""
    budget = num_ctx - REPLY_TOKENS - (estimate_tokens(json.dumps(tools)) if tools else 0)
    msgs = [dict(m) for m in messages]
    total = lambda: sum(estimate_tokens(m.get("content") or "") + 4 for m in msgs)  # noqa: E731
    while total() > budget and len(msgs) > 2:
        msgs.pop(1)  # oldest turn after the system prompt
    over = total() - budget
    if over > 0 and len(msgs) > 1:
        system = msgs[0]
        content = str(system.get("content") or "")
        mark = content.find(EVIDENCE_MARK)
        if mark >= 0:
            head, evidence = content[: mark + len(EVIDENCE_MARK)], content[mark + len(EVIDENCE_MARK) :]
            keep = max(0, estimate_tokens(evidence) - over - 32)  # room for the note and rounding
            system["content"] = head + _keep_tokens(evidence, keep) + "\n[evidence shortened to fit]"
            over = total() - budget
    if over > 0 and msgs:
        last = msgs[-1]
        content = str(last.get("content") or "")
        keep_tokens = max(200, estimate_tokens(content) - over)
        last["content"] = _keep_tokens(content, keep_tokens) + "\n[context shortened to fit]"
    return msgs


EVIDENCE_MARK = "Live Context:\n"


def _keep_tokens(text: str, tokens: int) -> str:
    """The start of `text` worth about `tokens` tokens."""
    ratio = len(text) / max(1, estimate_tokens(text))  # the same mix of scripts as the whole text
    return text[: int(tokens * ratio)]

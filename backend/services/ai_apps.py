"""AI for apps (COMP-07): one OpenAI-compatible endpoint other apps on the network can use.

Paperless-ngx, Open WebUI, Home Assistant and anything else that speaks the OpenAI API get the
chat model and the embedder this server already runs, through one address and a key per app.

- Chat goes to the configured chat server (llm_endpoint, e.g. an OpenVINO Model Server), and to
  the Ollama fallback model (llm_fallback_model) when that server can't be reached. Whatever model
  name the app sends, the configured one answers, so app settings don't change with the model.
- Embeddings come from the configured embedder (embedding_model on embedding_host).
- Each request takes its turn on the GPU like a chat reply (gpu_queue.CHAT): someone is waiting.
- A key is an API token limited to the "ai:apps" scope. It can do nothing else, and its owner's
  role switches still apply (ai_access).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from backend.config import logger

CHAT_MODEL = "zettnas-chat"
EMBED_MODEL = "zettnas-embed"
SCOPE = "ai:apps"
CHAT_TIMEOUT_SECS = 300.0
EMBED_TIMEOUT_SECS = 30.0
MAX_EMBED_INPUTS = 64

# What an app may send on to the chat server; anything else (a model name, a user field, the
# server's own options) is dropped
CHAT_FIELDS = (
    "messages",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stream",
    "stream_options",
    "stop",
    "seed",
    "presence_penalty",
    "frequency_penalty",
    "tools",
    "tool_choice",
    "response_format",
    "n",
)

# Settings to paste into each app, filled with the address and key (B14 gate: Paperless-ngx and
# Home Assistant use the shared endpoint)
APPS: dict[str, dict[str, Any]] = {
    "paperless": {
        "label": "Paperless-ngx",
        "how": "Add these to the Paperless-ngx container's environment, then restart it.",
        "env": {
            "PAPERLESS_AI_ENABLED": "true",
            "PAPERLESS_AI_LLM_BACKEND": "openai-like",
            "PAPERLESS_AI_LLM_ENDPOINT": "{base_url}",
            "PAPERLESS_AI_LLM_API_KEY": "{key}",
            "PAPERLESS_AI_LLM_MODEL": CHAT_MODEL,
            "PAPERLESS_AI_LLM_EMBEDDING_BACKEND": "openai-like",
            "PAPERLESS_AI_LLM_EMBEDDING_MODEL": EMBED_MODEL,
        },
    },
    "openwebui": {
        "label": "Open WebUI",
        "how": "Add these to the Open WebUI container's environment, or enter them under Admin settings, Connections.",
        "env": {"OPENAI_API_BASE_URL": "{base_url}", "OPENAI_API_KEY": "{key}"},
    },
    "homeassistant": {
        "label": "Home Assistant",
        "how": (
            "Home Assistant's own OpenAI integration can't change its address. Install an "
            "OpenAI-compatible conversation integration (for example from HACS) and enter these."
        ),
        "env": {"Base URL": "{base_url}", "API key": "{key}", "Model": CHAT_MODEL},
    },
    "other": {
        "label": "Another app",
        "how": "Any app that speaks the OpenAI API: use this address and key.",
        "env": {"Base URL": "{base_url}", "API key": "{key}", "Chat model": CHAT_MODEL, "Embedding model": EMBED_MODEL},
    },
}


class UpstreamError(Exception):
    """The chat or embedding server didn't answer (502 to the app)."""


def _config() -> dict[str, Any]:
    from backend.services.rag_engine import get_rag_engine

    return get_rag_engine().get_config()


def settings_for(app: str, base_url: str, key: str) -> dict[str, Any]:
    spec = APPS[app]
    return {
        "app": app,
        "label": spec["label"],
        "how": spec["how"],
        "settings": {k: v.format(base_url=base_url, key=key) for k, v in spec["env"].items()},
    }


def models() -> dict[str, Any]:
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": CHAT_MODEL, "object": "model", "created": now, "owned_by": "zettnas"},
            {"id": EMBED_MODEL, "object": "model", "created": now, "owned_by": "zettnas"},
        ],
    }


def chat_upstreams(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """(URL, model) to try in order: the chat server, then the Ollama fallback model."""
    from backend.services.rag_embeddings import _resolve_ollama_host

    model = str(cfg.get("active_model") or cfg.get("llm_model") or "").strip()
    out: list[tuple[str, str]] = []
    ep = str(cfg.get("llm_endpoint") or "").strip().rstrip("/")
    if ep:
        if ep.endswith("/chat/completions"):
            out.append((ep, model))
        elif "/v1" in ep or "/v3" in ep:  # an OpenAI-compatible server (OVMS, vLLM, LM Studio)
            out.append((f"{ep}/chat/completions", model))
        else:  # an Ollama host: it speaks the OpenAI API under /v1
            out.append((f"{ep}/v1/chat/completions", model))
    ollama = _resolve_ollama_host(str(cfg.get("ollama_host") or "").strip() or None)
    if not ep and model:
        out.append((f"{ollama}/v1/chat/completions", model))
    fallback = str(cfg.get("llm_fallback_model") or "").strip()
    if fallback and (f"{ollama}/v1/chat/completions", fallback) not in out:
        out.append((f"{ollama}/v1/chat/completions", fallback))
    return [(u, m) for u, m in out if m]


def chat_body(body: dict[str, Any], model: str) -> dict[str, Any]:
    out = {k: body[k] for k in CHAT_FIELDS if k in body}
    if not isinstance(out.get("messages"), list) or not out["messages"]:
        raise ValueError("messages must be a non-empty list")
    out["model"] = model
    return out


def _open(url: str, payload: dict[str, Any], timeout: float):
    if "//zettnas-ai:" in url:  # the AI pack, maybe stopped for idling (AI-40)
        from backend.services import ai_pack

        ai_pack.wake_for(url)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-AI-for-apps/1.0"},
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (configured AI servers only)


def _first_answering(body: dict[str, Any], timeout: float):
    """(response, model) from the first chat server that answers; UpstreamError when none does.
    A server that answers with an error status is not tried past: the app sees that answer."""
    last = "no chat model is set up"
    for url, model in chat_upstreams(_config()):
        try:
            return _open(url, chat_body(body, model), timeout), model
        except urllib.error.HTTPError as e:
            detail = e.read()[:2000].decode("utf-8", "replace")
            raise UpstreamError(f"the chat server answered {e.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            last = f"{url.split('/')[2]}: {getattr(e, 'reason', e)}"
            logger.info(f"[AI apps] chat server not answering ({last}), trying the next one")
    raise UpstreamError(f"no chat server answered ({last})")


def chat(body: dict[str, Any]) -> dict[str, Any]:
    """A whole reply (stream: false)."""
    from backend.services import gpu_queue
    from backend.services.chat_llm_runtime import mark_chat_activity

    mark_chat_activity()
    with gpu_queue.use(gpu_queue.CHAT):
        resp, _model = _first_answering({**body, "stream": False}, CHAT_TIMEOUT_SECS)
        with resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    if isinstance(data, dict):
        data["model"] = CHAT_MODEL
    return data


def chat_stream(body: dict[str, Any]) -> Iterator[bytes]:
    """The reply as the chat server streams it (server-sent events), passed on line by line. The
    GPU turn is held until the stream ends."""
    from backend.services import gpu_queue
    from backend.services.chat_llm_runtime import mark_chat_activity

    mark_chat_activity()
    with gpu_queue.use(gpu_queue.CHAT):
        resp, _model = _first_answering({**body, "stream": True}, CHAT_TIMEOUT_SECS)
        with resp:
            yield from resp


def embeddings(body: dict[str, Any]) -> dict[str, Any]:
    from backend.services import gpu_queue
    from backend.services.rag_embeddings import compute_neural_embedding_via_ollama, embedding_host

    raw = body.get("input")
    texts = [raw] if isinstance(raw, str) else raw
    if not isinstance(texts, list) or not texts or len(texts) > MAX_EMBED_INPUTS:
        raise ValueError(f"input must be a string or a list of 1-{MAX_EMBED_INPUTS} strings")
    if not all(isinstance(t, str) and t.strip() for t in texts):
        raise ValueError("every input must be non-empty text")
    cfg = _config()
    model = str(cfg.get("embedding_model") or "").strip()
    if not model:
        raise UpstreamError("no embedding model is set up")
    host = embedding_host(cfg)
    data = []
    with gpu_queue.use(gpu_queue.QUERY):
        for i, text in enumerate(texts):
            got = compute_neural_embedding_via_ollama(text, model=model, host=host, timeout=EMBED_TIMEOUT_SECS)
            if not got:
                raise UpstreamError("the embedding server didn't answer")
            data.append({"object": "embedding", "index": i, "embedding": got[1]})
    tokens = sum(len(t.split()) for t in texts)
    return {
        "object": "list",
        "model": EMBED_MODEL,
        "data": data,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }

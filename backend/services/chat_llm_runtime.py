"""Talking to the local language model: finding the runtime, streaming, reasoning blocks and telemetry (split out of ai_chat_agent.py, ARCH-1)."""

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import (  # noqa: F401
    Any,
)

from backend.config import (  # noqa: F401
    logger,
)
from backend.services.chat_context import (  # noqa: F401
    _context_window_for,
)
from backend.services.media_engine import (  # noqa: F401
    build_llm_recommendations,
    detect_hardware_accelerator,
    is_embedding_only_model,
    read_total_ram_bytes,
)


def _core():
    """backend.services.ai_chat_agent, read at call time: it holds the shared state, and tests patch names there."""
    from backend.services import ai_chat_agent

    return ai_chat_agent


def extract_and_strip_reasoning(text: str) -> tuple[str, str]:
    """
    Extracts internal reasoning/thought content from model outputs and strips both closed
    (<think>...</think>) and unclosed (<think>...<EOF>) reasoning blocks to prevent raw
    internal scratchpad thoughts from bleeding into user-visible chat responses.

    Returns:
        (think_content, clean_reply)
    """
    if not text:
        return "", ""
    think_parts: list[str] = []
    for m in _core().REASONING_TAG_RE.finditer(text):
        t = m.group(1).strip()
        if t:
            think_parts.append(t)
    cleaned = _core().REASONING_TAG_RE.sub("", text)

    unclosed = _core().UNCLOSED_REASONING_TAG_RE.search(cleaned)
    if unclosed:
        ut = unclosed.group(1).strip()
        if ut:
            think_parts.append(ut)
        cleaned = _core().UNCLOSED_REASONING_TAG_RE.sub("", cleaned)

    return "\n\n".join(think_parts).strip(), cleaned.strip()


def resolve_model_runtime_accelerator(active_model: str, host_accel: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Resolves the actual hardware compute tier and device for a given AI model.
    Differentiates between:
      - Tier 1 (NPU): OpenVINO Model Server / Intel AI Boost NPU models (e.g. DeepSeek-R1-Distill-Qwen-1.5B, builtin-npu)
      - Tier 2 (GPU): Ollama models running on a GPU (e.g. qwen2.5, embeddinggemma)
      - Tier 3 (CPU): Models running on CPU execution provider
    """
    if not host_accel:
        try:
            host_accel = detect_hardware_accelerator()
        except Exception:
            host_accel = {"has_npu": True, "has_igpu": True, "active_tier": 1}

    act_low = str(active_model or "").lower().strip()
    is_npu_model = any(
        k in act_low
        for k in (
            "deepseek-r1-distill-qwen-1.5b",
            "deepseek-r1:1.5b",
            "builtin-npu",
            "openvino",
            "ov-",
            "-ov",
            "npu",
        )
    )

    has_npu = bool(host_accel.get("has_npu") or os.path.exists("/dev/accel/accel0"))
    has_gpu = bool(
        host_accel.get("has_igpu")
        or host_accel.get("has_cuda")
        or host_accel.get("has_rocm")
        or host_accel.get("has_gpu")
        or os.path.exists("/dev/dri/renderD128")
    )

    if is_npu_model and has_npu:
        return {
            "active_tier": 1,
            "tier_number": 1,
            "tier": "NPU_TIER_1",
            "tier_code": "NPU_TIER_1",
            "tier_name": "NPU",
            "name": "Intel AI Boost NPU",
            "device_label": "Intel AI Boost NPU (/dev/accel/accel0)",
            "runtime_engine": "OpenVINO Model Server (NPU)",
            "has_npu": True,
            "has_gpu": False,
        }
    elif has_gpu:
        return {
            "active_tier": 2,
            "tier_number": 2,
            "tier": "GPU_TIER_2",
            "tier_code": "GPU_TIER_2",
            "tier_name": "GPU",
            "name": "Intel Arc Graphics (GPU)",
            "device_label": "Intel Arc Graphics (/dev/dri/renderD128)",
            "runtime_engine": "Ollama Local Neural Engine (Intel Arc GPU)",
            "has_npu": False,
            "has_gpu": True,
        }
    else:
        return {
            "active_tier": 3,
            "tier_number": 3,
            "tier": "CPU_TIER_3",
            "tier_code": "CPU_TIER_3",
            "tier_name": "CPU",
            "name": "CPU Execution Provider",
            "device_label": "CPU Execution Provider",
            "runtime_engine": "CPU Execution Provider",
            "has_npu": False,
            "has_gpu": False,
        }


def _cancelled() -> bool:
    ev = _core()._CANCEL_EVENT.get()
    return bool(ev is not None and ev.is_set())


class _ThinkSplitter:
    """Splits streamed text into answer tokens and <think>/<thought>/<reasoning> text."""

    OPEN = ("<think>", "<thought>", "<reasoning>")

    def __init__(self, sink):
        self.sink = sink
        self.buf = ""
        self.close_tag = ""
        self.emitted = False

    @staticmethod
    def _held(buf: str, tags) -> int:
        """Length of a trailing partial tag to hold back until more text arrives."""
        best = 0
        for tag in tags:
            for k in range(min(len(tag) - 1, len(buf)), 0, -1):
                if buf.endswith(tag[:k]):
                    best = max(best, k)
                    break
        return best

    def _emit(self, kind: str, text: str) -> None:
        if text:
            self.sink(kind, text)
            if kind == "token":
                self.emitted = True

    def feed(self, text: str) -> None:
        self.buf += text
        while self.buf:
            kind = "think" if self.close_tag else "token"
            if self.close_tag:
                i, tag = self.buf.find(self.close_tag), self.close_tag
                tags = (self.close_tag,)
            else:
                hits = [(self.buf.find(t), t) for t in self.OPEN if t in self.buf]
                i, tag = min(hits) if hits else (-1, "")
                tags = self.OPEN
            if i == -1:
                keep = self._held(self.buf, tags)
                self._emit(kind, self.buf[: len(self.buf) - keep])
                self.buf = self.buf[len(self.buf) - keep :]
                return
            self._emit(kind, self.buf[:i])
            self.buf = self.buf[i + len(tag) :]
            self.close_tag = "" if self.close_tag else "</" + tag[1:]

    def flush(self) -> None:
        self._emit("think" if self.close_tag else "token", self.buf)
        self.buf = ""


def _read_llm_stream(resp: Any, runtime_kind: str) -> dict[str, Any]:
    """Reads a streamed Ollama (NDJSON) or OpenAI-compatible (SSE) reply, passing pieces to the
    token sink as they arrive, and returns it in the same shape as a non-streamed reply."""
    sink = _core()._TOKEN_SINK.get() or (lambda kind, text: None)
    splitter = _ThinkSplitter(sink)
    content: list[str] = []
    thinking: list[str] = []
    ollama_calls: list[Any] = []
    oa_calls: dict[int, dict[str, Any]] = {}
    final: dict[str, Any] = {}
    is_openai = runtime_kind == "openai_compatible"
    for raw in resp:
        if _cancelled():
            final["cancelled"] = True
            break
        line = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line:
            continue
        if is_openai:
            if not line.startswith("data:"):
                continue
            line = line[5:].strip()
            if line == "[DONE]":
                break
        try:
            chunk = json.loads(line)
        except ValueError:
            continue
        if is_openai:
            if chunk.get("usage"):
                final["usage"] = chunk["usage"]
            if chunk.get("model"):
                final["model"] = chunk["model"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    thinking.append(delta["reasoning_content"])
                    sink("think", delta["reasoning_content"])
                if delta.get("content"):
                    content.append(delta["content"])
                    splitter.feed(delta["content"])
                for tc in delta.get("tool_calls") or []:
                    slot = oa_calls.setdefault(
                        int(tc.get("index", len(oa_calls))),
                        {"id": tc.get("id"), "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    fn = tc.get("function") or {}
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    slot["function"]["name"] += fn.get("name") or ""
                    slot["function"]["arguments"] += fn.get("arguments") or ""
        else:
            msg = chunk.get("message") or {}
            if msg.get("thinking"):
                thinking.append(msg["thinking"])
                sink("think", msg["thinking"])
            if msg.get("content"):
                content.append(msg["content"])
                splitter.feed(msg["content"])
            if msg.get("tool_calls"):
                ollama_calls.extend(msg["tool_calls"])
            if chunk.get("done"):
                for k in ("eval_count", "eval_duration", "prompt_eval_count"):
                    if chunk.get(k) is not None:
                        final[k] = chunk[k]
                break
    splitter.flush()
    calls = ollama_calls or [oa_calls[k] for k in sorted(oa_calls)]
    if calls and splitter.emitted:
        sink("reset", "")
    text = "".join(content)
    if is_openai:
        return {
            "choices": [{"message": {"content": text, "reasoning_content": "".join(thinking), "tool_calls": calls}}],
            "usage": final.get("usage") or {},
            "model": final.get("model"),
        }
    if thinking and "<think>" not in text:
        text = f"<think>\n{''.join(thinking)}\n</think>\n\n{text}"
    out = {"message": {"content": text, "tool_calls": calls}}
    out.update({k: v for k, v in final.items() if k != "cancelled"})
    return out


def _fallback_model() -> str:
    """The Ollama model that answers when the chat model's own server (e.g. an OpenVINO Model
    Server) can't: rag config "llm_fallback_model", empty for none."""
    try:
        from backend.services.rag_engine import get_rag_engine

        return str(get_rag_engine().get_config().get("llm_fallback_model") or "").strip()
    except Exception:
        logger.debug("chat_llm_runtime: no fallback model", exc_info=True)
        return ""


CHAT_BUSY_SECS = 120.0
_LAST_CHAT = {"at": 0.0}


def mark_chat_activity() -> None:
    """Someone is chatting: background model work (photo captions) waits (AI-14)."""
    _LAST_CHAT["at"] = time.time()


def chat_recently_active(now: float | None = None) -> bool:
    return (now or time.time()) - _LAST_CHAT["at"] < CHAT_BUSY_SECS


def _keep_alive() -> str:
    """Ollama keep_alive from AI settings ("idle_unload_minutes"; 0 keeps the model loaded)."""
    try:
        from backend.services.rag_engine import get_rag_engine

        minutes = int(get_rag_engine().get_config().get("idle_unload_minutes", 15))
    except Exception:
        logger.debug("chat_llm_runtime: idle unload setting unavailable", exc_info=True)
        minutes = 15
    return "-1" if minutes <= 0 else f"{minutes}m"


def _try_local_llm_completion(
    active_model: str,
    llm_endpoint: str,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | None = None,
    fallback_model: str | None = None,
) -> tuple[
    str | None,
    str | None,
    int,
    float | None,
    dict[str, Any] | None,
    list[dict[str, Any]] | None,
]:
    """
    Attempts to call a live local LLM runtime (Ollama `/api/chat` or OpenAI `/v1/chat/completions`)
    if reachable on the NAS or configured endpoint.
    Returns `(reply_text, runtime_name, eval_tokens, measured_tok_sec, runtime_accel, raw_tool_calls)` or `(None, None, 0, None, None, None)` if no external daemon is listening.
    """
    if os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1":
        return (None, None, 0, None, None, None)

    if active_model in ("OpenVINO/clip-vit-base-patch16-int8-ov",) or is_embedding_only_model(active_model):
        return (None, None, 0, None, None, None)

    mark_chat_activity()
    candidate_endpoints: list[tuple[str, str]] = []
    if llm_endpoint and llm_endpoint.strip():
        ep = llm_endpoint.strip().rstrip("/")
        if ep.endswith("/v1") or "/v1/" in ep:
            candidate_endpoints.append(
                ("openai_compatible", f"{ep}/chat/completions" if not ep.endswith("/chat/completions") else ep)
            )
        else:
            candidate_endpoints.append(("ollama_custom", f"{ep}/api/chat" if not ep.endswith("/api/chat") else ep))

    # Check cached successful endpoint first to eliminate connection timeout stalls
    cache_key = f"{active_model}:{llm_endpoint or ''}"
    now = time.time()
    cached_ep = _core()._ACTIVE_ENDPOINT_CACHE.get(cache_key)
    if cached_ep and cached_ep[2] > now:
        cached_tuple = (cached_ep[0], cached_ep[1])
        candidate_endpoints.append(cached_tuple)

    # Probe Ollama across discovered host & bridge IPs
    host_ips = _core()._get_docker_host_ips()
    for ip in host_ips:
        candidate_endpoints.append(("ollama_local", f"http://{ip}:11434/api/chat"))
    candidate_endpoints.append(("ollama_host", "http://host.docker.internal:11434/api/chat"))

    # OpenAI-compatible servers (OpenVINO Model Server, LM Studio, vLLM) are used only when
    # configured: guessing ports would send the prompt, which holds file text, to whatever
    # service listens there (AI-19).

    # Deduplicate candidate endpoints preserving order
    seen_eps = set()
    deduped_eps: list[tuple[str, str]] = []
    for ep in candidate_endpoints:
        if ep[1] not in seen_eps:
            seen_eps.add(ep[1])
            deduped_eps.append(ep)
    candidate_endpoints = deduped_eps

    # Prioritize OpenVINO Model Server (:8000) when NPU or OpenVINO models are requested
    is_npu_preferred = any(
        k in active_model.lower()
        for k in (
            "npu",
            "builtin-npu",
            "openvino",
            "ov-",
            "-ov",
            "deepseek-r1-distill-qwen-1.5b",
            "deepseek-r1:1.5b",
            "deepseek-r1-1.5b",
            "qwen2.5-1.5b",
            "qwen2.5:1.5b",
            "llama-3.2-1b",
        )
    )
    if is_npu_preferred:
        ovms_eps = [ep for ep in candidate_endpoints if ":8000" in ep[1]]
        other_eps = [ep for ep in candidate_endpoints if ":8000" not in ep[1]]
        candidate_endpoints = ovms_eps + other_eps

    streaming = _core()._TOKEN_SINK.get() is not None
    fallback = _fallback_model() if fallback_model is None else fallback_model.strip()
    for runtime_kind, url in candidate_endpoints:
        if _cancelled():
            break
        if _core()._ENDPOINT_REGISTRY.is_tripped(url):
            continue
        openai_req_body: dict[str, Any] = {}
        try:
            model_to_use = active_model
            if "ollama" in runtime_kind:
                # Fast model discovery on Ollama /api/tags
                tags_url = url.replace("/api/chat", "/api/tags")
                try:
                    t_req = urllib.request.Request(tags_url, headers={"User-Agent": "ZettNAS-Toolkit/2.0"})
                    with urllib.request.urlopen(t_req, timeout=1.2) as t_resp:
                        t_data = json.loads(t_resp.read().decode("utf-8", errors="replace"))
                        avail = [m.get("name", "") for m in t_data.get("models", []) if m.get("name")]
                        if avail:
                            clean_act = active_model.lower().strip()
                            # 1. Exact match (with or without :latest)
                            matched = next(
                                (
                                    m
                                    for m in avail
                                    if m.lower() == clean_act
                                    or m.lower() == f"{clean_act}:latest"
                                    or m.lower().replace(":latest", "") == clean_act
                                ),
                                None,
                            )
                            fb = next(
                                (
                                    m
                                    for m in avail
                                    if fallback
                                    and m.lower().replace(":latest", "") == fallback.lower().replace(":latest", "")
                                ),
                                None,
                            )
                            if matched:
                                model_to_use = matched
                            elif fb:
                                # The chat model lives on another server that didn't answer: the chosen
                                # fallback answers here, under its own name (AI-03).
                                model_to_use = fb
                            else:
                                # The selected model is not installed in this runtime. Never answer with
                                # a different model under its name (AI-03): no copies, no prefix matches.
                                _core()._LAST_MODEL_PROBLEM["text"] = (
                                    f"`{active_model}` is not installed in the AI runtime. "
                                    f"Installed: {', '.join(sorted(avail)[:8])}."
                                )
                                continue
                except Exception:
                    logger.debug(
                        "backend.services.ai_chat_agent._try_local_llm_completion: ignored error", exc_info=True
                    )

                ollama_req_body: dict[str, Any] = {
                    "model": model_to_use,
                    "messages": messages,
                    "stream": streaming,
                    "options": {"temperature": 0.2, "num_ctx": _context_window_for()},
                    # unloads after the idle time set in AI settings, giving its memory back (PERF-1)
                    "keep_alive": _keep_alive(),
                }
                if tools:
                    ollama_req_body["tools"] = tools
                payload = json.dumps(ollama_req_body).encode("utf-8")
            else:
                is_ovms = ":8000" in url
                models_url = url.replace("/chat/completions", "/models")
                try:
                    m_req = urllib.request.Request(models_url, headers={"User-Agent": "ZettNAS-Toolkit/2.0"})
                    with urllib.request.urlopen(m_req, timeout=1.0) as m_resp:
                        m_data = json.loads(m_resp.read().decode("utf-8", errors="replace"))
                        m_list = m_data.get("data", [])
                        if any(m.get("owned_by") == "OVMS" for m in m_list):
                            is_ovms = True
                        m_ids = [m.get("id") for m in m_list if m.get("id")]
                        if m_ids:
                            clean_act = active_model.lower().strip()
                            matched = next(
                                (
                                    m
                                    for m in m_ids
                                    if m.lower() == clean_act or m.lower().rsplit("/", 1)[-1] == clean_act
                                ),
                                None,
                            )
                            if not matched:
                                _core()._LAST_MODEL_PROBLEM["text"] = (
                                    f"`{active_model}` is not served by the model server at {models_url.rsplit('/v', 1)[0]}. "
                                    f"Served: {', '.join(sorted(m_ids)[:8])}."
                                )
                                continue
                            model_to_use = matched
                except Exception:
                    logger.debug(
                        "backend.services.ai_chat_agent._try_local_llm_completion: ignored error", exc_info=True
                    )

                openai_req_body: dict[str, Any] = {
                    "model": model_to_use,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 1024,
                }
                if tools:
                    openai_req_body["tools"] = tools
                if is_ovms:
                    # Qwen3 and other reasoning models would think before answering; Ask Zetty
                    # answers from the files it found, so it asks for the answer straight away.
                    openai_req_body["chat_template_kwargs"] = {"enable_thinking": False}
                if streaming:
                    openai_req_body["stream"] = True
                    openai_req_body["stream_options"] = {"include_usage": True}
                payload = json.dumps(openai_req_body).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-Toolkit/2.0"},
                method="POST",
            )
            # Streaming: at most 45 s between pieces. Without streaming nothing arrives until the
            # whole answer is written, which over a long document question takes minutes.
            # The first token waits for the whole prompt to be read: about 50 tokens a second on a
            # slow CPU, so a 6,000-token document question needs minutes there (AI-7)
            prompt_tokens = len(json.dumps(messages)) / 4
            first_token_wait = min(600.0, 45.0 + prompt_tokens / 50.0)
            try:
                resp = urllib.request.urlopen(
                    req, timeout=first_token_wait if streaming else max(180.0, first_token_wait)
                )
            except urllib.error.HTTPError as http_err:
                # A model server without tool support refuses the tools: ask again without them
                if (
                    http_err.code == 400
                    and runtime_kind == "openai_compatible"
                    and tools
                    and "tools" in openai_req_body
                ):
                    openai_req_body.pop("tools", None)
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(openai_req_body).encode("utf-8"),
                        headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-Toolkit/2.0"},
                        method="POST",
                    )
                    resp = urllib.request.urlopen(
                        req, timeout=first_token_wait if streaming else max(180.0, first_token_wait)
                    )
                else:
                    raise
            with resp:
                if streaming:
                    data = _read_llm_stream(resp, runtime_kind)
                else:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if runtime_kind == "openai_compatible":
                    choices = data.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        msg = choices[0].get("message", {})
                        content = msg.get("content", "") or ""
                        reasoning = msg.get("reasoning_content", "") or ""
                        raw_tool_calls = msg.get("tool_calls") or []
                        if reasoning:
                            if str(content).strip():
                                if "<think>" not in str(content):
                                    content = f"<think>\n{str(reasoning).strip()}\n</think>\n\n{str(content).strip()}"
                            else:
                                content = f"<think>\n{str(reasoning).strip()}\n</think>"
                        toks = int((data.get("usage") or {}).get("completion_tokens") or 0)
                        if is_ovms or ":8000" in url:
                            # Which device OVMS runs the model on is its own configuration; don't claim NPU.
                            ovms_accel = None
                            runtime_label = f"OpenVINO Model Server ({data.get('model') or model_to_use})"
                        else:
                            ovms_accel = None
                            runtime_label = "OpenAI-Compatible Local LLM"
                        if content or raw_tool_calls:
                            _core()._ACTIVE_ENDPOINT_CACHE[cache_key] = (runtime_kind, url, time.time() + 60.0)
                            return (
                                str(content).strip() if content else "",
                                runtime_label,
                                toks,
                                None,
                                ovms_accel,
                                raw_tool_calls,
                            )

                else:
                    msg_obj = data.get("message") or {}
                    content = msg_obj.get("content") or data.get("response") or ""
                    raw_tool_calls = msg_obj.get("tool_calls") or []
                    toks = int(data.get("eval_count") or 0)
                    eval_duration_ns = data.get("eval_duration") or 0
                    measured_tok_sec = None
                    if toks and eval_duration_ns and eval_duration_ns > 0:
                        measured_tok_sec = round(toks / (eval_duration_ns / 1e9), 1)

                    # Probe Ollama /api/ps to determine whether inference ran on GPU (VRAM > 0) or CPU
                    ollama_accel: dict[str, Any] | None = None
                    try:
                        ps_url = url.replace("/api/chat", "/api/ps")
                        p_req = urllib.request.Request(ps_url, headers={"User-Agent": "ZettNAS-Toolkit/2.0"})
                        with urllib.request.urlopen(p_req, timeout=0.8) as p_resp:
                            p_data = json.loads(p_resp.read().decode("utf-8", errors="replace"))
                            has_vram = any((m.get("size_vram") or 0) > 0 for m in p_data.get("models", []))
                            if has_vram:
                                ollama_accel = {
                                    "active_tier": 2,
                                    "tier_number": 2,
                                    "name": "GPU",
                                    "device_label": "GPU (Ollama reports VRAM in use)",
                                    "has_gpu": True,
                                    "has_npu": False,
                                }
                            else:
                                ollama_accel = {
                                    "active_tier": 3,
                                    "tier_number": 3,
                                    "name": "CPU",
                                    "device_label": "CPU",
                                    "has_gpu": False,
                                    "has_npu": False,
                                }
                    except Exception:
                        logger.debug(
                            "backend.services.ai_chat_agent._try_local_llm_completion: ignored error", exc_info=True
                        )

                    if content or raw_tool_calls:
                        _core()._ACTIVE_ENDPOINT_CACHE[cache_key] = (runtime_kind, url, time.time() + 60.0)
                        _core()._ENDPOINT_REGISTRY.record_success(url)
                        return (
                            str(content).strip() if content else "",
                            f"Ollama ({model_to_use})",
                            toks,
                            measured_tok_sec,
                            ollama_accel,
                            raw_tool_calls,
                        )
        except Exception:
            _core()._ENDPOINT_REGISTRY.record_failure(url)
            continue

    return (None, None, 0, None, None, None)


def _estimate_model_tok_per_sec(active_model: str, model_info: dict[str, Any] | None, tier_num: int) -> float:
    """Computes a realistic hardware token generation speed for the active model and NPU/GPU tier."""
    m_low = str(active_model or "").lower()
    spd_field = (model_info.get("estimated_speed") or model_info.get("est_speed")) if model_info else None
    if spd_field:
        spd_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*tok/s", str(spd_field))
        if spd_m:
            lo = float(spd_m.group(1))
            hi = float(spd_m.group(2)) if spd_m.group(2) else lo
            return round((lo + hi) / 2.0, 1)
    if any(x in m_low for x in ("70b", "72b", "67b")):
        return 7.5 if tier_num <= 2 else 3.5
    if any(x in m_low for x in ("32b", "34b", "27b")):
        return 24.0 if tier_num <= 2 else 12.0
    if any(x in m_low for x in ("14b", "13b", "12b")):
        return 28.5 if tier_num == 1 else (32.0 if tier_num == 2 else 16.0)
    if any(x in m_low for x in ("7b", "8b", "9b")):
        return 34.0 if tier_num == 1 else (38.0 if tier_num == 2 else 20.0)
    if any(x in m_low for x in ("4b", "3.8b", "3b")):
        return 45.0 if tier_num == 1 else (38.0 if tier_num == 2 else 26.0)
    if any(x in m_low for x in ("2b", "1.5b", "1b", "0.5b")):
        return 55.0 if tier_num == 1 else 42.0
    return 42.0 if tier_num == 1 else 32.0


def build_llm_execution_telemetry(
    active_model: str | None = None,
    accel: dict[str, Any] | None = None,
    elapsed_ms: float = 15.0,
    answer_text: str = "",
    runtime_name: str | None = None,
    eval_tokens: int = 0,
    measured_tok_sec: float | None = None,
    tools_called: list[str] | None = None,
    web_sources_count: int = 0,
) -> dict[str, Any]:
    """Builds transparent LLM & Hardware Execution Telemetry for both RAG and Chat responses."""
    if not active_model:
        try:
            cfg = _core().get_rag_engine().get_config()
            active_model = str(cfg.get("active_model") or cfg.get("llm_model") or "qwen2.5:3b")
        except Exception:
            active_model = "qwen2.5:3b"

    accel = resolve_model_runtime_accelerator(active_model, host_accel=accel)
    ram_gb = round(read_total_ram_bytes() / (1024**3), 1)
    recs = build_llm_recommendations(accel=accel, ram_gb=ram_gb, active_model=active_model)
    model_info = next(
        (
            m
            for m in recs.get("models", [])
            if str(m.get("id", "")).lower() == active_model.lower()
            or str(m.get("hf_repo", "")).lower() == active_model.lower()
        ),
        None,
    )
    tier_num = int(accel.get("active_tier") or accel.get("tier_number") or (1 if accel.get("has_npu") else 2))
    dev_label = accel.get("device_label") or accel.get("name") or "Intel Arc Graphics"
    compact_dev = re.sub(r"\s*\([^)]*\)", "", str(dev_label)).strip() or dev_label

    # Only measured values (AI-02): no estimated speeds or token counts.
    llm_invoked = bool(runtime_name)
    est_tokens = eval_tokens if (llm_invoked and eval_tokens > 0) else None
    tok_per_sec = round(measured_tok_sec, 1) if (llm_invoked and measured_tok_sec and measured_tok_sec > 0) else None

    is_reasoning = any(k in active_model.lower() for k in ("deepseek-r1", "qwq", "-r1"))
    effective_runtime = runtime_name or "No AI model (built-in tools only)"

    return {
        "active_model": active_model,
        "model_name": model_info.get("name") if model_info else active_model,
        "hf_repo": model_info.get("hf_repo") if model_info else active_model,
        "quantization": model_info.get("quantization") if model_info else None,
        "fits_hardware": bool(model_info.get("fits_hardware", True)) if model_info else True,
        "hardware_warning": bool(model_info.get("hardware_warning", False)) if model_info else False,
        "warning_message": model_info.get("warning_message") if model_info else None,
        "accelerator_tier": tier_num,
        "accelerator_label": f"Tier {tier_num}: {compact_dev}",
        "hardware_tier": f"Tier {tier_num}: {accel.get('tier_name', 'NPU' if tier_num == 1 else 'GPU')}",
        "tier_code": accel.get("tier_code", f"TIER_{tier_num}"),
        "hardware_device": dev_label,
        "hardware_device_compact": compact_dev,
        "runtime_mode": effective_runtime,
        "llm_invoked": llm_invoked,
        "elapsed_ms": round(elapsed_ms, 1),
        "tokens_generated": est_tokens,
        "tokens_per_sec": tok_per_sec,
        "tools_called": list(tools_called or []),
        "web_sources_count": int(web_sources_count or 0),
    }

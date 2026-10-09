"""
Structured JSON Logging & Diagnostics Utilities for ZettNAS.
Provides correlation ID propagation across HTTP requests, single-line JSON formatting,
thread-safe in-memory log buffer, and credential redaction for diagnostic bundles.
"""

import collections
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

# Context variable holding the correlation ID for the active request
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")

# Thread-safe in-memory ring buffer capturing recent log records
LOG_RING_BUFFER = collections.deque(maxlen=1000)

SENSITIVE_KEY_PATTERN = re.compile(
    r"(pass(word)?|token|secret|auth|bearer|key|jwt|credential|private|cert|api_key)",
    re.IGNORECASE,
)
URL_SECRET_PATTERN = re.compile(
    r"(https?://[^/\s]+/[^\s]*?(?:token|secret|key|password)=)[^\s&]+",
    re.IGNORECASE,
)
DISCORD_WEBHOOK_PATTERN = re.compile(
    r"(https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
TELEGRAM_BOT_PATTERN = re.compile(r"bot\d+:[A-Za-z0-9_-]+", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9_.-]+", re.IGNORECASE)
ZAT_TOKEN_PATTERN = re.compile(r"zat_[A-Za-z0-9_-]{16,}")
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN[ A-Z0-9_-]+PRIVATE KEY-----[\s\S]*?-----END[ A-Z0-9_-]+PRIVATE KEY-----",
    re.MULTILINE,
)
APPRISE_URL_PATTERN = re.compile(
    r"((?:tgram|discord|prowl|pushover|slack|gotify)://)[^\s\"']+",
    re.IGNORECASE,
)
CREDENTIAL_URL_PATTERN = re.compile(r"(://[^:\s/@]+:)[^@\s/]+(@)", re.IGNORECASE)


def sanitize_string(text: str) -> str:
    """Redacts passwords, tokens, webhooks, and private keys from strings."""
    if not text or not isinstance(text, str):
        return str(text or "")
    text = PRIVATE_KEY_BLOCK.sub("[REDACTED_PRIVATE_KEY_BLOCK]", text)
    text = DISCORD_WEBHOOK_PATTERN.sub(r"\1[REDACTED_WEBHOOK]", text)
    text = TELEGRAM_BOT_PATTERN.sub("bot[REDACTED_BOT_TOKEN]", text)
    text = APPRISE_URL_PATTERN.sub(r"\1[REDACTED]", text)
    text = CREDENTIAL_URL_PATTERN.sub(r"\1[REDACTED]\2", text)
    text = BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = ZAT_TOKEN_PATTERN.sub("zat_[REDACTED]", text)
    text = URL_SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    return text


def sanitize_dict(data: Any) -> Any:
    """Recursively sanitizes dictionary keys and values for diagnostic bundles."""
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            k_str = str(k)
            if SENSITIVE_KEY_PATTERN.search(k_str):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = sanitize_dict(v)
        return clean
    elif isinstance(data, list):
        return [sanitize_dict(item) for item in data]
    elif isinstance(data, str):
        return sanitize_string(data)
    return data


class JSONLogFormatter(logging.Formatter):
    """Formats log records as single-line structured JSON with correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_string(record.getMessage()),
            "module": record.module,
            "line": record.lineno,
        }

        # Attach request correlation ID if present
        corr_id = correlation_id_ctx.get() or getattr(record, "correlation_id", "")
        if corr_id:
            log_data["correlation_id"] = corr_id

        # Attach exception details if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class RingBufferHandler(logging.Handler):
    """Thread-safe logging handler appending formatted JSON lines to LOG_RING_BUFFER."""

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            LOG_RING_BUFFER.append(msg)
        except Exception:
            self.handleError(record)


_LOGGING_CONFIGURED = False


def setup_structured_logging():
    """Initializes structured logging and ring-buffer handler."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    json_formatter = JSONLogFormatter()

    # 1. Always attach the in-memory ring buffer handler so diagnostics can pull recent logs
    ring_handler = RingBufferHandler()
    ring_handler.setFormatter(json_formatter)
    ring_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.addHandler(ring_handler)

    # 2. Check if stdout JSON logging is active
    if os.environ.get("LOG_FORMAT", "").lower() == "json" or os.environ.get("STRUCTURED_LOGS", "") == "1":
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RingBufferHandler):
                handler.setFormatter(json_formatter)

    _LOGGING_CONFIGURED = True


def get_recent_logs(max_lines: int = 500) -> List[str]:
    """Returns the most recent log records from the in-memory ring buffer."""
    lines = list(LOG_RING_BUFFER)
    return lines[-max_lines:] if len(lines) > max_lines else lines

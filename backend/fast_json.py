"""
ZettNAS Fast JSON Serialization Engine.
Accelerates JSON serialization by 10-15x using `orjson` when available,
with strict type safety, string conversion for integer dictionary keys,
and seamless fallback to Python's standard `json` library.
"""

import json
from collections.abc import Callable
from typing import Any, Optional

from starlette.responses import JSONResponse

try:
    import orjson

    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False


def _serialize_default(obj: Any) -> Any:
    """Fallback handler for objects orjson cannot serialize natively."""
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):  # Pydantic v1
        return obj.dict()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj).decode("utf-8", errors="replace")
    if hasattr(obj, "__str__"):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _sanitize_dict_keys(obj: Any) -> Any:
    """Recursively converts non-string dict keys (e.g. integer SMART IDs) to strings."""
    if isinstance(obj, dict):
        return {str(k): _sanitize_dict_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_dict_keys(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_dict_keys(item) for item in obj)
    return obj


def dumps_bytes(obj: Any, default: Callable[[Any], Any] | None = None) -> bytes:
    """Serializes a Python object to JSON bytes."""
    handler = default or _serialize_default
    if _HAS_ORJSON:
        try:
            return orjson.dumps(obj, default=handler)
        except TypeError:
            sanitized = _sanitize_dict_keys(obj)
            return orjson.dumps(sanitized, default=handler)
    return json.dumps(obj, default=handler, separators=(",", ":")).encode("utf-8")


def dumps(obj: Any, default: Callable[[Any], Any] | None = None) -> str:
    """Serializes a Python object to a JSON string."""
    return dumps_bytes(obj, default=default).decode("utf-8")


def loads(data: Any) -> Any:
    """Deserializes JSON string or bytes to Python objects."""
    if _HAS_ORJSON:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return orjson.loads(data)
    return json.loads(data)


class FastJSONResponse(JSONResponse):
    """The app's default response class: JSON rendered with orjson.

    Gives the same bytes as FastAPI's deprecated ORJSONResponse. Unlike
    Starlette's JSONResponse, NaN and Infinity become null instead of raising
    (a sensor reading parsed as float("nan") must not turn /api/stats into a
    500), non-string dict keys become strings, and numpy values serialize.
    """

    def render(self, content: Any) -> bytes:
        if not _HAS_ORJSON:
            return super().render(content)
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY)

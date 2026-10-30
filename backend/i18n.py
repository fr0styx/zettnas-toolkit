"""The server's own text in the household's language (NUX-3).

Alerts pushed to a phone or sent by e-mail, and entries of the activity log, are written by the
server. They use the same strings as the interface: frontend/scripts/server-locales.mjs copies the
ones the server needs (alert.*, Drive Health's labels and findings) from frontend/src/locales into
backend/locales/<lang>.json, and a test keeps the copies in step.

t(key, default, params, lang) works like the interface's t(): {name} placeholders and ICU plurals
({n, plural, one {# drive} other {# drives}}). A key missing in a language falls back to English,
then to the default given.
"""

from __future__ import annotations

import json
import os
import re
from functools import cache, lru_cache
from typing import Any

LANGS = ("en", "de", "es", "fr", "zh")
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@cache
def strings(lang: str) -> dict[str, str]:
    """The server's strings in one language ({} when there are none)."""
    if lang not in LANGS:
        return {}
    try:
        with open(os.path.join(DIR, f"{lang}.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _category(lang: str, n: float) -> str:
    if lang == "zh":
        return "other"
    if lang == "fr":
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


def _closing(text: str, start: int) -> int:
    """The index of the brace that closes the one opened at text[start]."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _plurals(text: str, params: dict[str, Any], lang: str) -> str:
    out, i = [], 0
    while True:
        m = re.compile(r"\{(\w+),\s*plural,").search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out)
        end = _closing(text, m.start())
        if end < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i : m.start()])
        body = text[m.end() : end]
        options: dict[str, str] = {}
        j = 0
        while j < len(body):
            sel = re.compile(r"\s*(=\d+|zero|one|two|few|many|other)\s*\{").match(body, j)
            if not sel:
                break
            close = _closing(body, sel.end() - 1)
            options[sel.group(1)] = body[sel.end() : close]
            j = close + 1
        try:
            n = float(params.get(m.group(1), 0))
        except (TypeError, ValueError):
            n = 0
        exact = f"={int(n)}" if n == int(n) else ""
        chosen = options.get(exact) or options.get(_category(lang, n)) or options.get("other", "")
        shown = str(int(n)) if n == int(n) else str(n)
        out.append(_plurals(chosen, params, lang).replace("#", shown))
        i = end + 1


def fill(template: str, params: dict[str, Any] | None = None, lang: str = "en") -> str:
    params = params or {}
    text = _plurals(template, params, lang) if "plural," in template else template
    return _PLACEHOLDER.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), text)


def t(key: str, default: str = "", params: dict[str, Any] | None = None, lang: str = "en") -> str:
    """The string for key in lang, filled in; English, then `default`, when it is missing."""
    template = strings(lang).get(key) or strings("en").get(key) or default or key
    return fill(template, params, lang)


def ref(key: str, default: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """A value that is itself translated when filled in (a drive's label inside an alert's title).
    Stored in events as is, so the activity log shows it in the reader's language too."""
    return {"key": key, "default": default, "params": params or {}}


def resolve(params: dict[str, Any] | None, lang: str = "en") -> dict[str, Any]:
    """params with each ref() turned into its text in lang."""
    out = {}
    for k, v in (params or {}).items():
        if isinstance(v, dict) and "key" in v:
            out[k] = t(str(v["key"]), str(v.get("default") or ""), resolve(v.get("params"), lang), lang)
        else:
            out[k] = v
    return out


def text(key: str, default: str, params: dict[str, Any] | None = None, lang: str = "en") -> str:
    """t() with ref() values in params translated first."""
    return t(key, default, resolve(params, lang), lang)

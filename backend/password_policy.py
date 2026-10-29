"""What a new password must be (SEC-36): long enough, not the default, and not one of the
10,000 most common passwords (backend/resources/common-passwords.txt, from SecLists)."""

from __future__ import annotations

import functools
import os

from backend import config

COMMON_FILE = os.path.join(os.path.dirname(__file__), "resources", "common-passwords.txt")


@functools.lru_cache(maxsize=1)
def _common() -> frozenset[str]:
    try:
        with open(COMMON_FILE, encoding="utf-8") as f:
            return frozenset(line.strip() for line in f if line.strip() and not line.startswith("#"))
    except OSError:
        return frozenset()


def password_problem(password: str) -> str | None:
    """Why this password can't be used, in a sentence; None when it can."""
    pw = password or ""
    if len(pw) < config.MIN_PASSWORD_LENGTH:
        return f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters."
    if pw.lower() == "admin":
        return "Please choose a password other than the default."
    if pw.lower() in _common():
        return "That password is one of the 10,000 most used ones, so it is guessed first. Please choose another."
    return None

"""The short form of the old name, "zn", is gone from names (rebrand to Kiboto). Allowed: the
hardware runner's own folder, which lives inside its container, two values stored before 2.0.2
that are still read, and the release history."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = re.compile(r"(?<![A-Za-z0-9])zn(?=[-_][A-Za-z0-9])|znZoom|\bZN_[A-Z]")
ALLOWED = {
    ".github/workflows/hardware.yml": {"/opt/zn-eval"},  # the hardware-runner container's own folder
    "backend/passwords.py": {"WRAPPED_SHA256_BEFORE ="},  # hashes stored before 2.0.2 are still read
    "backend/services/photo_import.py": {'".kb-import", "." + "zn-import"'},  # an old staging folder is tidied
}
SKIP_DIRS = {".git", "node_modules", "static", "__pycache__", ".venv", "dist", "coverage"}
SKIP_FILES = {"CHANGELOG.md", "package-lock.json", "tests/test_no_zn_names.py"}
TEXT = {
    ".py",
    ".js",
    ".mjs",
    ".css",
    ".html",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".sh",
    ".toml",
    ".svg",
    ".txt",
    ".cfg",
    "",
}


def _files():
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or path.is_symlink() or not path.is_file():
            continue
        if path.suffix in TEXT and rel.as_posix() not in SKIP_FILES:
            yield rel.as_posix(), path


def test_no_zn_names_are_left():
    left = []
    for rel, path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.split("\n"), 1):
            if NAME.search(line) and not any(a in line for a in ALLOWED.get(rel, ())):
                left.append(f"{rel}:{n}: {line.strip()[:80]}")
    assert not left, "rename these to kb (Kiboto):\n" + "\n".join(left[:40])

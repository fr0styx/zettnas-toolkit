"""UX-2, UX-3: retired names stay out of text people read (see docs/GLOSSARY.md)."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETIRED = [r"hyper[- ]?backup"]
SOURCES = [
    "frontend/src/locales",
    "frontend/src/windows",
    "frontend/src/components",
    "docs/API.md",
    "docs/BACKUP_GUIDE.md",
]


def _files():
    for src in SOURCES:
        path = os.path.join(ROOT, src)
        if os.path.isfile(path):
            yield path
            continue
        for dirpath, _, names in os.walk(path):
            if "__tests__" in dirpath:
                continue
            for n in names:
                if n.endswith((".js", ".html", ".md")):
                    yield os.path.join(dirpath, n)


def _shown_text(line: str) -> str:
    """The part of a source line people can read: strings and markup text, not ids or code names."""
    line = re.sub(r"\b(id|class|data-[\w-]+|for|href)=\"[^\"]*\"", "", line)
    line = re.sub(r"#[\w-]+", "", line)  # selectors like '#btn-create-hyper-backup'
    line = re.sub(r"\b[\w.]+_hyper_backup[\w]*\b|\bhyper_backup[\w.]*", "", line)  # translation keys
    return re.sub(r"^\s*(//|<!--|\*).*$", "", line)  # comments


def test_retired_names_stay_out_of_the_interface():
    hits = []
    for path in _files():
        with open(path, encoding="utf-8") as f:
            for no, line in enumerate(f, 1):
                text = _shown_text(line)
                for pat in RETIRED:
                    if re.search(pat, text, re.IGNORECASE):
                        hits.append(f"{os.path.relpath(path, ROOT)}:{no}: {line.strip()[:120]}")
    assert not hits, "retired names (docs/GLOSSARY.md):\n" + "\n".join(hits)


def test_the_glossary_lists_what_the_test_enforces():
    with open(os.path.join(ROOT, "docs", "GLOSSARY.md"), encoding="utf-8") as f:
        glossary = f.read()
    assert "Hyper-Backup" in glossary and "test_glossary.py" in glossary

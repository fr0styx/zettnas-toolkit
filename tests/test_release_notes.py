"""The release job publishes the whole changelog entry for a tag."""

import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("ern", os.path.join(ROOT, "scripts", "extract_release_notes.py"))
ern = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ern)


def test_entry_keeps_subsections_and_stops_at_next_version():
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    from backend import __version__

    tag = f"v{__version__}"
    title, notes = ern.extract(text, tag, "fr0styx/zettnas-toolkit")
    assert title.startswith(f"{tag} - ")
    assert "#### " in notes  # subsections are kept
    assert "## v" not in notes and not notes.rstrip().endswith("---")
    assert "](docs/" not in notes and "](SECURITY.md" not in notes  # links are absolute


def test_unknown_tag_gives_empty_notes():
    assert ern.extract("## v1.0.0 (x)\n### hi\nbody\n", "v9.9.9") == ("v9.9.9", "")

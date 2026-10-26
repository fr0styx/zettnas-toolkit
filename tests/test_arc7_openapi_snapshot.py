"""ARC-7: the /api/v1 contract changes only on purpose."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import openapi_snapshot as snap  # noqa: E402


def test_the_v1_schema_matches_the_reviewed_snapshot():
    diff = snap.differences(snap.load(), snap.current())
    assert not diff, (
        "The /api/v1 contract changed. If intended, run: python scripts/openapi_snapshot.py --update "
        "(removed operations break API clients: note them in the release notes)\\n" + "\\n".join(diff[:20])
    )


def test_the_web_ui_alias_is_not_published():
    paths = snap.current()["paths"]
    assert any(p.startswith("/api/v1/") for p in paths)
    assert not [p for p in paths if p.startswith("/api/") and not p.startswith("/api/v1/")]


def test_differences_name_removed_and_added_operations():
    old = {"paths": {"/api/v1/a": {"get": {}}, "/api/v1/b": {"post": {}}}}
    new = {"paths": {"/api/v1/a": {"get": {}}, "/api/v1/c": {"get": {}}}}
    assert snap.differences(old, new) == ["removed: POST /api/v1/b", "added: GET /api/v1/c"]
    assert snap.differences(old, old) == []
    changed = {"paths": {"/api/v1/a": {"get": {"x": 1}}, "/api/v1/b": {"post": {}}}}
    assert snap.differences(old, changed) == ["changed: GET /api/v1/a"]

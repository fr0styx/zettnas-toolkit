"""Search speed-ups must return exactly what the slower code did."""

import math
import os
import random
import secrets

import pytest

from backend import config
from backend.services import share_access


def test_fast_cosine_matches_the_scaled_computation():
    from backend.services.rag_embeddings import _cosine_similarity_scaled, cosine_similarity_vec

    rng = random.Random(7)
    for dim_a, dim_b in ((768, 768), (768, 384), (384, 768), (3, 3)):
        for _ in range(50):
            a = [rng.uniform(-1, 1) for _ in range(dim_a)]
            b = [rng.uniform(-1, 1) for _ in range(dim_b)]
            assert cosine_similarity_vec(a, b) == pytest.approx(_cosine_similarity_scaled(a, b), abs=1e-12)
    # Cases the fast path hands to the scaled computation.
    for a, b in (
        ([1e160, 2e160], [1e160, 2e160]),
        ([1e-200, 3e-200], [2e-200, 6e-200]),
        ([float("nan"), 1.0], [1.0, 1.0]),
        ([1.0, 1.0, float("inf")], [1.0, 1.0]),
        ([0.0, 0.0], [1.0, 2.0]),
    ):
        assert cosine_similarity_vec(a, b) == _cosine_similarity_scaled(a, b)
    assert cosine_similarity_vec([1e-200, 3e-200], [2e-200, 6e-200]) == pytest.approx(1.0)
    assert math.isclose(cosine_similarity_vec([1e160, 2e160], [1e160, 2e160]), 1.0)


def _old_normalize(text):
    """The pre-optimisation text clean-up, kept here as the reference."""
    import re

    if not text:
        return ""
    s = str(text).lstrip()
    if s.startswith("["):
        end_bracket = s.find("]", 0, 220)
        if end_bracket > 0:
            s = s[end_bracket + 1 :].lstrip()
    s = re.sub(r"^`?\]\s*", "", s)
    s = re.sub(r"\\[0-7]{3}", " ", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", s)
    for _ in range(2):
        s = re.sub(r"([A-Za-zÀ-ÿ])-?[ \t]*\n[ \t]*([a-zà-ÿ])", r"\1\2", s)
    collapsed = re.sub(r"\s+", " ", s).strip()
    words = []
    for tok in collapsed.split(" "):
        if re.search(r"[®¤µ×÷þÿ¶§ª«¬¯±²³´¸¹º»¼½¾]", tok):
            continue
        if re.search(r"[A-Za-z0-9][@#$%^&*_+=<>|\\~`]+[A-Za-z0-9#]*|[A-Z0-9]{2,}#", tok):
            continue
        if re.search(r"\d", tok) and re.search(r"[^\x00-\x7f]", tok):
            continue
        words.append(tok)
    return " ".join(words).strip()


@pytest.mark.parametrize(
    "text",
    [
        "Health Car\ne and car\nrot, La id\nea, bus\ncar",
        "[Guide > Setup] `] Install \\222 the\x07 app id\ne\na",
        "price 12€ and 3½ cups ® token a@b C0DE# x_y back\\slash ~tilde `tick`",
        "  plain words only  ",
        "Straße 7ü naïve café 中文 العربية ٣",
        "",
    ],
)
def test_text_cleanup_matches_the_old_implementation(text):
    from backend.services.rag_text import _normalize_pdf_broken_words

    assert _normalize_pdf_broken_words(text) == _old_normalize(text)


def test_word_match_is_unchanged():
    from backend.services.rag_text import _token_matches_word

    assert _token_matches_word("car", "two cars here")
    assert not _token_matches_word("car", "removecards")
    assert _token_matches_word("cars", "a car")
    assert _token_matches_word("network", "networking guide")
    assert _token_matches_word("中文", "这是中文")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    name = f"sp{secrets.token_hex(3)}"
    root = tmp_path / "user"
    files = []
    for rel in (
        "media/a.mp3",
        "private/b.txt",
        f"homes/{name}/c.txt",
        "homes/bob/d.txt",
        "loose.txt",
        "appdata/app/e.txt",
        "media/sub/f.txt",
    ):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        files.append(str(p))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr("backend.api.fs.ALLOWED_BROWSE_ROOTS", [str(root)])
    monkeypatch.setattr(
        share_access,
        "known_shares",
        lambda: [
            {"name": "media", "path": str(root / "media"), "samba": None},
            {
                "name": "private",
                "path": str(root / "private"),
                "samba": {"valid": {"bob"}, "read": set(), "write": set(), "read_only": False},
            },
        ],
    )
    share_access.invalidate()
    return name, files


def test_index_path_check_agrees_with_the_full_check_without_touching_disks(tree, monkeypatch):
    from backend.api.fs import indexed_path_checker, user_can_access_path
    from backend.auth import AuthenticatedPrincipal

    name, files = tree
    user = AuthenticatedPrincipal(
        {"user_id": "u", "username": name, "role_id": "share_user", "scopes": ["shares:read"]}
    )
    expected = {p: user_can_access_path(p, user) for p in files}
    assert any(expected.values()) and not all(expected.values())

    checker = indexed_path_checker(user)

    def no_disk(*_a, **_k):
        raise AssertionError("the index path check touched the disk")

    monkeypatch.setattr(os.path, "realpath", no_disk)
    monkeypatch.setattr(os, "lstat", no_disk)
    monkeypatch.setattr(os, "stat", no_disk)
    assert {p: checker(p) for p in files} == expected


def test_newest_chunks_index_exists(tmp_path):
    from backend.services.rag_engine import RagSearchEngine

    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    engine._ensure_schema()
    conn = engine._get_conn(readonly=True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()
    assert "idx_chunks_file_level" in names

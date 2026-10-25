"""AI-10: shared folders are filtered by the person's access inside the search query."""

from types import SimpleNamespace


def test_the_search_filter_names_only_the_persons_readable_shares(monkeypatch):
    from backend.services import rag_engine_search, share_access

    monkeypatch.setattr(share_access, "known_shares", lambda: [{"name": "Family"}, {"name": "Work"}])
    monkeypatch.setattr(
        share_access,
        "grants_for",
        lambda u: [("/mnt/user/homes/kim", "write"), ("/mnt/user/Family", "read"), ("/mnt/user/Work", "none")],
    )
    kid = SimpleNamespace(role_id="kid", username="kim", has_any_scope=lambda *s: False)
    sql, params = rag_engine_search.RagSearchMixin._build_rbac_clause(kid, "f")
    assert "f.share_name IN (?)" in sql and params[0] == "family" and "work" not in params


def test_without_known_shares_the_old_rule_stays(monkeypatch):
    from backend.services import rag_engine_search, share_access

    monkeypatch.setattr(share_access, "known_shares", lambda: [])
    user = SimpleNamespace(role_id="share_user", username="kim", has_any_scope=lambda *s: False)
    sql, params = rag_engine_search.RagSearchMixin._build_rbac_clause(user, "f")
    assert "share_name IN" not in sql and params == ["kim", "kim"]

"""Missing features 6 and 7: Previous versions from snapshots, and Ask Zetty about a file."""

import os
import uuid

import pytest


def _read(path):
    with open(path) as f:
        return f.read()


def _write(path, text, mtime):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.utime(path, (mtime, mtime))


def _outside(pool_tree):
    return os.path.join(os.path.dirname(pool_tree), "outside")


@pytest.fixture
def zfs_share(pool_tree):
    """A share with ZFS-style snapshots: two older versions, one identical to today's file."""
    share = os.path.join(pool_tree, "zv-" + uuid.uuid4().hex[:6])
    _write(os.path.join(share, "docs", "plan.txt"), "version three", 3000)
    snaps = os.path.join(share, ".zfs", "snapshot")
    _write(os.path.join(snaps, "auto-1", "docs", "plan.txt"), "version one", 1000)
    _write(os.path.join(snaps, "auto-2", "docs", "plan.txt"), "version two", 2000)
    _write(os.path.join(snaps, "auto-3", "docs", "plan.txt"), "version three", 3000)  # same as today
    os.makedirs(os.path.join(snaps, "auto-0"))  # the file didn't exist yet
    for i, name in enumerate(("auto-0", "auto-1", "auto-2", "auto-3")):
        os.utime(os.path.join(snaps, name), (500 + i * 1000, 500 + i * 1000))
    return share


def test_versions_are_the_differing_snapshot_copies(client, auth_headers, zfs_share):
    path = os.path.join(zfs_share, "docs", "plan.txt")
    r = client.get("/api/fs/versions", params={"path": path}, headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = [v["id"] for v in r.json()["versions"]]
    assert ids == ["zfs:auto-2", "zfs:auto-1"]  # newest first; the copy equal to today is left out
    r = client.get("/api/fs/versions/download", params={"path": path, "version": "zfs:auto-1"}, headers=auth_headers)
    assert r.status_code == 200 and r.content == b"version one"


def test_restore_a_copy_beside_or_in_place(client, auth_headers, zfs_share):
    path = os.path.join(zfs_share, "docs", "plan.txt")
    r = client.post("/api/fs/versions/restore", json={"path": path, "version": "zfs:auto-2"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    copy = r.json()["path"]
    assert os.path.basename(copy).startswith("plan (version ") and _read(copy) == "version two"
    again = client.post("/api/fs/versions/restore", json={"path": path, "version": "zfs:auto-2"}, headers=auth_headers)
    assert again.json()["path"] != copy  # a second copy never overwrites the first
    r = client.post(
        "/api/fs/versions/restore",
        json={"path": path, "version": "zfs:auto-1", "overwrite": True},
        headers=auth_headers,
    )
    assert r.status_code == 200 and _read(path) == "version one"


def test_versions_refuse_outside_paths_and_unknown_versions(client, auth_headers, zfs_share, pool_tree):
    r = client.get(
        "/api/fs/versions", params={"path": os.path.join(_outside(pool_tree), "secret", "x")}, headers=auth_headers
    )
    assert r.status_code == 403
    path = os.path.join(zfs_share, "docs", "plan.txt")
    r = client.get("/api/fs/versions/download", params={"path": path, "version": "zfs:../../etc"}, headers=auth_headers)
    assert r.status_code == 404
    r = client.post("/api/fs/versions/restore", json={"path": path, "version": "zfs:nope"}, headers=auth_headers)
    assert r.status_code == 404
    r = client.get("/api/fs/versions", params={"path": "\x00"}, headers=auth_headers)
    assert r.status_code in (400, 422)


def test_a_deleted_file_lists_every_kept_copy(zfs_share):
    from backend.services import file_versions

    path = os.path.join(zfs_share, "docs", "plan.txt")
    os.remove(path)
    assert [v["id"] for v in file_versions.list_versions(path)] == ["zfs:auto-3", "zfs:auto-2", "zfs:auto-1"]


def test_files_outside_zfs_have_no_zfs_versions(tmp_path):
    from backend.services import file_versions

    f = tmp_path / "a" / "b.txt"
    f.parent.mkdir()
    f.write_text("x")
    assert file_versions._zfs_candidates(str(f)) == []


def test_btrfs_share_snapshots_are_versions_too(tmp_path, monkeypatch):
    from backend.services import file_versions, snapshot_service

    live = tmp_path / "pool" / "photos"
    _write(str(live / "cat.jpg"), "new", 2000)
    snap = tmp_path / "pool" / ".snapshots" / "photos@auto-20260101-0000"
    _write(str(snap / "cat.jpg"), "old", 1000)

    class Share:
        name = "photos"
        mountpoint = str(live)

    class Pal:
        def list_pools(self):
            return []

        def list_snapshots(self, pool_id):
            return [
                {"name": "photos@auto-20260101-0000", "path": str(snap), "created_at": 1500},
                {"name": "gone@auto-1", "path": str(snap), "created_at": 1},
                {"name": "", "path": ""},
            ]

        def list_shares(self):
            return [Share()]

        def get_pool_path(self, pool_id):
            return str(tmp_path / "nowhere")

    monkeypatch.setattr(snapshot_service, "_pal", lambda: Pal())
    out = file_versions.list_versions(str(live / "cat.jpg"))
    assert [v["id"] for v in out] == ["btrfs:photos@auto-20260101-0000"]
    monkeypatch.setattr(snapshot_service, "_pal", lambda: (_ for _ in ()).throw(RuntimeError("no pal")))
    assert file_versions._btrfs_candidates(str(live / "cat.jpg")) == []


def test_ask_zetty_about_a_file_scopes_the_search(monkeypatch):
    """The file in focus becomes the search scope for that turn only."""
    from backend.services import chat_nas_tools
    from backend.services.chat_nas_tools import FOCUS_PATH

    seen = {}

    class Stop(Exception):
        pass

    class Rag:
        def ask(self, **kw):
            seen.update(kw)
            raise Stop

    monkeypatch.setattr(
        chat_nas_tools, "_core", lambda: type("C", (), {"get_rag_engine": staticmethod(lambda: Rag())})()
    )
    token = FOCUS_PATH.set("/mnt/user/docs/plan.txt")
    try:
        with pytest.raises(Stop):
            chat_nas_tools.tool_search_nas_knowledge("what is the budget?")
    finally:
        FOCUS_PATH.reset(token)
    assert seen["path_prefix"] == "/mnt/user/docs/plan.txt"
    seen.clear()
    with pytest.raises(Stop):
        chat_nas_tools.tool_search_nas_knowledge("what is the budget?")
    assert seen["path_prefix"] is None


def test_the_focus_reaches_the_turn_and_no_further(monkeypatch):
    from backend.services import ai_chat_agent
    from backend.services.chat_nas_tools import FOCUS_PATH

    seen = []
    monkeypatch.setattr(
        ai_chat_agent, "_run_agentic_chat_turn", lambda *a: seen.append(FOCUS_PATH.get()) or {"reply": "ok"}
    )
    ai_chat_agent.run_agentic_chat("hi", focus_path="/mnt/user/a.txt")
    assert seen == ["/mnt/user/a.txt"] and FOCUS_PATH.get() is None


def test_asking_about_a_file_you_cannot_read_is_refused(client, auth_headers, pool_tree):
    r = client.post(
        "/api/media/chat",
        json={"message": "what is in it?", "focus_path": os.path.join(_outside(pool_tree), "secret")},
        headers=auth_headers,
    )
    assert r.status_code == 403

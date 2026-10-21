"""SEC-11: mutations need the right scope; transfers belong to whoever started them."""

import pytest

from backend.services.fs_transfer import transfer_manager

ROLES = {
    "auditor": ["*:read", "system:view"],
    "share_user": ["shares:read", "shares:user_write", "system:view"],
}


@pytest.fixture
def as_role(monkeypatch):
    def use(role, username=None):
        monkeypatch.setattr(
            "backend.auth.get_current_session",
            lambda tok: {
                "user_id": f"u_{username or role}",
                "username": username or role,
                "role_id": role,
                "scopes": ROLES[role],
            },
        )
        return {"Authorization": "Bearer x"}

    return use


def test_auditor_cannot_clear_the_event_log(client, as_role):
    assert client.delete("/api/events/clear", headers=as_role("auditor")).status_code == 403


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/ai/models/huggingface/pull", {"repo_id": "x/y"}),
        ("/api/ai/models/remove", {"model": "llama"}),
        ("/api/ai/models/select", {"model": "llama"}),
        ("/api/ai/index/control", {"action": "pause"}),
        ("/api/ai/folders", {"folders": ["/"]}),
    ],
)
def test_share_users_cannot_manage_ai_models_or_indexing(client, as_role, path, body):
    assert client.post(path, json=body, headers=as_role("share_user")).status_code == 403


def test_transfers_are_private_to_their_owner(client, as_role, tmp_path):
    task = transfer_manager.submit_archive_extract(str(tmp_path / "missing.tar"), str(tmp_path / "out"), owner="alice")
    bob = as_role("share_user", "bob")
    listed = client.get("/api/fs/transfers", headers=bob).json()["tasks"]
    assert all(t["id"] != task.id for t in listed)
    for verb in ("pause", "resume", "cancel"):
        assert client.post(f"/api/fs/transfers/{task.id}/{verb}", headers=bob).status_code == 404
    alice = as_role("share_user", "alice")
    assert any(t["id"] == task.id for t in client.get("/api/fs/transfers", headers=alice).json()["tasks"])

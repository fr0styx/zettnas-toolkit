"""Password hashing, filesystem helpers and the night-window helper."""

import hashlib
import json
import os

import pytest

from backend.fsutil import atomic_write_json, read_json, resolve_within, root_for
from backend.hardware.screen import is_in_time_window
from backend.passwords import hash_password, is_legacy_hash, verify_password

# ---- passwords ----


def test_hash_format_is_scrypt():
    h = hash_password("correct horse")
    assert h.startswith("$argon2id$") or (h.startswith("scrypt$") and len(h.split("$")) == 6)


def test_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_verify_roundtrip():
    h = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)


def test_legacy_sha256_hash_still_verifies():
    legacy = hashlib.sha256(b"oldpass").hexdigest()
    assert is_legacy_hash(legacy)
    assert verify_password("oldpass", legacy)
    assert not verify_password("nope", legacy)


def test_scrypt_hash_is_not_legacy():
    assert not is_legacy_hash(hash_password("x"))


@pytest.mark.parametrize("stored", ["", None, "garbage", "scrypt$bad", "scrypt$1$2$3$zz$zz"])
def test_malformed_hashes_never_verify(stored):
    assert verify_password("anything", stored) is False


# ---- atomic JSON ----


def test_atomic_write_and_read(tmp_path):
    fp = tmp_path / "state.json"
    atomic_write_json(str(fp), {"a": 1})
    assert read_json(str(fp)) == {"a": 1}


def test_atomic_write_leaves_no_temp_files(tmp_path):
    fp = tmp_path / "state.json"
    for i in range(5):
        atomic_write_json(str(fp), {"i": i})
    assert sorted(os.listdir(tmp_path)) == ["state.json"]


def test_atomic_write_failure_keeps_old_file(tmp_path):
    fp = tmp_path / "state.json"
    atomic_write_json(str(fp), {"ok": True})
    with pytest.raises(TypeError):
        atomic_write_json(str(fp), {"bad": object()})
    assert json.loads(fp.read_text()) == {"ok": True}
    assert sorted(os.listdir(tmp_path)) == ["state.json"]


def test_atomic_write_creates_parent_dirs(tmp_path):
    fp = tmp_path / "nested" / "dir" / "x.json"
    atomic_write_json(str(fp), [1, 2])
    assert read_json(str(fp)) == [1, 2]


def test_read_json_defaults(tmp_path):
    assert read_json(str(tmp_path / "missing.json"), {"d": 1}) == {"d": 1}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert read_json(str(bad), []) == []


# ---- path containment ----


def test_resolve_within_accepts_root_and_children(pool_tree):
    assert resolve_within(pool_tree, [pool_tree]) == os.path.realpath(pool_tree)
    assert resolve_within(os.path.join(pool_tree, "media"), [pool_tree]).endswith("/media")


def test_resolve_within_rejects_dotdot_escape(pool_tree):
    assert resolve_within(os.path.join(pool_tree, "..", "outside"), [pool_tree]) is None


def test_resolve_within_rejects_symlink_escape(pool_tree):
    assert resolve_within(os.path.join(pool_tree, "escape", "secret"), [pool_tree]) is None


def test_resolve_within_rejects_sibling_prefix(pool_tree):
    # "/x/pool-evil" must not match root "/x/pool".
    sibling = pool_tree.rstrip("/") + "-evil"
    os.makedirs(sibling, exist_ok=True)
    assert resolve_within(sibling, [pool_tree]) is None


def test_resolve_within_empty_path():
    assert resolve_within("", ["/"]) is None


def test_root_for(pool_tree):
    real = os.path.realpath(os.path.join(pool_tree, "media"))
    assert root_for(real, [pool_tree]) == os.path.realpath(pool_tree)
    assert root_for("/definitely/elsewhere", [pool_tree]) is None


# ---- night window ----


@pytest.mark.parametrize(
    "start,end,now,expected",
    [
        ("09:00", "17:00", 12 * 60, True),
        ("09:00", "17:00", 17 * 60, False),  # end is exclusive
        ("23:00", "07:00", 23 * 60 + 30, True),  # wraps midnight
        ("23:00", "07:00", 3 * 60, True),
        ("23:00", "07:00", 12 * 60, False),
        ("bad", "07:00", 0, False),
    ],
)
def test_is_in_time_window(start, end, now, expected):
    assert is_in_time_window(start, end, now_minutes=now) is expected


# ---- hostname resolution & container ID suppression ----


def test_is_container_id():
    from backend.config import _is_container_id

    assert _is_container_id("425dae47b7b9") is True
    assert _is_container_id("425DAE47B7B9") is True
    assert _is_container_id("a" * 64) is True
    assert _is_container_id("") is True
    assert _is_container_id(None) is True
    assert _is_container_id("Ark") is False
    assert _is_container_id("ZettNAS") is False
    assert _is_container_id("my-homelab-server") is False


def test_get_server_hostname_env_override(monkeypatch):
    from backend.config import clear_hostname_cache, get_server_hostname

    clear_hostname_cache()
    monkeypatch.setenv("NAS_NAME", "IronVault")
    assert get_server_hostname() == "IronVault"


def test_get_server_hostname_suppresses_container_id(monkeypatch, tmp_path):
    from backend.config import clear_hostname_cache, get_server_hostname

    clear_hostname_cache()
    monkeypatch.delenv("NAS_NAME", raising=False)

    # Mock socket hostname to a 12-char docker container ID
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: "425dae47b7b9")

    # Mock docker socket not found
    import os

    real_exists = os.path.exists

    def mock_exists(p):
        if p == "/var/run/docker.sock":
            return False
        return real_exists(p)

    monkeypatch.setattr(os.path, "exists", mock_exists)

    # Should NOT return 425DAE47B7B9, should fallback cleanly to ZettNAS
    assert get_server_hostname() == "ZettNAS"


def test_get_server_hostname_unraid_ident(monkeypatch, tmp_path):
    from backend.config import clear_hostname_cache, get_server_hostname

    clear_hostname_cache()
    monkeypatch.delenv("NAS_NAME", raising=False)

    ident_file = tmp_path / "ident.cfg"
    ident_file.write_text('NAME="Ark"\nCOMMENT="Main Storage"\n')

    import os

    real_exists = os.path.exists

    def mock_exists(p):
        if p == "/boot/config/ident.cfg":
            return True
        if p == "/var/run/docker.sock":
            return False
        return real_exists(p)

    monkeypatch.setattr(os.path, "exists", mock_exists)

    import builtins

    real_open = builtins.open

    def mock_open(file, *args, **kwargs):
        if file == "/boot/config/ident.cfg":
            return real_open(str(ident_file), *args, **kwargs)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", mock_open)

    assert get_server_hostname() == "Ark"

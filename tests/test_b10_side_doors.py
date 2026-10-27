"""B10 / SEC-20, SEC-28: SFTP accounts and SMB shares can never reach ZettNAS's own data folder."""

import io
import json
import os

import pytest

from backend import config, fsutil
from backend.passwords import hash_password


@pytest.fixture
def pool(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    install = pool / "appdata" / "zettnas-toolkit"
    data = install / "data"
    data.mkdir(parents=True)
    (install / "docker-compose.yml").write_text("services: {}\n")
    (pool / "photos").mkdir()
    (pool / "appdata" / "immich").mkdir()
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "POOL_PATH", str(pool))
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    fsutil.reset_protected_dirs()
    yield {"pool": str(pool), "data": str(data), "install": str(install)}
    fsutil.reset_protected_dirs()


def test_serve_roots_never_include_the_data_folder(pool):
    p = pool["pool"]
    real = os.path.realpath
    assert fsutil.safe_serve_root(p, p) == real(p)  # the pool root: its serve command hides the app folders
    assert fsutil.safe_serve_root(os.path.join(p, "photos"), p) == real(os.path.join(p, "photos"))
    assert fsutil.safe_serve_root(os.path.join(p, "appdata", "immich"), p)  # another app's folder is fine
    for bad in (
        pool["data"],  # the data folder itself
        pool["install"],  # the install folder (compose file, .env)
        os.path.join(p, "appdata"),  # a folder that holds it
        os.path.join(p, "photos", "..", "appdata", "zettnas-toolkit", "data"),
        "/",
        "/etc",
        "",
    ):
        assert fsutil.safe_serve_root(bad, p) is None, bad


def test_an_sftp_account_cannot_be_given_the_data_folder(pool, monkeypatch, tmp_path):
    from backend.services import sftp_engine

    monkeypatch.setattr(sftp_engine, "SFTP_USERS_FILE", str(tmp_path / "users.json"))
    engine = sftp_engine.SftpEngine() if hasattr(sftp_engine, "SftpEngine") else sftp_engine.get_sftp_engine()
    for bad in (pool["data"], os.path.join(pool["pool"], "appdata"), "appdata/zettnas-toolkit"):
        with pytest.raises(ValueError, match="cannot be shared"):
            engine.add_user({"username": "mallory", "password": "x" * 12, "shares": [bad]})
    ok = engine.add_user({"username": "aunt", "password": "x" * 12, "shares": ["photos"]})
    assert ok["shares"] == ["photos"]


def _sign_in(monkeypatch, capsys, username, password):
    from backend.services import rclone_auth_proxy as proxy

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"user": username, "pass": password})))
    with pytest.raises(SystemExit) as e:
        proxy.main()
    out = capsys.readouterr().out
    return e.value.code, (json.loads(out) if out else None)


def _store(pool, accounts):
    path = os.path.join(pool["data"], "sftp")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "users.json"), "w") as f:
        json.dump(accounts, f)


def test_an_account_already_pointing_at_the_data_folder_is_refused_at_sign_in(pool, monkeypatch, capsys):
    pw = hash_password("correct horse")
    _store(
        pool,
        [
            {"username": "mallory", "password": pw, "shares": [pool["data"]], "enabled": True},
            {"username": "wide", "password": pw, "shares": [os.path.join(pool["pool"], "appdata")], "enabled": True},
            {"username": "aunt", "password": pw, "shares": ["photos"], "enabled": True},
        ],
    )
    code, cfg = _sign_in(monkeypatch, capsys, "mallory", "correct horse")
    assert code == 1 and cfg is None
    code, cfg = _sign_in(monkeypatch, capsys, "wide", "correct horse")
    assert code == 1 and cfg is None
    code, cfg = _sign_in(monkeypatch, capsys, "aunt", "correct horse")
    assert code == 0 and cfg["_root"] == os.path.realpath(os.path.join(pool["pool"], "photos"))


def test_several_shares_are_linked_from_outside_the_data_folder(pool, monkeypatch, capsys):
    (Path := __import__("pathlib").Path)(pool["pool"], "music").mkdir()
    pw = hash_password("correct horse")
    _store(pool, [{"username": "aunt", "password": pw, "shares": ["photos", "music", pool["data"]], "enabled": True}])
    code, cfg = _sign_in(monkeypatch, capsys, "aunt", "correct horse")
    assert code == 0
    root = cfg["_root"]
    assert not root.startswith(os.path.realpath(pool["data"]))
    assert sorted(os.listdir(root)) == ["music", "photos"]  # the data folder was dropped, the rest linked
    assert Path(root, "photos").resolve() == Path(pool["pool"], "photos").resolve()


def test_smb_shares_cannot_be_the_data_folder_and_hide_it_when_they_hold_it(pool):
    from backend.services import samba_engine

    with pytest.raises(ValueError, match="own data folder"):
        samba_engine.validate_share_path(pool["data"])
    with pytest.raises(ValueError, match="own data folder"):
        samba_engine.validate_share_path(pool["install"])
    assert samba_engine.validate_share_path(os.path.join(pool["pool"], "photos"))
    # a share of the whole pool hides the install folder (and with it the data folder)
    assert samba_engine.protected_veto_names(pool["pool"]) == ["zettnas-toolkit"]
    assert samba_engine.protected_veto_names(os.path.join(pool["pool"], "photos")) == []

"""B11 (D1, SEC-21/22/23, SEC-30 auditor): new installs start safe; upgraded installs keep their
settings, and the Security Advisor offers a confirmed one-click fix for each looser one."""

import json
import os

import pytest

from backend import config
from backend.api.storage import StorageShareCreateRequest, nfs_clients_for
from backend.services import install_defaults, nfs_engine, safe_defaults_advisor, samba_engine, share_access
from backend.services.nfs_engine import NfsExportRule
from backend.services.samba_engine import SambaShareConfig
from backend.users_db import create_user, users_db_session


def _raw_share_access():
    path = share_access._file()
    return json.load(open(path)) if os.path.exists(path) else {}


def _forget_marker():
    if os.path.exists(install_defaults._marker()):
        os.remove(install_defaults._marker())


# --- new vs upgraded install -------------------------------------------------------------------


def test_an_upgraded_install_keeps_write_access_written_down_once():
    _forget_marker()
    if os.path.exists(share_access._file()):
        os.remove(share_access._file())
    assert install_defaults.apply_once(existing_install=True) is True
    assert _raw_share_access()["default_level"] == "write"
    assert install_defaults.is_existing_install() is True
    assert share_access.load_config()["default_level"] == "write"
    # it runs once: a later admin choice is never overwritten
    share_access.save_config({"default_level": "none", "shares": {}})
    assert install_defaults.apply_once(existing_install=True) is False
    assert share_access.load_config()["default_level"] == "none"


def test_an_upgraded_install_keeps_a_level_it_already_chose():
    _forget_marker()
    share_access.save_config({"default_level": "read", "shares": {}})
    install_defaults.apply_once(existing_install=True)
    assert share_access.load_config()["default_level"] == "read"


def test_a_new_install_starts_with_no_share_access():
    _forget_marker()
    if os.path.exists(share_access._file()):
        os.remove(share_access._file())
    install_defaults.apply_once(existing_install=False)
    assert install_defaults.is_existing_install() is False
    assert not os.path.exists(share_access._file())
    assert share_access.load_config()["default_level"] == "none"


# --- share access by role -----------------------------------------------------------------------


@pytest.fixture
def shares(tmp_path, monkeypatch):
    root = tmp_path / "user"
    (root / "media").mkdir(parents=True)
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr(
        share_access, "known_shares", lambda: [{"name": "media", "path": str(root / "media"), "samba": None}]
    )
    share_access.invalidate()
    return root


def test_role_defaults_close_shares_for_kids_but_not_for_others(shares):
    create_user("kiddo", "Kiddo", "GoodPass123!", role_id="kid")
    create_user("parent", "Parent", "GoodPass123!", role_id="share_user")
    share_access.save_config({"default_level": "write", "role_defaults": {"kid": "none"}, "shares": {}})
    media = str(shares / "media")
    assert (media, "none") in share_access.grants_for("kiddo")
    assert (media, "write") in share_access.grants_for("parent")
    # a grant for the person still wins over their role's default
    share_access.save_config(
        {"default_level": "write", "role_defaults": {"kid": "none"}, "shares": {"media": {"users": {"kiddo": "read"}}}}
    )
    assert (media, "read") in share_access.grants_for("kiddo")


def test_role_defaults_are_validated():
    with pytest.raises(ValueError):
        share_access.save_config({"default_level": "none", "role_defaults": {"kid": "everything"}, "shares": {}})


def test_saving_shares_alone_keeps_the_default_and_role_defaults(client, auth_headers, shares):
    share_access.save_config({"default_level": "write", "role_defaults": {"guest": "none"}, "shares": {}})
    res = client.put(
        "/api/storage/share-access", json={"shares": {"media": {"users": {"Ann": "read"}}}}, headers=auth_headers
    )
    assert res.status_code == 200, res.text
    got = client.get("/api/storage/share-access", headers=auth_headers).json()
    assert got["default_level"] == "write" and got["role_defaults"] == {"guest": "none"}
    assert got["shares"][0]["users"] == {"ann": "read"}


# --- shares: private, root squashed, this network --------------------------------------------


def test_a_new_share_is_private_and_nfs_is_squashed_and_local_by_default():
    req = StorageShareCreateRequest(name="photos")
    assert req.security == "private"
    assert req.nfs_squash == "root_squash"
    assert req.nfs_clients == "" and req.nfs_allow_everyone is False
    assert NfsExportRule(name="x", path="/mnt/user/x").insecure is False


def test_nfs_reaches_every_host_only_when_chosen(monkeypatch):
    monkeypatch.setattr(nfs_engine, "home_network", lambda: "192.168.7.0/24")
    assert nfs_clients_for("", False) == "192.168.7.0/24"
    assert nfs_clients_for("*", False) == "192.168.7.0/24"
    assert nfs_clients_for("*", True) == "*"
    assert nfs_clients_for(" 10.0.0.0/8 ", False) == "10.0.0.0/8"


def test_home_network_is_the_nas_own_slash_24(monkeypatch):
    from backend.hardware.net import topology

    monkeypatch.setattr(topology, "read_ip", lambda: "192.168.5.20")
    assert nfs_engine.home_network() == "192.168.5.0/24"
    monkeypatch.setattr(topology, "read_ip", lambda: None)
    assert nfs_engine.home_network() == "127.0.0.1"
    monkeypatch.setattr(topology, "read_ip", lambda: "127.0.1.1")
    assert nfs_engine.home_network() == "127.0.0.1"


def _samba(tmp_path, monkeypatch, shares):
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    monkeypatch.setattr(samba_engine, "validate_share", lambda share: None)
    engine = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    engine._shares = {s.name: s for s in shares}
    return engine


def test_samba_refuses_wrong_passwords_instead_of_mapping_them_to_guest(tmp_path, monkeypatch):
    path = str(tmp_path)
    conf = _samba(tmp_path, monkeypatch, [SambaShareConfig(name="a", path=path)]).generate_and_save_conf()
    assert "map to guest = Never" in conf and "Bad User" not in conf
    conf = _samba(
        tmp_path, monkeypatch, [SambaShareConfig(name="a", path=path, guest_ok=True)]
    ).generate_and_save_conf()
    assert "map to guest = Bad User" in conf


# --- auditor ---------------------------------------------------------------------------------


def _auditor_scopes():
    with users_db_session() as conn:
        return json.loads(conn.execute("SELECT scopes_json FROM roles WHERE id = 'auditor'").fetchone()[0])


def test_a_new_install_auditor_reads_system_status_only():
    scopes = _auditor_scopes()
    assert "*:read" not in scopes
    assert scopes == install_defaults.SAFE_AUDITOR_SCOPES


# --- Security Advisor findings and fixes -------------------------------------------------------


def _ids():
    return {f["id"] for f in safe_defaults_advisor.findings()}


def test_family_share_access_finding_and_fix(shares, monkeypatch):
    share_access.save_config({"default_level": "write", "shares": {}})
    with monkeypatch.context() as m:
        m.setattr(safe_defaults_advisor, "_family_users", lambda: [])
        assert "share_access_family" not in _ids()  # no kids or guests: nothing to warn about
    create_user("kid2", "Kid Two", "GoodPass123!", role_id="kid")
    assert "share_access_family" in _ids()
    safe_defaults_advisor.apply_fix("share_access_family")
    cfg = share_access.load_config()
    assert cfg["default_level"] == "write"  # everyone else keeps what they had
    assert cfg["role_defaults"] == {"kid": "none", "guest": "none"}
    assert "share_access_family" not in _ids()


def test_auditor_finding_and_fix():
    with users_db_session() as conn:
        conn.execute("UPDATE roles SET scopes_json = ? WHERE id = 'auditor'", (json.dumps(["*:read"]),))
    assert "auditor_reads_everything" in _ids()
    safe_defaults_advisor.apply_fix("auditor_reads_everything")
    assert _auditor_scopes() == install_defaults.SAFE_AUDITOR_SCOPES
    assert "auditor_reads_everything" not in _ids()


class _FakeNfs:
    def __init__(self, rules):
        self.rules = {r.name: r for r in rules}

    def list_exports(self):
        return list(self.rules.values())

    def add_or_update_export(self, rule):
        self.rules[rule.name] = rule


def test_open_nfs_export_finding_and_fix(monkeypatch):
    fake = _FakeNfs(
        [
            NfsExportRule(name="k8s", path="/mnt/user/k8s", clients="*", squash="no_root_squash"),
            NfsExportRule(name="ok", path="/mnt/user/ok", clients="10.0.0.0/8"),
        ]
    )
    monkeypatch.setattr(nfs_engine, "get_nfs_engine", lambda: fake)
    monkeypatch.setattr(nfs_engine, "home_network", lambda: "192.168.7.0/24")
    found = [f for f in safe_defaults_advisor.findings() if f["id"] == "nfs_open_exports"]
    assert found and "k8s" in found[0]["details"] and "ok (" not in found[0]["details"]
    assert "k8s" in safe_defaults_advisor.apply_fix("nfs_open_exports")
    assert fake.rules["k8s"].clients == "192.168.7.0/24" and fake.rules["k8s"].squash == "root_squash"
    assert fake.rules["ok"].clients == "10.0.0.0/8"
    assert "nfs_open_exports" not in _ids()


def test_smb_guest_fix_makes_guest_shares_private(tmp_path, monkeypatch):
    engine = _samba(
        tmp_path,
        monkeypatch,
        [
            SambaShareConfig(name="open", path=str(tmp_path), guest_ok=True),
            SambaShareConfig(name="p", path=str(tmp_path)),
        ],
    )
    saved = []
    monkeypatch.setattr(engine, "add_or_update_share", lambda share: saved.append(share) or share, raising=False)
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: engine)
    assert "open" in safe_defaults_advisor.apply_fix("smb_guest_access")
    assert [(s.name, s.guest_ok) for s in saved] == [("open", False)]


def test_posture_lists_the_fix_and_the_endpoint_applies_it(client, auth_headers, shares):
    share_access.save_config({"default_level": "write", "shares": {}})
    create_user("guesty", "Guesty", "GoodPass123!", role_id="guest")
    posture = client.get("/api/system/security-posture", headers=auth_headers).json()
    check = next(c for c in posture["checks"] if c["id"] == "share_access_family")
    assert check["fix"] == "share_access_family" and check["passed"] is False
    res = client.post("/api/system/security-posture/fix/share_access_family", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert share_access.load_config()["role_defaults"]["guest"] == "none"
    assert client.post("/api/system/security-posture/fix/nope", headers=auth_headers).status_code == 404


@pytest.mark.real_confirmations
def test_an_advisor_fix_needs_the_person_to_confirm(client, auth_headers):
    res = client.post("/api/system/security-posture/fix/auditor_reads_everything", headers=auth_headers)
    assert res.status_code == 428
    assert res.json()["action"] == "security.advisor_fix" and res.json()["target"] == "auditor_reads_everything"

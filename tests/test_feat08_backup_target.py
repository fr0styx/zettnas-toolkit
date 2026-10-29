"""FEAT-08: be the backup target of another NAS or a friend (an append-only restic REST server in
the catalog), and back up to one (rest: destinations with their own sign-in)."""

import json
import os

import pytest

from backend import config, secret_box
from backend.services import offsite_backup as ob
from backend.services.catalog_templates import CURATED_APP_CATALOG


@pytest.fixture
def env(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "family").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(storage)])
    monkeypatch.setattr(config, "SECRET_KEY", "first-key")
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    return storage


URL = "rest:http://friend-nas:8000/backup/"


def _save(storage, **kw):
    return ob.save_repo("friend", "Friend's NAS", kw.pop("location", URL), [str(storage / "family")], **kw)


def test_the_catalog_offers_an_append_only_target_with_one_account():
    app = next(a for a in CURATED_APP_CATALOG if a["id"] == "rest-server")
    assert "--append-only" in app["env"]["OPTIONS"] and "--private-repos" in app["env"]["OPTIONS"]
    script = app["command"][-1]
    # the account is made once, with bcrypt, and never replaced on a restart
    assert script.startswith('[ -s "$PASSWORD_FILE" ] ||') and "htpasswd -B" in script
    assert script.rstrip().endswith("exec /entrypoint.sh")
    assert app["env"]["REST_PASSWORD"] == app["credentials"]["password"] == "{{secret:password}}"
    assert app["env"]["REST_USER"] == app["credentials"]["user"]
    path = os.path.join(os.path.dirname(ob.__file__), "catalog_digests.json")
    with open(path, encoding="utf-8") as f:
        assert json.load(f)[app["image"]].startswith("sha256:")


def test_a_rest_destination_keeps_its_password_sealed_and_out_of_the_list(env):
    saved = _save(env, rest_user="backup", rest_password="s3cret-pass")
    assert "rest_password" not in saved and saved["has_rest_password"] is True
    stored = ob._repos()["friend"]["rest_password"]
    assert secret_box.is_sealed(stored) and "s3cret" not in stored
    listed = ob.list_repos()[0]
    assert listed["rest_user"] == "backup" and "rest_password" not in listed
    # saving again without a password keeps the one there is
    _save(env, rest_user="backup")
    assert secret_box.unseal(ob._repos()["friend"]["rest_password"]) == "s3cret-pass"


@pytest.mark.parametrize(
    "location",
    ["rest:http://backup:pw@friend-nas:8000/backup/", "rest:ftp://friend-nas/", "rest:http://friend nas/", "rest:"],
)
def test_bad_rest_addresses_are_refused(env, location):
    with pytest.raises(ValueError):
        _save(env, location=location)


def test_bad_user_names_and_unknown_destinations_are_refused(env):
    with pytest.raises(ValueError):
        _save(env, rest_user="back up; rm")
    with pytest.raises(ValueError, match="REST server"):
        _save(env, location="s3:bucket")


def test_restic_gets_the_sign_in_only_for_its_own_rest_server(env, monkeypatch):
    monkeypatch.setenv("RESTIC_REST_PASSWORD", "leaked-from-the-environment")
    _save(env, rest_user="backup", rest_password="s3cret-pass")
    e = ob._env(ob.get_repo("friend"))
    assert e["RESTIC_REST_USERNAME"] == "backup" and e["RESTIC_REST_PASSWORD"] == "s3cret-pass"
    ob.save_repo("usb", "USB", str(env / "usb"), [str(env / "family")])
    e = ob._env(ob.get_repo("usb"))
    assert "RESTIC_REST_PASSWORD" not in e and "RESTIC_REST_USERNAME" not in e


def test_an_append_only_server_is_noticed_and_not_asked_to_prune_again(env, monkeypatch):
    _save(env, rest_user="backup", rest_password="pw")
    calls = []

    def fake(repo, args, **kw):
        calls.append(args[0])
        # restic 0.18 exits 0 here even though the server refused every delete
        return 0, "", "Remove(<snapshot/9b77933975>) failed: unexpected HTTP response (403): 403 Forbidden\n"

    monkeypatch.setattr(ob, "_run_full", fake)
    keep = ob.DEFAULT_KEEP
    ob._forget(ob.get_repo("friend"), keep)
    assert ob.get_repo("friend")["append_only"] is True
    ob._forget(ob.get_repo("friend"), keep)
    assert calls == ["forget"]
    # a new address is asked again
    _save(env, location="rest:http://other-nas:8000/backup/")
    assert ob.get_repo("friend")["append_only"] is False


def test_a_refused_pack_delete_fails_restic_but_not_the_backup(env, monkeypatch):
    _save(env)

    def fake(repo, args, **kw):
        raise ob.ResticError("Fatal: unexpected HTTP response (403): 403 Forbidden")

    monkeypatch.setattr(ob, "_run_full", fake)
    ob._forget(ob.get_repo("friend"), ob.DEFAULT_KEEP)
    assert ob.get_repo("friend")["append_only"] is True


def test_other_prune_failures_still_fail(env, monkeypatch):
    _save(env)

    def fake(repo, args, **kw):
        raise ob.ResticError("Fatal: repository is already locked")

    monkeypatch.setattr(ob, "_run_full", fake)
    with pytest.raises(ob.ResticError, match="locked"):
        ob._forget(ob.get_repo("friend"), ob.DEFAULT_KEEP)
    assert ob.get_repo("friend")["append_only"] is False


def test_a_server_that_prunes_stays_pruned(env, monkeypatch):
    _save(env)
    monkeypatch.setattr(ob, "_run_full", lambda repo, args, **kw: (0, "", ""))
    ob._forget(ob.get_repo("friend"), ob.DEFAULT_KEEP)
    assert ob.get_repo("friend")["append_only"] is False


def test_the_recovery_kit_carries_the_rest_sign_in(env):
    _save(env, rest_user="backup", rest_password="s3cret-pass")
    os.makedirs(ob.KEY_DIR, exist_ok=True)
    with open(ob._key_file("friend"), "w") as f:
        f.write("repo-key\n")
    kit = ob.recovery_kit("friend")
    assert "export RESTIC_REST_USERNAME='backup' RESTIC_REST_PASSWORD='s3cret-pass'" in kit
    assert kit.index("RESTIC_REST_USERNAME") < kit.index("RESTIC_PASSWORD='repo-key'")


def test_a_new_secret_key_seals_the_rest_passwords_again(env):
    _save(env, rest_user="backup", rest_password="s3cret-pass")
    ob.save_repo("usb", "USB", str(env / "usb"), [str(env / "family")])
    with open(config.SECRET_KEY_FILE + ".previous", "w") as f:
        f.write("first-key")
    config.SECRET_KEY = "second-key"
    assert ob.reseal_rest_passwords() == 1
    os.remove(config.SECRET_KEY_FILE + ".previous")
    assert secret_box.unseal(ob._repos()["friend"]["rest_password"]) == "s3cret-pass"


def test_the_api_takes_the_sign_in_and_never_returns_it(env, client, auth_headers):
    r = client.put(
        "/api/offsite/repos",
        json={
            "id": "friend",
            "name": "Friend",
            "location": URL,
            "paths": [str(env / "family")],
            "rest_user": "backup",
            "rest_password": "s3cret-pass",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert "s3cret" not in r.text and r.json()["has_rest_password"] is True
    listed = client.get("/api/offsite", headers=auth_headers).text
    assert "s3cret" not in listed and "enc1:" not in listed

"""FEAT-03 / COMP-09: a locked cloud copy. The bucket's Object Lock is read from the provider
(Backblaze's API, or a signed S3 GET ?object-lock), versions inside the lock are never pruned,
and the list says until when the newest copy is locked."""

import datetime as dt
import json
import time

import pytest

from backend.services import object_lock as ol
from backend.services import offsite_backup as ob

AK, SK = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def test_sigv4_matches_the_aws_examples():
    """The two signed GETs from Amazon's Signature Version 4 documentation."""
    now = dt.datetime(2013, 5, 24)
    h = ol.sigv4_headers(
        "https://examplebucket.s3.amazonaws.com/test.txt", "us-east-1", AK, SK, now, {"Range": "bytes=0-9"}
    )
    assert h["Authorization"].endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    h = ol.sigv4_headers("https://examplebucket.s3.amazonaws.com/?lifecycle", "us-east-1", AK, SK, now)
    assert h["Authorization"].endswith("Signature=fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in h["Authorization"]


@pytest.fixture
def rclone_conf(tmp_path):
    p = tmp_path / "rclone.conf"
    p.write_text(
        "[b2cloud]\ntype = b2\naccount = 0012345\nkey = K001secret\n\n"
        "[wasabi]\ntype = s3\nprovider = Wasabi\naccess_key_id = AK\nsecret_access_key = SK\n"
        "region = eu-central-1\nendpoint = s3.eu-central-1.wasabisys.com\n\n"
        "[aws]\ntype = s3\nprovider = AWS\naccess_key_id = AK\nsecret_access_key = SK\n\n"
        "[nokey]\ntype = s3\n\n[nob2key]\ntype = b2\n\n[gdrive]\ntype = drive\n"
    )
    return str(p)


LOCKED_XML = (
    b'<?xml version="1.0"?><ObjectLockConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    b"<ObjectLockEnabled>Enabled</ObjectLockEnabled><Rule><DefaultRetention><Mode>COMPLIANCE</Mode>"
    b"<Days>30</Days></DefaultRetention></Rule></ObjectLockConfiguration>"
)


class Opener:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, req, timeout=15.0):
        self.requests.append(req)
        return self.answers.pop(0)


def test_s3_bucket_lock(rclone_conf):
    o = Opener([(200, LOCKED_XML)])
    res = ol.check("rclone:wasabi:family-backup/zettnas", o, rclone_conf)
    assert res == {"enabled": True, "mode": "COMPLIANCE", "days": 30, "bucket": "family-backup", "ok": True}
    req = o.requests[0]
    assert req.full_url == "https://s3.eu-central-1.wasabisys.com/family-backup?object-lock="
    assert "eu-central-1/s3/aws4_request" in req.get_header("Authorization")
    assert req.get_method() == "GET"


def test_s3_years_governance_and_no_retention(rclone_conf):
    years = LOCKED_XML.replace(b"<Days>30</Days>", b"<Years>1</Years>").replace(b"COMPLIANCE", b"GOVERNANCE")
    res = ol.check("rclone:aws:b", Opener([(200, years)]), rclone_conf)
    assert res["days"] == 365 and "Governance" in res["note"]
    on_no_rule = b"<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled></ObjectLockConfiguration>"
    res = ol.check("rclone:aws:b", Opener([(200, on_no_rule)]), rclone_conf)
    assert res["ok"] is False and "no default retention" in res["note"]


def test_s3_without_lock_or_permission(rclone_conf):
    missing = b"<Error><Code>ObjectLockConfigurationNotFoundError</Code></Error>"
    assert ol.check("rclone:aws:b", Opener([(404, missing)]), rclone_conf)["ok"] is False
    with pytest.raises(ol.LockCheckError, match="GetBucketObjectLockConfiguration"):
        ol.check("rclone:aws:b", Opener([(403, b"<Error/>")]), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="answered 500"):
        ol.check("rclone:aws:b", Opener([(500, b"")]), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="no access key"):
        ol.check("rclone:nokey:b", Opener([]), rclone_conf)


def test_aws_default_endpoint(rclone_conf):
    o = Opener([(200, LOCKED_XML)])
    ol.check("rclone:aws:my-bucket", o, rclone_conf)
    assert o.requests[0].full_url == "https://s3.us-east-1.amazonaws.com/my-bucket?object-lock="


def _b2(lock, status=200):
    auth = {
        "accountId": "acc",
        "authorizationToken": "tok",
        "apiInfo": {"storageApi": {"apiUrl": "https://api005.backblazeb2.com"}},
    }
    return [
        (200, json.dumps(auth).encode()),
        (status, json.dumps({"buckets": [{"fileLockConfiguration": lock}] if lock is not None else []}).encode()),
    ]


def test_b2_file_lock(rclone_conf):
    lock = {
        "isClientAuthorizedToRead": True,
        "value": {
            "isFileLockEnabled": True,
            "defaultRetention": {"mode": "compliance", "period": {"duration": 30, "unit": "days"}},
        },
    }
    o = Opener(_b2(lock))
    res = ol.check("rclone:b2cloud:photos-locked/zettnas", o, rclone_conf)
    assert res["ok"] and res["mode"] == "COMPLIANCE" and res["days"] == 30
    assert o.requests[0].full_url == ol.B2_AUTH_URL and o.requests[0].get_header("Authorization").startswith("Basic ")
    list_req = o.requests[1]
    assert list_req.full_url == "https://api005.backblazeb2.com/b2api/v3/b2_list_buckets"
    assert json.loads(list_req.data) == {"accountId": "acc", "bucketName": "photos-locked"}
    yearly = {
        "value": {
            "isFileLockEnabled": True,
            "defaultRetention": {"mode": "governance", "period": {"duration": 2, "unit": "years"}},
        }
    }
    assert ol.check("rclone:b2cloud:x", Opener(_b2(yearly)), rclone_conf)["days"] == 730


def test_b2_failures(rclone_conf):
    with pytest.raises(ol.LockCheckError, match="refused the application key"):
        ol.check("rclone:b2cloud:x", Opener([(401, b"{}")]), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="no bucket called x"):
        ol.check("rclone:b2cloud:x", Opener(_b2(None)), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="answered 400"):
        ol.check("rclone:b2cloud:x", Opener(_b2({}, status=400)), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="readBucketRetentions"):
        ol.check("rclone:b2cloud:x", Opener(_b2({"isClientAuthorizedToRead": False})), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="no application key"):
        ol.check("rclone:nob2key:x", Opener([]), rclone_conf)
    off = ol.check("rclone:b2cloud:x", Opener(_b2({"value": {"isFileLockEnabled": False}})), rclone_conf)
    assert off["ok"] is False and off["mode"] is None


def test_what_cant_be_locked(rclone_conf, tmp_path):
    with pytest.raises(ol.LockCheckError, match="rclone:remote:bucket"):
        ol.check("/mnt/disks/usb", Opener([]), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="no cloud drive called missing"):
        ol.check("rclone:missing:b", Opener([]), rclone_conf)
    with pytest.raises(ol.LockCheckError, match="drive remote"):
        ol.check("rclone:gdrive:b", Opener([]), rclone_conf)
    bad = tmp_path / "bad.conf"
    bad.write_text("not [ini")
    with pytest.raises(ol.LockCheckError, match="can't be read"):
        ol.remote_settings("x", str(bad))


def test_lock_days_and_locked_until():
    assert ol.lock_days("30") == 30 and ol.lock_days(None) == 0 and ol.lock_days(99999) == ol.MAX_DAYS
    with pytest.raises(ValueError):
        ol.lock_days("a month")
    assert ol.locked_until({"lock_days": 30, "last_backup": 1000.0}) == 1000.0 + 30 * 86400
    assert ol.locked_until({"lock_days": 0, "last_backup": 1000.0}) is None
    assert ol.locked_until({"lock_days": 30}) is None
    assert {p["id"] for p in ol.presets()} == {"b2", "wasabi", "s3", "other"}


# --- the off-site backup ---


@pytest.fixture
def offsite(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ob, "_in_storage", lambda p: True)
    return ob


def test_a_cloud_backup_keeps_its_lock_period(offsite):
    repo = offsite.save_repo("cloud", "Cloud", "rclone:b2cloud:locked/zettnas", ["/mnt/user/photos"], lock_days=30)
    assert repo["lock_days"] == 30 and repo["locked_until"] is None
    usb = offsite.save_repo("usb", "USB", "/mnt/disks/usb/zettnas", ["/mnt/user/photos"], lock_days=30)
    assert usb["lock_days"] == 0  # only a cloud bucket can lock
    assert offsite._forget_args(offsite.DEFAULT_KEEP, 30)[:2] == ["--keep-within", "30d"]
    assert "--keep-within" not in offsite._forget_args(offsite.DEFAULT_KEEP)


def test_forget_keeps_everything_inside_the_lock(offsite, monkeypatch):
    seen = []
    monkeypatch.setattr(offsite, "_run_full", lambda repo, args, **kw: seen.append(args) or (0, "", ""))
    offsite._forget({"id": "c", "name": "c", "lock_days": 14}, offsite.DEFAULT_KEEP)
    assert seen[0][:2] == ["--keep-within", "14d"]


def test_check_lock_is_stored_and_survives_an_edit(offsite, monkeypatch):
    offsite.save_repo("cloud", "Cloud", "rclone:b2cloud:locked/zettnas", ["/mnt/user/photos"], lock_days=30)
    monkeypatch.setattr(ol, "check", lambda location: {"ok": True, "enabled": True, "mode": "COMPLIANCE", "days": 30})
    res = offsite.check_lock("cloud")
    assert res["ok"] and res["at"] <= time.time()
    assert offsite.get_repo("cloud")["lock_check"]["days"] == 30
    offsite.save_repo("cloud", "Cloud 2", "rclone:b2cloud:locked/zettnas", ["/mnt/user/photos"], lock_days=30)
    assert offsite.get_repo("cloud")["lock_check"]["mode"] == "COMPLIANCE"
    offsite.save_repo("cloud", "Cloud", "rclone:b2cloud:other/zettnas", ["/mnt/user/photos"], lock_days=30)
    assert offsite.get_repo("cloud")["lock_check"] is None  # a new bucket is checked again

    def refuse(location):
        raise ol.LockCheckError("Backblaze refused the application key.")

    monkeypatch.setattr(ol, "check", refuse)
    assert offsite.check_lock("cloud") == {
        "ok": False,
        "error": "Backblaze refused the application key.",
        "at": pytest.approx(time.time(), abs=5),
    }


def test_api(client, auth_headers, offsite, monkeypatch):
    body = {
        "id": "cloud",
        "name": "Cloud",
        "location": "rclone:b2cloud:locked/zettnas",
        "paths": ["/mnt/user/photos"],
        "lock_days": 30,
    }
    res = client.put("/api/offsite/repos", json=body, headers=auth_headers)
    assert res.status_code == 200 and res.json()["lock_days"] == 30
    assert client.put("/api/offsite/repos", json={**body, "lock_days": 5000}, headers=auth_headers).status_code == 422
    assert len(client.get("/api/offsite/lock-presets", headers=auth_headers).json()["presets"]) == 4
    monkeypatch.setattr(ol, "check", lambda location: {"ok": True, "enabled": True, "mode": "COMPLIANCE", "days": 30})
    assert client.post("/api/offsite/repos/cloud/lock-check", headers=auth_headers).json()["ok"] is True
    assert client.post("/api/offsite/repos/nope/lock-check", headers=auth_headers).status_code == 404

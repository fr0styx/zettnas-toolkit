"""NFEAT-3 / D14: photos home from iCloud with an Apple ID sign-in (pyicloud, here faked)."""

import io
import os
import time
from datetime import UTC, datetime

import pytest
from pyicloud.exceptions import PyiCloudFailedLoginException, PyiCloudServiceNotActivatedException

from backend.services import icloud_photos, jobs
from backend.services.jobs import job_manager

TAKEN = datetime(2021, 7, 14, 9, 30, tzinfo=UTC)


class Raw(io.BytesIO):
    decode_content = False


class Resp:
    def __init__(self, data):
        self.raw = Raw(data)

    def raise_for_status(self):
        return None


class Asset:
    def __init__(self, i, data=None, created=TAKEN):
        self.id, self.filename, self.created = f"id{i}", f"IMG_{i:04d}.HEIC", created
        self.data = data if data is not None else f"photo {i}".encode()
        self.size = len(self.data)

    def download_url(self, version="original"):
        return None if self.data == b"" else f"https://cvws.icloud-content.com/{self.id}"


class Session:
    def __init__(self, assets):
        self.by_url = {f"https://cvws.icloud-content.com/{a.id}": a for a in assets}
        self.gets = []

    def get(self, url, stream=False, timeout=None):
        assert stream and timeout
        self.gets.append(url)
        a = self.by_url[url]
        if a.data == b"boom":
            raise OSError("connection reset")
        return Resp(a.data)


class Photos:
    def __init__(self, assets):
        self.all = assets
        self.session = Session(assets)


class FakeApple:
    """PyiCloudService as the module uses it."""

    accounts = {"ana@icloud.com": "right"}
    twofa = True
    adp = False
    trusted = set()
    assets = []
    created = []

    def __init__(self, apple_id, password, cookie_directory=None):
        FakeApple.created.append((apple_id, password, cookie_directory))
        if FakeApple.adp:
            raise PyiCloudServiceNotActivatedException("ADP")
        if password is None:
            if apple_id not in FakeApple.trusted:
                raise PyiCloudFailedLoginException("No password set")
        elif FakeApple.accounts.get(apple_id) != password:
            raise PyiCloudFailedLoginException("Invalid email/password combination.")
        self.apple_id = apple_id
        self.requires_2fa = FakeApple.twofa and apple_id not in FakeApple.trusted
        self.requires_2sa = False
        self.is_trusted_session = False
        self.photos = Photos(FakeApple.assets)
        self.codes_sent = 0

    def request_2fa_code(self):
        self.codes_sent += 1

    def validate_2fa_code(self, code):
        return code == "123456"

    def trust_session(self):
        FakeApple.trusted.add(self.apple_id)
        self.is_trusted_session = True


@pytest.fixture(autouse=True)
def apple(monkeypatch, tmp_path):
    monkeypatch.setattr(icloud_photos, "ROOT", str(tmp_path / "icloud"))
    monkeypatch.setattr(icloud_photos, "_service_class", lambda: FakeApple)
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "jobs_history.json"))
    monkeypatch.setattr(job_manager, "_history", [])
    monkeypatch.setattr(job_manager, "_history_loaded", True)
    monkeypatch.setattr(job_manager, "_jobs", {})
    FakeApple.twofa, FakeApple.adp, FakeApple.trusted, FakeApple.created = True, False, set(), []
    FakeApple.assets = [Asset(1), Asset(2), Asset(3, created=datetime(2019, 1, 2, tzinfo=UTC))]
    icloud_photos._pending.clear()
    icloud_photos._running.clear()
    yield FakeApple


def signed_in(owner="ana"):
    st = icloud_photos.sign_in(owner, " ana@icloud.com ", "right")
    assert st["needs_code"] and not st["signed_in"]
    return icloud_photos.verify(owner, "123 456")


def test_sign_in_with_the_code_keeps_only_the_session(apple, tmp_path):
    st = signed_in()
    assert st == {
        "signed_in": True,
        "apple_id": "ana@icloud.com",
        "needs_code": False,
        "downloading": False,
        "last_download": None,
        "error": "",
    }
    home = icloud_photos._home("ana")
    assert oct(os.stat(home).st_mode & 0o777) == "0o700"
    with open(os.path.join(home, "account.json")) as f:
        assert "right" not in f.read()  # the password is not kept
    assert apple.created[0][2] == os.path.join(home, "session")


def test_what_apple_refuses_is_said_plainly(apple):
    with pytest.raises(icloud_photos.SignInError, match="didn't accept"):
        icloud_photos.sign_in("ana", "ana@icloud.com", "wrong")
    apple.adp = True
    with pytest.raises(icloud_photos.SignInError, match="Advanced Data Protection"):
        icloud_photos.sign_in("ana", "ana@icloud.com", "right")
    apple.adp = False
    icloud_photos.sign_in("ana", "ana@icloud.com", "right")
    with pytest.raises(icloud_photos.SignInError, match="didn't work"):
        icloud_photos.verify("ana", "000000")
    with pytest.raises(icloud_photos.SignInError, match="Sign in again"):
        icloud_photos.verify("ben", "123456")


def test_an_account_without_a_code_is_signed_in_at_once(apple):
    apple.twofa = False
    assert icloud_photos.sign_in("ana", "ana@icloud.com", "right")["signed_in"] is True


def wait(job_id):
    for _ in range(200):
        hist = [h for h in job_manager.list(everyone=True)["history"] if h["id"] == job_id]
        if hist:
            return hist[0]
        time.sleep(0.05)
    raise AssertionError("the download did not finish")


def files(root):
    return sorted(os.path.relpath(os.path.join(d, n), root) for d, _ds, ns in os.walk(root) for n in ns)


def test_the_download_streams_files_by_date_and_only_once(apple, tmp_path):
    signed_in()
    dest = str(tmp_path / "Photos")
    done = wait(icloud_photos.start("ana", dest))
    assert done["status"] == "done" and done["owner"] == "ana" and done["title_params"] == {"source": "iCloud"}
    assert done["detail"] == "3 brought home, 0 already there"
    local = time.localtime(TAKEN.timestamp())
    assert files(dest) == [
        "2019/01/IMG_0003.HEIC",
        f"{local.tm_year}/{local.tm_mon:02d}/IMG_0001.HEIC",
        f"{local.tm_year}/{local.tm_mon:02d}/IMG_0002.HEIC",
    ]
    assert os.stat(os.path.join(dest, "2019/01/IMG_0003.HEIC")).st_mtime == datetime(2019, 1, 2, tzinfo=UTC).timestamp()
    assert apple.created[-1][1] is None  # the saved session, without the password
    apple.assets.append(Asset(4))
    done = wait(icloud_photos.start("ana", dest))
    assert done["detail"] == "1 brought home, 0 already there"  # only the new one is downloaded
    st = icloud_photos.status("ana")
    assert st["last_download"]["imported"] == 1 and not st["downloading"]


def test_a_failed_photo_is_counted_and_the_rest_continue(apple, tmp_path):
    signed_in()
    apple.assets[1].data = b"boom"
    apple.assets.append(Asset(5, data=b""))  # no original to download
    done = wait(icloud_photos.start("ana", str(tmp_path / "P")))
    assert done["status"] == "done" and "2 could not be copied" in done["detail"] and done["error"]


def test_an_ended_session_asks_for_a_new_sign_in(apple, tmp_path):
    signed_in()
    apple.trusted.clear()  # Apple ended the session
    done = wait(icloud_photos.start("ana", str(tmp_path / "P")))
    assert done["status"] == "error" and "new sign-in" in done["error"]
    st = icloud_photos.status("ana")
    assert not st["signed_in"] and st["error"] == "Apple asks for a new sign-in."


def test_one_download_at_a_time_and_signing_out(apple, tmp_path):
    signed_in()
    icloud_photos._running.add("ana")
    with pytest.raises(icloud_photos.SignInError, match="already running"):
        icloud_photos.start("ana", str(tmp_path / "P"))
    icloud_photos._running.clear()
    st = icloud_photos.sign_out("ana")
    assert not st["signed_in"] and st["apple_id"] == ""


def test_cancelling_stops_between_photos(apple, tmp_path):
    signed_in()
    dl = icloud_photos.Download("ana", str(tmp_path / "P"))
    dl.progress = lambda done, total, r: dl.cancelled.set()
    r = dl.run()
    assert r.imported == 1


def test_the_api(client, auth_headers, apple, tmp_path, monkeypatch):
    from backend.api import media as media_api

    root = tmp_path / "pool"
    root.mkdir()
    monkeypatch.setattr(media_api, "ALLOWED_BROWSE_ROOTS", [str(root)])
    assert client.get("/api/media/icloud", headers=auth_headers).json()["signed_in"] is False
    bad = client.post(
        "/api/media/icloud/sign-in", json={"apple_id": "ana@icloud.com", "password": "wrong"}, headers=auth_headers
    )
    assert bad.status_code == 400 and "didn't accept" in bad.json()["detail"] and "wrong" not in bad.text
    r = client.post(
        "/api/media/icloud/sign-in", json={"apple_id": "ana@icloud.com", "password": "right"}, headers=auth_headers
    )
    assert r.status_code == 200 and r.json()["needs_code"] is True
    assert client.post("/api/media/icloud/code", json={"code": "123456"}, headers=auth_headers).json()["signed_in"]
    r = client.post("/api/media/icloud/download", json={"destination": str(root / "iCloud")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert wait(r.json()["job_id"])["status"] == "done"
    outside = client.post("/api/media/icloud/download", json={"destination": "/etc/x"}, headers=auth_headers)
    assert outside.status_code == 403
    assert client.delete("/api/media/icloud", headers=auth_headers).json()["signed_in"] is False

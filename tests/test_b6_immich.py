"""Batch 6: photo search through Immich, per person."""

import httpx
import pytest

from backend.services import immich_photos as im


class Resp:
    def __init__(self, status, data=None, content=b"", ctype="image/jpeg"):
        self.status_code, self._data, self.content = status, data, content
        self.headers = {"content-type": ctype}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("x", request=None, response=None)


KEYS = {"key-for-anna-0123456789abc": "Anna", "key-for-ben-0123456789abcd": "Ben"}


def fake_get(url, headers=None, params=None, timeout=None):
    key = (headers or {}).get("x-api-key")
    if key not in KEYS:
        return Resp(401)
    if url.endswith("/api/users/me"):
        return Resp(200, {"name": KEYS[key]})
    if "/thumbnail" in url:
        return Resp(200, content=b"\xff\xd8" + KEYS[key].encode())
    return Resp(404)


def fake_post(url, headers=None, json=None, timeout=None):
    who = KEYS.get((headers or {}).get("x-api-key"))
    if not who:
        return Resp(401)
    items = [
        {"id": f"{who.lower()}-beach-1", "originalFileName": f"{who}_beach.jpg", "localDateTime": "2025-07-01T10:00:00"}
    ]
    return Resp(200, {"assets": {"items": items}})


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "CONFIG_FILE", str(tmp_path / "immich.json"))
    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)


def test_each_person_sees_their_own_immich_library():
    with pytest.raises(ValueError):
        im.connect("anna", "key-for-anna-0123456789abc")  # no address yet
    im.set_url("http://immich.local:2283/")
    assert im.connect("anna", "key-for-anna-0123456789abc")["immich_user"] == "Anna"
    im.connect("ben", "key-for-ben-0123456789abcd")
    assert [r["name"] for r in im.smart_search("anna", "beach")] == ["Anna_beach.jpg"]
    assert [r["name"] for r in im.smart_search("ben", "beach")] == ["Ben_beach.jpg"]
    assert im.smart_search("carl", "beach") == []  # not connected
    data, ctype = im.thumbnail("anna", "anna-beach-1")
    assert data.endswith(b"Anna") and ctype == "image/jpeg"


def test_wrong_keys_and_addresses_are_refused():
    with pytest.raises(ValueError):
        im.set_url("ftp://immich")
    im.set_url("http://immich.local:2283")
    with pytest.raises(im.ImmichError):
        im.connect("anna", "not-a-real-key-0123456789")
    with pytest.raises(ValueError):
        im.thumbnail_id = im.thumbnail("anna", "../../etc")  # noqa: B018


def test_the_key_never_reaches_the_results():
    im.set_url("http://immich.local:2283")
    im.connect("anna", "key-for-anna-0123456789abc")
    res = im.smart_search("anna", "beach")
    assert "key-for-anna" not in str(res)
    assert res[0]["thumbnail_url"] == "/api/immich/thumbnail/anna-beach-1"

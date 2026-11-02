"""NPERF-3: the ISO upload reads the image's volume descriptor in a thread (_image_format)."""

from backend.api import vms as vms_api


def _image(tmp_path, name, marker: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(b"\0" * 32768 + b"\x01" + marker + b"\0" * 2000)
    return str(p)


def test_image_format_by_its_volume_descriptor(tmp_path):
    assert vms_api._image_format(_image(tmp_path, "a.iso", b"CD001")) == "iso9660"
    assert vms_api._image_format(_image(tmp_path, "b.iso", b"NSR02")) == "udf"
    assert vms_api._image_format(_image(tmp_path, "c.img", b"XXXXX")) == "generic_image"
    assert vms_api._image_format(str(tmp_path / "missing.iso")) == "generic_image"


def test_a_large_upload_is_checked(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(vms_api.vm_host, "_get_target_iso_dir", lambda: str(tmp_path))
    monkeypatch.setattr(vms_api, "add_event", lambda *a, **k: None)
    body = b"\0" * 32768 + b"\x01CD001" + b"\0" * 4000
    res = client.post("/api/vms/isos/upload", content=body, headers={**auth_headers, "x-filename": "big.iso"})
    assert res.status_code == 200 and res.json()["format_verified"] == "iso9660"
    assert (tmp_path / "big.iso").stat().st_size == len(body)

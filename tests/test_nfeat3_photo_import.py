"""NFEAT-3: photos home from a Google Takeout or an iCloud Photos export, read as files (D14)."""

import io
import json
import os
import time
import zipfile

import pytest
from PIL import Image

from backend.services import jobs, photo_import
from backend.services.jobs import job_manager

TS_2019 = 1564567890  # 31 Jul 2019 10:11:30 UTC


def jpeg(color=(200, 10, 10), taken=None):
    img = Image.new("RGB", (8, 8), color)
    buf = io.BytesIO()
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, bytes) else json.dumps(data))
    return str(path)


def takeout(tmp_path):
    base = "Takeout/Google Photos/"
    red, blue, green = jpeg((200, 0, 0)), jpeg((0, 0, 200)), jpeg((0, 200, 0))
    long_name = "Screenshot_20190731-101130_WhatsApp_Business_Extra.jpg"
    folder = tmp_path / "export"
    folder.mkdir()
    make_zip(
        folder / "takeout-20261104-001.zip",
        {
            base + "Photos from 2019/IMG_0001.jpg": red,
            base + "Holiday/IMG_0001.jpg": red,  # the album copy of the same photo
            base + "Photos from 2019/IMG_0002(1).jpg": blue,
            base + "Photos from 2019/IMG_0003-edited.jpg": green,
            base + f"Photos from 2019/{long_name}": jpeg((9, 9, 9)),
            base + "Photos from 2019/VID_0004.mp4": b"\x00\x00\x00\x18ftypmp42not-really-a-video",
        },
    )
    sidecar = {"title": "IMG_0001.jpg", "photoTakenTime": {"timestamp": str(TS_2019)}}
    make_zip(
        folder / "takeout-20261104-002.zip",  # the records in the other part
        {
            base + "Photos from 2019/IMG_0001.jpg.supplemental-metadata.json": sidecar,
            base + "Holiday/IMG_0001.jpg.json": sidecar,
            base + "Photos from 2019/IMG_0002.jpg(1).json": {"photoTakenTime": {"timestamp": "1262347200"}},
            base + "Photos from 2019/IMG_0003.jpg.json": {"photoTakenTime": {"timestamp": "1609459200"}},
            base + "Photos from 2019/Screenshot_20190731-101130_WhatsApp_Bu.json": {
                "title": long_name,
                "photoTakenTime": {"timestamp": "1700000000"},
            },
            base + "Holiday/metadata.json": {"title": "Holiday"},
        },
    )
    return str(folder)


def files_under(root):
    out = {}
    for d, _dirs, names in os.walk(root):
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), root)
            out[rel] = os.stat(os.path.join(d, n)).st_mtime
    return out


def ym(ts):
    t = time.localtime(ts)
    return f"{t.tm_year:04d}/{t.tm_mon:02d}"


def test_a_takeout_in_two_parts_comes_home_by_date_once(tmp_path):
    src, dest = takeout(tmp_path), str(tmp_path / "Photos")
    info = photo_import.inspect(src)
    assert info == {"kind": "google", "photos": 5, "videos": 1, "bytes": info["bytes"], "zip_parts": 2}
    r = photo_import.Importer(src, dest).run()
    assert (r.imported, r.duplicates, r.failed) == (5, 1, 0)  # the album copy is a duplicate
    got = files_under(dest)
    assert got[f"{ym(TS_2019)}/IMG_0001.jpg"] == TS_2019  # the sidecar's time, also as the file's date
    assert f"{ym(1262347200)}/IMG_0002(1).jpg" in got  # IMG_0002.jpg(1).json
    assert f"{ym(1609459200)}/IMG_0003-edited.jpg" in got  # the original's sidecar
    assert f"{ym(1700000000)}/Screenshot_20190731-101130_WhatsApp_Business_Extra.jpg" in got  # cut-short name
    assert any(k.endswith("VID_0004.mp4") for k in got)  # no record: the zip's own date
    assert not any(".part" in k or ".kb-import" in k for k in got)


def test_running_it_again_brings_nothing_twice(tmp_path):
    src, dest = takeout(tmp_path), str(tmp_path / "Photos")
    photo_import.Importer(src, dest).run()
    r = photo_import.Importer(src, dest).run()
    assert (r.imported, r.duplicates) == (0, 6)


def test_a_different_photo_with_the_same_name_is_kept_beside_it(tmp_path):
    src, dest = takeout(tmp_path), tmp_path / "Photos"
    target = dest / ym(TS_2019)
    target.mkdir(parents=True)
    (target / "IMG_0001.jpg").write_bytes(b"another photo")
    photo_import.Importer(src, str(dest)).run()
    assert (target / "IMG_0001 (2).jpg").exists() and (target / "IMG_0001.jpg").read_bytes() == b"another photo"


def test_an_icloud_export_uses_its_details_and_leaves_deleted_photos_out(tmp_path):
    csv_text = (
        "imgName,fileChecksum,favorite,hidden,deleted,originalCreationDate,importDate\n"
        'IMG_5000.HEIC,abc,no,no,no,"Thursday October 6,2022 12:58 PM GMT","Thursday October 6,2022 12:58 PM GMT"\n'
        'IMG_5001.JPG,def,no,no,yes,"Friday October 7,2022 9:00 AM GMT",\n'
    )
    z = make_zip(
        tmp_path / "iCloud Photos Part 1 of 1.zip",
        {
            "iCloud Photos/Photos/IMG_5000.HEIC": b"heic-bytes",
            "iCloud Photos/Photos/IMG_5001.JPG": jpeg(),
            "iCloud Photos/Photos/Photo Details.csv": csv_text.encode(),
        },
    )
    assert photo_import.inspect(z)["kind"] == "icloud"
    dest = str(tmp_path / "out")
    r = photo_import.Importer(z, dest).run()
    assert (r.imported, r.skipped_deleted) == (1, 1)
    when = photo_import.parse_icloud_date("Thursday October 6,2022 12:58 PM GMT")
    assert files_under(dest) == {f"{ym(when)}/IMG_5000.HEIC": when}
    assert photo_import.parse_icloud_date("not a date") is None


def test_a_plain_folder_falls_back_to_the_photos_exif(tmp_path):
    src = tmp_path / "loose"
    src.mkdir()
    (src / "a.jpg").write_bytes(jpeg(taken="2018:05:06 07:08:09"))
    (src / "notes.txt").write_text("not a photo")
    assert photo_import.inspect(str(src))["kind"] == "folder"
    dest = str(tmp_path / "out")
    photo_import.Importer(str(src), dest).run()
    assert list(files_under(dest)) == ["2018/05/a.jpg"]
    with pytest.raises(ValueError):
        list(photo_import.entries(str(src / "notes.txt")))


def test_cancelling_stops_between_files(tmp_path):
    src, dest = takeout(tmp_path), str(tmp_path / "Photos")
    imp = photo_import.Importer(src, dest)
    imp.progress = lambda done, total, r: imp.cancelled.set()
    r = imp.run()
    assert r.imported + r.duplicates == 1


def test_a_broken_entry_is_counted_and_the_rest_continue(tmp_path, monkeypatch):
    src, dest = takeout(tmp_path), str(tmp_path / "Photos")
    real = photo_import._copy_in

    def flaky(e, folder):
        if e.name == "IMG_0002(1).jpg":
            raise OSError("read error")
        return real(e, folder)

    monkeypatch.setattr(photo_import, "_copy_in", flaky)
    r = photo_import.Importer(src, dest).run()
    assert r.failed == 1 and r.imported == 4 and "read error" in r.errors[0]


@pytest.fixture
def clean_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "jobs_history.json"))
    monkeypatch.setattr(job_manager, "_history", [])
    monkeypatch.setattr(job_manager, "_history_loaded", True)
    monkeypatch.setattr(job_manager, "_jobs", {})


def _wait_done(job_id):
    for _ in range(200):
        hist = [h for h in job_manager.list(everyone=True)["history"] if h["id"] == job_id]
        if hist:
            return hist[0]
        time.sleep(0.05)
    raise AssertionError("the import did not finish")


def test_it_runs_as_a_job_for_who_started_it(tmp_path, clean_jobs):
    src, dest = takeout(tmp_path), str(tmp_path / "Photos")
    job_id = photo_import.start(src, dest, "ana", "Google Photos")
    done = _wait_done(job_id)
    assert done["status"] == "done" and done["owner"] == "ana" and done["kind"] == "photo_import"
    assert done["title_params"] == {"source": "Google Photos"} and done["detail"] == "5 brought home, 1 already there"
    assert not os.path.exists(os.path.join(dest, ".kb-import"))


def test_an_unreadable_export_fails_the_job_with_the_reason(tmp_path, clean_jobs):
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"not a zip")
    done = _wait_done(photo_import.start(str(bad), str(tmp_path / "out"), None, "a folder"))
    assert done["status"] == "error" and done["error"]


def test_the_api_inspects_and_starts(client, auth_headers, tmp_path, monkeypatch, clean_jobs):
    from backend.api import media as media_api

    root = tmp_path / "pool"
    root.mkdir()
    monkeypatch.setattr(media_api, "ALLOWED_BROWSE_ROOTS", [str(root)])
    src = takeout(root)
    r = client.get("/api/media/photo-import/inspect", params={"path": src}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "google" and r.json()["destination"] == str(root / "Google Photos")
    bad = client.post(
        "/api/media/photo-import", json={"source": src, "destination": src + "/inside"}, headers=auth_headers
    )
    assert bad.status_code == 400
    r = client.post(
        "/api/media/photo-import",
        json={"source": src, "destination": str(root / "Google Photos")},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert _wait_done(r.json()["job_id"])["status"] == "done"
    outside = client.get("/api/media/photo-import/inspect", params={"path": "/etc"}, headers=auth_headers)
    assert outside.status_code == 403
    empty = root / "empty"
    empty.mkdir()
    none = client.post(
        "/api/media/photo-import", json={"source": str(empty), "destination": str(root / "x")}, headers=auth_headers
    )
    assert none.status_code == 400

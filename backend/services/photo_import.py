"""Bringing photos home from Google Photos and iCloud (NFEAT-3).

Reads the export files the family downloads, never an account (D14): a Google Takeout or an
iCloud Photos export, as its .zip parts or unpacked into a folder. Each photo and video is filed
under <destination>/<year>/<month>/ by when it was taken, which the export itself says: Google's
JSON sidecar (photoTakenTime), iCloud's "Photo Details.csv" (originalCreationDate), else the
photo's EXIF, else the file's own date. The file's modification time is set to that moment, so
the explorer, the timeline and the AI index sort it right; the file itself is copied unchanged.

Duplicates are skipped by content: a Takeout lists every album photo twice (in its album and in
"Photos from <year>"), and running an import again finds what it already brought home. Photos an
iCloud export marks as deleted are left out. The export is only read, never changed or removed.
"""

import csv
import hashlib
import io
import json
import logging
import os
import re
import secrets
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any

from backend.services import thumbs

logger = logging.getLogger("kiboto.photo_import")

MEDIA_EXTS = thumbs.IMAGE_EXTS | thumbs.VIDEO_EXTS
_CHUNK = 1 << 20
# Google gives an edited copy its own name and no sidecar of its own, in the account's language
_EDITED = re.compile(r"-(edited|bearbeitet|modifié|editado|编辑|已编辑)(?=\.[^.]+$)", re.I)
_DUP_SUFFIX = re.compile(r"^(?P<stem>.*?)(?P<ext>\.[^.()]+)\((?P<n>\d+)\)$")  # IMG.jpg(1) -> IMG(1).jpg
_ICLOUD_DATE = re.compile(r"^\w+ (\w+ \d{1,2}),(\d{4}) (\d{1,2}:\d{2} [AP]M)")


@dataclass
class Entry:
    """One file of the export, wherever it lies (a zip part or a folder)."""

    path: str  # its path inside the export, with forward slashes
    size: int
    mtime: float
    open: Callable[[], IO[bytes]]

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def folder(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


@dataclass
class Result:
    imported: int = 0
    duplicates: int = 0
    skipped_deleted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# --- reading the export -----------------------------------------------------------------------
def _zip_entries(zpath: str) -> Iterator[Entry]:
    with zipfile.ZipFile(zpath) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
    for info in infos:

        def opener(info=info) -> IO[bytes]:
            z = zipfile.ZipFile(zpath)
            f = z.open(info)
            f_close = f.close

            def close() -> None:  # the part stays open only while its entry is read
                f_close()
                z.close()

            f.close = close  # type: ignore[method-assign]
            return f

        yield Entry(info.filename.replace("\\", "/"), info.file_size, time.mktime((*info.date_time, 0, 0, -1)), opener)


def _folder_entries(root: str) -> Iterator[Entry]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for n in sorted(filenames):
            full = os.path.join(dirpath, n)
            if n.startswith(".") or os.path.islink(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if n.lower().endswith(".zip"):
                yield from _zip_entries(full)
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            yield Entry(rel, st.st_size, st.st_mtime, lambda full=full: open(full, "rb"))  # noqa: SIM115 (the caller closes it)


def entries(source: str) -> Iterator[Entry]:
    """Every file of an export: a .zip, or a folder of .zip parts and unpacked files."""
    if os.path.isfile(source):
        if not source.lower().endswith(".zip"):
            raise ValueError("Choose the export's .zip file or the folder it was unpacked into.")
        yield from _zip_entries(source)
    else:
        yield from _folder_entries(source)


def is_media(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in MEDIA_EXTS


# --- when each photo was taken ------------------------------------------------------------------
def _sidecar_key(folder: str, json_name: str) -> tuple[str, str]:
    """The media file a Takeout sidecar describes, by its file name: IMG.jpg.json,
    IMG.jpg.supplemental-metadata.json (newer exports, often cut short), IMG.jpg(1).json."""
    stem = json_name[: -len(".json")]
    stem = re.sub(r"\.supp[a-z-]*$", "", stem)  # .supplemental-metadata and its shortened forms
    m = _DUP_SUFFIX.match(stem)
    if m:
        stem = f"{m['stem']}({m['n']}){m['ext']}"
    return folder, stem


class Dates:
    """Taken times from the export's own records: Google sidecars and iCloud's details CSV."""

    def __init__(self) -> None:
        self.google: dict[tuple[str, str], float] = {}
        self.icloud: dict[str, float] = {}
        self.icloud_deleted: set[str] = set()

    def read(self, e: Entry) -> None:
        low = e.name.lower()
        try:
            if low.endswith(".json"):
                self._google(e)
            elif low.endswith(".csv") and low.startswith("photo details"):
                self._icloud(e)
        except (OSError, ValueError, KeyError, UnicodeDecodeError, zipfile.BadZipFile):
            logger.debug("Could not read %s", e.path, exc_info=True)

    def _google(self, e: Entry) -> None:
        if e.size > 1 << 20:
            return
        with e.open() as f:
            doc = json.load(f)
        ts = ((doc.get("photoTakenTime") or {}).get("timestamp")) if isinstance(doc, dict) else None
        if not ts:
            return
        when = float(ts)
        self.google[_sidecar_key(e.folder, e.name)] = when
        if doc.get("title"):  # the original name, when the file name was cut short
            self.google.setdefault((e.folder, str(doc["title"])), when)

    def _icloud(self, e: Entry) -> None:
        with e.open() as f:
            rows = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in rows:
                name = (row.get("imgName") or "").strip()
                if not name:
                    continue
                if (row.get("deleted") or "").strip().lower() == "yes":
                    self.icloud_deleted.add(name)
                when = parse_icloud_date(row.get("originalCreationDate") or "")
                if when is not None:
                    self.icloud[name] = when

    def taken(self, e: Entry) -> tuple[float | None, str]:
        """(when, where it came from): google, icloud, or None when the export doesn't say."""
        name = e.name
        for candidate in (name, _EDITED.sub("", name)):
            if (e.folder, candidate) in self.google:
                return self.google[(e.folder, candidate)], "google"
        # Google cuts long sidecar names to 46 characters (with .json, 51)
        for (folder, key), when in self.google.items():
            if folder == e.folder and len(key) >= 30 and name.startswith(key):
                return when, "google"
        if name in self.icloud:
            return self.icloud[name], "icloud"
        return None, ""


def parse_icloud_date(text: str) -> float | None:
    """iCloud's "Thursday October 6,2022 12:58 PM GMT" as seconds since 1970."""
    m = _ICLOUD_DATE.match(text.strip())
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%B %d %Y %I:%M %p")
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC).timestamp()


def exif_taken(data_head: bytes) -> float | None:
    """DateTimeOriginal from a photo's first bytes (local time, as cameras write it)."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data_head)) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError, Image.DecompressionBombError):
        return None  # not a photo Pillow reads, or cut off before its EXIF
    if not raw:
        return None
    try:
        return time.mktime(time.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


# --- what an export holds, before importing -----------------------------------------------------
def inspect(source: str) -> dict[str, Any]:
    """Which export it is and how much it holds (only the zip directories and file names are read)."""
    photos = videos = size = parts = 0
    google = icloud = False
    for e in entries(source):
        low = e.name.lower()
        if low.endswith(".json") and "takeout/" in e.path.lower():
            google = True
        if low.startswith("photo details") and low.endswith(".csv"):
            icloud = True
        if is_media(e.name):
            size += e.size
            if thumbs.kind(e.name) == "video":
                videos += 1
            else:
                photos += 1
    if os.path.isdir(source):
        parts = sum(1 for _r, _d, files in os.walk(source) for n in files if n.lower().endswith(".zip"))
    elif source.lower().endswith(".zip"):
        parts = 1
    kind = "google" if google else "icloud" if icloud else "folder"
    return {"kind": kind, "photos": photos, "videos": videos, "bytes": size, "zip_parts": parts}


def default_destination(source: str, kind: str) -> str:
    """Beside the export, in a folder named after where the photos came from."""
    parent = os.path.dirname(source.rstrip("/"))
    return os.path.join(parent, {"google": "Google Photos", "icloud": "iCloud Photos"}.get(kind, "Imported photos"))


# --- importing -------------------------------------------------------------------------------------
def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip()
    if name in ("", ".", ".."):
        raise ValueError("bad file name")
    return name[:200]


def _copy_in(e: Entry, folder: str) -> tuple[str, str, bytes]:
    """Copies the entry into a hidden part file in `folder`: (part path, sha256, first bytes)."""
    os.makedirs(folder, exist_ok=True)
    part = os.path.join(folder, f".kb-import-{secrets.token_hex(6)}.part")
    h, head = hashlib.sha256(), b""
    with e.open() as src, open(part, "wb") as dst:
        for chunk in iter(lambda: src.read(_CHUNK), b""):
            if len(head) < 256 * 1024:
                head += chunk[: 256 * 1024 - len(head)]
            h.update(chunk)
            dst.write(chunk)
    return part, h.hexdigest(), head


def _place(part: str, digest: str, folder: str, name: str, known: set[str]) -> str | None:
    """Moves the part file to its name, or removes it when that content is already there.
    Returns the final path, or None for a duplicate."""
    if digest in known:
        os.remove(part)
        return None
    stem, ext = os.path.splitext(name)
    for n in range(1, 1000):
        target = os.path.join(folder, name if n == 1 else f"{stem} ({n}){ext}")
        if not os.path.exists(target):
            os.replace(part, target)
            known.add(digest)
            return target
        if os.path.getsize(target) == os.path.getsize(part) and _sha256_file(target) == digest:
            os.remove(part)
            known.add(digest)
            return None
    os.remove(part)
    raise OSError(f"too many files named {name}")


def file_entry(e: Entry, when: float | None, destination: str, known: set[str]) -> bool:
    """Files one photo or video under <destination>/<year>/<month>/ by when it was taken (`when`,
    else its EXIF, else the entry's own date) and sets its date to that moment. True when it was
    brought home, False when that content was already there. Shared with the iCloud download."""
    part = None
    try:
        name = _safe_name(e.name)
        part, digest, head = _copy_in(e, os.path.join(destination, ".kb-import"))
        if when is None and thumbs.kind(name) == "image":
            when = exif_taken(head)
        when = when if when is not None else e.mtime
        local = time.localtime(when)
        folder = os.path.join(destination, f"{local.tm_year:04d}", f"{local.tm_mon:02d}")
        os.makedirs(folder, exist_ok=True)
        final = _place(part, digest, folder, name, known)
        part = None
        if final is None:
            return False
        os.utime(final, (when, when))
        return True
    finally:
        if part and os.path.exists(part):
            os.remove(part)


class Importer:
    """One import, run on its own thread; `progress` hears (done, total, result) as it goes."""

    def __init__(self, source: str, destination: str, progress: Callable[[int, int, Result], None] | None = None):
        self.source, self.destination = source, destination
        self.progress = progress or (lambda done, total, result: None)
        self.cancelled = threading.Event()
        self.result = Result()

    def run(self) -> Result:
        dates, media = Dates(), []
        for e in entries(self.source):  # the records first: a sidecar may sit in another zip part
            if is_media(e.name):
                media.append(e)
            else:
                dates.read(e)
        known: set[str] = set()
        for done, e in enumerate(media, start=1):
            if self.cancelled.is_set():
                break
            self._one(e, dates, known)
            self.progress(done, len(media), self.result)
        return self.result

    def _one(self, e: Entry, dates: Dates, known: set[str]) -> None:
        r = self.result
        if e.name in dates.icloud_deleted:
            r.skipped_deleted += 1
            return
        try:
            when, _how = dates.taken(e)
            if file_entry(e, when, self.destination, known):
                r.imported += 1
            else:
                r.duplicates += 1
        except (OSError, ValueError, zipfile.BadZipFile, EOFError) as exc:
            r.failed += 1
            if len(r.errors) < 20:
                r.errors.append(f"{e.path}: {exc}")
            logger.warning("[PhotoImport] %s failed: %s", e.path, exc)

    def tidy(self) -> None:
        """Removes the staging folder when it is empty (it is, unless the NAS stopped mid-copy),
        and the one an import before 2.0.2 left under its old name."""
        for name in (".kb-import", "." + "zn-import"):
            staging = os.path.join(self.destination, name)
            if not os.path.isdir(staging):
                continue
            try:
                for n in os.listdir(staging):
                    if n.endswith(".part"):
                        os.remove(os.path.join(staging, n))
                os.rmdir(staging)
            except OSError:
                logger.debug("Could not tidy %s", staging, exc_info=True)  # kept: something else is in it


# --- as a job --------------------------------------------------------------------------------------
def detail(r: Result) -> str:
    out = f"{r.imported} brought home, {r.duplicates} already there"
    if r.skipped_deleted:
        out += f", {r.skipped_deleted} deleted in iCloud left out"
    if r.failed:
        out += f", {r.failed} could not be copied"
    return out


def start(source: str, destination: str, owner: str | None, label: str) -> str:
    """Runs the import on its own thread as a job in the Jobs centre; returns the job's id."""
    from backend.services.jobs import job_manager

    job_id: dict[str, str] = {}

    def progress(done: int, total: int, r: Result) -> None:
        job_manager.update(job_id["id"], percent=round(100.0 * done / total, 1) if total else None, detail=detail(r))

    importer = Importer(source, destination, progress)
    job = job_manager.register(
        "photo_import",
        f"Bringing photos home from {label}",
        owner=owner,
        cancel=importer.cancelled.set,
        title_id="jobs.t.photo_import",
        title_params={"source": label},
    )
    job_id["id"] = job.id

    def run() -> None:
        finished = False
        try:
            r = importer.run()
            importer.tidy()
            job_manager.update(job.id, detail=detail(r))
            status = "cancelled" if importer.cancelled.is_set() else "done"
            job_manager.finish(job.id, status, ("; ".join(r.errors[:3]) or None) if r.failed else None)
            finished = True
            logger.info("[PhotoImport] %s into %s: %s", source, destination, detail(r))
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:  # an unreadable export
            logger.warning("[PhotoImport] %s failed", source, exc_info=True)
            importer.tidy()
            job_manager.finish(job.id, "error", str(exc)[:300])
            finished = True
        finally:
            if not finished:  # anything else: the job must not stay "running"
                importer.tidy()
                job_manager.finish(job.id, "error", "The import stopped unexpectedly; the log says why.")

    threading.Thread(target=run, name="photo-import", daemon=True).start()
    return job.id

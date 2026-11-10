"""Photos home from iCloud with an Apple ID sign-in (NFEAT-3; D14 answered yes on 4 Nov 2026).

Through pyicloud (MIT), the iCloud web interface Apple's own iCloud.com uses; it is not an official
API, so Apple can change it, and accounts with Advanced Data Protection can't be read this way.

The password is used for the sign-in only and never kept: what stays is Apple's trusted session,
in a private folder per NAS user (data/icloud/<user>/session, 0700). Apple asks for a new sign-in
every few weeks to months; the download then says so. Each photo's original is streamed to disk
(never held in memory) and filed by photo_import.file_entry: <folder>/<year>/<month>/, the file's
date set to when it was taken, content already there skipped. A photo brought home once is not
downloaded again, even if it was moved since.
"""

import hashlib
import logging
import os
import shutil
import threading
import time
from typing import IO, Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.services import photo_import

logger = logging.getLogger("kiboto.icloud_photos")

ROOT = os.path.join(DATA_DIR, "icloud")
DOWNLOAD_TIMEOUT_S = 300
SAVE_EVERY = 50
_pending: dict[str, Any] = {}  # NAS user -> a sign-in waiting for its code
_running: set[str] = set()  # NAS users with a download under way
_lock = threading.Lock()


class SignInError(Exception):
    """Something to tell the person: a wrong password, a code that didn't work, an account Apple
    won't open this way."""


def _service_class() -> Any:
    from pyicloud import PyiCloudService  # lazy: the import pulls in the sign-in libraries

    return PyiCloudService


def _home(owner: str) -> str:
    path = os.path.join(ROOT, hashlib.sha256(owner.encode()).hexdigest()[:16])
    os.makedirs(os.path.join(path, "session"), mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _meta(owner: str) -> dict[str, Any]:
    data = read_json(os.path.join(_home(owner), "account.json"), {})
    return data if isinstance(data, dict) else {}


def _save_meta(owner: str, **changes: Any) -> None:
    meta = {**_meta(owner), **changes}
    atomic_write_json(os.path.join(_home(owner), "account.json"), meta)


def _explain(exc: Exception) -> str:
    name = type(exc).__name__
    return {
        "PyiCloudFailedLoginException": "Apple didn't accept that Apple ID and password.",
        "PyiCloudServiceNotActivatedException": (
            "Apple won't open iCloud Photos this way for this account. If Advanced Data Protection is "
            "on, turn on 'Access iCloud Data on the Web' in the iPhone's iCloud settings, or use an export."
        ),
        "PyiCloudAccountLockedException": "Apple has locked this Apple ID for now. Unlock it at iforgot.apple.com.",
        "PyiCloudAcceptTermsException": "Apple wants new terms accepted first: sign in at icloud.com once.",
        "PyiCloudConnectionException": "iCloud could not be reached. Check the NAS's internet connection.",
    }.get(name, f"Apple refused the sign-in ({name}).")


def sign_in(owner: str, apple_id: str, password: str) -> dict[str, Any]:
    """Signs in with the Apple ID and password; most accounts then need the code Apple sends."""
    from pyicloud.exceptions import PyiCloudException

    apple_id = apple_id.strip()
    try:
        api = _service_class()(apple_id, password, cookie_directory=os.path.join(_home(owner), "session"))
    except PyiCloudException as exc:
        raise SignInError(_explain(exc)) from exc
    _save_meta(owner, apple_id=apple_id, trusted=False)
    if getattr(api, "requires_2sa", False) and not getattr(api, "requires_2fa", False):
        raise SignInError("This Apple ID uses the old two-step verification. Turn on two-factor authentication.")
    if getattr(api, "requires_2fa", False):
        api.request_2fa_code()  # to the trusted devices, or by text message
        with _lock:
            _pending[owner] = api
        return status(owner)
    _save_meta(owner, trusted=True, signed_in_at=time.time())
    return status(owner)


def verify(owner: str, code: str) -> dict[str, Any]:
    """The six-digit code from the person's iPhone, iPad or Mac (or a text message)."""
    from pyicloud.exceptions import PyiCloudException

    with _lock:
        api = _pending.get(owner)
    if api is None:
        raise SignInError("Sign in again: the sign-in waiting for this code has expired.")
    code = "".join(c for c in code if c.isdigit())
    try:
        if not api.validate_2fa_code(code):
            raise SignInError("That code didn't work. Check it, or ask Apple for a new one.")
        if not api.is_trusted_session:
            api.trust_session()
    except PyiCloudException as exc:
        raise SignInError(_explain(exc)) from exc
    with _lock:
        _pending.pop(owner, None)
    _save_meta(owner, trusted=True, signed_in_at=time.time())
    return status(owner)


def sign_out(owner: str) -> dict[str, Any]:
    """Forgets the Apple session (the downloaded photos stay)."""
    with _lock:
        _pending.pop(owner, None)
    shutil.rmtree(_home(owner), ignore_errors=True)
    return status(owner)


def status(owner: str) -> dict[str, Any]:
    meta = _meta(owner)
    with _lock:
        waiting, running = owner in _pending, owner in _running
    return {
        "signed_in": bool(meta.get("trusted")),
        "apple_id": meta.get("apple_id") or "",
        "needs_code": waiting,
        "downloading": running,
        "last_download": meta.get("last_download"),
        "error": meta.get("error") or "",
    }


def _connect(owner: str) -> Any:
    """The saved session, without the password; None when Apple wants a new sign-in."""
    from pyicloud.exceptions import PyiCloudException

    meta = _meta(owner)
    if not meta.get("apple_id") or not meta.get("trusted"):
        return None
    try:
        api = _service_class()(meta["apple_id"], None, cookie_directory=os.path.join(_home(owner), "session"))
    except PyiCloudException:
        logger.info("[iCloud] the saved session for a NAS user ended", exc_info=True)
        return None
    if getattr(api, "requires_2fa", False) or getattr(api, "requires_2sa", False):
        return None
    return api


# --- the download -----------------------------------------------------------------------------------
def _entry(api: Any, asset: Any) -> photo_import.Entry:
    url = asset.download_url("original")
    if not url:
        raise ValueError("no original to download")
    created = asset.created
    when = created.timestamp() if hasattr(created, "timestamp") else time.time()

    def opener() -> IO[bytes]:
        resp = api.photos.session.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_S)
        resp.raise_for_status()
        resp.raw.decode_content = True
        return resp.raw

    return photo_import.Entry(str(asset.filename), int(asset.size or 0), when, opener)


class Download:
    """All of the account's photos into one folder; `progress` hears (done, total, result)."""

    def __init__(self, owner: str, destination: str, progress=None):
        self.owner, self.destination = owner, destination
        self.progress = progress or (lambda done, total, result: None)
        self.cancelled = threading.Event()
        self.result = photo_import.Result()
        self.seen_file = os.path.join(_home(owner), "downloaded.json")

    def run(self) -> photo_import.Result:
        api = _connect(self.owner)
        if api is None:
            _save_meta(self.owner, trusted=False, error="Apple asks for a new sign-in.")
            raise SignInError("Apple asks for a new sign-in. Open the iCloud dialog and sign in again.")
        r = self._walk(api)
        last = {"at": time.time(), **{k: getattr(r, k) for k in ("imported", "duplicates", "failed")}}
        _save_meta(self.owner, error="", last_download=last)
        return r

    @json_locked(lambda self, api: self.seen_file)
    def _walk(self, api: Any) -> photo_import.Result:
        """Every photo of the library, newest first; the list of those brought home is saved as it goes."""
        seen = set(read_json(self.seen_file, []) or [])
        album = api.photos.all
        total, known, r = len(album), set(), self.result
        for done, asset in enumerate(album, start=1):
            if self.cancelled.is_set():
                break
            if asset.id not in seen:
                self._one(api, asset, known, seen)
            if done % SAVE_EVERY == 0:
                atomic_write_json(self.seen_file, sorted(seen))
            self.progress(done, total, r)
        atomic_write_json(self.seen_file, sorted(seen))
        return r

    def _one(self, api: Any, asset: Any, known: set[str], seen: set[str]) -> None:
        r = self.result
        try:
            e = _entry(api, asset)
            if photo_import.file_entry(e, e.mtime, self.destination, known):
                r.imported += 1
            else:
                r.duplicates += 1
            seen.add(asset.id)
        except (OSError, ValueError) as exc:  # requests' errors are OSErrors
            r.failed += 1
            if len(r.errors) < 20:
                r.errors.append(f"{getattr(asset, 'filename', '?')}: {exc}")
            logger.warning("[iCloud] %s failed: %s", getattr(asset, "filename", "?"), exc)


def start(owner: str, destination: str) -> str:
    """Runs the download as a job in the Jobs centre for this NAS user; returns its id."""
    from backend.services.jobs import job_manager

    with _lock:
        if owner in _running:
            raise SignInError("A download from iCloud is already running.")
        _running.add(owner)
    job_id: dict[str, str] = {}

    def progress(done: int, total: int, r: photo_import.Result) -> None:
        pct = round(100.0 * done / total, 1) if total else None
        job_manager.update(job_id["id"], percent=pct, detail=photo_import.detail(r))

    dl = Download(owner, destination, progress)
    job = job_manager.register(
        "photo_import",
        "Bringing photos home from iCloud",
        owner=owner,
        cancel=dl.cancelled.set,
        title_id="jobs.t.photo_import",
        title_params={"source": "iCloud"},
    )
    job_id["id"] = job.id

    def run() -> None:
        # anything unexpected still ends the job, so it never stays "running"
        status_, error = "error", "The download stopped unexpectedly; the log says why."
        try:
            r = dl.run()
            status_ = "cancelled" if dl.cancelled.is_set() else "done"
            error = ("; ".join(r.errors[:3]) or None) if r.failed else None
            job_manager.update(job.id, detail=photo_import.detail(r))
        except (SignInError, OSError, ValueError, KeyError) as exc:
            logger.warning("[iCloud] the download stopped: %s", exc)
            error = str(exc)[:300]
        finally:
            photo_import.Importer(destination, destination).tidy()
            with _lock:
                _running.discard(owner)  # before the job ends, so its end means the person can start another
            job_manager.finish(job.id, status_, error)

    threading.Thread(target=run, name="icloud-photos", daemon=True).start()
    return job.id

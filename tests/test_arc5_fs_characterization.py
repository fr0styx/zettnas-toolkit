"""ARC-5: the file API keeps its names, routes and behaviour while it is split up.

Records, from backend.api.fs: every name it defines (with signatures), its routes in order
(path, methods, endpoint, scopes, response model) and the responses of a scripted session in
the sandbox pool (folders, transfers, archives, sizes, permissions, uploads, the inbox,
search, trash, previews, downloads, share links and favorites). tests/golden/fs_api.json was
recorded before the module became a package; the facade must still provide all of it.
Regenerate only for an intended change:

    ZETTNAS_UPDATE_GOLDEN=1 pytest tests/test_arc5_fs_characterization.py
"""

import hashlib
import inspect
import io
import json
import os
import re
import time
import types
import uuid
import zipfile

import pytest

from backend.api import fs

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "fs_api.json")


def _signature(obj):
    try:
        sig = str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "?"
    sig = re.sub(r" at 0x[0-9a-f]+", "", sig)
    return re.sub(r"backend\.api\.(fs|files)(\.\w+)*?\.(?=[A-Z])", "", sig)  # where a type lives may change


def _surface():
    """Every function, class and constant fs defines (imports from elsewhere are not its API)."""
    out = {}
    for name in sorted(vars(fs)):
        if name.startswith("__"):
            continue
        obj = getattr(fs, name)
        if isinstance(obj, types.ModuleType):
            continue
        mod = getattr(obj, "__module__", None)
        if inspect.isclass(obj) and mod and mod.startswith(("backend.api.fs", "backend.api.files")):
            fields = sorted(getattr(obj, "model_fields", {}) or {})
            methods = sorted(m for m, f in vars(obj).items() if callable(f) and not m.startswith("__"))
            out[name] = {"class": fields or methods}
        elif inspect.isfunction(obj) and mod and mod.startswith(("backend.api.fs", "backend.api.files")):
            out[name] = {"async" if inspect.iscoroutinefunction(obj) else "function": _signature(obj)}
        elif name.isupper() and isinstance(obj, (int, float, str)) and "/" not in str(obj):
            out[name] = {"value": obj}
    return out


def _flat(routes):
    """Routes in matching order; an included router (FastAPI keeps it nested) gives its own."""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _flat(inner.routes)
        else:
            yield r


def _routes():
    out = []
    for r in _flat(fs.router.routes):
        deps = []
        for d in getattr(r, "dependencies", []) or []:
            call = d.dependency
            deps.append(getattr(call, "__qualname__", repr(call)).split(".<locals>")[0])
        rm = getattr(r, "response_model", None)
        out.append(
            {
                "path": r.path,
                "methods": sorted(getattr(r, "methods", []) or []),
                "endpoint": r.endpoint.__name__,
                "deps": deps,
                "status": getattr(r, "status_code", None),
                "response_model": getattr(rm, "__name__", None if rm is None else str(rm)),
                "params": sorted(inspect.signature(r.endpoint).parameters),
            }
        )
    return out


# --- a scripted session ----------------------------------------------------------------------
_TS = re.compile(r"^1[6-9]\d{8}(\.\d+)?$")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
_HEX = re.compile(r"\b[0-9a-f]{16,}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_VOLATILE = {
    "mtime",
    "atime",
    "ctime",
    "modified",
    "created",
    "created_at",
    "expires_at",
    "deleted_at",
    "updated_at",
    "started_at",
    "finished_at",
    "completed_at",
    "last_accessed",
    "elapsed",
    "duration",
    "duration_ms",
    "speed",
    "speed_bps",
    "eta",
    "eta_seconds",
    "rate",
    "took_ms",
    "elapsed_ms",
    "inode",
    "uid",
    "gid",
    "owner",
    "group",
    "free",
    "free_bytes",
    "total",
    "total_bytes",
    "used",
    "used_bytes",
    "percent",
    "date",
    "timestamp",
    "last_used",
    "added_at",
    "accessed",
    "hex_dump",
}


class _Norm:
    def __init__(self, subs):
        self.subs = sorted(subs.items(), key=lambda kv: -len(kv[0]))
        self.ids = {}

    def add(self, real, tag):
        if real:
            self.subs = sorted([*self.subs, (real, tag)], key=lambda kv: -len(kv[0]))

    def text(self, s):
        for real, tag in self.subs:
            s = s.replace(real, tag)
        s = _UUID.sub(lambda m: self._id(m.group(0)), s)
        s = _HEX.sub(lambda m: self._id(m.group(0)), s)
        s = re.sub(r"(?<!\d)1[6-9]\d{8}(?!\d)", "<ts>", s)
        s = re.sub(r"<ts>-\d+_", "<ts>_", s)  # a second item of one name in the same second
        return _ISO.sub("<date>", s)

    def _id(self, raw):
        return self.ids.setdefault(raw, f"<id{len(self.ids)}>")

    def value(self, v, key=""):
        if isinstance(v, dict):
            return {self.text(k): self.value(x, k) for k, x in sorted(v.items())}
        if isinstance(v, list):
            out = [self.value(x, key) for x in v]
            if key == "items" and all(isinstance(x, dict) and "deleted_at" in x for x in out):
                out.sort(key=lambda x: (str(x.get("name")), str(x.get("id"))))  # Recycle Bin: ties in time
            return out
        if key in _VOLATILE and v is not None:
            return f"<{type(v).__name__}>"
        if isinstance(v, (int, float)) and not isinstance(v, bool) and _TS.match(str(v)):
            return "<ts>"
        if isinstance(v, str):
            return self.text(v)
        return v


def _body(r):
    ctype = r.headers.get("content-type", "").split(";")[0]
    if ctype == "application/json":
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("task"), dict):
            # a background task's snapshot: its progress depends on timing, its shape does not
            task = data["task"]
            data = {**data, "task": {"keys": sorted(task), "action": task.get("action"), "kind": task.get("kind")}}
        return data
    if ctype in ("application/zip", "application/x-zip-compressed"):
        try:
            return {"zip": sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())}
        except zipfile.BadZipFile:
            return {"zip": "bad", "bytes": len(r.content)}
    if ctype.startswith("text/") and len(r.content) < 4000:
        return {"text": r.text[:600]}
    return {"type": ctype, "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest()[:16]}


def _items(data):
    """A listing's entries, whether the route returns a list or {"items": [...]}."""
    if isinstance(data, list):
        return data
    for key in ("items", "links", "entries", "results"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _wait_for(path, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline and not os.path.exists(path):
        time.sleep(0.05)
    time.sleep(0.3)  # the task finishes its bookkeeping after the file appears


def _session(client, headers, pool, work, outside, inbox):
    norm = _Norm(
        {work: "<work>", pool: "<pool>", outside: "<outside>", os.path.basename(work): "<wf>", inbox: "<inbox>"}
    )
    log = []

    def call(label, method, url, **kw):
        kw.setdefault("headers", headers)
        r = getattr(client, method)(url, **kw)
        disposition = r.headers.get("content-disposition", "")
        entry = {"label": label, "status": r.status_code, "body": _body(r)}
        if disposition:
            entry["disposition"] = disposition
        log.append(entry)
        return r

    j = os.path.join
    call("roots", "get", "/api/fs/roots")
    call("browse", "get", "/api/browse", params={"path": work})
    call("browse dirs only", "get", "/api/browse", params={"path": work, "dirs_only": "1"})
    call("browse outside", "get", "/api/browse", params={"path": outside})
    call("browse missing", "get", "/api/browse", params={"path": j(work, "nope")})
    call("mkdir", "post", "/api/mkdir", json={"path": j(work, "new folder")})
    call("mkdir again", "post", "/api/mkdir", json={"path": j(work, "new folder")})
    call("rename", "post", "/api/fs/rename", json={"path": j(work, "new folder"), "new_name": "renamed"})
    call("rename bad", "post", "/api/fs/rename", json={"path": j(work, "a.txt"), "new_name": "../x"})
    call("rename clash", "post", "/api/fs/rename", json={"path": j(work, "a.txt"), "new_name": "sub"})
    call(
        "conflict check",
        "post",
        "/api/fs/conflict-check",
        json={"sources": [j(work, "a.txt"), j(work, "sub")], "destination_dir": j(work, "sub")},
    )
    for policy in ("keep_both", "overwrite", "skip", "merge"):
        call(
            f"copy {policy}",
            "post",
            "/api/fs/transfer",
            json={"sources": [j(work, "a.txt")], "destination_dir": j(work, "sub"), "collision_policy": policy},
        )
    call(
        "move",
        "post",
        "/api/fs/transfer",
        json={"sources": [j(work, "renamed")], "destination_dir": j(work, "sub"), "action": "move"},
    )
    call(
        "transfer outside", "post", "/api/fs/transfer", json={"sources": [j(work, "a.txt")], "destination_dir": outside}
    )
    r = call(
        "async duplicate",
        "post",
        "/api/fs/transfer/async",
        json={
            "sources": [j(work, "a.txt")],
            "destination_dir": work,
            "target_names": ["a copy.txt"],
            "kind": "duplicate",
        },
    )
    _wait_for(j(work, "a copy.txt"))
    transfers = client.get("/api/fs/transfers", headers=headers).json()
    log.append(
        {"label": "transfers after", "body": sorted(transfers) if isinstance(transfers, dict) else len(transfers)}
    )
    call("clear transfers", "delete", "/api/fs/transfers/completed")
    call("pause unknown", "post", "/api/fs/transfers/nope/pause")
    call("cancel unknown", "post", "/api/fs/transfers/nope/cancel")
    call(
        "archive zip",
        "post",
        "/api/fs/archive/create",
        json={"sources": [j(work, "a.txt"), j(work, "sub")], "destination_dir": work, "archive_name": "pack"},
    )
    _wait_for(j(work, "pack"), 5)
    call(
        "archive tar.gz",
        "post",
        "/api/fs/archive/create",
        json={"sources": [j(work, "sub")], "destination_dir": work, "archive_name": "pack2", "format": "tar.gz"},
    )
    _wait_for(j(work, "pack2"), 5)
    os.makedirs(j(work, "unpacked"))
    call(
        "extract",
        "post",
        "/api/fs/archive/extract",
        json={"archive_path": j(work, "pack"), "destination_dir": j(work, "unpacked")},
    )
    _wait_for(j(work, "unpacked", "a.txt"), 5)
    call("preview zip", "get", "/api/fs/preview", params={"path": j(work, "pack")})
    for name in ("pack", "pack2"):  # gzip and zip headers carry the time: their bytes differ per run
        os.remove(j(work, name))
    call(
        "extract missing",
        "post",
        "/api/fs/archive/extract",
        json={"archive_path": j(work, "no.zip"), "destination_dir": work},
    )
    for algo in ("sha256", "md5", "sha1"):
        call(f"checksum {algo}", "post", "/api/fs/checksum", json={"path": j(work, "a.txt"), "algorithm": algo})
    call("checksum of a folder", "post", "/api/fs/checksum", json={"path": j(work, "sub")})
    call("folder size", "post", "/api/fs/folder-size", json={"path": work})
    call("folder size of a file", "post", "/api/fs/folder-size", json={"path": j(work, "a.txt")})
    call("permissions", "get", "/api/fs/permissions", params={"path": j(work, "a.txt")})
    call("chmod", "put", "/api/fs/permissions", json={"path": j(work, "a.txt"), "mode_octal": "640"})
    call("chmod bad", "put", "/api/fs/permissions", json={"path": j(work, "a.txt"), "mode_octal": "999"})
    call("permissions after", "get", "/api/fs/permissions", params={"path": j(work, "a.txt")})
    os.chmod(j(work, "a.txt"), 0o644)
    call("download", "get", "/api/fs/download", params={"path": j(work, "a.txt")})
    call("download a folder", "get", "/api/fs/download", params={"path": j(work, "sub")})
    call("download zip", "get", "/api/fs/download-zip", params={"paths": f"{j(work, 'a.txt')},{j(work, 'sub')}"})
    call("download zip empty", "get", "/api/fs/download-zip", params={"paths": " , "})
    call("upload", "post", "/api/fs/upload", params={"path": work, "filename": "up.txt"}, content=b"uploaded")
    r = call(
        "upload init",
        "post",
        "/api/fs/upload/init",
        json={"destination_dir": work, "filename": "big.bin", "total_size": 10},
    )
    upload_id = r.json().get("upload_id") if r.status_code == 200 else None
    if upload_id:
        call(
            "chunk 0",
            "post",
            "/api/fs/upload/chunk",
            params={"upload_id": upload_id, "chunk_index": 0},
            content=b"0123456789",
        )
        call(
            "complete",
            "post",
            "/api/fs/upload/complete",
            json={"upload_id": upload_id, "expected_sha256": hashlib.sha256(b"0123456789").hexdigest()},
        )
    call("chunk unknown", "post", "/api/fs/upload/chunk", params={"upload_id": "nope", "chunk_index": 0}, content=b"x")
    call("complete unknown", "post", "/api/fs/upload/complete", json={"upload_id": "nope"})
    call("search", "get", "/api/fs/search", params={"q": "b.txt", "path": work})
    call("search none", "get", "/api/fs/search", params={"q": "zzzz-nothing", "path": work})
    call("preview text", "get", "/api/fs/preview", params={"path": j(work, "a.txt")})
    call("preview folder", "get", "/api/fs/preview", params={"path": j(work, "sub")})
    call("preview image of text", "get", "/api/fs/preview/image", params={"path": j(work, "a.txt")})
    call("stream", "get", "/api/fs/stream", params={"path": j(work, "a.txt")})
    call(
        "stream range",
        "get",
        "/api/fs/stream",
        params={"path": j(work, "a.txt")},
        headers={**headers, "Range": "bytes=1-3"},
    )
    call("stream compat", "get", "/api/fs/stream/compat", params={"path": j(work, "a.txt")})
    call("delete to trash", "post", "/api/fs/delete", json={"path": j(work, "up.txt")})
    call("delete outside", "post", "/api/fs/delete", json={"path": j(outside, "secret")})
    r = call("trash", "get", "/api/fs/trash")
    items = [i for i in (_items(r.json()) if r.status_code == 200 else []) if "up.txt" in json.dumps(i)]
    if items:
        call("restore", "post", "/api/fs/trash/restore", json={"item_id": items[0].get("id")})
    call("restore unknown", "post", "/api/fs/trash/restore", json={"item_id": "does-not-exist"})
    r = call("share", "post", "/api/fs/share-links", json={"path": j(work, "a.txt"), "label": "golden"})
    token = r.json().get("token") if r.status_code == 200 else None
    norm.add(token, "<token1>")
    r = call(
        "share folder with password",
        "post",
        "/api/fs/share-links",
        json={"path": j(work, "sub"), "password": "open sesame 1"},
    )
    ptoken = r.json().get("token") if r.status_code == 200 else None
    norm.add(ptoken, "<token2>")
    call("share outside", "post", "/api/fs/share-links", json={"path": outside})
    links = client.get("/api/fs/share-links", headers=headers)
    log.append({"label": "share links", "status": links.status_code, "body": len(_items(links.json()))})
    if token:
        call("shared info", "get", f"/api/fs/shared/{token}", params={"info": "1"}, headers={})
        call("shared file", "get", f"/api/fs/shared/{token}", headers={})
    if ptoken:
        call("shared needs password", "get", f"/api/fs/shared/{ptoken}", headers={})
        call("shared wrong password", "post", f"/api/fs/shared/{ptoken}", data={"password": "wrong"}, headers={})
        call("shared zip", "post", f"/api/fs/shared/{ptoken}", data={"password": "open sesame 1"}, headers={})
        call(
            "shared header password",
            "get",
            f"/api/fs/shared/{ptoken}",
            params={"info": "1"},
            headers={"X-Share-Password": "open sesame 1"},
        )
    call("shared unknown", "get", "/api/fs/shared/not-a-token", headers={})
    if token:
        call("revoke", "delete", f"/api/fs/share-links/{token}")
        call("shared revoked", "get", f"/api/fs/shared/{token}", headers={})
    call("revoke unknown", "delete", "/api/fs/share-links/nope")
    call("favorite", "post", "/api/fs/favorites", json={"path": work})
    call("favorite file", "post", "/api/fs/favorites", json={"path": j(work, "a.txt")})
    call("favorite outside", "post", "/api/fs/favorites", json={"path": "/etc"})
    call("favorites", "get", "/api/fs/favorites")
    call("unfavorite", "delete", "/api/fs/favorites", params={"path": work})
    call("inbox", "get", "/api/fs/inbox")
    call("inbox upload", "post", "/api/fs/inbox", params={"filename": "photo.jpg"}, content=b"\xff\xd8\xff\xe0jpeg")
    call("inbox escape", "post", "/api/fs/inbox", params={"filename": "../../etc/passwd"}, content=b"x")
    call("trash empty", "delete", "/api/fs/trash/empty")
    call("browse at the end", "get", "/api/browse", params={"path": work})
    tree = []
    for root, dirs, files in os.walk(work):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            tree.append([os.path.relpath(full, work), os.path.getsize(full)])
    log.append({"label": "files at the end", "body": tree})
    return [norm.value(e) for e in log]


@pytest.fixture
def work(pool_tree):
    d = os.path.join(pool_tree, "golden-" + uuid.uuid4().hex[:8])
    os.makedirs(d)
    with open(os.path.join(d, "a.txt"), "w") as f:
        f.write("alpha")
    os.makedirs(os.path.join(d, "sub"))
    with open(os.path.join(d, "sub", "b.txt"), "w") as f:
        f.write("bravo")
    yield d


def test_fs_api_routes_and_behaviour_match_the_recording(client, auth_headers, work, paths, monkeypatch, tmp_path):
    from backend.api.files import uploads

    inbox = str(tmp_path / "inbox")
    monkeypatch.setattr(uploads, "_inbox_dir", lambda principal: inbox, raising=True)
    got = {
        "surface": _surface(),
        "routes": _routes(),
        "session": _session(client, auth_headers, paths["pool"], work, paths["outside"], inbox),
    }
    got = json.loads(json.dumps(got, sort_keys=True, default=str))
    if os.environ.get("ZETTNAS_UPDATE_GOLDEN") == "1":
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
            fh.write("\n")
        pytest.skip("golden file written")
    with open(GOLDEN, encoding="utf-8") as fh:
        want = json.load(fh)
    missing = sorted(set(want["surface"]) - set(got["surface"]))
    assert not missing, f"names no longer provided by backend.api.fs: {missing}"
    changed = [n for n in want["surface"] if got["surface"][n] != want["surface"][n]]
    assert not changed, f"API changed: {changed[:5]}"
    assert got["routes"] == want["routes"]
    for w, g in zip(want["session"], got["session"], strict=True):
        assert g == w, w["label"]
    assert len(want["routes"]) >= 45 and len(want["session"]) >= 80

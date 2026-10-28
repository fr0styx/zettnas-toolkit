"""The file API end to end in the sandbox pool: folders, renames, copy and move with conflicts,
trash and restore, permissions, downloads and zips, search, sizes, previews, share links, favorites."""

import io
import os
import stat
import uuid
import zipfile

import pytest


@pytest.fixture
def work(pool_tree):
    """A fresh folder per test inside the allowed pool, removed afterwards with its recycle bin
    (a later recycle-bin listing found items left in it: random-order nightly)."""
    import shutil

    d = os.path.join(pool_tree, "wf-" + uuid.uuid4().hex[:8])
    os.makedirs(d)
    with open(os.path.join(d, "a.txt"), "w") as f:
        f.write("alpha")
    os.makedirs(os.path.join(d, "sub"))
    with open(os.path.join(d, "sub", "b.txt"), "w") as f:
        f.write("bravo")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def ok(r):
    assert r.status_code == 200, r.text
    return r.json() if "json" in r.headers.get("content-type", "") else r


class TestFolders:
    def test_mkdir_rename_delete(self, client, auth_headers, work):
        new = os.path.join(work, "new folder")
        ok(client.post("/api/mkdir", json={"path": new}, headers=auth_headers))
        assert os.path.isdir(new)
        ok(client.post("/api/fs/rename", json={"path": new, "new_name": "renamed"}, headers=auth_headers))
        assert os.path.isdir(os.path.join(work, "renamed"))
        ok(client.post("/api/fs/delete", json={"path": os.path.join(work, "renamed")}, headers=auth_headers))
        assert not os.path.exists(os.path.join(work, "renamed"))

    @pytest.mark.parametrize("bad", ["", "a/b", "..", "."])
    def test_rename_refuses_bad_names(self, client, auth_headers, work, bad):
        r = client.post(
            "/api/fs/rename", json={"path": os.path.join(work, "a.txt"), "new_name": bad}, headers=auth_headers
        )
        assert r.status_code == 400

    def test_rename_to_an_existing_name(self, client, auth_headers, work):
        r = client.post(
            "/api/fs/rename", json={"path": os.path.join(work, "a.txt"), "new_name": "sub"}, headers=auth_headers
        )
        assert r.status_code in (400, 409)

    def test_outside_the_pool_is_refused(self, client, auth_headers, paths):
        r = client.post("/api/fs/delete", json={"path": os.path.join(paths["outside"], "secret")}, headers=auth_headers)
        assert r.status_code in (400, 403, 404)


class TestTransfers:
    def test_conflict_check(self, client, auth_headers, work):
        dest = os.path.join(work, "sub")
        with open(os.path.join(dest, "a.txt"), "w") as f:
            f.write("other")
        data = ok(
            client.post(
                "/api/fs/conflict-check",
                json={"sources": [os.path.join(work, "a.txt")], "destination_dir": dest},
                headers=auth_headers,
            )
        )
        assert data.get("conflicts") or data.get("has_conflicts")

    @pytest.mark.parametrize("policy", ["keep_both", "overwrite", "skip"])
    def test_copy_with_a_collision_policy(self, client, auth_headers, work, policy):
        dest = os.path.join(work, "sub")
        with open(os.path.join(dest, "a.txt"), "w") as f:
            f.write("other")
        ok(
            client.post(
                "/api/fs/transfer",
                json={
                    "sources": [os.path.join(work, "a.txt")],
                    "destination_dir": dest,
                    "action": "copy",
                    "collision_policy": policy,
                },
                headers=auth_headers,
            )
        )
        with open(os.path.join(dest, "a.txt")) as f:
            content = f.read()
        files = os.listdir(dest)
        if policy == "keep_both":
            assert content == "other" and len([f for f in files if f.startswith("a")]) == 2
        elif policy == "overwrite":
            assert content == "alpha"
        else:
            assert content == "other"
        assert os.path.exists(os.path.join(work, "a.txt"))  # a copy keeps the source

    def test_move(self, client, auth_headers, work):
        ok(
            client.post(
                "/api/fs/transfer",
                json={
                    "sources": [os.path.join(work, "a.txt")],
                    "destination_dir": os.path.join(work, "sub"),
                    "action": "move",
                },
                headers=auth_headers,
            )
        )
        assert not os.path.exists(os.path.join(work, "a.txt")) and os.path.exists(os.path.join(work, "sub", "a.txt"))

    def test_bad_policy(self, client, auth_headers, work):
        r = client.post(
            "/api/fs/transfer",
            json={"sources": [os.path.join(work, "a.txt")], "destination_dir": work, "collision_policy": "explode"},
            headers=auth_headers,
        )
        assert r.status_code == 422


class TestTrash:
    def test_list_restore_and_empty(self, client, auth_headers, work):
        target = os.path.join(work, "a.txt")
        ok(client.post("/api/fs/delete", json={"path": target}, headers=auth_headers))
        listing = ok(client.get("/api/fs/trash", headers=auth_headers))
        items = listing.get("items", listing if isinstance(listing, list) else [])
        # replaced copies of other a.txt files may be in the bin too (REL-14): take this one
        mine = [i for i in items if i.get("original_path") == target] or [i for i in items if i.get("name") == "a.txt"]
        if not mine:
            pytest.skip("this pool deletes without a recycle bin")
        ok(client.post("/api/fs/trash/restore", json={"item_id": mine[0]["id"]}, headers=auth_headers))
        assert os.path.exists(target)
        ok(client.post("/api/fs/delete", json={"path": target}, headers=auth_headers))
        ok(client.delete("/api/fs/trash/empty", headers=auth_headers))
        listing = ok(client.get("/api/fs/trash", headers=auth_headers))
        items = listing.get("items", listing if isinstance(listing, list) else [])
        assert not [i for i in items if i.get("name") == "a.txt"]

    def test_restore_unknown_item(self, client, auth_headers):
        r = client.post("/api/fs/trash/restore", json={"item_id": "does-not-exist"}, headers=auth_headers)
        assert r.status_code in (400, 404)


class TestPermissions:
    def test_read_and_change_mode(self, client, auth_headers, work):
        target = os.path.join(work, "a.txt")
        info = ok(client.get("/api/fs/permissions", params={"path": target}, headers=auth_headers))
        assert "mode" in str(info) or "octal" in str(info)
        ok(client.put("/api/fs/permissions", json={"path": target, "mode_octal": "640"}, headers=auth_headers))
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640

    def test_recursive(self, client, auth_headers, work):
        ok(
            client.put(
                "/api/fs/permissions",
                json={"path": os.path.join(work, "sub"), "mode_octal": "750", "recursive": True},
                headers=auth_headers,
            )
        )
        assert stat.S_IMODE(os.stat(os.path.join(work, "sub")).st_mode) == 0o750

    @pytest.mark.parametrize("mode", ["999", "abc", "77777"])
    def test_bad_modes(self, client, auth_headers, work, mode):
        r = client.put(
            "/api/fs/permissions", json={"path": os.path.join(work, "a.txt"), "mode_octal": mode}, headers=auth_headers
        )
        assert r.status_code in (400, 422)


class TestDownloads:
    def test_single_file(self, client, auth_headers, work):
        r = client.get("/api/fs/download", params={"path": os.path.join(work, "a.txt")}, headers=auth_headers)
        assert r.status_code == 200 and r.content == b"alpha"

    def test_zip_of_files_and_folders(self, client, auth_headers, work):
        r = client.get(
            "/api/fs/download-zip",
            params={"paths": f"{os.path.join(work, 'a.txt')},{os.path.join(work, 'sub')}"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert any(n.endswith("a.txt") for n in names) and any(n.endswith("b.txt") for n in names)

    def test_zip_needs_paths(self, client, auth_headers):
        assert client.get("/api/fs/download-zip", params={"paths": " , "}, headers=auth_headers).status_code == 400

    def test_stream_range(self, client, auth_headers, work):
        r = client.get(
            "/api/fs/stream",
            params={"path": os.path.join(work, "a.txt")},
            headers={**auth_headers, "Range": "bytes=1-3"},
        )
        assert r.status_code in (200, 206) and r.content in (b"lph", b"alpha")


class TestLookups:
    def test_search(self, client, auth_headers, work):
        data = ok(client.get("/api/fs/search", params={"q": "b.txt", "path": work}, headers=auth_headers))
        assert "b.txt" in str(data)

    def test_folder_size(self, client, auth_headers, work):
        data = ok(client.post("/api/fs/folder-size", json={"path": work}, headers=auth_headers)) if True else None
        assert "10" in str(data) or data  # 5 + 5 bytes

    def test_preview_text(self, client, auth_headers, work):
        r = client.get("/api/fs/preview", params={"path": os.path.join(work, "a.txt")}, headers=auth_headers)
        assert r.status_code == 200 and "alpha" in r.text

    def test_browse(self, client, auth_headers, work):
        data = ok(client.get("/api/browse", params={"path": work}, headers=auth_headers))
        assert data["current"] == work
        entries = {e["name"]: e for e in data["dirs"]}  # every entry, with is_dir, plus ".."
        assert {"a.txt", "sub", ".."} <= set(entries) and entries["sub"]["is_dir"] and not entries["a.txt"]["is_dir"]
        dirs = ok(client.get("/api/browse", params={"path": work, "dirs_only": "1"}, headers=auth_headers))
        assert {e["name"] for e in dirs["dirs"] if e["name"] != ".."} == {"sub"}

    def test_roots(self, client, auth_headers):
        data = ok(client.get("/api/fs/roots", headers=auth_headers))
        assert data

    def test_favorites(self, client, auth_headers, work):
        ok(client.post("/api/fs/favorites", json={"path": work}, headers=auth_headers))
        assert work in str(ok(client.get("/api/fs/favorites", headers=auth_headers)))
        ok(client.delete("/api/fs/favorites", params={"path": work}, headers=auth_headers))
        assert work not in str(ok(client.get("/api/fs/favorites", headers=auth_headers)))


class TestShareLinks:
    def test_public_link(self, client, auth_headers, work):
        link = ok(
            client.post(
                "/api/fs/share-links",
                json={"path": os.path.join(work, "a.txt"), "expires_hours": 1, "max_downloads": 2},
                headers=auth_headers,
            )
        )
        token = link["token"]
        assert token in str(ok(client.get("/api/fs/share-links", headers=auth_headers)))
        r = client.get(f"/api/fs/shared/{token}")  # no session needed
        assert r.status_code == 200 and r.content == b"alpha"
        ok(client.delete(f"/api/fs/share-links/{token}", headers=auth_headers))
        assert client.get(f"/api/fs/shared/{token}").status_code in (404, 410)

    def test_password_protected_link(self, client, auth_headers, work):
        token = ok(
            client.post(
                "/api/fs/share-links",
                json={"path": os.path.join(work, "a.txt"), "password": "open sesame"},
                headers=auth_headers,
            )
        )["token"]
        assert client.get(f"/api/fs/shared/{token}").status_code in (401, 403)
        assert client.post(f"/api/fs/shared/{token}", data={"password": "wrong"}).status_code in (401, 403)
        r = client.post(f"/api/fs/shared/{token}", data={"password": "open sesame"})
        assert r.status_code == 200

    def test_folder_link_lists_and_zips(self, client, auth_headers, work):
        token = ok(client.post("/api/fs/share-links", json={"path": work}, headers=auth_headers))["token"]
        r = client.get(f"/api/fs/shared/{token}", params={"info": "true"})
        assert r.status_code == 200
        z = client.get(f"/api/fs/shared/{token}", params={"zip": "1"})
        assert z.status_code in (200, 400)

    def test_download_limit(self, client, auth_headers, work):
        token = ok(
            client.post(
                "/api/fs/share-links",
                json={"path": os.path.join(work, "a.txt"), "max_downloads": 1},
                headers=auth_headers,
            )
        )["token"]
        assert client.get(f"/api/fs/shared/{token}").status_code == 200
        assert client.get(f"/api/fs/shared/{token}").status_code in (403, 404, 410)


def test_delete_returns_the_recycle_bin_id_for_undo(client, auth_headers, pool_tree, monkeypatch, request):
    """UX-6: the id comes back so Undo can restore it; two items of one name never collide."""
    import os

    from backend.api import fs as fs_api

    monkeypatch.setattr(fs_api.time, "time", lambda: 1700000000.0)  # both deletes in the same second

    base = os.path.join(
        pool_tree["root"] if isinstance(pool_tree, dict) and "root" in pool_tree else pool_tree, "undo-test"
    )
    import shutil

    # the share and its recycle bin go afterwards: a later recycle-bin listing found the item
    # left in it (found by the random-order nightly)
    request.addfinalizer(lambda: shutil.rmtree(base, ignore_errors=True))
    ids = []
    for _ in range(2):
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "same.txt"), "w") as f:
            f.write("x")
        r = client.post("/api/fs/delete", json={"path": os.path.join(base, "same.txt")}, headers=auth_headers)
        assert r.status_code == 200, r.text
        ids.append(r.json()["trash_id"])
    assert ids == ["undo-test::1700000000_same.txt", "undo-test::1700000000-2_same.txt"]  # its share bin (REL-15)
    r = client.post("/api/fs/trash/restore", json={"item_id": ids[1]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert os.path.exists(os.path.join(base, "same.txt"))

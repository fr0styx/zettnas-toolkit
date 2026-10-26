"""Generic Linux shares: Samba and NFS merged into one list, folders as the fallback."""

import types

from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter


def _engines(monkeypatch, smb, nfs):
    from backend.services import nfs_engine, samba_engine

    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: types.SimpleNamespace(list_shares=smb))
    monkeypatch.setattr(nfs_engine, "get_nfs_engine", lambda: types.SimpleNamespace(list_exports=nfs))


def test_samba_and_nfs_merge(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()

    def smb():
        return [
            types.SimpleNamespace(name="media", path=str(media), comment="Films", guest_ok=True),
            types.SimpleNamespace(name="private", path="/nowhere", comment="", guest_ok=False),
        ]

    def nfs():
        return [
            types.SimpleNamespace(name="media", path=str(media), comment="", clients="*"),
            types.SimpleNamespace(name="vmstore", path=str(tmp_path), comment="", clients="10.0.0.0/24"),
        ]

    _engines(monkeypatch, smb, nfs)
    shares = {s.name: s for s in GenericLinuxStorageAdapter(pool_path=str(tmp_path)).list_shares()}
    assert set(shares) == {"media", "private", "vmstore"}
    assert shares["media"].export_smb and shares["media"].export_nfs and shares["media"].security == "public"
    assert shares["media"].comment == "Films" and shares["media"].total_bytes > 0
    assert shares["private"].security == "private" and shares["private"].comment == "ZettNAS Managed Share"
    assert shares["vmstore"].export_nfs and not shares["vmstore"].export_smb
    assert shares["vmstore"].security == "private" and shares["vmstore"].comment == "ZettNAS Managed NFS Export"


def test_without_engines_the_pool_folders_are_the_shares(tmp_path, monkeypatch):
    def broken():
        raise RuntimeError("not configured")

    _engines(monkeypatch, broken, broken)
    for name in ("photos", "docs", ".hidden", "@snapshots"):
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("x")
    shares = GenericLinuxStorageAdapter(pool_path=str(tmp_path)).list_shares()
    assert [s.name for s in shares] == ["docs", "photos"]
    assert all(s.export_smb and s.comment == "Managed Linux Share" for s in shares)

"""ZettNAS's own searches see every file, and the Overview asks for the server's time zone."""

from backend.services import status_summary
from backend.services.rag_engine_search import SYSTEM_PRINCIPAL, RagSearchMixin


def test_zettnas_itself_reads_every_indexed_file():
    from backend.services.path_access import indexed_path_checker

    assert indexed_path_checker(SYSTEM_PRINCIPAL)("/mnt/user/Family/tax/2021.pdf") is True
    ok = RagSearchMixin._post_rbac_checker(SYSTEM_PRINCIPAL)
    assert ok("/mnt/user/Family/tax/2021.pdf") is True
    assert ok("/mnt/user/Family/.RecycleBin/old.pdf") is False  # the bin stays out, as for everyone
    assert RagSearchMixin._post_rbac_checker(None)("/mnt/user/Family/x.pdf") is True  # no checker: SQL decided


def test_no_time_zone_is_a_warning(monkeypatch):
    from backend.services import identity

    monkeypatch.setattr(identity, "get_identity", lambda: {"server_name": "", "timezone": ""})
    assert status_summary._timezone() == [
        {"id": "server:timezone", "level": "warning", "kind": "timezone_unset", "subject": "", "open": "time"}
    ]
    monkeypatch.setattr(identity, "get_identity", lambda: {"server_name": "", "timezone": "Europe/Berlin"})
    assert status_summary._timezone() == []

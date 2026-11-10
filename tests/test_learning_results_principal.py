"""SEC-37 callers: Retry failed files reads every file as Kiboto itself, and the AI status counts
only what the person asking may see (it used to ask as nobody and always got nothing)."""

from backend.services.rag_engine_learning import RagLearningMixin
from backend.services.rag_engine_search import SYSTEM_PRINCIPAL


class _Fake(RagLearningMixin):
    def __init__(self):
        self.seen = []

    def get_learning_results(self, principal=None):
        self.seen.append(principal)
        return {"failed_files": [{"path": "/mnt/user/gone/missing.pdf"}]}


def test_retry_failed_files_reads_them_as_kiboto(monkeypatch):
    from backend.services import rag_standby

    fake = _Fake()
    monkeypatch.setattr(rag_standby, "resolve_path_backing_dev", lambda p: "")
    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda d: True)  # skipped: its disk sleeps
    out = fake.relearn_failed_files()
    assert fake.seen == [SYSTEM_PRINCIPAL, SYSTEM_PRINCIPAL]
    assert out["retried"] == 0


def test_the_status_asks_for_the_persons_results_only(monkeypatch):
    from backend.services import media_engine

    seen = []

    class Rag:
        def get_learning_results(self, principal=None):
            seen.append(principal)
            return {"kib_status": "Idle"}

        def discover_available_folders(self):
            return []

        def __getattr__(self, name):
            return lambda *a, **k: {}

    monkeypatch.setattr(media_engine, "get_rag_engine", lambda: Rag())
    monkeypatch.setattr(media_engine, "detect_hardware_accelerator", lambda: {"type": "cpu"})
    monkeypatch.setattr(media_engine, "build_llm_recommendations", lambda **k: [])
    engine = media_engine.MediaEngine()
    someone = object()
    engine.get_status(principal=someone)
    assert seen == [someone]
    seen.clear()
    engine.get_status()
    assert seen == []  # the acceleration-only callers don't search at all

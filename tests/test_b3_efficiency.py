"""Batch 3 of the v1.10 audit: efficiency."""

import os
import threading

import pytest


@pytest.mark.skipif(not os.path.isdir("/proc/self/task"), reason="Linux only")
def test_threads_show_their_names_to_the_os():
    from backend.services.supervisor import install_os_thread_names

    assert install_os_thread_names()
    seen = {}

    def work():
        tid = threading.get_native_id()
        with open(f"/proc/self/task/{tid}/comm") as f:
            seen["comm"] = f.read().strip()

    t = threading.Thread(target=work, name="ZnTestThread")
    t.start()
    t.join()
    assert seen["comm"] == "ZnTestThread"


def test_chat_models_unload_after_the_idle_setting(monkeypatch):
    from backend.services import chat_llm_runtime, rag_engine

    monkeypatch.setattr(rag_engine.get_rag_engine(), "get_config", lambda: {"idle_unload_minutes": 15})
    assert chat_llm_runtime._keep_alive() == "15m"
    monkeypatch.setattr(rag_engine.get_rag_engine(), "get_config", lambda: {"idle_unload_minutes": 0})
    assert chat_llm_runtime._keep_alive() == "-1"


def test_captions_wait_while_someone_chats(monkeypatch):
    from backend.services import chat_llm_runtime, vision_queue

    chat_llm_runtime.mark_chat_activity()
    assert vision_queue.system_idle() is False
    chat_llm_runtime._LAST_CHAT["at"] = 0.0


def test_the_pool_list_is_read_at_most_every_30_seconds(monkeypatch):
    from backend.hardware import storage

    calls = []

    class _Adapter:
        def list_pools(self):
            calls.append(1)
            return []

    a = _Adapter()
    storage._POOLS_CACHE.update(at=0.0, pools=None, adapter=None)
    storage._cached_pools(a)
    storage._cached_pools(a)
    assert len(calls) == 1


def test_nothing_is_serialised_while_nobody_listens(monkeypatch):
    from unittest.mock import MagicMock

    from backend.services import broadcaster as bmod

    b = bmod.StatsBroadcaster()
    b._loop = MagicMock(is_running=lambda: True)
    called = []
    monkeypatch.setattr(bmod, "fast_dumps", lambda d: called.append(d) or "{}")
    b.broadcast({"cpu": 1}, full_data={"cpu": 1})
    assert called == [] and b._latest_full_data == {"cpu": 1}

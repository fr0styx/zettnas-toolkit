"""NAI-7: the nightly re-embed keeps to its hours and makes way for one started from settings."""

import asyncio
import inspect

from backend.services import rag_engine_learning as rel


class Engine(rel.RagLearningMixin):
    def __init__(self):
        import threading

        self._reembed_lock = threading.Lock()


def test_the_go_check():
    e = Engine()
    assert e._reembed_go()  # no limit set: a re-embed from settings runs through
    e._reembed_keep = lambda: True
    assert e._reembed_go()
    e._reembed_keep = lambda: False
    assert not e._reembed_go() and "tonight" in e._reembed_why


def test_every_batch_asks():
    src = inspect.getsource(rel.RagLearningMixin.in_place_reembed_collection)
    assert "if not self._reembed_go():" in src and "self._reembed_why or" in src


def test_a_settings_re_embed_stops_the_nightly_one():
    e = Engine()

    @rel._one_reembed_at_a_time
    async def job(self):
        return {"status": "ok"}

    e._reembed_lock.acquire()  # the nightly one holds it
    e._reembed_keep = lambda: True
    out = asyncio.run(job(e))
    assert out["status"] == "busy" and "stopping" in out["message"] and e._text_upgrade_stop is True
    e._reembed_keep = None
    assert asyncio.run(job(e))["message"] == "A re-embed is already running."

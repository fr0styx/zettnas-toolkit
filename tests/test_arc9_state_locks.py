"""ARC-9: copy progress is changed and read under its lock."""

import json
import threading

from backend.state import CopyState


def test_counters_from_several_threads_add_up():
    c = CopyState()
    c.start(copied=0, files_done=0)

    def work():
        for _ in range(5000):
            c.add("copied", 3)
            c.add("files_done", 1)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.snapshot() == {"copied": 60000, "files_done": 20000}


def test_a_snapshot_can_be_serialised_while_the_copy_adds_keys():
    c = CopyState()
    c.start(total=0)
    stop = threading.Event()
    errors = []

    def writer():
        i = 0
        while not stop.is_set():
            c.update(**{f"k{i % 500}": i, "file": f"f{i}"})
            i += 1

    def reader():
        for _ in range(3000):
            try:
                json.dumps(c.snapshot())
            except RuntimeError as e:  # "dictionary changed size during iteration"
                errors.append(e)

    w = threading.Thread(target=writer)
    w.start()
    reader()
    stop.set()
    w.join()
    assert not errors
    snap = c.snapshot()
    snap["total"] = 99  # a copy: changing it leaves the state alone
    assert c.snapshot()["total"] == 0

"""NFEAT-9: the media status reports only counts the index keeps, never made-up ones."""

import inspect

from backend.services import media_engine


def test_no_invented_counts_in_the_source():
    src = inspect.getsource(media_engine)
    for made_up in ('"faces"', '"locations"', '"albums"', "// 4", "// 6", "// 10"):
        assert made_up not in src, made_up


def test_the_status_counts_come_from_the_index():
    src = inspect.getsource(media_engine.MediaEngine)
    assert '"photos": rag_stats.get("total_photos", 0)' in src
    assert '"chunks": rag_stats.get("total_chunks", 0)' in src

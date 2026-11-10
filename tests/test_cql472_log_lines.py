"""CodeQL alert 472: a file's name can't add lines to the log."""

import logging

from backend.services import media_info


def test_a_name_with_a_line_break_stays_on_one_log_line(tmp_path, caplog):
    bad = tmp_path / "x.mov\nERROR forged entry"
    bad.write_bytes(b"not a video")
    with caplog.at_level(logging.INFO, logger="kiboto.media_info"):
        assert media_info._probe(str(bad)) is None
    (rec,) = [r for r in caplog.records if r.getMessage().startswith("Not a media file")]
    assert "\n" not in rec.getMessage() and "x.mov\\nERROR forged entry" in rec.getMessage()

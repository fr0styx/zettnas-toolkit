"""SET-03, the owner's decision S10: file actions are not written to the event log.

The event log rides in the live stream to everyone who may look at the system, family members
included, so the name of every uploaded, deleted, moved or restored file reached them, also from
private and encrypted folders. File activity keeps the record: it is for administrators, masks home
folders and leaves out what is inside encrypted folders.
"""

import os
import re

from backend import db
from backend.services import file_activity
from backend.state import Z_STATE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES_API = ("api/files/operations.py", "api/files/trash.py", "api/files/uploads.py", "api/file_versions.py")


def test_only_emptying_the_bin_is_still_an_event():
    left = []
    for rel in FILES_API:
        with open(os.path.join(ROOT, "backend", rel), encoding="utf-8") as fh:
            src = fh.read()
        for m in re.finditer(r"add_event\((.*?)\n    \)", src, flags=re.S):
            left.append((rel, "fm_bin_emptied" in m.group(1) or "purged" in m.group(1)))
    assert left == [("api/files/trash.py", True)], left  # it names no file


def test_an_upload_is_in_file_activity_and_not_in_the_event_log(client, auth_headers, monkeypatch, tmp_path):
    from backend.api.files import uploads

    monkeypatch.setattr(uploads, "_inbox_dir", lambda principal: str(tmp_path / "inbox"), raising=True)
    db.init_db()
    before = len(Z_STATE.event_log)
    res = client.post(
        "/api/fs/inbox", params={"filename": "set03-payslip.pdf"}, content=b"%PDF-1.4 x", headers=auth_headers
    )
    assert res.status_code == 200, res.text
    assert "set03-payslip.pdf" not in str(Z_STATE.event_log)
    assert len(Z_STATE.event_log) == before
    rows = file_activity.search(q="set03-payslip.pdf")
    assert any(r.get("action") == "upload" for r in rows), rows
